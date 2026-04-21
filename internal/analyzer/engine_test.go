package analyzer_test

import (
	"path/filepath"
	"testing"

	"github.com/aidun/wowcoach/internal/analyzer"
	"github.com/aidun/wowcoach/internal/logparser"
	"github.com/aidun/wowcoach/internal/segments"
)

func TestAnalyzeFightProducesStructuredResult(t *testing.T) {
	events, err := logparser.ParseFile(filepath.Join("..", "..", "testdata", "sample_retail.log"))
	if err != nil {
		t.Fatal(err)
	}
	fights := segments.BuildFights(events)
	actors := segments.DetectActors(fights[0], events)
	engine := analyzer.NewEngine()
	result, err := engine.Analyze(events, fights[0], actors[0], "frost_mage")
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Scores) == 0 {
		t.Fatal("expected scores")
	}
	if len(result.Sections) == 0 {
		t.Fatal("expected sections")
	}
	if result.Summary.SpecID != "frost_mage" {
		t.Fatalf("unexpected spec %s", result.Summary.SpecID)
	}
}
