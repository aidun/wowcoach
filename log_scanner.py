"""
log_scanner.py – Pre-scan a WoWCombatLog file to extract:
  - Encounter segments (boss fights, trash runs, M+ challenge)
  - Player names present in the log
  - Trash-pack markers (>5 unique creatures within a short time window)

Content-type detection:
  - CHALLENGE_MODE_START present → Mythic+ run
    * ENCOUNTER_START/END within = mini-boss markers
    * >5 unique Creature GUIDs dealing damage in 10s window = trash-pack marker
  - No CHALLENGE_MODE_START → Raid
    * ENCOUNTER_START/END = boss segments
    * Between them = trash segments

Usage:
    from log_scanner import scan_log, scan_players_in_log

    segments = scan_log(Path("WoWCombatLog.txt"))
    players  = scan_players_in_log(Path("WoWCombatLog.txt"))
"""
from __future__ import annotations

import importlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

_log = logging.getLogger("wowcoach.scanner")

# Use our own parser module (avoids stdlib name conflict)
_parser_mod = importlib.import_module("parser")
parse_line = _parser_mod.parse_line

# Regex to extract a Creature-GUID source from a raw log line
_CREATURE_GUID_RE = re.compile(r"\bCreature-\d+-\d+-\d+-\d+-(\d+)-[0-9A-F]+\b")
_PLAYER_NAME_RE  = re.compile(r'"([A-Za-z]+(?:-[A-Za-z]+){1,2})"')   # "Name-Realm-EU"
_PLAYER_GUID_RE  = re.compile(r"\bPlayer-\d+-[0-9A-F]+\b")

# Time window for trash-pack detection (seconds)
TRASH_PACK_WINDOW_S   = 10.0
# Minimum unique creatures to count as a "large trash pack"
TRASH_PACK_MIN_MOBS   = 5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SegmentMarker:
    """A notable moment within an EncounterSegment."""
    time: datetime
    label: str          # e.g. "Boss: Stitchflesh", "Trash: 7 mobs"
    marker_type: str    # "boss" | "trash_pack" | "challenge_start" | "challenge_end"


@dataclass
class EncounterSegment:
    """One analysable segment of a combat log file."""
    name: str
    start: datetime
    end: Optional[datetime]
    segment_type: str           # "boss" | "trash_run" | "mythic_plus"
    content_type: str           # "raid" | "mythic_plus" | "unknown"
    markers: list[SegmentMarker] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        if self.end and self.start:
            return (self.end - self.start).total_seconds()
        return 0.0

    def display_name(self) -> str:
        dur = self.duration_s
        tag = {"boss": "👑", "trash_run": "🗡", "mythic_plus": "🔑"}.get(
            self.segment_type, "•"
        )
        return f"{tag} {self.name}  ({dur:.0f}s)"


# ---------------------------------------------------------------------------
# Player scanner
# ---------------------------------------------------------------------------

def scan_players_in_log(path: Path, max_lines: int = 50_000) -> list[str]:
    """
    Scan the first *max_lines* lines of the log and return a sorted list of
    unique player base-names (without realm suffix).

    Looks for Player-GUID patterns and extracts the name from the adjacent
    quoted string. Strips realm suffixes (e.g. "Lugoor-Blackhand-EU" → "Lugoor").
    """
    seen_names: set[str] = set()
    # Pattern: Player-GUID immediately followed by ,"Name...
    _combined = re.compile(r'Player-\d+-[0-9A-F]+,"([^"]+)"')

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                for m in _combined.finditer(line):
                    full_name = m.group(1)
                    # Strip realm suffix: "Lugoor-Blackhand-EU" → "Lugoor"
                    base = full_name.split("-")[0]
                    if base and base[0].isupper():
                        seen_names.add(full_name)   # keep full name for display
    except OSError as e:
        _log.error("scan_players_in_log failed: %s", e)

    _log.info("scan_players_in_log: found %d players in %s", len(seen_names), path.name)
    return sorted(seen_names)


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

