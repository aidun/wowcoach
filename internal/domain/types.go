package domain

import "time"

type CombatEvent struct {
	Raw           string    `json:"raw"`
	Timestamp     time.Time `json:"timestamp"`
	EventType     string    `json:"eventType"`
	SourceGUID    string    `json:"sourceGUID"`
	SourceName    string    `json:"sourceName"`
	SourceFlags   string    `json:"sourceFlags"`
	DestGUID      string    `json:"destGUID"`
	DestName      string    `json:"destName"`
	DestFlags     string    `json:"destFlags"`
	SpellID       int       `json:"spellID"`
	SpellName     string    `json:"spellName"`
	SpellSchool   string    `json:"spellSchool"`
	AuraType      string    `json:"auraType"`
	AuraStacks    int       `json:"auraStacks"`
	EncounterID   int       `json:"encounterID"`
	EncounterName string    `json:"encounterName"`
	DifficultyID  int       `json:"difficultyID"`
	RaidSize      int       `json:"raidSize"`
	Amount        int       `json:"amount"`
	Extra         []string  `json:"extra"`
}

type Fight struct {
	ID         string    `json:"id"`
	Name       string    `json:"name"`
	Kind       string    `json:"kind"`
	SourceType string    `json:"sourceType"`
	Start      time.Time `json:"start"`
	End        time.Time `json:"end"`
	StartIndex int       `json:"-"`
	EndIndex   int       `json:"-"`
}

type FightRef struct {
	ID         string    `json:"id"`
	Name       string    `json:"name"`
	Kind       string    `json:"kind"`
	SourceType string    `json:"sourceType"`
	Start      time.Time `json:"start"`
	End        time.Time `json:"end"`
	Duration   float64   `json:"duration"`
}

type ActorRef struct {
	ID            string   `json:"id"`
	Name          string   `json:"name"`
	Class         string   `json:"class"`
	DetectedSpecs []string `json:"detectedSpecs"`
}

type ImportSummary struct {
	Path          string     `json:"path"`
	EventCount    int        `json:"eventCount"`
	FightCount    int        `json:"fightCount"`
	ActorCount    int        `json:"actorCount"`
	SourceTypes   []string   `json:"sourceTypes"`
	Fights        []FightRef `json:"fights"`
	DetectedSpecs []string   `json:"detectedSpecs"`
}

type Score struct {
	Key    string  `json:"key"`
	Label  string  `json:"label"`
	Value  float64 `json:"value"`
	Max    float64 `json:"max"`
	Detail string  `json:"detail"`
}

type Finding struct {
	ID             string   `json:"id"`
	Title          string   `json:"title"`
	Severity       string   `json:"severity"`
	Impact         string   `json:"impact"`
	Explanation    string   `json:"explanation"`
	Recommendation string   `json:"recommendation"`
	Timestamp      *string  `json:"timestamp,omitempty"`
	Window         *string  `json:"window,omitempty"`
	Tags           []string `json:"tags,omitempty"`
}

type Metric struct {
	Key      string  `json:"key"`
	Label    string  `json:"label"`
	Value    float64 `json:"value"`
	Display  string  `json:"display"`
	Category string  `json:"category"`
}

type TimelineEvent struct {
	Timestamp string   `json:"timestamp"`
	Label     string   `json:"label"`
	Kind      string   `json:"kind"`
	Tags      []string `json:"tags,omitempty"`
}

type ReportSection struct {
	ID      string   `json:"id"`
	Title   string   `json:"title"`
	Summary string   `json:"summary"`
	Lines   []string `json:"lines"`
}

type Summary struct {
	FightName     string  `json:"fightName"`
	FightType     string  `json:"fightType"`
	ActorName     string  `json:"actorName"`
	SpecID        string  `json:"specID"`
	SpecName      string  `json:"specName"`
	Duration      float64 `json:"duration"`
	ContentSource string  `json:"contentSource"`
	TotalCasts    int     `json:"totalCasts"`
}

type AnalysisResult struct {
	Summary    Summary         `json:"summary"`
	Scores     []Score         `json:"scores"`
	Findings   []Finding       `json:"findings"`
	Sections   []ReportSection `json:"sections"`
	Timeline   []TimelineEvent `json:"timeline"`
	RawMetrics []Metric        `json:"rawMetrics"`
}

func ToFightRefs(fights []Fight) []FightRef {
	out := make([]FightRef, 0, len(fights))
	for _, fight := range fights {
		out = append(out, FightRef{
			ID:         fight.ID,
			Name:       fight.Name,
			Kind:       fight.Kind,
			SourceType: fight.SourceType,
			Start:      fight.Start,
			End:        fight.End,
			Duration:   fight.End.Sub(fight.Start).Seconds(),
		})
	}
	return out
}
