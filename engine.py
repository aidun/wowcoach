"""
engine.py - Frost Mage analysis engine.

Responsibilities:
  - Load rules from rules/frost_mage.json
  - Track active buffs on the player
  - Detect rotation errors in real time
  - Track opener sequence (first 10s after ENCOUNTER_START)
  - Track GCD efficiency (gaps between GCD spells)
  - Detect delayed cooldown usage
  - Produce a post-fight summary

Public interface used by main.py:
  engine = FrostMageEngine(talent="frostfire")
  engine.process_event(combat_event)   # call for every event
  hints = engine.live_hints            # list[str] – cleared after each read
  summary = engine.build_summary()     # FightSummary dataclass
  engine.reset()                       # clear state for new fight
"""

from __future__ import annotations

import importlib
import json
import logging
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

_log = logging.getLogger("wowcoach.engine")

# Import our local parser module (named "parser.py").
# We avoid the name colliding with the stdlib "parser" module by loading via
# importlib when running Python 3.9+ where the stdlib "parser" was removed,
# but we still do it explicitly to be safe.
_parser_mod = importlib.import_module("parser")
CombatEvent = _parser_mod.CombatEvent

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

RULES_DIR  = Path(__file__).parent / "rules"
RULES_PATH = RULES_DIR / "frost_mage.json"   # default / backward-compat

