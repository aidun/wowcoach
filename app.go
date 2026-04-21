package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"

	"github.com/aidun/wowcoach/internal/analyzer"
	"github.com/aidun/wowcoach/internal/domain"
	"github.com/aidun/wowcoach/internal/logparser"
	"github.com/aidun/wowcoach/internal/report"
	"github.com/aidun/wowcoach/internal/segments"
	"github.com/aidun/wowcoach/internal/specs"
	"github.com/wailsapp/wails/v2/pkg/runtime"
)

type App struct {
	ctx context.Context

	mu     sync.RWMutex
	state  *appState
	engine *analyzer.Engine
}

type appState struct {
	path          string
	events        []domain.CombatEvent
	fights        []domain.Fight
	actorsByFight map[string][]domain.ActorRef
}

func NewApp() *App {
	return &App{
		engine: analyzer.NewEngine(),
	}
}

func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
}

func (a *App) SelectLogFile() (string, error) {
	if a.ctx == nil {
		return "", fmt.Errorf("app context not ready")
	}
	return runtime.OpenFileDialog(a.ctx, runtime.OpenDialogOptions{
		Title: "Select WoWCombatLog.txt",
		Filters: []runtime.FileFilter{
			{
				DisplayName: "Combat Logs",
				Pattern:     "*.txt;*.log",
			},
		},
	})
}

func (a *App) OpenLog(path string) (domain.ImportSummary, error) {
	resolved := strings.TrimSpace(path)
	if resolved == "" {
		return domain.ImportSummary{}, fmt.Errorf("path is required")
	}
	events, err := logparser.ParseFile(resolved)
	if err != nil {
		return domain.ImportSummary{}, err
	}
	fights := segments.BuildFights(events)
	actorsByFight := make(map[string][]domain.ActorRef, len(fights))
	actorCount := 0
	for _, fight := range fights {
		actors := segments.DetectActors(fight, events)
		actorsByFight[fight.ID] = actors
		actorCount += len(actors)
	}
	contentTypes := make(map[string]struct{})
	for _, fight := range fights {
		contentTypes[fight.SourceType] = struct{}{}
	}
	sources := make([]string, 0, len(contentTypes))
	for source := range contentTypes {
		sources = append(sources, source)
	}
	sort.Strings(sources)

	a.mu.Lock()
	a.state = &appState{
		path:          resolved,
		events:        events,
		fights:        fights,
		actorsByFight: actorsByFight,
	}
	a.mu.Unlock()

	return domain.ImportSummary{
		Path:          resolved,
		EventCount:    len(events),
		FightCount:    len(fights),
		ActorCount:    actorCount,
		SourceTypes:   sources,
		Fights:        domain.ToFightRefs(fights),
		DetectedSpecs: specs.KnownSpecIDs(),
	}, nil
}

func (a *App) ListFights() []domain.FightRef {
	a.mu.RLock()
	defer a.mu.RUnlock()
	if a.state == nil {
		return nil
	}
	return domain.ToFightRefs(a.state.fights)
}

func (a *App) ListActors(fightID string) []domain.ActorRef {
	a.mu.RLock()
	defer a.mu.RUnlock()
	if a.state == nil {
		return nil
	}
	actors := a.state.actorsByFight[fightID]
	out := make([]domain.ActorRef, len(actors))
	copy(out, actors)
	return out
}

func (a *App) AnalyzeFight(fightID, actorID, specID string) (domain.AnalysisResult, error) {
	a.mu.RLock()
	state := a.state
	a.mu.RUnlock()
	if state == nil {
		return domain.AnalysisResult{}, fmt.Errorf("no log loaded")
	}
	fight, ok := findFight(state.fights, fightID)
	if !ok {
		return domain.AnalysisResult{}, fmt.Errorf("fight not found")
	}
	actor, ok := findActor(state.actorsByFight[fightID], actorID)
	if !ok {
		return domain.AnalysisResult{}, fmt.Errorf("actor not found")
	}
	if _, ok := specs.Get(specID); !ok {
		return domain.AnalysisResult{}, fmt.Errorf("unsupported spec: %s", specID)
	}
	return a.engine.Analyze(state.events, fight, actor, specID)
}

func (a *App) ExportReport(fightID, actorID, specID, format string) (string, error) {
	if strings.TrimSpace(format) == "" {
		format = "html"
	}
	if !strings.EqualFold(format, "html") {
		return "", fmt.Errorf("unsupported export format: %s", format)
	}
	result, err := a.AnalyzeFight(fightID, actorID, specID)
	if err != nil {
		return "", err
	}
	filename := sanitizeFileName(fmt.Sprintf("%s-%s-%s.html", fightID, actorID, specID))
	outPath := filepath.Join(os.TempDir(), filename)
	if err := os.WriteFile(outPath, []byte(report.RenderHTML(result)), 0o644); err != nil {
		return "", err
	}
	return outPath, nil
}

func findFight(fights []domain.Fight, fightID string) (domain.Fight, bool) {
	for _, fight := range fights {
		if fight.ID == fightID {
			return fight, true
		}
	}
	return domain.Fight{}, false
}

func findActor(actors []domain.ActorRef, actorID string) (domain.ActorRef, bool) {
	for _, actor := range actors {
		if actor.ID == actorID {
			return actor, true
		}
	}
	return domain.ActorRef{}, false
}

func sanitizeFileName(name string) string {
	replacer := strings.NewReplacer("/", "-", "\\", "-", " ", "-", ":", "-", "\"", "")
	return replacer.Replace(name)
}