def scan_log(path: Path) -> list[EncounterSegment]:
    """
    Read an entire WoWCombatLog file and return a list of EncounterSegment
    objects ordered by start time.

    Boss encounters in Raids are identified by ENCOUNTER_START/END pairs.
    Mythic+ runs are wrapped by CHALLENGE_MODE_START/END; bosses inside are
    marked as SegmentMarkers, not separate segments.
    Trash packs (>5 unique creatures active in 10 s) are marked within segments.
    """
    segments: list[EncounterSegment] = []

    # --- state ---
    has_challenge_mode  = False
    current_segment: Optional[EncounterSegment] = None
    challenge_segment:  Optional[EncounterSegment] = None

    # Creature activity window for trash-pack detection:
    # maps timestamp-bucket (floor to TRASH_PACK_WINDOW_S) → set of creature-IDs
    creature_windows: defaultdict[float, set[str]] = defaultdict(set)
    # Track which windows already generated a marker (avoid duplicates)
    marked_windows: set[float] = set()

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        _log.error("scan_log failed to read %s: %s", path, e)
        return []

    _log.info("scan_log: scanning %d lines in %s", len(lines), path.name)

    for raw in lines:
        if not raw.strip():
            continue

        ev = parse_line(raw)
        if ev is None:
            # Try to extract creature activity even from unparsed lines
            _record_creature_activity(raw, creature_windows)
            continue

        ts = ev.timestamp
        et = ev.event_type

        # ----------------------------------------------------------------
        # Challenge mode detection
        # ----------------------------------------------------------------
        if et == "CHALLENGE_MODE_START":
            has_challenge_mode = True
            name = ev.encounter_name or "Mythic+"
            challenge_segment = EncounterSegment(
                name=name,
                start=ts,
                end=None,
                segment_type="mythic_plus",
                content_type="mythic_plus",
            )
            challenge_segment.markers.append(SegmentMarker(
                time=ts, label=f"M+ Start: {name}", marker_type="challenge_start"
            ))
            current_segment = challenge_segment
            continue

        if et == "CHALLENGE_MODE_END":
            if challenge_segment:
                challenge_segment.end = ts
                challenge_segment.markers.append(SegmentMarker(
                    time=ts, label="M+ Ende", marker_type="challenge_end"
                ))
                segments.append(challenge_segment)
                challenge_segment = None
                current_segment = None
            continue

        # ----------------------------------------------------------------
        # Boss encounter detection
        # ----------------------------------------------------------------
        if et == "ENCOUNTER_START":
            boss_name = ev.encounter_name or f"Boss #{ev.encounter_id}"
            if has_challenge_mode and challenge_segment:
                # M+: boss is a marker inside the challenge segment
                challenge_segment.markers.append(SegmentMarker(
                    time=ts,
                    label=f"Boss: {boss_name}",
                    marker_type="boss",
                ))
            else:
                # Raid: boss is its own segment
                # Close any open trash segment first
                if current_segment and current_segment.segment_type == "trash_run":
                    current_segment.end = ts
                    segments.append(current_segment)
                    current_segment = None
                current_segment = EncounterSegment(
                    name=boss_name,
                    start=ts,
                    end=None,
                    segment_type="boss",
                    content_type="raid",
                )
            continue

        if et == "ENCOUNTER_END":
            boss_name = ev.encounter_name or ""
            if has_challenge_mode and challenge_segment:
                challenge_segment.markers.append(SegmentMarker(
                    time=ts,
                    label=f"Boss Ende: {boss_name}",
                    marker_type="boss",
                ))
            else:
                if current_segment and current_segment.segment_type == "boss":
                    current_segment.end = ts
                    segments.append(current_segment)
                    current_segment = None
                # Open a trash segment after boss
                # (will be closed on next ENCOUNTER_START or end of log)
                current_segment = EncounterSegment(
                    name="Trash",
                    start=ts,
                    end=None,
                    segment_type="trash_run",
                    content_type="raid",
                )
            continue

        # ----------------------------------------------------------------
        # Creature activity for trash-pack detection
        # ----------------------------------------------------------------
        _record_creature_activity(raw, creature_windows)

    # Close any unclosed segments
    if challenge_segment and challenge_segment.end is None:
        segments.append(challenge_segment)
    elif current_segment and current_segment.end is None:
        segments.append(current_segment)

    # ----------------------------------------------------------------
    # Trash-pack markers: inject into matching segments
    # ----------------------------------------------------------------
    _inject_trash_pack_markers(creature_windows, marked_windows, segments)

    _log.info("scan_log: found %d segments", len(segments))
    return segments


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DAMAGE_EVENTS = frozenset([
    "SWING_DAMAGE", "SPELL_CAST_SUCCESS",
])


def _record_creature_activity(
    line: str,
    windows: defaultdict[float, set[str]],
) -> None:
    """Extract creature GUIDs from damage-dealing log lines."""
    # Only look at lines with SWING_DAMAGE or SPELL_CAST_SUCCESS
    if "SWING_DAMAGE" not in line and "SPELL_CAST_SUCCESS" not in line:
        return
    # Extract timestamp seconds-of-day for windowing
    ts_sec = _line_seconds(line)
    if ts_sec is None:
        return
    bucket = (ts_sec // TRASH_PACK_WINDOW_S) * TRASH_PACK_WINDOW_S
    for m in _CREATURE_GUID_RE.finditer(line):
        npc_id = m.group(1)
        windows[bucket].add(npc_id)


_TS_SECS_RE = re.compile(
    r"^\d{1,2}/\d{1,2}(?:/\d{4})?\s+(\d{2}):(\d{2}):(\d{2})"
)


def _line_seconds(line: str) -> Optional[float]:
    m = _TS_SECS_RE.match(line)
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def _inject_trash_pack_markers(
    windows: defaultdict[float, set[str]],
    marked: set[float],
    segments: list[EncounterSegment],
) -> None:
    """For each 10s window with >5 unique creatures, add a marker to the right segment."""
    for bucket_sec, creature_ids in sorted(windows.items()):
        if len(creature_ids) <= TRASH_PACK_MIN_MOBS:
            continue
        if bucket_sec in marked:
            continue
        marked.add(bucket_sec)
        # Find the segment this window falls into
        hh = int(bucket_sec // 3600)
        mm = int((bucket_sec % 3600) // 60)
        ss = int(bucket_sec % 60)
        # We can't reconstruct full datetime without date; use a proxy
        label = f"Trash-Pack: {len(creature_ids)} Mobs ({hh:02d}:{mm:02d}:{ss:02d})"

        # Inject into ALL segments (since we don't have the full datetime,
        # we mark the trash_run / mythic_plus segment generically)
        for seg in segments:
            if seg.segment_type in ("trash_run", "mythic_plus"):
                seg.markers.append(SegmentMarker(
                    time=seg.start,   # proxy – real time is bucket_sec
                    label=label,
                    marker_type="trash_pack",
                ))
                break  # only first matching segment
