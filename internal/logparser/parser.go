package logparser

import (
	"bufio"
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/aidun/wowcoach/internal/domain"
)

var (
	tsRE = regexp.MustCompile(`^(\d{1,2}/\d{1,2}(?:[/ ]\d{4})?)\s+(\d{2}:\d{2}:\d{2}\.\d+)\s{2}(\w+)(?:,|\s{2})`)
)

var supportedEvents = map[string]struct{}{
	"SPELL_CAST_SUCCESS":      {},
	"SPELL_CAST_START":        {},
	"SPELL_CAST_FAILED":       {},
	"SPELL_MISSED":            {},
	"SPELL_AURA_APPLIED":      {},
	"SPELL_AURA_REMOVED":      {},
	"SPELL_AURA_APPLIED_DOSE": {},
	"SPELL_AURA_REMOVED_DOSE": {},
	"SWING_DAMAGE":            {},
	"SPELL_DAMAGE":            {},
	"ENCOUNTER_START":         {},
	"ENCOUNTER_END":           {},
	"CHALLENGE_MODE_START":    {},
	"CHALLENGE_MODE_END":      {},
	"UNIT_DIED":               {},
}

func ParseFile(path string) ([]domain.CombatEvent, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	events := make([]domain.CombatEvent, 0, 4096)
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		ev, ok := ParseLine(line)
		if ok {
			events = append(events, ev)
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	if len(events) == 0 {
		return nil, fmt.Errorf("no supported combat log events found in %s", path)
	}
	return events, nil
}

func ParseLine(line string) (domain.CombatEvent, bool) {
	match := tsRE.FindStringSubmatch(line)
	if match == nil {
		return domain.CombatEvent{}, false
	}
	eventType := match[3]
	if _, ok := supportedEvents[eventType]; !ok {
		return domain.CombatEvent{}, false
	}
	ts, err := parseTimestamp(match[1] + " " + match[2])
	if err != nil {
		return domain.CombatEvent{}, false
	}

	payload := strings.TrimSpace(line[len(match[0]):])
	if strings.HasPrefix(match[0], ",") {
		payload = strings.TrimPrefix(payload, ",")
	}
	fields := splitCSV(payload)
	event := domain.CombatEvent{
		Raw:       line,
		Timestamp: ts,
		EventType: eventType,
	}

	switch eventType {
	case "ENCOUNTER_START", "ENCOUNTER_END":
		parseEncounter(fields, &event)
	case "CHALLENGE_MODE_START", "CHALLENGE_MODE_END":
		parseChallenge(fields, &event)
	default:
		rest := parseBaseUnitFields(fields, &event)
		switch eventType {
		case "SPELL_CAST_SUCCESS", "SPELL_CAST_START", "SPELL_CAST_FAILED", "SPELL_MISSED", "SPELL_DAMAGE",
			"SPELL_AURA_APPLIED", "SPELL_AURA_REMOVED", "SPELL_AURA_APPLIED_DOSE", "SPELL_AURA_REMOVED_DOSE":
			rest = parseSpellPrefix(rest, &event)
		}
		parseEventSpecific(eventType, rest, &event)
	}
	return event, true
}

func parseTimestamp(raw string) (time.Time, error) {
	layouts := []string{
		"1/2/2006 15:04:05.9999999",
		"1/2/2006 15:04:05.999999",
		"1/2/2006 15:04:05.9999",
		"1/2/2006 15:04:05.999",
		"1/2 2006 15:04:05.9999999",
		"1/2 2006 15:04:05.999999",
		"1/2 2006 15:04:05.9999",
		"1/2 2006 15:04:05.999",
		"1/2 15:04:05.9999999",
		"1/2 15:04:05.999999",
		"1/2 15:04:05.9999",
		"1/2 15:04:05.999",
	}
	for _, layout := range layouts {
		ts, err := time.ParseInLocation(layout, raw, time.Local)
		if err == nil {
			if !strings.Contains(layout, "2006") {
				ts = ts.AddDate(time.Now().Year()-ts.Year(), 0, 0)
			}
			return ts, nil
		}
	}
	return time.Time{}, fmt.Errorf("cannot parse timestamp %q", raw)
}

func splitCSV(text string) []string {
	if text == "" {
		return nil
	}
	fields := make([]string, 0, 12)
	var current strings.Builder
	inQuotes := false
	for _, ch := range text {
		switch ch {
		case '"':
			inQuotes = !inQuotes
			current.WriteRune(ch)
		case ',':
			if inQuotes {
				current.WriteRune(ch)
				continue
			}
			fields = append(fields, strings.TrimSpace(current.String()))
			current.Reset()
		default:
			current.WriteRune(ch)
		}
	}
	fields = append(fields, strings.TrimSpace(current.String()))
	return fields
}

func parseBaseUnitFields(fields []string, event *domain.CombatEvent) []string {
	if len(fields) < 8 {
		return nil
	}
	event.SourceGUID = trimQuotes(fields[0])
	event.SourceName = trimQuotes(fields[1])
	event.SourceFlags = fields[2]
	event.DestGUID = trimQuotes(fields[4])
	event.DestName = trimQuotes(fields[5])
	event.DestFlags = fields[6]
	return fields[8:]
}

func parseSpellPrefix(fields []string, event *domain.CombatEvent) []string {
	if len(fields) < 3 {
		return nil
	}
	event.SpellID = safeInt(fields[0])
	event.SpellName = trimQuotes(fields[1])
	event.SpellSchool = fields[2]
	return fields[3:]
}

func parseEventSpecific(eventType string, fields []string, event *domain.CombatEvent) {
	switch eventType {
	case "SPELL_AURA_APPLIED", "SPELL_AURA_REMOVED":
		if len(fields) > 0 {
			event.AuraType = trimQuotes(fields[0])
			event.Extra = append(event.Extra, fields[1:]...)
		}
	case "SPELL_AURA_APPLIED_DOSE", "SPELL_AURA_REMOVED_DOSE":
		if len(fields) > 0 {
			event.AuraType = trimQuotes(fields[0])
		}
		if len(fields) > 1 {
			event.AuraStacks = safeInt(fields[1])
			event.Extra = append(event.Extra, fields[2:]...)
		}
	case "SPELL_DAMAGE", "SWING_DAMAGE":
		if len(fields) > 0 {
			event.Amount = safeInt(fields[0])
			event.Extra = append(event.Extra, fields[1:]...)
		}
	default:
		event.Extra = append(event.Extra, fields...)
	}
}

func parseEncounter(fields []string, event *domain.CombatEvent) {
	if len(fields) < 4 {
		return
	}
	event.EncounterID = safeInt(fields[0])
	event.EncounterName = trimQuotes(fields[1])
	event.DifficultyID = safeInt(fields[2])
	event.RaidSize = safeInt(fields[3])
	if len(fields) > 4 {
		event.Extra = append(event.Extra, fields[4:]...)
	}
}

func parseChallenge(fields []string, event *domain.CombatEvent) {
	if len(fields) == 0 {
		return
	}
	event.EncounterName = trimQuotes(fields[0])
	if len(fields) > 1 {
		event.EncounterID = safeInt(fields[1])
	}
	if len(fields) > 2 {
		event.DifficultyID = safeInt(fields[2])
	}
	event.Extra = append(event.Extra, fields[3:]...)
}

func safeInt(raw string) int {
	raw = strings.TrimSpace(raw)
	raw = trimQuotes(raw)
	if raw == "" || strings.EqualFold(raw, "nil") {
		return 0
	}
	if strings.HasPrefix(raw, "0x") || strings.HasPrefix(raw, "0X") {
		v, err := strconv.ParseInt(raw[2:], 16, 64)
		if err == nil {
			return int(v)
		}
	}
	v, err := strconv.Atoi(raw)
	if err != nil {
		return 0
	}
	return v
}

func trimQuotes(raw string) string {
	return strings.Trim(raw, "\"")
}
