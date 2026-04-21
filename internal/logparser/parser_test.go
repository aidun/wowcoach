package logparser_test

import (
	"testing"

	"github.com/aidun/wowcoach/internal/logparser"
)

func TestParseEncounterStart(t *testing.T) {
	line := `4/4 2026 12:00:01.000  ENCOUNTER_START  2093,"Tindral Sageswift",14,20`
	ev, ok := logparser.ParseLine(line)
	if !ok {
		t.Fatal("expected event")
	}
	if ev.EventType != "ENCOUNTER_START" {
		t.Fatalf("unexpected event type %s", ev.EventType)
	}
	if ev.EncounterName != "Tindral Sageswift" {
		t.Fatalf("unexpected encounter %s", ev.EncounterName)
	}
}

func TestParseRetailCommaSeparatedLine(t *testing.T) {
	line := `4/1/2026 20:00:01.0000  SPELL_CAST_SUCCESS,Player-1-AABBCCDD,"Frosty",0x514,0x0,Creature-0-1-1-1-90001,"Boss",0xa48,0x0,116,"Frostbolt",0x10`
	ev, ok := logparser.ParseLine(line)
	if !ok {
		t.Fatal("expected event")
	}
	if ev.SpellID != 116 {
		t.Fatalf("unexpected spell id %d", ev.SpellID)
	}
	if ev.SourceName != "Frosty" {
		t.Fatalf("unexpected source %s", ev.SourceName)
	}
}

func TestIgnoreUnsupportedEvent(t *testing.T) {
	line := `4/4 2026 12:00:01.000  COMBAT_LOG_VERSION  something`
	if _, ok := logparser.ParseLine(line); ok {
		t.Fatal("expected unsupported event to be ignored")
	}
}
