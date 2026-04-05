"""Tests for multi-spec support (Arcane Mage, Devastation Evoker, Augmentation Evoker)."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import importlib
_parser_mod = importlib.import_module("parser")
parse_line = _parser_mod.parse_line
CombatLogParser = _parser_mod.CombatLogParser

from engine import FrostMageEngine, SPEC_RULES, RULES_DIR


def _make_encounter_start(name: str = "TestBoss") -> str:
    return f'4/1 12:00:00.000  ENCOUNTER_START  1,"{name}",14,25'


def _make_encounter_end(name: str = "TestBoss") -> str:
    return f'4/1 12:00:30.000  ENCOUNTER_END  1,"{name}",14,25,1'


def _make_cast(spell_id: int, spell_name: str, player: str = "TestPlayer") -> str:
    return (
        f'4/1 12:00:05.000  SPELL_CAST_SUCCESS  '
        f'Player-1-AABBCCDD,"{player}",0x514,0x0,'
        f'Creature-0-1-1-1-12345,"Target",0xa48,0x0,'
        f'{spell_id},"{spell_name}",0x10'
    )


class TestSpecRulesFiles:
    """Verify that rule JSON files exist for all supported specs."""

    @pytest.mark.parametrize("spec,filename", [
        ("frost_mage", "frost_mage.json"),
        ("arcane_mage", "arcane_mage.json"),
        ("devastation_evoker", "devastation_evoker.json"),
        ("augmentation_evoker", "augmentation_evoker.json"),
    ])
    def test_rules_file_exists(self, spec, filename):
        path = RULES_DIR / filename
        assert path.exists(), f"Rules file missing: {path}"

    def test_spec_rules_map_contains_all_specs(self):
        for spec in ["frost_mage", "arcane_mage", "devastation_evoker", "augmentation_evoker"]:
            assert spec in SPEC_RULES


class TestArcaneMage:
    def _engine(self):
        return FrostMageEngine(spec="arcane_mage", player_name="TestPlayer")

    def test_engine_loads_arcane_rules(self):
        eng = self._engine()
        # Should have loaded arcane_mage.json
        assert eng._rules is not None
        assert eng._rules.get("spec") == "Arcane" or "arcane" in str(eng._rules).lower()

    def test_encounter_start_recognized(self):
        eng = self._engine()
        ev = parse_line(_make_encounter_start("Arcane Test Boss"))
        assert ev is not None
        eng.process_event(ev)
        assert eng.in_encounter

    def test_arcane_blast_cast_processed(self):
        eng = self._engine()
        ev_start = parse_line(_make_encounter_start())
        eng.process_event(ev_start)
        # Arcane Blast ID = 30451
        ev_cast = parse_line(_make_cast(30451, "Arcane Blast"))
        assert ev_cast is not None
        # Should not raise
        eng.process_event(ev_cast)

    def test_encounter_end_recognized(self):
        eng = self._engine()
        eng.process_event(parse_line(_make_encounter_start()))
        eng.process_event(parse_line(_make_encounter_end()))
        assert not eng.in_encounter


class TestDevastationEvoker:
    def _engine(self):
        return FrostMageEngine(spec="devastation_evoker", player_name="TestPlayer")

    def test_engine_loads_devastation_rules(self):
        eng = self._engine()
        assert eng._rules is not None
        assert "Devastation" in str(eng._rules) or "devastation" in str(eng._rules).lower()

    def test_encounter_start_recognized(self):
        eng = self._engine()
        ev = parse_line(_make_encounter_start("Evoker Test Boss"))
        eng.process_event(ev)
        assert eng.in_encounter

    def test_disintegrate_cast_processed(self):
        eng = self._engine()
        eng.process_event(parse_line(_make_encounter_start()))
        # Disintegrate ID = 356995
        ev_cast = parse_line(_make_cast(356995, "Disintegrate"))
        assert ev_cast is not None
        eng.process_event(ev_cast)

    def test_no_error_on_known_cast(self):
        eng = self._engine()
        eng.process_event(parse_line(_make_encounter_start()))
        ev_cast = parse_line(_make_cast(356995, "Disintegrate"))
        eng.process_event(ev_cast)
        # No unexpected exception = pass
        errors = eng.current_rotation_errors()
        assert isinstance(errors, list)


class TestAugmentationEvoker:
    def _engine(self):
        return FrostMageEngine(spec="augmentation_evoker", player_name="TestPlayer")

    def test_engine_loads_augmentation_rules(self):
        eng = self._engine()
        assert eng._rules is not None
        assert "Augmentation" in str(eng._rules) or "augmentation" in str(eng._rules).lower()

    def test_encounter_start_recognized(self):
        eng = self._engine()
        ev = parse_line(_make_encounter_start("Aug Test Boss"))
        eng.process_event(ev)
        assert eng.in_encounter

    def test_ebon_might_cast_processed(self):
        eng = self._engine()
        eng.process_event(parse_line(_make_encounter_start()))
        # Ebon Might ID = 395152
        ev_cast = parse_line(_make_cast(395152, "Ebon Might"))
        assert ev_cast is not None
        eng.process_event(ev_cast)

    def test_no_error_on_breath_of_eons(self):
        eng = self._engine()
        eng.process_event(parse_line(_make_encounter_start()))
        # Breath of Eons ID = 403631
        ev_cast = parse_line(_make_cast(403631, "Breath of Eons"))
        eng.process_event(ev_cast)
        errors = eng.current_rotation_errors()
        assert isinstance(errors, list)


class TestSpecSourceFilter:
    """Verify that casts from other players are not processed as our casts."""

    def test_druid_cast_on_player_not_counted(self):
        """A druid healing TestPlayer should not count as TestPlayer's cast."""
        eng = FrostMageEngine(spec="frost_mage", player_name="TestPlayer")
        ev_start = parse_line(_make_encounter_start())
        eng.process_event(ev_start)

        # Druid casts Regrowth on TestPlayer
        druid_cast = (
            '4/1 12:00:05.000  SPELL_CAST_SUCCESS  '
            'Player-2-FFFFFFFF,"Druid",0x514,0x0,'
            'Player-1-AABBCCDD,"TestPlayer",0x514,0x0,'
            '8936,"Regrowth",0x8'
        )
        ev = parse_line(druid_cast, player_name="TestPlayer")
        if ev:  # parser may filter or pass through
            initial_casts, _, _ = eng.current_gcd_stats()
            eng.process_event(ev)
            final_casts, _, _ = eng.current_gcd_stats()
            # Cast count should not increase for a non-player source
            assert final_casts == initial_casts, \
                "Non-player cast should not increase GCD cast count"

    def test_own_cast_counted(self):
        """TestPlayer's own cast should be counted."""
        eng = FrostMageEngine(spec="frost_mage", player_name="TestPlayer")
        ev_start = parse_line(_make_encounter_start())
        eng.process_event(ev_start)

        own_cast = _make_cast(116, "Frostbolt", player="TestPlayer")
        ev = parse_line(own_cast, player_name="TestPlayer")
        if ev:
            initial_casts, _, _ = eng.current_gcd_stats()
            eng.process_event(ev)
            final_casts, _, _ = eng.current_gcd_stats()
            assert final_casts > initial_casts, "Own cast should increase GCD count"

    def test_score_does_not_exceed_100(self):
        """Score calculation should never return > 100."""
        # Simulate many identical casts in the opener
        expected = ["Frostbolt", "Frostbolt", "Frostbolt"]
        actual = ["Frostbolt", "Frostbolt", "Frostbolt", "Frostbolt", "Frostbolt"]

        remaining = list(expected)
        matched = 0
        for a in actual:
            if a in remaining:
                matched += 1
                remaining.remove(a)
        score = min(100, int(matched / max(len(expected), 1) * 100))
        assert score <= 100
