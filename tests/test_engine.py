"""Tests für engine.py – FrostMageEngine."""
import importlib
import threading
from datetime import datetime, timedelta

import pytest

_parser_mod = importlib.import_module("parser")
parse_line = _parser_mod.parse_line

from engine import FrostMageEngine

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

PLAYER = "Lugoor"
PLAYER_GUID = "Player-1-AABBCCDD"
ENEMY_GUID = "Creature-0-1-1-1-99999"
ENEMY = "Tindral"


def ts(offset_s: float = 0.0) -> str:
    """Erzeuge Timestamp-String relativ zu 12:00:00 (Windows-kompatibel)."""
    base = datetime(2026, 4, 4, 12, 0, 0)
    t = base + timedelta(seconds=offset_s)
    return f"{t.month}/{t.day} {t.year} {t.strftime('%H:%M:%S.')}{t.microsecond // 1000:03d}"


def cast_line(spell_id, spell_name, offset_s=0.0,
              source=PLAYER, src_guid=PLAYER_GUID,
              dest=ENEMY, dest_guid=ENEMY_GUID):
    return (
        f'{ts(offset_s)}  SPELL_CAST_SUCCESS  '
        f'{src_guid},"{source}",0x514,0x0,'
        f'{dest_guid},"{dest}",0xa48,0x0,'
        f'{spell_id},"{spell_name}",0x10'
    )


def aura_line(spell_id, spell_name, aura_type="BUFF", stacks=None,
              offset_s=0.0,
              source=PLAYER, src_guid=PLAYER_GUID,
              dest=PLAYER, dest_guid=PLAYER_GUID):
    event = "SPELL_AURA_APPLIED" if stacks is None else "SPELL_AURA_APPLIED_DOSE"
    stack_part = f",{stacks}" if stacks is not None else ""
    return (
        f'{ts(offset_s)}  {event}  '
        f'{src_guid},"{source}",0x514,0x0,'
        f'{dest_guid},"{dest}",0x514,0x0,'
        f'{spell_id},"{spell_name}",0x10,"{aura_type}"{stack_part}'
    )


def encounter_start(offset_s=0.0):
    return f'{ts(offset_s)}  ENCOUNTER_START  2093,"Tindral Sageswift",14,20'


def encounter_end(offset_s=60.0):
    return f'{ts(offset_s)}  ENCOUNTER_END  2093,"Tindral Sageswift",14,20,1'


def feed(engine, line):
    ev = parse_line(line, player_name=PLAYER)
    if ev:
        engine.process_event(ev)


def make_engine(talent="spellslinger"):
    return FrostMageEngine(talent=talent, player_name=PLAYER)


# ---------------------------------------------------------------------------
# Encounter-Lifecycle
# ---------------------------------------------------------------------------

class TestEncounterLifecycle:
    def test_not_in_encounter_by_default(self):
        eng = make_engine()
        assert eng.in_encounter is False

    def test_in_encounter_after_start(self):
        eng = make_engine()
        feed(eng, encounter_start())
        assert eng.in_encounter is True

    def test_encounter_name_set(self):
        eng = make_engine()
        feed(eng, encounter_start())
        assert eng.encounter_name == "Tindral Sageswift"

    def test_not_in_encounter_after_end(self):
        eng = make_engine()
        feed(eng, encounter_start())
        feed(eng, encounter_end())
        assert eng.in_encounter is False

    def test_events_before_encounter_ignored(self):
        eng = make_engine()
        feed(eng, cast_line(116, "Frostbolt", offset_s=0))
        assert eng._gcd_cast_count == 0

    def test_reset_on_new_encounter(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, cast_line(116, "Frostbolt", 1))
        feed(eng, encounter_start(30))  # neue Encounter → reset
        assert eng._gcd_cast_count == 0
        assert eng.encounter_name == "Tindral Sageswift"


# ---------------------------------------------------------------------------
# Flurry ohne Brain Freeze
# ---------------------------------------------------------------------------

