"""
parser.py - Parses WoW combat log lines into structured CombatEvent objects.

Supported event types:
    SPELL_CAST_SUCCESS, SPELL_CAST_START, SPELL_MISSED,
    SPELL_AURA_APPLIED, SPELL_AURA_REMOVED,
    SWING_DAMAGE, ENCOUNTER_START, ENCOUNTER_END

WoW combat log format (TWW / 11.x):
    TIMESTAMP  EVENT_TYPE  sourceGUID,sourceName,sourceFlags,sourceRaidFlags,
                           destGUID,destName,destFlags,destRaidFlags,
                           [event-specific fields...]

Timestamp format: "M/D YYYY HH:MM:SS.mmm"
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

_log = logging.getLogger("wowcoach.parser")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_EVENTS = frozenset(
    [
        "SPELL_CAST_SUCCESS",
        "SPELL_CAST_START",
        "SPELL_CAST_FAILED",
        "SPELL_MISSED",
        "SPELL_AURA_APPLIED",
        "SPELL_AURA_REMOVED",
        "SPELL_AURA_APPLIED_DOSE",
        "SPELL_AURA_REMOVED_DOSE",
        "SWING_DAMAGE",
        "ENCOUNTER_START",
        "ENCOUNTER_END",
        "CHALLENGE_MODE_START",
        "CHALLENGE_MODE_END",
        "UNIT_DIED",
    ]
)

# Regex for the timestamp + event_type prefix.
# Supports all known WoW combat log formats:
#   Real WoW Midnight: "4/1/2026 12:34:56.5032  SPELL_CAST_SUCCESS,..."
#   Test (with year):  "4/1 2026 12:34:56.789  SPELL_CAST_SUCCESS  ..."
#   Test (no year):    "4/1 12:34:56.789  SPELL_CAST_SUCCESS  ..."
#
# Groups: (1) date part, (2) time part, (3) event type
# Field separator after event type: comma (real logs) or two spaces (tests)
_TS_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}(?:[/ ]\d{4})?)\s+(\d{2}:\d{2}:\d{2}\.\d+)\s{2}(\w+)(?:,|\s{2})"
)

# Player GUID prefix (player characters start with "Player-")
_PLAYER_GUID_PREFIX = "Player-"


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class CombatEvent:
    """Structured representation of a single combat log event."""

    raw: str                        # Original unparsed line
    timestamp: datetime             # Parsed timestamp
    event_type: str                 # e.g. SPELL_CAST_SUCCESS

    # Source unit
    source_guid: str = ""
    source_name: str = ""
    source_flags: str = ""
    source_raid_flags: str = ""

    # Destination unit
    dest_guid: str = ""
    dest_name: str = ""
    dest_flags: str = ""
    dest_raid_flags: str = ""

    # Spell/ability info (present on most events)
    spell_id: Optional[int] = None
    spell_name: str = ""
    spell_school: str = ""

    # Buff/debuff type for AURA events: "BUFF" | "DEBUFF"
    aura_type: str = ""

    # Stack count for DOSE events
    aura_stacks: Optional[int] = None

    # Encounter info
    encounter_id: Optional[int] = None
    encounter_name: str = ""
    difficulty_id: Optional[int] = None
    raid_size: Optional[int] = None

    # Amount info (SWING_DAMAGE, SPELL_DAMAGE, etc.)
    amount: Optional[int] = None
    overkill: Optional[int] = None
    school: Optional[int] = None
    resisted: Optional[int] = None
    blocked: Optional[int] = None
    absorbed: Optional[int] = None
    critical: Optional[bool] = None

    # Miss type for SPELL_MISSED
    miss_type: str = ""

    # Extra unparsed fields (anything beyond what we explicitly parse)
    extra: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _csv_split(text: str) -> list[str]:
    """
    Split a comma-separated string respecting quoted fields.
    WoW log strings are wrapped in double-quotes; numbers/flags are bare.
    """
    fields: list[str] = []
    current: list[str] = []
    in_quote = False
    for ch in text:
        if ch == '"':
            in_quote = not in_quote
        elif ch == "," and not in_quote:
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    return fields


def _parse_ts(ts_str: str) -> datetime:
    """Parse WoW timestamp, trying all known formats."""
    ts = ts_str.strip()
    for fmt in (
        "%m/%d/%Y %H:%M:%S.%f",   # real WoW Midnight: M/D/YYYY HH:MM:SS.fraction
        "%m/%d %Y %H:%M:%S.%f",   # test format with year: M/D YYYY HH:MM:SS.mmm
        "%m/%d %H:%M:%S.%f",      # test format no year: M/D HH:MM:SS.mmm
    ):
        try:
            dt = datetime.strptime(ts, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=datetime.now().year)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {ts!r}")


def _safe_int(value: str) -> Optional[int]:
    try:
        v = value.strip()
        if v.startswith("0x") or v.startswith("0X"):
            return int(v, 16)
        return int(v)
    except (ValueError, AttributeError):
        return None


def _safe_bool_nil(value: str) -> Optional[bool]:
    v = value.strip().lower()
    if v in ("1", "true"):
        return True
    if v in ("0", "false", "nil"):
        return False
    return None


# ---------------------------------------------------------------------------
# Per-event-type payload parsers
# ---------------------------------------------------------------------------


def _parse_base_unit_fields(fields: list[str], event: CombatEvent) -> list[str]:
    """
    Consume the 8 standard unit fields from the front of *fields*.
    Returns remaining fields.
    """
    if len(fields) >= 8:
        event.source_guid  = fields[0]
        event.source_name  = fields[1].strip('"')
        event.source_flags = fields[2]
        event.source_raid_flags = fields[3]
        event.dest_guid    = fields[4]
        event.dest_name    = fields[5].strip('"')
        event.dest_flags   = fields[6]
        event.dest_raid_flags = fields[7]
        return fields[8:]
    return []


def _parse_spell_prefix(fields: list[str], event: CombatEvent) -> list[str]:
    """
    Consume spellId, spellName, spellSchool from front of *fields*.
    Returns remaining fields.
    """
    if len(fields) >= 3:
        event.spell_id     = _safe_int(fields[0])
        event.spell_name   = fields[1].strip('"')
        event.spell_school = fields[2]
        return fields[3:]
    return []


def _parse_damage_fields(fields: list[str], event: CombatEvent) -> None:
    """Parse standard damage tuple: amount, overkill, school, resisted, blocked, absorbed, critical"""
    try:
        if len(fields) >= 1:
            event.amount   = _safe_int(fields[0])
        if len(fields) >= 2:
            event.overkill = _safe_int(fields[1])
        if len(fields) >= 3:
            event.school   = _safe_int(fields[2])
        if len(fields) >= 4:
            event.resisted = _safe_int(fields[3])
        if len(fields) >= 5:
            event.blocked  = _safe_int(fields[4])
        if len(fields) >= 6:
            event.absorbed = _safe_int(fields[5])
        if len(fields) >= 7:
            event.critical = _safe_bool_nil(fields[6])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main parser entry point
# ---------------------------------------------------------------------------


def parse_line(line: str, player_name: Optional[str] = None) -> Optional[CombatEvent]:
    """
    Parse a single combat log line into a CombatEvent.

    Returns None if:
      - The line does not match the expected format.
      - The event type is not in SUPPORTED_EVENTS.
      - player_name is given and the source/dest is not that player
        (except for ENCOUNTER_START / ENCOUNTER_END which are always kept).
    """
    m = _TS_RE.match(line)
    if not m:
        _log.debug("TS_RE no match: %.80r", line)
        return None

    date_part, time_part, event_type = m.group(1), m.group(2), m.group(3)
    ts_str = f"{date_part} {time_part}"

    if event_type not in SUPPORTED_EVENTS:
        _log.debug("Unsupported event: %s", event_type)
        return None

    rest = line[m.end():]
    fields = _csv_split(rest)

    try:
        ts = _parse_ts(ts_str)
    except ValueError:
        return None

    event = CombatEvent(raw=line, timestamp=ts, event_type=event_type)

    # --------------- CHALLENGE_MODE_START / CHALLENGE_MODE_END ---------------
    if event_type in ("CHALLENGE_MODE_START", "CHALLENGE_MODE_END"):
        # Fields for START: zoneName, mapID, challengeID, keystoneLevel, ...
        # Fields for END: mapID, success, time, ...
        # We keep them as raw events for the log scanner; no player filter.
        if len(fields) >= 1:
            event.encounter_name = fields[0].strip('"') if fields[0].strip('"') else event_type
        _log.debug("OK %s", event_type)
        return event

    # --------------- UNIT_DIED ---------------
    if event_type == "UNIT_DIED":
        # Standard unit prefix only; we return for log scanner use.
        remaining_ud = _parse_base_unit_fields(fields, event)
        _log.debug("OK UNIT_DIED dest=%r", event.dest_name)
        return event

    # --------------- ENCOUNTER_START ---------------
    if event_type == "ENCOUNTER_START":
        # Fields: encounterID, encounterName, difficultyID, groupSize[, instanceID]
        if len(fields) >= 4:
            event.encounter_id   = _safe_int(fields[0])
            event.encounter_name = fields[1].strip('"')
            event.difficulty_id  = _safe_int(fields[2])
            event.raid_size      = _safe_int(fields[3])
        _log.info("OK ENCOUNTER_START: %r", event.encounter_name)
        return event

    # --------------- ENCOUNTER_END ---------------
    if event_type == "ENCOUNTER_END":
        # Fields: encounterID, encounterName, difficultyID, groupSize, success
        if len(fields) >= 4:
            event.encounter_id   = _safe_int(fields[0])
            event.encounter_name = fields[1].strip('"')
            event.difficulty_id  = _safe_int(fields[2])
            event.raid_size      = _safe_int(fields[3])
        _log.info("OK ENCOUNTER_END: %r", event.encounter_name)
        return event

    # All remaining events have standard unit prefix
    remaining = _parse_base_unit_fields(fields, event)

    # Optionally filter to player only.
    # Use startswith to tolerate realm suffix (e.g. "Lugoor-Blackhand-EU").
    if player_name:
        is_encounter = event_type in ("ENCOUNTER_START", "ENCOUNTER_END")
        source_match = event.source_name.startswith(player_name)
        dest_match   = event.dest_name.startswith(player_name)
        if not is_encounter and not source_match and not dest_match:
            _log.debug("Filtered (player=%r): %s src=%r dest=%r",
                       player_name, event_type, event.source_name, event.dest_name)
            return None

    # --------------- SWING_DAMAGE ---------------
    if event_type == "SWING_DAMAGE":
        _parse_damage_fields(remaining, event)
        return event

    # All spell events need the spell prefix
    remaining = _parse_spell_prefix(remaining, event)

    # --------------- SPELL_CAST_SUCCESS / SPELL_CAST_START ---------------
    if event_type in ("SPELL_CAST_SUCCESS", "SPELL_CAST_START", "SPELL_CAST_FAILED"):
        # No additional mandatory fields for these
        event.extra = remaining
        _log.debug("OK %s spell=%r src=%r", event_type, event.spell_name, event.source_name)
        return event

    # --------------- SPELL_MISSED ---------------
    if event_type == "SPELL_MISSED":
        if remaining:
            event.miss_type = remaining[0].strip('"')
        return event

    # --------------- SPELL_AURA_APPLIED / REMOVED ---------------
    if event_type in (
        "SPELL_AURA_APPLIED",
        "SPELL_AURA_REMOVED",
        "SPELL_AURA_APPLIED_DOSE",
        "SPELL_AURA_REMOVED_DOSE",
    ):
        if remaining:
            event.aura_type = remaining[0].strip('"')
        if len(remaining) >= 2 and "DOSE" in event_type:
            event.aura_stacks = _safe_int(remaining[1])
        _log.debug("OK %s spell=%r stacks=%s on=%r", event_type, event.spell_name,
                   event.aura_stacks, event.dest_name)
        return event

    _log.debug("OK %s spell=%r src=%r", event_type, event.spell_name, event.source_name)
    event.extra = remaining
    return event


# ---------------------------------------------------------------------------
# Streaming helper used by main.py / engine.py
# ---------------------------------------------------------------------------


class CombatLogParser:
    """
    Stateful parser that wraps parse_line with an optional player filter.
    Call feed(line) to get a CombatEvent or None.
    """

    def __init__(self, player_name: Optional[str] = None) -> None:
        self.player_name = player_name

    def feed(self, line: str) -> Optional[CombatEvent]:
        return parse_line(line, player_name=self.player_name)


# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    _samples = [
        '4/1 2026 12:00:01.000  ENCOUNTER_START  1234,"Onyxia",14,25',
        '4/1 2026 12:00:02.000  SPELL_CAST_SUCCESS  Player-1-AABBCCDD,"Frostmage",0x514,0x0,Creature-0-1-1-1-12345,"Onyxia",0xa48,0x0,12472,"Icy Veins",0x40',
        '4/1 2026 12:00:02.500  SPELL_AURA_APPLIED  Player-1-AABBCCDD,"Frostmage",0x514,0x0,Player-1-AABBCCDD,"Frostmage",0x514,0x0,12472,"Icy Veins",0x40,"BUFF"',
        '4/1 2026 12:00:03.000  SPELL_CAST_SUCCESS  Player-1-AABBCCDD,"Frostmage",0x514,0x0,Creature-0-1-1-1-12345,"Onyxia",0xa48,0x0,44614,"Flurry",0x10',
        '4/1 2026 12:00:10.000  ENCOUNTER_END  1234,"Onyxia",14,25,1',
    ]
    for s in _samples:
        ev = parse_line(s)
        if ev:
            print(f"[{ev.event_type}] spell={ev.spell_name}({ev.spell_id}) src={ev.source_name} ts={ev.timestamp}")