# Map CLI spec name → JSON filename
SPEC_RULES: dict[str, str] = {
    "frost_mage":             "frost_mage.json",
    "frostfire":              "frost_mage.json",   # alias (old --talent)
    "spellslinger":           "frost_mage.json",   # alias (old --talent)
    "arcane_mage":            "arcane_mage.json",
    "devastation_evoker":     "devastation_evoker.json",
    "augmentation_evoker":    "augmentation_evoker.json",
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPENER_WINDOW_SECONDS = 10.0
GCD_WASTE_THRESHOLD_MS = 400       # gaps > this are "wasted" GCD time
GCD_BASE_MS = 1500                 # approximate base GCD for gap bucketing
CD_CHECK_DELAY_TOLERANCE_S = 3.0   # seconds of delay before we flag a CD

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class GcdGap:
    """Represents a measured gap between two consecutive GCD casts."""
    start_spell: str
    end_spell: str
    gap_ms: float
    timestamp: datetime


@dataclass
class RotationError:
    """A single detected rotation mistake."""
    rule_id: str
    severity: str          # "major" | "moderate" | "minor" | "info"
    message: str
    explanation: str
    timestamp: datetime
    spell_name: str = ""


@dataclass
class OpenerStep:
    """One observed spell during the opener window."""
    spell_id: int
    spell_name: str
    timestamp: datetime
    step_index: int        # position in observed sequence (0-based)


@dataclass
class FightSummary:
    """Post-fight analysis results."""
    encounter_name: str = ""
    fight_duration_s: float = 0.0

    # Opener
    opener_score: int = 0          # 0-100
    opener_actual: list[str] = field(default_factory=list)
    opener_expected: list[str] = field(default_factory=list)
    opener_missed: list[str] = field(default_factory=list)

    # GCD
    total_gcd_casts: int = 0
    total_gcd_waste_ms: float = 0.0
    gcd_waste_pct: float = 0.0
    worst_gaps: list[GcdGap] = field(default_factory=list)  # top 3

    # Rotation errors
    rotation_errors: list[RotationError] = field(default_factory=list)

    # Cooldowns
    cd_delays: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


class FrostMageEngine:
    """
    Stateful analysis engine for a single Frost Mage player.

    Parameters
    ----------
    talent : str
        "frostfire" or "spellslinger"
    player_name : str, optional
        The character name being tracked (used for buff filtering).
    """

    def __init__(self, talent: str = "frostfire", player_name: str = "",
                 spec: str = "") -> None:
        # `spec` takes precedence; fall back to `talent` for backward-compat
        raw = (spec or talent).lower()
        self.talent = raw          # kept for backward-compat property access
        self.spec   = raw
        self.player_name = player_name

        # Load spec-specific rules JSON
        json_name = SPEC_RULES.get(raw, "frost_mage.json")
        rules_path = RULES_DIR / json_name
        if not rules_path.exists():
            _log.warning("Rules file not found: %s – falling back to frost_mage.json", rules_path)
            rules_path = RULES_PATH
        with open(rules_path, "r", encoding="utf-8") as fh:
            self._rules: dict = json.load(fh)

        # Talent builds (frost_mage has frostfire/spellslinger; others may have one default)
        builds = self._rules.get("talent_builds", {})
        self._build = builds.get(raw) or next(iter(builds.values()), {})
        self._error_rules: list[dict] = self._rules.get("error_rules", [])
        self._off_gcd_ids: set[int] = set(self._rules.get("off_gcd_spells", []))
        self._major_cd_ids: set[int] = {
            cd["spell_id"] for cd in self._rules.get("major_cooldowns", [])
        }

        # Build index of major CDs with their cooldown durations
        self._major_cd_info: dict[int, dict] = {
            cd["spell_id"]: cd for cd in self._rules.get("major_cooldowns", [])
        }

        # Spec-specific IDs (from JSON spec_ids section) – used in rotation checks
        _sids = self._rules.get("spec_ids", {})
        self._sid_flurry:         int = _sids.get("flurry", 0)
        self._sid_brain_freeze:   int = _sids.get("brain_freeze_buff", 0)
        self._sid_fof:            int = _sids.get("fingers_of_frost_buff", 0)
        self._sid_freezing:       int = _sids.get("freezing_debuff", 0)
        self._sid_thermal_void:   int = _sids.get("thermal_void_buff", 0)
        self._sid_ice_lance:      int = _sids.get("ice_lance", 0)
        self._sid_primary_cd:     int = _sids.get("primary_dps_cd", 0)
        self._sid_secondary_cd:   int = _sids.get("secondary_dps_cd", 0)

        # Spell info index
        self._spell_info: dict[int, dict] = {
            int(v.get("id", 0)): v
            for v in self._rules["spells"].values()
            if v.get("id")
        }

        # Thread-safety for live_hints (watcher thread writes, UI thread reads)
        self._hint_lock = threading.Lock()

        # ------- Runtime state -------
        self.reset()

    # ------------------------------------------------------------------
    # State reset (call at each new encounter)
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all fight-tracking state."""
        # Fight metadata
        self._encounter_name: str = ""
        self._encounter_start: Optional[datetime] = None
        self._encounter_end: Optional[datetime] = None
        self._in_encounter: bool = False

        # Opener tracking
        self._in_opener: bool = False
        self._opener_casts: list[OpenerStep] = []

        # Buff tracking: spell_id -> (gained_time, stacks)
        self._active_buffs: dict[int, tuple[datetime, int]] = {}

        # GCD tracking
        self._last_gcd_cast_time: Optional[datetime] = None
        self._last_gcd_spell: str = ""
        self._gcd_gaps: list[GcdGap] = []
        self._gcd_cast_count: int = 0

        # Cooldown tracking: spell_id -> last_used_time
        self._cd_last_used: dict[int, Optional[datetime]] = {}

        # Rotation errors
        self._rotation_errors: list[RotationError] = []

        # Live hints queue – guarded by _hint_lock for thread safety
        self._live_hints: list[str] = []

        # Freezing stack tracking (Midnight debuff ID 1221389 on target)
        self._freezing_stacks: int = 0

    # ------------------------------------------------------------------
    # Live hints access (consumed by UI)
    # ------------------------------------------------------------------

    def _hint(self, msg: str) -> None:
        """Thread-safe append to live hints."""
        _log.debug("Hint: %s", msg)
        with self._hint_lock:
            self._live_hints.append(msg)

    @property
    def live_hints(self) -> list[str]:
        """Return and clear the pending hints list."""
        with self._hint_lock:
            hints = list(self._live_hints)
            self._live_hints.clear()
        return hints

    def peek_hints(self) -> list[str]:
        """Return hints without clearing them."""
        return list(self._live_hints)

    # ------------------------------------------------------------------
    # Main entry point: process one event
    # ------------------------------------------------------------------

    def process_event(self, ev: CombatEvent) -> None:
        """Feed a parsed CombatEvent into the engine."""
        _log.debug("process_event: %s spell=%r src=%r", ev.event_type, ev.spell_name, ev.source_name)
        et = ev.event_type

        if et == "ENCOUNTER_START":
            self._on_encounter_start(ev)
            return

        if et == "ENCOUNTER_END":
            self._on_encounter_end(ev)
            return

        if not self._in_encounter:
            return

        if et in ("SPELL_CAST_SUCCESS", "SPELL_CAST_START"):
            self._on_spell_cast(ev)

        elif et in ("SPELL_AURA_APPLIED", "SPELL_AURA_APPLIED_DOSE"):
            self._on_aura_applied(ev)

        elif et in ("SPELL_AURA_REMOVED", "SPELL_AURA_REMOVED_DOSE"):
            self._on_aura_removed(ev)

        elif et == "SPELL_MISSED":
            self._on_spell_missed(ev)

    # ------------------------------------------------------------------
    # Encounter lifecycle
    # ------------------------------------------------------------------

    def _on_encounter_start(self, ev: CombatEvent) -> None:
        self.reset()
        self._encounter_name = ev.encounter_name or "Unknown Encounter"
        self._encounter_start = ev.timestamp
        self._in_encounter = True
        self._in_opener = True
        self._hint(f"Encounter started: {self._encounter_name}")  # thread-safe
        _log.info("ENCOUNTER_START: %s", self._encounter_name)

    def _on_encounter_end(self, ev: CombatEvent) -> None:
        self._encounter_end = ev.timestamp
        self._in_encounter = False
        self._in_opener = False
        _log.info("ENCOUNTER_END: %s", self._encounter_name)

    # ------------------------------------------------------------------
    # Spell cast handling
    # ------------------------------------------------------------------

    def _on_spell_cast(self, ev: CombatEvent) -> None:
        if ev.event_type != "SPELL_CAST_SUCCESS":
            return   # Only count completed casts for analysis

        # Only process casts from the tracked player (not heals/buffs cast ON the player
        # by someone else, which also pass the parser's dest-name filter).
        if self.player_name and ev.source_name and \
                not ev.source_name.startswith(self.player_name):
            _log.debug("Skipping cast from non-player src=%r (player=%r)",
                       ev.source_name, self.player_name)
            return

        spell_id = ev.spell_id
        spell_name = ev.spell_name or ""
        ts = ev.timestamp

        # Check opener window (first OPENER_WINDOW_SECONDS)
        if self._in_opener and self._encounter_start:
            elapsed = (ts - self._encounter_start).total_seconds()
            if elapsed <= OPENER_WINDOW_SECONDS:
                self._opener_casts.append(
                    OpenerStep(
                        spell_id=spell_id or 0,
                        spell_name=spell_name,
                        timestamp=ts,
                        step_index=len(self._opener_casts),
                    )
                )
            else:
                self._in_opener = False

        # Track GCD spells
        is_off_gcd = spell_id in self._off_gcd_ids if spell_id else False
        if not is_off_gcd and spell_id:
            self._track_gcd(ts, spell_name)

        # Track major cooldown usage
        if spell_id in self._major_cd_ids:
            self._cd_last_used[spell_id] = ts

        # Run rotation checks
        if spell_id:
            self._check_rotation_rules(ev)

    def _track_gcd(self, ts: datetime, spell_name: str) -> None:
        """Measure gap between this GCD cast and the previous one."""
        self._gcd_cast_count += 1
        if self._last_gcd_cast_time is not None:
            gap_ms = (ts - self._last_gcd_cast_time).total_seconds() * 1000.0
            # Only flag gaps that are meaningfully larger than a GCD
            # (i.e. more than GCD_BASE_MS + waste_threshold)
            expected_max_ms = GCD_BASE_MS + GCD_WASTE_THRESHOLD_MS
            if gap_ms > expected_max_ms:
                waste_ms = gap_ms - GCD_BASE_MS
                gap_obj = GcdGap(
                    start_spell=self._last_gcd_spell,
                    end_spell=spell_name,
                    gap_ms=gap_ms,
                    timestamp=ts,
                )
                self._gcd_gaps.append(gap_obj)
                self._hint(
                    f"GCD gap: {waste_ms:.0f}ms wasted between "
                    f"{self._last_gcd_spell} -> {spell_name}"
                )

        self._last_gcd_cast_time = ts
        self._last_gcd_spell = spell_name

    # ------------------------------------------------------------------
    # Buff tracking
    # ------------------------------------------------------------------

    def _on_aura_applied(self, ev: CombatEvent) -> None:
        if ev.spell_id is None:
            return
        spell_id = ev.spell_id
        stacks = ev.aura_stacks or 1
        ts = ev.timestamp

        # Check for Brain Freeze overcap (applying when already have it)
        if self._sid_brain_freeze and spell_id == self._sid_brain_freeze \
                and spell_id in self._active_buffs:
            self._add_error("overwrite_brain_freeze", ts)
            self._hint("Brain Freeze überschrieben! Sofort Flurry casten.")

        # Check FoF overcap (applying at 2 stacks)
        if self._sid_fof and spell_id == self._sid_fof:
            _, existing_stacks = self._active_buffs.get(self._sid_fof, (None, 0))
            if existing_stacks >= 2:
                self._add_error("overwrite_fingers_of_frost", ts)
                self._hint("Fingers of Frost bei 2 Stacks! Sofort Ice Lance casten.")

        # Freezing debuff stack tracking (Midnight core mechanic)
        if self._sid_freezing and spell_id == self._sid_freezing:
            self._freezing_stacks = ev.aura_stacks or 1
            if self._freezing_stacks >= 20:
                self._add_error("freezing_stacks_capped", ts)
                self._hint("Freezing Stacks bei 20 (Cap)! Sofort Ice Lance casten!")
            elif self._freezing_stacks >= 18:
                self._hint("Freezing fast bei Cap (18+)! Sofort Ice Lance casten.")
        else:
            self._active_buffs[spell_id] = (ts, stacks)

    def _on_aura_removed(self, ev: CombatEvent) -> None:
        if ev.spell_id is None:
            return
        spell_id = ev.spell_id
        if self._sid_freezing and spell_id == self._sid_freezing:
            self._freezing_stacks = 0
        else:
            self._active_buffs.pop(spell_id, None)

    def _has_buff(self, spell_id: int) -> bool:
        return spell_id in self._active_buffs

    def _buff_stacks(self, spell_id: int) -> int:
        _, stacks = self._active_buffs.get(spell_id, (None, 0))
        return stacks

    # ------------------------------------------------------------------
    # Rotation error detection
    # ------------------------------------------------------------------

    def _check_rotation_rules(self, ev: CombatEvent) -> None:
        spell_id = ev.spell_id
        ts = ev.timestamp

        # --- Flurry without Brain Freeze / during Thermal Void ---
        if self._sid_flurry and spell_id == self._sid_flurry:
            has_bf = self._has_buff(self._sid_brain_freeze)
            if not has_bf:
                self._add_error("flurry_no_brain_freeze", ts, spell_name="Flurry")
                self._hint("Flurry ohne Brain Freeze! Nur mit Brain Freeze Proc casten.")
            elif self._sid_thermal_void and self._has_buff(self._sid_thermal_void):
                self._add_error("flurry_during_thermal_void", ts, spell_name="Flurry")
                self._hint("Flurry während Thermal Void! Erst Thermal Void mit Ice Lance verbrauchen.")

        # --- Ice Lance: threshold check (6+ Freezing or FoF) ---
        if self._sid_ice_lance and spell_id == self._sid_ice_lance:
            has_fof = self._has_buff(self._sid_fof) if self._sid_fof else False
            threshold = self._build.get("ice_lance_freezing_threshold", 6) \
                if self.spec in ("spellslinger",) else \
                self._build.get("ice_lance_freezing_threshold", 10)
            if not has_fof and self._freezing_stacks < threshold:
                self._add_error(
                    "ice_lance_below_threshold_spellslinger", ts, spell_name="Ice Lance"
                )

        # --- Primary DPS CD delayed ---
        if self._sid_primary_cd and spell_id == self._sid_primary_cd \
                and self._encounter_start:
            elapsed = (ts - self._encounter_start).total_seconds()
            if elapsed > 8.0:
                cd_name = next(
                    (c["name"] for c in self._rules.get("major_cooldowns", [])
                     if c["spell_id"] == self._sid_primary_cd), "Primary CD"
                )
                self._add_error("ray_of_frost_delayed", ts, spell_name=cd_name)
                self._hint(f"{cd_name} erst nach {elapsed:.1f}s! Früher einsetzen.")

        # --- Secondary DPS CD delayed at opener ---
        if self._sid_secondary_cd and spell_id == self._sid_secondary_cd \
                and self._encounter_start:
            elapsed = (ts - self._encounter_start).total_seconds()
            if elapsed > 5.0:
                cd_name = next(
                    (c["name"] for c in self._rules.get("major_cooldowns", [])
                     if c["spell_id"] == self._sid_secondary_cd), "Secondary CD"
                )
                self._add_error("frozen_orb_delayed", ts, spell_name=cd_name)
                self._hint(f"{cd_name} erst nach {elapsed:.1f}s ins Encounter.")

    def _add_error(
        self, rule_id: str, ts: datetime, spell_name: str = ""
    ) -> None:
        rule = next(
            (r for r in self._error_rules if r["id"] == rule_id), None
        )
        if rule is None:
            _log.warning("Unknown rule_id: %r", rule_id)
            return
        err = RotationError(
            rule_id=rule_id,
            severity=rule.get("severity", "info"),
            message=rule["message"],
            explanation=rule.get("explanation", ""),
            timestamp=ts,
            spell_name=spell_name,
        )
        self._rotation_errors.append(err)
        _log.info("Rule violated: %s (%s)", rule_id, spell_name)

    def _on_spell_missed(self, ev: CombatEvent) -> None:
        pass   # Not used for rotation analysis currently

    # ------------------------------------------------------------------
    # Periodic cooldown check (called by UI timer every 5s)
    # ------------------------------------------------------------------

    def check_cooldowns(self, current_time: Optional[datetime] = None) -> list[str]:
        """
        Check whether major cooldowns are available but unused.
        Returns a list of hint strings.
        """
        if not self._in_encounter:
            return []
        if not self._encounter_start:
            return []

        now = current_time or datetime.utcnow()
        hints: list[str] = []

        for spell_id, cd_info in self._major_cd_info.items():
            last_used = self._cd_last_used.get(spell_id)
            cooldown_s = cd_info.get("cooldown", 0)
            name = cd_info["name"]

            if last_used is None:
                # Never used in this fight
                elapsed = (now - self._encounter_start).total_seconds()
                if elapsed > CD_CHECK_DELAY_TOLERANCE_S:
                    hints.append(f"{name} has not been used yet!")
            else:
                elapsed_since = (now - last_used).total_seconds()
                if elapsed_since >= cooldown_s:
                    hints.append(f"{name} is off cooldown – use it now!")

        return hints

    # ------------------------------------------------------------------
    # Opener analysis
    # ------------------------------------------------------------------

    def _analyze_opener(self) -> tuple[int, list[str], list[str], list[str]]:
        """
        Compare observed opener casts to the expected sequence.

        Returns (score_0_100, actual_names, expected_names, missed_names).
        """
        expected_steps = self._build.get("opener", [])
        expected_names = [s["name"] for s in expected_steps]
        expected_ids   = [s["spell_id"] for s in expected_steps]

        actual_ids   = [c.spell_id for c in self._opener_casts]
        actual_names = [c.spell_name or str(c.spell_id) for c in self._opener_casts]

        if not expected_ids:
            return 100, actual_names, expected_names, []

        # Compute how many expected spells appeared (order-tolerant but sequence-aware)
        # Use a greedy matching approach
        matched = 0
        search_start = 0
        for exp_id in expected_ids:
            for i in range(search_start, len(actual_ids)):
                if actual_ids[i] == exp_id:
                    matched += 1
                    search_start = i + 1
                    break

        # Also penalise if Icy Veins (12472) was cast after >3s
        icy_veins_penalty = 0
        if self._encounter_start:
            for step in self._opener_casts:
                if step.spell_id == 12472:
                    elapsed = (step.timestamp - self._encounter_start).total_seconds()
                    if elapsed > CD_CHECK_DELAY_TOLERANCE_S:
                        icy_veins_penalty = 15
                    break
            else:
                # Icy Veins not cast at all in opener
                icy_veins_penalty = 20

        score = max(0, int(matched / max(len(expected_ids), 1) * 100) - icy_veins_penalty)

        # Determine missed steps
        missed: list[str] = []
        found_set = set()
        for exp_id, exp_name in zip(expected_ids, expected_names):
            if exp_id in actual_ids:
                found_set.add(exp_id)
            else:
                missed.append(exp_name)

        return score, actual_names, expected_names, missed

    # ------------------------------------------------------------------
    # Post-fight summary
    # ------------------------------------------------------------------

    def build_summary(self) -> FightSummary:
        """Build and return a FightSummary for the completed (or current) fight."""
        summary = FightSummary()
        summary.encounter_name = self._encounter_name

        # Fight duration
        if self._encounter_start:
            end = self._encounter_end or datetime.utcnow()
            summary.fight_duration_s = (end - self._encounter_start).total_seconds()

        # Opener
        score, actual, expected, missed = self._analyze_opener()
        summary.opener_score    = score
        summary.opener_actual   = actual
        summary.opener_expected = expected
        summary.opener_missed   = missed

        # GCD efficiency
        summary.total_gcd_casts = self._gcd_cast_count
        total_waste = sum(
            max(0, g.gap_ms - GCD_BASE_MS) for g in self._gcd_gaps
        )
        summary.total_gcd_waste_ms = total_waste
        if self._encounter_start:
            fight_ms = summary.fight_duration_s * 1000.0
            summary.gcd_waste_pct = (
                total_waste / fight_ms * 100.0 if fight_ms > 0 else 0.0
            )

        # Top 3 worst GCD gaps
        sorted_gaps = sorted(self._gcd_gaps, key=lambda g: g.gap_ms, reverse=True)
        summary.worst_gaps = sorted_gaps[:3]

        # Rotation errors (deduplicated by rule_id)
        seen_ids: set[str] = set()
        deduped: list[RotationError] = []
        for err in self._rotation_errors:
            if err.rule_id not in seen_ids:
                seen_ids.add(err.rule_id)
                deduped.append(err)
        summary.rotation_errors = self._rotation_errors[:]

        # Cooldown delays
        cd_delays: list[str] = []
        if self._encounter_start:
            for spell_id, cd_info in self._major_cd_info.items():
                last_used = self._cd_last_used.get(spell_id)
                if last_used is None:
                    cd_delays.append(f"{cd_info['name']} never used")
                else:
                    elapsed = (last_used - self._encounter_start).total_seconds()
                    if elapsed > CD_CHECK_DELAY_TOLERANCE_S:
                        cd_delays.append(
                            f"{cd_info['name']} first used at {elapsed:.1f}s into fight"
                        )
        summary.cd_delays = cd_delays

        return summary

    # ------------------------------------------------------------------
    # Convenience: current fight state for UI refresh
    # ------------------------------------------------------------------

    def current_opener_state(self) -> tuple[list[str], list[str]]:
        """Return (actual_cast_names, expected_step_names) for live display."""
        actual = [c.spell_name or str(c.spell_id) for c in self._opener_casts]
        expected = [s["name"] for s in self._build.get("opener", [])]
        return actual, expected

    def current_gcd_stats(self) -> tuple[int, float, float]:
        """Return (cast_count, total_waste_ms, waste_pct_of_fight)."""
        total_waste = sum(
            max(0, g.gap_ms - GCD_BASE_MS) for g in self._gcd_gaps
        )
        fight_ms = 0.0
        if self._encounter_start:
            end = self._encounter_end or datetime.utcnow()
            fight_ms = (end - self._encounter_start).total_seconds() * 1000.0
        pct = total_waste / fight_ms * 100.0 if fight_ms > 0 else 0.0
        return self._gcd_cast_count, total_waste, pct

    def current_rotation_errors(self) -> list[RotationError]:
        return list(self._rotation_errors)

    @property
    def in_encounter(self) -> bool:
        return self._in_encounter

    @property
    def encounter_name(self) -> str:
        return self._encounter_name


# SpecEngine alias – FrostMageEngine is the generic engine; new name for clarity
SpecEngine = FrostMageEngine