class TestFlurryWithoutBrainFreeze:
    def test_flurry_without_bf_creates_error(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, cast_line(44614, "Flurry", offset_s=2))
        errors = eng.current_rotation_errors()
        assert any(e.rule_id == "flurry_no_brain_freeze" for e in errors)

    def test_flurry_with_bf_no_error(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        # Brain Freeze Buff aufsetzen
        feed(eng, aura_line(190447, "Brain Freeze", offset_s=1))
        feed(eng, cast_line(44614, "Flurry", offset_s=2))
        errors = eng.current_rotation_errors()
        assert not any(e.rule_id == "flurry_no_brain_freeze" for e in errors)

    def test_flurry_hint_generated(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, cast_line(44614, "Flurry", offset_s=2))
        hints = eng.live_hints
        assert any("Flurry" in h for h in hints)


# ---------------------------------------------------------------------------
# Brain Freeze Overcap
# ---------------------------------------------------------------------------

class TestBrainFreezeOvercap:
    def test_bf_overwrite_creates_error(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, aura_line(190447, "Brain Freeze", offset_s=1))
        # Zweites Mal → Overcap
        feed(eng, aura_line(190447, "Brain Freeze", offset_s=3))
        errors = eng.current_rotation_errors()
        assert any(e.rule_id == "overwrite_brain_freeze" for e in errors)

    def test_no_overcap_if_consumed(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, aura_line(190447, "Brain Freeze", offset_s=1))
        # AURA_REMOVED simuliert Verbrauch durch Flurry
        removed_line = (
            f'{ts(2.0)}  SPELL_AURA_REMOVED  '
            f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
            f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
            f'190447,"Brain Freeze",0x10,"BUFF"'
        )
        feed(eng, removed_line)
        # Neuer BF nach Verbrauch → kein Overcap
        feed(eng, aura_line(190447, "Brain Freeze", offset_s=3))
        errors = eng.current_rotation_errors()
        assert not any(e.rule_id == "overwrite_brain_freeze" for e in errors)


# ---------------------------------------------------------------------------
# Fingers of Frost Overcap
# ---------------------------------------------------------------------------

class TestFingersOfFrostOvercap:
    def test_fof_overcap_at_2_stacks(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, aura_line(112965, "Fingers of Frost", stacks=2, offset_s=1))
        # Weitere Anwendung bei 2 Stacks → Overcap
        feed(eng, aura_line(112965, "Fingers of Frost", stacks=2, offset_s=2))
        errors = eng.current_rotation_errors()
        assert any(e.rule_id == "overwrite_fingers_of_frost" for e in errors)


# ---------------------------------------------------------------------------
# Ice Lance Threshold (Spellslinger: 6 Freezing Stacks)
# ---------------------------------------------------------------------------

class TestIceLanceThreshold:
    def test_ice_lance_below_6_stacks_no_fof_creates_error(self):
        eng = make_engine(talent="spellslinger")
        feed(eng, encounter_start(0))
        # Freezing Debuff bei 4 Stacks setzen
        feed(eng, aura_line(1221389, "Freezing", aura_type="DEBUFF",
                             stacks=4, offset_s=1,
                             dest=ENEMY, dest_guid=ENEMY_GUID))
        feed(eng, cast_line(30455, "Ice Lance", offset_s=2))
        errors = eng.current_rotation_errors()
        assert any(e.rule_id == "ice_lance_below_threshold_spellslinger" for e in errors)

    def test_ice_lance_with_fof_no_error(self):
        eng = make_engine(talent="spellslinger")
        feed(eng, encounter_start(0))
        feed(eng, aura_line(112965, "Fingers of Frost", offset_s=1))
        feed(eng, cast_line(30455, "Ice Lance", offset_s=2))
        errors = eng.current_rotation_errors()
        assert not any(e.rule_id == "ice_lance_below_threshold_spellslinger" for e in errors)

    def test_ice_lance_at_6_stacks_no_error(self):
        eng = make_engine(talent="spellslinger")
        feed(eng, encounter_start(0))
        feed(eng, aura_line(1221389, "Freezing", aura_type="DEBUFF",
                             stacks=6, offset_s=1,
                             dest=ENEMY, dest_guid=ENEMY_GUID))
        feed(eng, cast_line(30455, "Ice Lance", offset_s=2))
        errors = eng.current_rotation_errors()
        assert not any(e.rule_id == "ice_lance_below_threshold_spellslinger" for e in errors)

    def test_frostfire_threshold_is_10(self):
        eng = make_engine(talent="frostfire")
        feed(eng, encounter_start(0))
        # 8 Stacks → Fehler für Frostfire (Threshold 10)
        feed(eng, aura_line(1221389, "Freezing", aura_type="DEBUFF",
                             stacks=8, offset_s=1,
                             dest=ENEMY, dest_guid=ENEMY_GUID))
        feed(eng, cast_line(30455, "Ice Lance", offset_s=2))
        errors = eng.current_rotation_errors()
        assert any(e.rule_id == "ice_lance_below_threshold_spellslinger" for e in errors)


# ---------------------------------------------------------------------------
# Freezing Stack Cap-Warnung
# ---------------------------------------------------------------------------

class TestFreezingCap:
    def test_hint_at_18_stacks(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, aura_line(1221389, "Freezing", aura_type="DEBUFF",
                             stacks=18, offset_s=1,
                             dest=ENEMY, dest_guid=ENEMY_GUID))
        hints = eng.live_hints
        assert any("Freezing" in h or "Cap" in h for h in hints)


# ---------------------------------------------------------------------------
# GCD-Tracking
# ---------------------------------------------------------------------------

class TestGcdTracking:
    def test_normal_gap_not_flagged(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, cast_line(116, "Frostbolt", offset_s=1.0))
        feed(eng, cast_line(116, "Frostbolt", offset_s=2.5))  # 1.5s gap = normal GCD
        assert len(eng._gcd_gaps) == 0

    def test_large_gap_flagged(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, cast_line(116, "Frostbolt", offset_s=1.0))
        feed(eng, cast_line(116, "Frostbolt", offset_s=4.0))  # 3s gap → deutlich > 1.9s
        assert len(eng._gcd_gaps) == 1
        assert eng._gcd_gaps[0].gap_ms > 1900

    def test_gcd_count_increments(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        for i in range(5):
            feed(eng, cast_line(116, "Frostbolt", offset_s=float(i) * 2))
        assert eng._gcd_cast_count == 5


# ---------------------------------------------------------------------------
# Cooldown-Verzögerungen
# ---------------------------------------------------------------------------

class TestCooldownDelays:
    def test_ray_of_frost_delayed_creates_error(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        # Ray of Frost erst nach 10s
        feed(eng, cast_line(205021, "Ray of Frost", offset_s=10))
        errors = eng.current_rotation_errors()
        assert any(e.rule_id == "ray_of_frost_delayed" for e in errors)

    def test_ray_of_frost_early_no_error(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, cast_line(205021, "Ray of Frost", offset_s=3))
        errors = eng.current_rotation_errors()
        assert not any(e.rule_id == "ray_of_frost_delayed" for e in errors)

    def test_frozen_orb_delayed_creates_error(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, cast_line(84714, "Frozen Orb", offset_s=6))
        errors = eng.current_rotation_errors()
        assert any(e.rule_id == "frozen_orb_delayed" for e in errors)

    def test_frozen_orb_early_no_error(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, cast_line(84714, "Frozen Orb", offset_s=2))
        errors = eng.current_rotation_errors()
        assert not any(e.rule_id == "frozen_orb_delayed" for e in errors)


# ---------------------------------------------------------------------------
# Opener-Score
# ---------------------------------------------------------------------------

class TestOpenerScore:
    def test_perfect_opener_scores_high(self):
        eng = make_engine(talent="spellslinger")
        feed(eng, encounter_start(0))
        # Spellslinger Opener: Glacial Spike → Ice Lance → Frozen Orb → Flurry → Ray of Frost
        feed(eng, aura_line(190447, "Brain Freeze", offset_s=0.5))  # BF für Flurry
        for offset, spell_id, name in [
            (1.0, 199786, "Glacial Spike"),
            (2.0, 30455,  "Ice Lance"),
            (3.0, 84714,  "Frozen Orb"),
            (4.0, 44614,  "Flurry"),
            (5.0, 205021, "Ray of Frost"),
        ]:
            feed(eng, cast_line(spell_id, name, offset_s=offset))
        summary = eng.build_summary()
        assert summary.opener_score > 0

    def test_empty_opener_scores_zero(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        # Kein einziger Cast
        summary = eng.build_summary()
        assert summary.opener_score == 0

    def test_missed_spells_in_summary(self):
        eng = make_engine(talent="spellslinger")
        feed(eng, encounter_start(0))
        # Nur Frostbolt casten, alle Opener-Spells fehlen
        feed(eng, cast_line(116, "Frostbolt", offset_s=1))
        summary = eng.build_summary()
        assert len(summary.opener_missed) > 0


# ---------------------------------------------------------------------------
# Kein Winter's Chill mehr
# ---------------------------------------------------------------------------

class TestNoWintersChill:
    def test_no_winters_chill_attribute(self):
        eng = make_engine()
        assert not hasattr(eng, "_winters_chill_window"), \
            "_winters_chill_window sollte nicht mehr existieren (Midnight entfernt)"

    def test_no_winters_chill_hint(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, cast_line(44614, "Flurry", offset_s=1))
        feed(eng, cast_line(116, "Frostbolt", offset_s=2))
        hints = eng.live_hints
        assert not any("Winter's Chill" in h for h in hints)


# ---------------------------------------------------------------------------
# Thermal Void Suppression (Spellslinger-spezifisch)
# ---------------------------------------------------------------------------

THERMAL_VOID_ID = 1247729   # Spellslinger Buff nach Brain-Freeze-Flurry


class TestThermalVoid:
    def test_flurry_during_thermal_void_creates_error(self):
        """Flurry mit BF während Thermal Void → flurry_during_thermal_void."""
        eng = make_engine(talent="spellslinger")
        feed(eng, encounter_start(0))
        # Brain Freeze aufsetzen
        feed(eng, aura_line(190447, "Brain Freeze", offset_s=1))
        # Thermal Void aufsetzen (simuliert: BF Flurry wurde vorher gecasted)
        feed(eng, aura_line(THERMAL_VOID_ID, "Thermal Void", offset_s=1.5))
        # Jetzt Flurry mit BF WÄHREND Thermal Void → Fehler
        feed(eng, cast_line(44614, "Flurry", offset_s=2))
        errors = eng.current_rotation_errors()
        assert any(e.rule_id == "flurry_during_thermal_void" for e in errors)

    def test_flurry_without_thermal_void_no_tv_error(self):
        """Flurry mit BF, kein Thermal Void → kein flurry_during_thermal_void."""
        eng = make_engine(talent="spellslinger")
        feed(eng, encounter_start(0))
        feed(eng, aura_line(190447, "Brain Freeze", offset_s=1))
        feed(eng, cast_line(44614, "Flurry", offset_s=2))
        errors = eng.current_rotation_errors()
        assert not any(e.rule_id == "flurry_during_thermal_void" for e in errors)

    def test_thermal_void_hint_generated(self):
        """Thermal Void Fehler erzeugt auch einen Hint."""
        eng = make_engine(talent="spellslinger")
        feed(eng, encounter_start(0))
        feed(eng, aura_line(190447, "Brain Freeze", offset_s=1))
        feed(eng, aura_line(THERMAL_VOID_ID, "Thermal Void", offset_s=1.5))
        feed(eng, cast_line(44614, "Flurry", offset_s=2))
        hints = eng.live_hints
        assert any("Thermal Void" in h for h in hints)

    def test_thermal_void_removed_allows_flurry(self):
        """Nach Thermal Void REMOVED darf Flurry wieder gecasted werden."""
        eng = make_engine(talent="spellslinger")
        feed(eng, encounter_start(0))
        feed(eng, aura_line(190447, "Brain Freeze", offset_s=1))
        feed(eng, aura_line(THERMAL_VOID_ID, "Thermal Void", offset_s=1.5))
        # Thermal Void läuft ab
        tv_removed = (
            f'{ts(2.5)}  SPELL_AURA_REMOVED  '
            f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
            f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
            f'{THERMAL_VOID_ID},"Thermal Void",0x10,"BUFF"'
        )
        feed(eng, tv_removed)
        # Jetzt neue BF aufsetzen und Flurry casten → kein TV-Fehler
        feed(eng, aura_line(190447, "Brain Freeze", offset_s=3))
        feed(eng, cast_line(44614, "Flurry", offset_s=4))
        errors = eng.current_rotation_errors()
        assert not any(e.rule_id == "flurry_during_thermal_void" for e in errors)


# ---------------------------------------------------------------------------
# Freezing Stack Cap (20 Stacks → Error)
# ---------------------------------------------------------------------------

class TestFreezingStackCapError:
    def test_20_stacks_triggers_capped_error(self):
        """Bei 20 Freezing Stacks → freezing_stacks_capped Error."""
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, aura_line(1221389, "Freezing", aura_type="DEBUFF",
                             stacks=20, offset_s=1,
                             dest=ENEMY, dest_guid=ENEMY_GUID))
        errors = eng.current_rotation_errors()
        assert any(e.rule_id == "freezing_stacks_capped" for e in errors)

    def test_19_stacks_no_capped_error(self):
        """19 Stacks → kein freezing_stacks_capped Error, aber Hint."""
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, aura_line(1221389, "Freezing", aura_type="DEBUFF",
                             stacks=19, offset_s=1,
                             dest=ENEMY, dest_guid=ENEMY_GUID))
        errors = eng.current_rotation_errors()
        assert not any(e.rule_id == "freezing_stacks_capped" for e in errors)

    def test_cap_error_severity_is_major(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, aura_line(1221389, "Freezing", aura_type="DEBUFF",
                             stacks=20, offset_s=1,
                             dest=ENEMY, dest_guid=ENEMY_GUID))
        errors = eng.current_rotation_errors()
        cap_errors = [e for e in errors if e.rule_id == "freezing_stacks_capped"]
        assert cap_errors[0].severity == "major"

    def test_freezing_removed_resets_stacks(self):
        """AURA_REMOVED für Freezing setzt _freezing_stacks auf 0."""
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, aura_line(1221389, "Freezing", aura_type="DEBUFF",
                             stacks=12, offset_s=1,
                             dest=ENEMY, dest_guid=ENEMY_GUID))
        assert eng._freezing_stacks == 12
        # Ice Lance konsumiert alle Stacks → AURA_REMOVED
        removed_line = (
            f'{ts(2)}  SPELL_AURA_REMOVED  '
            f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
            f'{ENEMY_GUID},"{ENEMY}",0xa48,0x0,'
            f'1221389,"Freezing",0x10,"DEBUFF"'
        )
        feed(eng, removed_line)
        assert eng._freezing_stacks == 0


# ---------------------------------------------------------------------------
# Off-GCD Spells werden nicht als GCD gezählt
# ---------------------------------------------------------------------------

class TestOffGcdSpells:
    def test_icy_veins_not_counted_as_gcd(self):
        """Icy Veins (12472) ist off-GCD → soll _gcd_cast_count NICHT erhöhen."""
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, cast_line(12472, "Icy Veins", offset_s=1))
        assert eng._gcd_cast_count == 0

    def test_ice_barrier_not_counted_as_gcd(self):
        """Ice Barrier (11426) ist off-GCD."""
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, cast_line(11426, "Ice Barrier", offset_s=1))
        assert eng._gcd_cast_count == 0

    def test_shimmer_not_counted_as_gcd(self):
        """Shimmer (212653) ist off-GCD."""
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, cast_line(212653, "Shimmer", offset_s=1))
        assert eng._gcd_cast_count == 0

    def test_gcd_spell_after_off_gcd_not_affected(self):
        """Off-GCD zwischen zwei GCD-Spells erzeugt keine False-Gap."""
        eng = make_engine()
        feed(eng, encounter_start(0))
        feed(eng, cast_line(116, "Frostbolt", offset_s=1.0))
        feed(eng, cast_line(12472, "Icy Veins", offset_s=1.5))   # off-GCD
        feed(eng, cast_line(30455, "Ice Lance", offset_s=2.5))    # 1.5s nach Frostbolt = normaler GCD
        assert eng._gcd_cast_count == 2
        assert len(eng._gcd_gaps) == 0


# ---------------------------------------------------------------------------
# Encounter-Hint
# ---------------------------------------------------------------------------

class TestEncounterHint:
    def test_encounter_start_generates_hint(self):
        """Engine erzeugt einen Hint wenn der Encounter startet."""
        eng = make_engine()
        feed(eng, encounter_start(0))
        hints = eng.live_hints
        assert any("Encounter" in h for h in hints)

    def test_encounter_hint_contains_name(self):
        eng = make_engine()
        feed(eng, encounter_start(0))
        hints = eng.live_hints
        assert any("Tindral Sageswift" in h for h in hints)
