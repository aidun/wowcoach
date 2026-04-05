"""Integrationstests – vollständige Pipeline Parser → Engine."""
import importlib
from datetime import datetime, timedelta

_parser_mod = importlib.import_module("parser")
parse_line = _parser_mod.parse_line
CombatLogParser = _parser_mod.CombatLogParser

from engine import FrostMageEngine

PLAYER = "Lugoor"
PLAYER_GUID = "Player-1-AABBCCDD"
ENEMY_GUID = "Creature-0-1-1-1-99999"
ENEMY = "Tindral"


def ts(offset_s: float = 0.0) -> str:
    base = datetime(2026, 4, 4, 12, 0, 0)
    t = base + timedelta(seconds=offset_s)
    return f"{t.month}/{t.day} {t.year} {t.strftime('%H:%M:%S.')}{t.microsecond // 1000:03d}"


# Vollständige Beispiel-Encounter-Sequenz
SAMPLE_LOG = [
    # Encounter Start
    f'{ts(0)}  ENCOUNTER_START  2093,"Tindral Sageswift",14,20',

    # Opener: Glacial Spike Precast
    (f'{ts(1)}  SPELL_CAST_SUCCESS  '
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'{ENEMY_GUID},"{ENEMY}",0xa48,0x0,'
     f'199786,"Glacial Spike",0x10'),

    # Ice Lance direkt danach
    (f'{ts(2)}  SPELL_CAST_SUCCESS  '
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'{ENEMY_GUID},"{ENEMY}",0xa48,0x0,'
     f'30455,"Ice Lance",0x10'),

    # Fingers of Frost Buff
    (f'{ts(2.5)}  SPELL_AURA_APPLIED  '
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'112965,"Fingers of Frost",0x10,"BUFF"'),

    # Frozen Orb
    (f'{ts(3)}  SPELL_CAST_SUCCESS  '
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'{ENEMY_GUID},"{ENEMY}",0xa48,0x0,'
     f'84714,"Frozen Orb",0x10'),

    # Freezing Debuff auf Target (6 Stacks)
    (f'{ts(3.5)}  SPELL_AURA_APPLIED_DOSE  '
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'{ENEMY_GUID},"{ENEMY}",0xa48,0x0,'
     f'1221389,"Freezing",0x10,"DEBUFF",6'),

    # Brain Freeze Buff
    (f'{ts(4)}  SPELL_AURA_APPLIED  '
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'190447,"Brain Freeze",0x10,"BUFF"'),

    # Flurry (mit Brain Freeze → kein Fehler)
    (f'{ts(4.5)}  SPELL_CAST_SUCCESS  '
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'{ENEMY_GUID},"{ENEMY}",0xa48,0x0,'
     f'44614,"Flurry",0x10'),

    # Ray of Frost früh eingesetzt (kein Delay-Fehler)
    (f'{ts(5)}  SPELL_CAST_SUCCESS  '
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'{ENEMY_GUID},"{ENEMY}",0xa48,0x0,'
     f'205021,"Ray of Frost",0x10'),

    # Weiterer Frostbolt-Filler
    (f'{ts(7)}  SPELL_CAST_SUCCESS  '
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'{ENEMY_GUID},"{ENEMY}",0xa48,0x0,'
     f'116,"Frostbolt",0x10'),

    # Encounter Ende
    f'{ts(60)}  ENCOUNTER_END  2093,"Tindral Sageswift",14,20,1',
]

# Sequenz mit absichtlichen Fehlern
BAD_LOG = [
    f'{ts(0)}  ENCOUNTER_START  2093,"Tindral Sageswift",14,20',

    # Flurry OHNE Brain Freeze → Fehler
    (f'{ts(2)}  SPELL_CAST_SUCCESS  '
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'{ENEMY_GUID},"{ENEMY}",0xa48,0x0,'
     f'44614,"Flurry",0x10'),

    # Ice Lance unter 6 Stacks ohne FoF → Fehler
    (f'{ts(4)}  SPELL_CAST_SUCCESS  '
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'{ENEMY_GUID},"{ENEMY}",0xa48,0x0,'
     f'30455,"Ice Lance",0x10'),

    # Ray of Frost SEHR SPÄT → Fehler
    (f'{ts(20)}  SPELL_CAST_SUCCESS  '
     f'{PLAYER_GUID},"{PLAYER}",0x514,0x0,'
     f'{ENEMY_GUID},"{ENEMY}",0xa48,0x0,'
     f'205021,"Ray of Frost",0x10'),

    f'{ts(60)}  ENCOUNTER_END  2093,"Tindral Sageswift",14,20,1',
]


