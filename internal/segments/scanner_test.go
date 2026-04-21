package segments_test

import (
	"path/filepath"
	"testing"

	"github.com/aidun/wowcoach/internal/logparser"
	"github.com/aidun/wowcoach/internal/segments"
)

func TestBuildFightsAndActors(t *testing.T) {
	events, err := logparser.ParseFile(filepath.Join("..", "..", "testdata", "sample_retail.log"))
	if err != nil {
		t.Fatal(err)
	}
	fights := segments.BuildFights(events)
	if len(fights) != 2 {
		t.Fatalf("expected 2 fights, got %d", len(fights))
	}
	actors := segments.DetectActors(fights[1], events)
	if len(actors) < 2 {
		t.Fatalf("expected multiple actors, got %d", len(actors))
	}
}
