package specs

import (
	"fmt"
	"math"
	"sort"

	"github.com/aidun/wowcoach/internal/domain"
)

type Cooldown struct {
	SpellID   int
	Name      string
	CooldownS float64
}

type AuraGoal struct {
	SpellID  int
	Name     string
	Target   float64
	Category string
}

type CoreSpellGoal struct {
	SpellID     int
	Name        string
	MinPerMin   float64
	Description string
}

type Definition struct {
	ID              string
	Name            string
	Class           string
	SignatureSpells []int
	Cooldowns       []Cooldown
	TrackedBuffs    []AuraGoal
	TrackedDebuffs  []AuraGoal
	CoreSpells      []CoreSpellGoal
	OpenerSpells    []int
	MinActivity     float64
}

type Snapshot struct {
	DurationSeconds float64
	ActivityPct     float64
	SpellCounts     map[int]int
	BuffUptimes     map[int]float64
	DebuffUptimes   map[int]float64
	CooldownUses    map[int]int
	OpenerHits      map[int]bool
	TotalCasts      int
}

var definitions = map[string]Definition{
	"frost_mage": {
		ID:              "frost_mage",
		Name:            "Frost Mage",
		Class:           "Mage",
		SignatureSpells: []int{116, 44614, 30455, 12472},
		Cooldowns: []Cooldown{
			{SpellID: 12472, Name: "Icy Veins", CooldownS: 120},
			{SpellID: 190319, Name: "Combustion of Frostfire", CooldownS: 90},
		},
		TrackedBuffs: []AuraGoal{
			{SpellID: 12472, Name: "Icy Veins", Target: 0.18, Category: "buff"},
			{SpellID: 190447, Name: "Brain Freeze", Target: 0.12, Category: "proc"},
		},
		TrackedDebuffs: []AuraGoal{
			{SpellID: 1221389, Name: "Freezing", Target: 0.25, Category: "debuff"},
		},
		CoreSpells: []CoreSpellGoal{
			{SpellID: 116, Name: "Frostbolt", MinPerMin: 10, Description: "core generator"},
			{SpellID: 30455, Name: "Ice Lance", MinPerMin: 8, Description: "primary spender"},
		},
		OpenerSpells: []int{116, 12472},
		MinActivity:  0.78,
	},
	"arcane_mage": {
		ID:              "arcane_mage",
		Name:            "Arcane Mage",
		Class:           "Mage",
		SignatureSpells: []int{30451, 321507, 365350},
		Cooldowns: []Cooldown{
			{SpellID: 365350, Name: "Arcane Surge", CooldownS: 90},
			{SpellID: 80353, Name: "Time Warp", CooldownS: 300},
		},
		TrackedBuffs: []AuraGoal{
			{SpellID: 365362, Name: "Arcane Surge", Target: 0.12, Category: "buff"},
		},
		CoreSpells: []CoreSpellGoal{
			{SpellID: 30451, Name: "Arcane Blast", MinPerMin: 12, Description: "main cast"},
			{SpellID: 44425, Name: "Arcane Barrage", MinPerMin: 3, Description: "resource reset"},
		},
		OpenerSpells: []int{365350, 30451},
		MinActivity:  0.76,
	},
	"devastation_evoker": {
		ID:              "devastation_evoker",
		Name:            "Devastation Evoker",
		Class:           "Evoker",
		SignatureSpells: []int{356995, 359073, 375087},
		Cooldowns: []Cooldown{
			{SpellID: 375087, Name: "Dragonrage", CooldownS: 120},
			{SpellID: 359073, Name: "Eternity Surge", CooldownS: 30},
		},
		TrackedBuffs: []AuraGoal{
			{SpellID: 375087, Name: "Dragonrage", Target: 0.14, Category: "buff"},
		},
		CoreSpells: []CoreSpellGoal{
			{SpellID: 356995, Name: "Disintegrate", MinPerMin: 5, Description: "essence spender"},
			{SpellID: 362969, Name: "Azure Strike", MinPerMin: 3, Description: "filler"},
		},
		OpenerSpells: []int{375087, 359073},
		MinActivity:  0.72,
	},
	"augmentation_evoker": {
		ID:              "augmentation_evoker",
		Name:            "Augmentation Evoker",
		Class:           "Evoker",
		SignatureSpells: []int{395152, 403631, 364342},
		Cooldowns: []Cooldown{
			{SpellID: 395152, Name: "Ebon Might", CooldownS: 30},
			{SpellID: 403631, Name: "Breath of Eons", CooldownS: 120},
		},
		TrackedBuffs: []AuraGoal{
			{SpellID: 395152, Name: "Ebon Might", Target: 0.50, Category: "buff"},
		},
		CoreSpells: []CoreSpellGoal{
			{SpellID: 364342, Name: "Upheaval", MinPerMin: 2, Description: "empower cycle"},
			{SpellID: 396286, Name: "Prescience", MinPerMin: 4, Description: "support upkeep"},
		},
		OpenerSpells: []int{395152, 403631},
		MinActivity:  0.70,
	},
	"unholy_death_knight": {
		ID:              "unholy_death_knight",
		Name:            "Unholy Death Knight",
		Class:           "Death Knight",
		SignatureSpells: []int{85948, 55090, 63560, 42650},
		Cooldowns: []Cooldown{
			{SpellID: 63560, Name: "Dark Transformation", CooldownS: 60},
			{SpellID: 42650, Name: "Army of the Dead", CooldownS: 180},
		},
		TrackedDebuffs: []AuraGoal{
			{SpellID: 191587, Name: "Virulent Plague", Target: 0.75, Category: "disease"},
		},
		TrackedBuffs: []AuraGoal{
			{SpellID: 81340, Name: "Sudden Doom", Target: 0.12, Category: "proc"},
		},
		CoreSpells: []CoreSpellGoal{
			{SpellID: 85948, Name: "Festering Strike", MinPerMin: 3, Description: "wound builder"},
			{SpellID: 55090, Name: "Scourge Strike", MinPerMin: 6, Description: "wound spender"},
		},
		OpenerSpells: []int{63560, 85948},
		MinActivity:  0.73,
	},
	"feral_druid": {
		ID:              "feral_druid",
		Name:            "Feral Druid",
		Class:           "Druid",
		SignatureSpells: []int{1822, 1079, 5217, 22568},
		Cooldowns: []Cooldown{
			{SpellID: 5217, Name: "Tiger's Fury", CooldownS: 30},
			{SpellID: 22568, Name: "Ferocious Bite", CooldownS: 0},
		},
		TrackedBuffs: []AuraGoal{
			{SpellID: 5217, Name: "Tiger's Fury", Target: 0.18, Category: "buff"},
		},
		TrackedDebuffs: []AuraGoal{
			{SpellID: 1822, Name: "Rake", Target: 0.80, Category: "bleed"},
			{SpellID: 1079, Name: "Rip", Target: 0.80, Category: "bleed"},
		},
		CoreSpells: []CoreSpellGoal{
			{SpellID: 1822, Name: "Rake", MinPerMin: 2, Description: "bleed maintenance"},
			{SpellID: 22568, Name: "Ferocious Bite", MinPerMin: 2, Description: "combo spender"},
		},
		OpenerSpells: []int{5217, 1822, 1079},
		MinActivity:  0.80,
	},
}