def run_log(lines, talent="spellslinger"):
    parser = CombatLogParser(player_name=PLAYER)
    engine = FrostMageEngine(talent=talent, player_name=PLAYER)
    all_hints = []
    for line in lines:
        ev = parser.feed(line)
        if ev:
            engine.process_event(ev)
            hints = engine.live_hints
            all_hints.extend(hints)
    return engine, all_hints


class TestGoodEncounter:
    def test_encounter_starts_and_ends(self):
        engine, _ = run_log(SAMPLE_LOG)
        assert engine.in_encounter is False  # nach ENCOUNTER_END
        assert engine.encounter_name == "Tindral Sageswift"

    def test_opener_score_positive(self):
        engine, _ = run_log(SAMPLE_LOG)
        summary = engine.build_summary()
        assert summary.opener_score > 0

    def test_fight_duration_set(self):
        engine, _ = run_log(SAMPLE_LOG)
        summary = engine.build_summary()
        assert summary.fight_duration_s > 0

    def test_no_flurry_error_with_brain_freeze(self):
        engine, _ = run_log(SAMPLE_LOG)
        errors = engine.current_rotation_errors()
        assert not any(e.rule_id == "flurry_no_brain_freeze" for e in errors)

    def test_no_ray_of_frost_delay_error(self):
        engine, _ = run_log(SAMPLE_LOG)
        errors = engine.current_rotation_errors()
        assert not any(e.rule_id == "ray_of_frost_delayed" for e in errors)

    def test_no_frozen_orb_delay_error(self):
        engine, _ = run_log(SAMPLE_LOG)
        errors = engine.current_rotation_errors()
        assert not any(e.rule_id == "frozen_orb_delayed" for e in errors)

    def test_gcd_casts_counted(self):
        engine, _ = run_log(SAMPLE_LOG)
        assert engine._gcd_cast_count >= 5  # mind. 5 GCD-Spells in SAMPLE_LOG

    def test_no_winters_chill_hints(self):
        _, hints = run_log(SAMPLE_LOG)
        assert not any("Winter's Chill" in h for h in hints)


class TestBadEncounter:
    def test_flurry_no_brain_freeze_detected(self):
        engine, _ = run_log(BAD_LOG)
        errors = engine.current_rotation_errors()
        assert any(e.rule_id == "flurry_no_brain_freeze" for e in errors)

    def test_ice_lance_threshold_error_detected(self):
        engine, _ = run_log(BAD_LOG)
        errors = engine.current_rotation_errors()
        assert any(e.rule_id == "ice_lance_below_threshold_spellslinger" for e in errors)

    def test_ray_of_frost_delay_detected(self):
        engine, _ = run_log(BAD_LOG)
        errors = engine.current_rotation_errors()
        assert any(e.rule_id == "ray_of_frost_delayed" for e in errors)

    def test_hints_generated_for_errors(self):
        _, hints = run_log(BAD_LOG)
        assert len(hints) > 0

    def test_multiple_errors_in_summary(self):
        engine, _ = run_log(BAD_LOG)
        summary = engine.build_summary()
        assert len(summary.rotation_errors) >= 2


class TestPlayerFilter:
    def test_foreign_player_events_ignored(self):
        """Events von anderen Spielern dürfen nicht in die Engine."""
        parser = CombatLogParser(player_name=PLAYER)
        engine = FrostMageEngine(talent="spellslinger", player_name=PLAYER)

        ev = parser.feed(f'{ts(0)}  ENCOUNTER_START  2093,"Tindral Sageswift",14,20')
        engine.process_event(ev)

        # Anderer Spieler castet Flurry ohne BF → darf KEINEN Fehler erzeugen
        other_line = (
            f'{ts(2)}  SPELL_CAST_SUCCESS  '
            f'Player-1-ZZZZZZZZ,"Jemand",0x514,0x0,'
            f'{ENEMY_GUID},"{ENEMY}",0xa48,0x0,'
            f'44614,"Flurry",0x10'
        )
        ev2 = parser.feed(other_line)
        assert ev2 is None  # Parser filtert es raus
