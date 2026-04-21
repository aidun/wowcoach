package segments

import (
	"fmt"
	"sort"
	"strings"

	"github.com/aidun/wowcoach/internal/domain"
	"github.com/aidun/wowcoach/internal/specs"
)

func BuildFights(events []domain.CombatEvent) []domain.Fight {
	fights := make([]domain.Fight, 0, 16)
	var current *domain.Fight
	var mythic *domain.Fight

	for idx, event := range events {
		switch event.EventType {
		case "CHALLENGE_MODE_START":
			name := event.EncounterName
			if name == "" {
				name = "Mythic+"
			}
			fight := domain.Fight{
				ID:         fmt.Sprintf("fight-%d", len(fights)+1),
				Name:       name,
				Kind:       "mythic_plus",
				SourceType: "mythic_plus",
				Start:      event.Timestamp,
				StartIndex: idx,
			}
			mythic = &fight
			current = mythic
		case "CHALLENGE_MODE_END":
			if mythic == nil {
				continue
			}
			mythic.End = event.Timestamp
			mythic.EndIndex = idx
			fights = append(fights, *mythic)
			mythic = nil
			current = nil
		case "ENCOUNTER_START":
			if mythic != nil {
				continue
			}
			fight := domain.Fight{
				ID:         fmt.Sprintf("fight-%d", len(fights)+1),
				Name:       fallback(event.EncounterName, fmt.Sprintf("Encounter %d", event.EncounterID)),
				Kind:       "boss",
				SourceType: "raid",
				Start:      event.Timestamp,
				StartIndex: idx,
			}
			current = &fight
		case "ENCOUNTER_END":
			if mythic != nil {
				continue
			}
			if current == nil {
				continue
			}
			current.End = event.Timestamp
			current.EndIndex = idx
			fights = append(fights, *current)
			current = nil
		}
	}

	if mythic != nil {
		mythic.End = events[len(events)-1].Timestamp
		mythic.EndIndex = len(events) - 1
		fights = append(fights, *mythic)
	}
	if current != nil {
		current.End = events[len(events)-1].Timestamp
		current.EndIndex = len(events) - 1
		fights = append(fights, *current)
	}
	return fights
}

func DetectActors(fight domain.Fight, events []domain.CombatEvent) []domain.ActorRef {
	type actorState struct {
		Name     string
		Spells   map[int]int
		Detected map[string]struct{}
	}
	actors := map[string]*actorState{}
	for _, event := range SliceFightEvents(fight, events) {
		if !strings.HasPrefix(event.SourceGUID, "Player-") || event.SourceName == "" {
			continue
		}
		state := actors[event.SourceGUID]
		if state == nil {
			state = &actorState{
				Name:     event.SourceName,
				Spells:   map[int]int{},
				Detected: map[string]struct{}{},
			}
			actors[event.SourceGUID] = state
		}
		if event.SpellID > 0 {
			state.Spells[event.SpellID]++
		}
	}

	out := make([]domain.ActorRef, 0, len(actors))
	for guid, actor := range actors {
		detected := specs.DetectSpecs(actor.Spells)
		for _, specID := range detected {
			actor.Detected[specID] = struct{}{}
		}
		detected = detected[:0]
		for specID := range actor.Detected {
			detected = append(detected, specID)
		}
		sort.Strings(detected)
		className := "Unknown"
		if len(detected) > 0 {
			if def, ok := specs.Get(detected[0]); ok {
				className = def.Class
			}
		}
		out = append(out, domain.ActorRef{
			ID:            guid,
			Name:          actor.Name,
			Class:         className,
			DetectedSpecs: detected,
		})
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].Name < out[j].Name
	})
	return out
}

func SliceFightEvents(fight domain.Fight, events []domain.CombatEvent) []domain.CombatEvent {
	start := fight.StartIndex
	end := fight.EndIndex
	if start < 0 {
		start = 0
	}
	if end < start || end >= len(events) {
		end = len(events) - 1
	}
	return events[start : end+1]
}

func fallback(value, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return value
}