func Get(id string) (Definition, bool) {
	def, ok := definitions[id]
	return def, ok
}

func KnownSpecIDs() []string {
	keys := make([]string, 0, len(definitions))
	for key := range definitions {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

func DetectSpecs(spellCounts map[int]int) []string {
	type hit struct {
		id    string
		score int
	}
	hits := make([]hit, 0, len(definitions))
	for _, def := range definitions {
		score := 0
		for _, spellID := range def.SignatureSpells {
			score += spellCounts[spellID]
		}
		if score > 0 {
			hits = append(hits, hit{id: def.ID, score: score})
		}
	}
	sort.Slice(hits, func(i, j int) bool {
		if hits[i].score == hits[j].score {
			return hits[i].id < hits[j].id
		}
		return hits[i].score > hits[j].score
	})
	out := make([]string, 0, len(hits))
	for _, hit := range hits {
		out = append(out, hit.id)
	}
	return out
}

func Evaluate(def Definition, snap Snapshot) ([]domain.Finding, []domain.ReportSection, []domain.Score, []domain.Metric) {
	findings := make([]domain.Finding, 0, 12)
	sections := make([]domain.ReportSection, 0, 4)
	metrics := make([]domain.Metric, 0, 16)
	scores := make([]domain.Score, 0, 4)

	activityScore := clampScore(snap.ActivityPct * 100)
	scores = append(scores, domain.Score{
		Key:    "activity",
		Label:  "Activity",
		Value:  activityScore,
		Max:    100,
		Detail: fmt.Sprintf("%.0f%% active cast coverage", snap.ActivityPct*100),
	})
	metrics = append(metrics, domain.Metric{
		Key:      "activity_pct",
		Label:    "Activity",
		Value:    snap.ActivityPct * 100,
		Display:  fmt.Sprintf("%.0f%%", snap.ActivityPct*100),
		Category: "rotation",
	})
	if snap.ActivityPct < def.MinActivity {
		findings = append(findings, domain.Finding{
			ID:             "activity-low",
			Title:          "Low rotational activity",
			Severity:       "major",
			Impact:         "high",
			Explanation:    fmt.Sprintf("%s spent too much of the fight without meaningful casts or spenders.", def.Name),
			Recommendation: "Reduce dead air between globals and align fillers so burst windows stay dense.",
			Tags:           []string{"rotation", "activity"},
		})
	}

	cooldownLines := make([]string, 0, len(def.Cooldowns))
	cooldownScore := 100.0
	for _, cooldown := range def.Cooldowns {
		uses := snap.CooldownUses[cooldown.SpellID]
		expected := expectedCooldownUses(snap.DurationSeconds, cooldown.CooldownS)
		ratio := 1.0
		if expected > 0 {
			ratio = math.Min(1, float64(uses)/float64(expected))
		}
		cooldownScore += ratio * 100
		label := fmt.Sprintf("%s: %d / %d planned uses", cooldown.Name, uses, expected)
		cooldownLines = append(cooldownLines, label)
		metrics = append(metrics, domain.Metric{
			Key:      fmt.Sprintf("cooldown_%d", cooldown.SpellID),
			Label:    cooldown.Name,
			Value:    float64(uses),
			Display:  label,
			Category: "cooldowns",
		})
		if uses < expected {
			findings = append(findings, domain.Finding{
				ID:             fmt.Sprintf("cd-%d", cooldown.SpellID),
				Title:          cooldown.Name + " underused",
				Severity:       severityByGap(expected - uses),
				Impact:         "high",
				Explanation:    fmt.Sprintf("%s only used %d times although the fight length allowed %d planned windows.", cooldown.Name, uses, expected),
				Recommendation: "Anchor major cooldowns earlier and avoid drifting them out of later windows.",
				Tags:           []string{"cooldowns", def.ID},
			})
		}
	}
	if len(def.Cooldowns) > 0 {
		cooldownScore = cooldownScore / float64(len(def.Cooldowns)+1)
	}
	scores = append(scores, domain.Score{
		Key:    "cooldowns",
		Label:  "Cooldowns",
		Value:  clampScore(cooldownScore),
		Max:    100,
		Detail: "Major windows versus expected opportunities",
	})
	sections = append(sections, domain.ReportSection{
		ID:      "cooldowns",
		Title:   "Cooldowns",
		Summary: "Major cooldown timing and realized windows.",
		Lines:   cooldownLines,
	})

	uptimeLines := []string{}
	uptimeValues := []float64{}
	for _, aura := range append(def.TrackedBuffs, def.TrackedDebuffs...) {
		value := snap.BuffUptimes[aura.SpellID]
		if value == 0 {
			value = snap.DebuffUptimes[aura.SpellID]
		}
		uptimeValues = append(uptimeValues, value)
		display := fmt.Sprintf("%s: %.0f%% uptime", aura.Name, value*100)
		uptimeLines = append(uptimeLines, display)
		metrics = append(metrics, domain.Metric{
			Key:      fmt.Sprintf("uptime_%d", aura.SpellID),
			Label:    aura.Name,
			Value:    value * 100,
			Display:  fmt.Sprintf("%.0f%%", value*100),
			Category: aura.Category,
		})
		if value < aura.Target {
			findings = append(findings, domain.Finding{
				ID:             fmt.Sprintf("uptime-%d", aura.SpellID),
				Title:          aura.Name + " uptime below target",
				Severity:       "moderate",
				Impact:         "medium",
				Explanation:    fmt.Sprintf("%s sat at %.0f%% uptime against a target of %.0f%%.", aura.Name, value*100, aura.Target*100),
				Recommendation: "Plan refreshes earlier and protect key buff or debuff windows during movement.",
				Tags:           []string{"uptime", def.ID},
			})
		}
	}
	uptimeScore := 100.0
	if len(uptimeValues) > 0 {
		sum := 0.0
		for _, value := range uptimeValues {
			sum += value
		}
		uptimeScore = clampScore((sum / float64(len(uptimeValues))) * 100)
	}
	scores = append(scores, domain.Score{
		Key:    "uptime",
		Label:  "Uptime",
		Value:  uptimeScore,
		Max:    100,
		Detail: "Buff, debuff and maintenance coverage",
	})
	sections = append(sections, domain.ReportSection{
		ID:      "uptime",
		Title:   "Buffs and Uptime",
		Summary: "Key maintenance effects for the selected spec.",
		Lines:   uptimeLines,
	})

	coreLines := []string{}
	coreScore := 0.0
	for _, goal := range def.CoreSpells {
		perMinute := 0.0
		if snap.DurationSeconds > 0 {
			perMinute = float64(snap.SpellCounts[goal.SpellID]) / (snap.DurationSeconds / 60)
		}
		coreScore += math.Min(1, perMinute/goal.MinPerMin) * 100
		line := fmt.Sprintf("%s: %.1f casts/min", goal.Name, perMinute)
		coreLines = append(coreLines, line)
		metrics = append(metrics, domain.Metric{
			Key:      fmt.Sprintf("casts_%d", goal.SpellID),
			Label:    goal.Name,
			Value:    perMinute,
			Display:  line,
			Category: "rotation",
		})
		if perMinute < goal.MinPerMin {
			findings = append(findings, domain.Finding{
				ID:             fmt.Sprintf("core-%d", goal.SpellID),
				Title:          goal.Name + " frequency too low",
				Severity:       "moderate",
				Impact:         "medium",
				Explanation:    fmt.Sprintf("%s averaged %.1f casts per minute, below the target %.1f for %s.", goal.Name, perMinute, goal.MinPerMin, goal.Description),
				Recommendation: "Recenter the rotation around the spec's core builder and spender cadence.",
				Tags:           []string{"rotation", def.ID},
			})
		}
	}
	if len(def.CoreSpells) > 0 {
		coreScore = coreScore / float64(len(def.CoreSpells))
	} else {
		coreScore = 100
	}
	scores = append(scores, domain.Score{
		Key:    "rotation",
		Label:  "Rotation",
		Value:  clampScore(coreScore),
		Max:    100,
		Detail: "Core spell cadence and throughput rhythm",
	})
	sections = append(sections, domain.ReportSection{
		ID:      "rotation",
		Title:   "Spec Focus",
		Summary: def.Name + " core spell cadence.",
		Lines:   coreLines,
	})

	missingOpener := []string{}
	for _, spellID := range def.OpenerSpells {
		if !snap.OpenerHits[spellID] {
			missingOpener = append(missingOpener, spellName(def, spellID))
		}
	}
	if len(missingOpener) > 0 {
		findings = append(findings, domain.Finding{
			ID:             "opener-missing",
			Title:          "Opener key pieces missing",
			Severity:       "moderate",
			Impact:         "medium",
			Explanation:    fmt.Sprintf("The opener did not include all planned anchors: %v.", missingOpener),
			Recommendation: "Front-load the opener so your first burst cycle contains the key buttons for the spec.",
			Tags:           []string{"opener", def.ID},
		})
	}

	sort.Slice(findings, func(i, j int) bool {
		return findings[i].Severity > findings[j].Severity
	})
	overall := clampScore((activityScore + cooldownScore + uptimeScore + coreScore) / 4)
	scores = append([]domain.Score{{
		Key:    "overall",
		Label:  "Overall",
		Value:  overall,
		Max:    100,
		Detail: "Weighted synthesis across activity, cooldowns, uptime and spec cadence",
	}}, scores...)
	return findings, sections, scores, metrics
}

func expectedCooldownUses(duration, cooldown float64) int {
	if cooldown <= 0 {
		return 0
	}
	if duration <= cooldown {
		return 1
	}
	return int(math.Floor(duration/cooldown)) + 1
}

func severityByGap(gap int) string {
	switch {
	case gap >= 2:
		return "major"
	case gap == 1:
		return "moderate"
	default:
		return "minor"
	}
}

func clampScore(value float64) float64 {
	switch {
	case value < 0:
		return 0
	case value > 100:
		return 100
	default:
		return math.Round(value*10) / 10
	}
}

func spellName(def Definition, spellID int) string {
	for _, cd := range def.Cooldowns {
		if cd.SpellID == spellID {
			return cd.Name
		}
	}
	for _, aura := range def.TrackedBuffs {
		if aura.SpellID == spellID {
			return aura.Name
		}
	}
	for _, aura := range def.TrackedDebuffs {
		if aura.SpellID == spellID {
			return aura.Name
		}
	}
	for _, spell := range def.CoreSpells {
		if spell.SpellID == spellID {
			return spell.Name
		}
	}
	return fmt.Sprintf("Spell %d", spellID)
}
