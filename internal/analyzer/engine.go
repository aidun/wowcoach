package analyzer

import (
	"fmt"
	"sort"
	"time"

	"github.com/aidun/wowcoach/internal/domain"
	"github.com/aidun/wowcoach/internal/segments"
	"github.com/aidun/wowcoach/internal/specs"
)

type Engine struct{}

func NewEngine() *Engine {
	return &Engine{}
}

func (e *Engine) Analyze(events []domain.CombatEvent, fight domain.Fight, actor domain.ActorRef, specID string) (domain.AnalysisResult, error) {
	def, ok := specs.Get(specID)
	if !ok {
		return domain.AnalysisResult{}, fmt.Errorf("unknown spec %s", specID)
	}
	fightEvents := segments.SliceFightEvents(fight, events)
	actorEvents := make([]domain.CombatEvent, 0, len(fightEvents))
	spellCounts := map[int]int{}
	buffStarts := map[int]time.Time{}
	debuffStarts := map[int]time.Time{}
	buffDurations := map[int]float64{}
	debuffDurations := map[int]float64{}
	cooldownUses := map[int]int{}
	openerHits := map[int]bool{}
	timeline := make([]domain.TimelineEvent, 0, 80)

	start := fight.Start
	end := fight.End
	if end.Before(start) {
		end = start
	}
	duration := end.Sub(start).Seconds()

	var lastCast time.Time
	idleSeconds := 0.0
	totalCasts := 0

	trackedBuffs := make(map[int]struct{}, len(def.TrackedBuffs))
	trackedDebuffs := make(map[int]struct{}, len(def.TrackedDebuffs))
	trackedCooldowns := make(map[int]string, len(def.Cooldowns))
	for _, aura := range def.TrackedBuffs {
		trackedBuffs[aura.SpellID] = struct{}{}
	}
	for _, aura := range def.TrackedDebuffs {
		trackedDebuffs[aura.SpellID] = struct{}{}
	}
	for _, cooldown := range def.Cooldowns {
		trackedCooldowns[cooldown.SpellID] = cooldown.Name
	}

	for _, event := range fightEvents {
		if event.SourceGUID == actor.ID {
			if isCastEvent(event) {
				actorEvents = append(actorEvents, event)
				totalCasts++
				spellCounts[event.SpellID]++
				if !lastCast.IsZero() {
					gap := event.Timestamp.Sub(lastCast).Seconds()
					if gap > 1.6 {
						idleSeconds += gap - 1.6
					}
				}
				lastCast = event.Timestamp
				if len(timeline) < 80 {
					timeline = append(timeline, domain.TimelineEvent{
						Timestamp: formatOffset(start, event.Timestamp),
						Label:     event.SpellName,
						Kind:      "cast",
						Tags:      []string{specID},
					})
				}
				if _, ok := trackedCooldowns[event.SpellID]; ok {
					cooldownUses[event.SpellID]++
				}
				if event.Timestamp.Sub(start).Seconds() <= 18 {
					openerHits[event.SpellID] = true
				}
			}
			switch event.EventType {
			case "SPELL_AURA_APPLIED", "SPELL_AURA_APPLIED_DOSE":
				if _, ok := trackedBuffs[event.SpellID]; ok && event.DestGUID == actor.ID {
					if _, seen := buffStarts[event.SpellID]; !seen {
						buffStarts[event.SpellID] = event.Timestamp
					}
					if len(timeline) < 80 {
						timeline = append(timeline, domain.TimelineEvent{
							Timestamp: formatOffset(start, event.Timestamp),
							Label:     event.SpellName + " gained",
							Kind:      "buff",
						})
					}
				}
				if _, ok := trackedDebuffs[event.SpellID]; ok && event.DestGUID != actor.ID {
					if _, seen := debuffStarts[event.SpellID]; !seen {
						debuffStarts[event.SpellID] = event.Timestamp
					}
				}
			case "SPELL_AURA_REMOVED", "SPELL_AURA_REMOVED_DOSE":
				if startTime, ok := buffStarts[event.SpellID]; ok && event.DestGUID == actor.ID {
					buffDurations[event.SpellID] += event.Timestamp.Sub(startTime).Seconds()
					delete(buffStarts, event.SpellID)
				}
				if startTime, ok := debuffStarts[event.SpellID]; ok && event.DestGUID != actor.ID {
					debuffDurations[event.SpellID] += event.Timestamp.Sub(startTime).Seconds()
					delete(debuffStarts, event.SpellID)
				}
			}
		}
	}

	for spellID, since := range buffStarts {
		buffDurations[spellID] += end.Sub(since).Seconds()
	}
	for spellID, since := range debuffStarts {
		debuffDurations[spellID] += end.Sub(since).Seconds()
	}

	buffUptimes := map[int]float64{}
	for spellID, durationS := range buffDurations {
		if duration > 0 {
			buffUptimes[spellID] = durationS / duration
		}
	}
	debuffUptimes := map[int]float64{}
	for spellID, durationS := range debuffDurations {
		if duration > 0 {
			debuffUptimes[spellID] = durationS / duration
		}
	}

	activity := 1.0
	if duration > 0 {
		activity = 1 - idleSeconds/duration
	}
	if activity < 0 {
		activity = 0
	}

	findings, sections, scores, metrics := specs.Evaluate(def, specs.Snapshot{
		DurationSeconds: duration,
		ActivityPct:     activity,
		SpellCounts:     spellCounts,
		BuffUptimes:     buffUptimes,
		DebuffUptimes:   debuffUptimes,
		CooldownUses:    cooldownUses,
		OpenerHits:      openerHits,
		TotalCasts:      totalCasts,
	})

	sort.Slice(timeline, func(i, j int) bool {
		return timeline[i].Timestamp < timeline[j].Timestamp
	})

	return domain.AnalysisResult{
		Summary: domain.Summary{
			FightName:     fight.Name,
			FightType:     fight.Kind,
			ActorName:     actor.Name,
			SpecID:        def.ID,
			SpecName:      def.Name,
			Duration:      duration,
			ContentSource: fight.SourceType,
			TotalCasts:    totalCasts,
		},
		Scores:     scores,
		Findings:   findings,
		Sections:   sections,
		Timeline:   timeline,
		RawMetrics: metrics,
	}, nil
}

func isCastEvent(event domain.CombatEvent) bool {
	switch event.EventType {
	case "SPELL_CAST_SUCCESS", "SPELL_CAST_START":
		return event.SpellID > 0 && event.SourceGUID != ""
	default:
		return false
	}
}

func formatOffset(start, ts time.Time) string {
	diff := ts.Sub(start)
	minutes := int(diff.Minutes())
	seconds := int(diff.Seconds()) % 60
	return fmt.Sprintf("%02d:%02d", minutes, seconds)
}
