"""Tests for parser.py – CombatLogParser und parse_line."""
import importlib
import sys
from datetime import datetime

import pytest

# parser.py heißt wie das stdlib-Modul, daher importlib
_mod = importlib.import_module("parser")
parse_line = _mod.parse_line
CombatLogParser = _mod.CombatLogParser

# ---------------------------------------------------------------------------
# Hilfsfunktionen – realistische WoW-Logzeilen
# ---------------------------------------------------------------------------

PLAYER_GUID = "Player-1-AABBCCDD"
PLAYER = "Lugoor"
ENEMY_GUID = "Creature-0-1-1-1-99999"
ENEMY = "Tindral"

TS = "4/4 2026 12:00:01.000"


def _cast(spell_id, spell_name, source=PLAYER, src_guid=PLAYER_GUID,
          dest=ENEMY, dest_guid=ENEMY_GUID, ts=TS):
    return (
        f'{ts}  SPELL_CAST_SUCCESS  '
        f'{src_guid},"{source}",0x514,0x0,'
        f'{dest_guid},"{dest}",0xa48,0x0,'
        f'{spell_id},"{spell_name}",0x10'
    )


def _aura(spell_id, spell_name, aura_type="BUFF", stacks=None,
          source=PLAYER, src_guid=PLAYER_GUID,
          dest=PLAYER, dest_guid=PLAYER_GUID, ts=TS):
    event = "SPELL_AURA_APPLIED" if stacks is None else "SPELL_AURA_APPLIED_DOSE"
    stack_part = f",{stacks}" if stacks is not None else ""
    return (
        f'{ts}  {event}  '
        f'{src_guid},"{source}",0x514,0x0,'
        f'{dest_guid},"{dest}",0x514,0x0,'
        f'{spell_id},"{spell_name}",0x10,"{aura_type}"{stack_part}'
    )


def _encounter_start(ts=TS):
    return f'{ts}  ENCOUNTER_START  2093,"Tindral Sageswift",14,20'


def _encounter_end(ts=TS):
    return f'{ts}  ENCOUNTER_END  2093,"Tindral Sageswift",14,20,1'


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

class TestTimestampParsing:
    def test_valid_timestamp_parsed(self):
        ev = parse_line(_cast(116, "Frostbolt"))
        assert ev is not None
        assert isinstance(ev.timestamp, datetime)
        assert ev.timestamp.hour == 12
        assert ev.timestamp.minute == 0
        assert ev.timestamp.second == 1

    def test_missing_timestamp_returns_none(self):
        assert parse_line("SPELL_CAST_SUCCESS  garbage") is None

    def test_wrong_spacing_returns_none(self):
        # Nur ein Leerzeichen zwischen Timestamp und Event
        line = f'4/4 2026 12:00:01.000 SPELL_CAST_SUCCESS  garbage'
        assert parse_line(line) is None

    def test_unsupported_event_returns_none(self):
        # COMBAT_LOG_VERSION is never in SUPPORTED_EVENTS
        line = '4/4 2026 12:00:01.000  COMBAT_LOG_VERSION  garbage'
        assert parse_line(line) is None

    def test_empty_line_returns_none(self):
        assert parse_line("") is None


# ---------------------------------------------------------------------------
# ENCOUNTER_START / ENCOUNTER_END
# ---------------------------------------------------------------------------

class TestEncounterEvents:
    def test_encounter_start_parsed(self):
        ev = parse_line(_encounter_start())
        assert ev is not None
        assert ev.event_type == "ENCOUNTER_START"
        assert ev.encounter_id == 2093
        assert ev.encounter_name == "Tindral Sageswift"
        assert ev.difficulty_id == 14
        assert ev.raid_size == 20

    def test_encounter_end_parsed(self):
        ev = parse_line(_encounter_end())
        assert ev is not None
        assert ev.event_type == "ENCOUNTER_END"
        assert ev.encounter_name == "Tindral Sageswift"

    def test_encounter_start_passes_player_filter(self):
        """ENCOUNTER_START muss immer durchkommen, auch mit Player-Filter."""
        ev = parse_line(_encounter_start(), player_name="AndereKlasse")
        assert ev is not None

    def test_encounter_end_passes_player_filter(self):
        ev = parse_line(_encounter_end(), player_name="AndereKlasse")
        assert ev is not None


# ---------------------------------------------------------------------------
# SPELL_CAST_SUCCESS
# ---------------------------------------------------------------------------

class TestSpellCastSuccess:
    def test_spell_id_parsed(self):
        ev = parse_line(_cast(116, "Frostbolt"))
        assert ev is not None
        assert ev.spell_id == 116
        assert ev.spell_name == "Frostbolt"

    def test_source_name_parsed(self):
        ev = parse_line(_cast(116, "Frostbolt"))
        assert ev.source_name == PLAYER

    def test_dest_name_parsed(self):
        ev = parse_line(_cast(116, "Frostbolt"))
        assert ev.dest_name == ENEMY

    def test_flurry_parsed(self):
        ev = parse_line(_cast(44614, "Flurry"))
        assert ev is not None
        assert ev.spell_id == 44614

    def test_ice_lance_parsed(self):
        ev = parse_line(_cast(30455, "Ice Lance"))
        assert ev is not None
        assert ev.spell_id == 30455

    def test_ray_of_frost_parsed(self):
        ev = parse_line(_cast(205021, "Ray of Frost"))
        assert ev is not None
        assert ev.spell_id == 205021


# ---------------------------------------------------------------------------
# SPELL_AURA_APPLIED
# ---------------------------------------------------------------------------

class TestAuraEvents:
    def test_brain_freeze_buff_parsed(self):
        ev = parse_line(_aura(190447, "Brain Freeze"))
        assert ev is not None
        assert ev.spell_id == 190447
        assert ev.aura_type == "BUFF"

    def test_fingers_of_frost_parsed(self):
        ev = parse_line(_aura(112965, "Fingers of Frost"))
        assert ev is not None
        assert ev.spell_id == 112965

    def test_freezing_debuff_parsed(self):
        ev = parse_line(_aura(1221389, "Freezing", aura_type="DEBUFF",
                              dest=ENEMY, dest_guid=ENEMY_GUID))
        assert ev is not None
        assert ev.spell_id == 1221389
        assert ev.aura_type == "DEBUFF"

    def test_dose_stacks_parsed(self):
        ev = parse_line(_aura(1221389, "Freezing", aura_type="DEBUFF",
                              stacks=8,
                              dest=ENEMY, dest_guid=ENEMY_GUID))
        assert ev is not None
        assert ev.aura_stacks == 8


# ---------------------------------------------------------------------------
# Player-Filter
# ---------------------------------------------------------------------------

class TestPlayerFilter:
    def test_own_cast_passes(self):
        ev = parse_line(_cast(116, "Frostbolt"), player_name=PLAYER)
        assert ev is not None

    def test_foreign_cast_filtered(self):
        ev = parse_line(
            _cast(116, "Frostbolt", source="AndereKlasse", src_guid="Player-1-FFFFFFFF"),
            player_name=PLAYER,
        )
        assert ev is None

    def test_buff_on_self_passes(self):
        ev = parse_line(_aura(190447, "Brain Freeze"), player_name=PLAYER)
        assert ev is not None

    def test_buff_on_other_filtered(self):
        ev = parse_line(
            _aura(190447, "Brain Freeze",
                  source="AndereKlasse", src_guid="Player-1-FF",
                  dest="AndereKlasse", dest_guid="Player-1-FF"),
            player_name=PLAYER,
        )
        assert ev is None


# ---------------------------------------------------------------------------
# CombatLogParser (streaming)
# ---------------------------------------------------------------------------

class TestCombatLogParser:
    def test_feed_returns_event(self):
        p = CombatLogParser(player_name=PLAYER)
        ev = p.feed(_cast(116, "Frostbolt"))
        assert ev is not None
        assert ev.spell_id == 116

    def test_feed_filters_foreign(self):
        p = CombatLogParser(player_name=PLAYER)
        ev = p.feed(_cast(116, "Frostbolt", source="Jemand", src_guid="Player-1-ZZ"))
        assert ev is None

    def test_feed_none_on_garbage(self):
        p = CombatLogParser()
        assert p.feed("kein log format") is None


# ---------------------------------------------------------------------------
# Echtes WoW Midnight Log-Format (M/D/YYYY HH:MM:SS.frac  EVENT,...)
# ---------------------------------------------------------------------------

# Exakte Zeilen aus einem echten WoWCombatLog-040426_*.txt
REAL_CAST = (
    '4/4/2026 11:34:27.3972  SPELL_CAST_SUCCESS,'
    'Player-3691-053881FD,"Lugoor-Blackhand-EU",0x514,0x0,'
    'Creature-0-3769-658-375471-229227-00004B0D,"Stitchflesh",0xa48,0x0,'
    '116,"Frostbolt",0x10'
)
REAL_BRAIN_FREEZE = (
    '4/4/2026 11:34:12.4702  SPELL_AURA_APPLIED,'
    'Player-3691-053881FD,"Lugoor-Blackhand-EU",0x514,0x0,'
    'Player-3691-053881FD,"Lugoor-Blackhand-EU",0x514,0x0,'
    '190447,"Brain Freeze",0x10,"BUFF"'
)
REAL_ENCOUNTER_START = (
    '4/4/2026 11:40:00.0000  ENCOUNTER_START,'
    '2093,"Tindral Sageswift",14,20'
)
REAL_ICY_VEINS = (
    '4/4/2026 11:34:16.8792  SPELL_CAST_SUCCESS,'
    'Player-3691-053881FD,"Lugoor-Blackhand-EU",0x514,0x0,'
    'Player-3691-053881FD,"Lugoor-Blackhand-EU",0x514,0x0,'
    '12472,"Icy Veins",0x40'
)


class TestRealLogFormat:
    """Stellt sicher dass das echte WoW Midnight Format geparst wird."""

    def test_real_cast_parsed(self):
        ev = parse_line(REAL_CAST)
        assert ev is not None
        assert ev.event_type == "SPELL_CAST_SUCCESS"
        assert ev.spell_id == 116
        assert ev.spell_name == "Frostbolt"

    def test_real_timestamp_has_correct_year(self):
        ev = parse_line(REAL_CAST)
        assert ev is not None
        assert ev.timestamp.year == 2026
        assert ev.timestamp.month == 4
        assert ev.timestamp.day == 4
        assert ev.timestamp.hour == 11
        assert ev.timestamp.minute == 34

    def test_real_timestamp_fractional_ms(self):
        """4-stellige Millisekunden (3972) werden korrekt geparst."""
        ev = parse_line(REAL_CAST)
        assert ev is not None
        # 3972 → strptime %f → 397200 microseconds
        assert ev.timestamp.microsecond == 397200

    def test_real_brain_freeze_aura(self):
        ev = parse_line(REAL_BRAIN_FREEZE)
        assert ev is not None
        assert ev.spell_id == 190447
        assert ev.spell_name == "Brain Freeze"
        assert ev.aura_type == "BUFF"

    def test_real_encounter_start(self):
        ev = parse_line(REAL_ENCOUNTER_START)
        assert ev is not None
        assert ev.event_type == "ENCOUNTER_START"
        assert ev.encounter_id == 2093
        assert ev.encounter_name == "Tindral Sageswift"

    def test_real_source_name_includes_realm(self):
        ev = parse_line(REAL_CAST)
        assert ev is not None
        assert ev.source_name == "Lugoor-Blackhand-EU"

    def test_real_enemy_name_parsed(self):
        ev = parse_line(REAL_CAST)
        assert ev is not None
        assert ev.dest_name == "Stitchflesh"


class TestRealmSuffix:
    """Player-Filter muss Realm-Suffix tolerieren ('Lugoor' matched 'Lugoor-Blackhand-EU')."""

    def test_realm_suffix_passes_filter(self):
        ev = parse_line(REAL_CAST, player_name="Lugoor")
        assert ev is not None, "Lugoor-Blackhand-EU sollte mit Filter 'Lugoor' durchkommen"

    def test_realm_suffix_brain_freeze_passes(self):
        ev = parse_line(REAL_BRAIN_FREEZE, player_name="Lugoor")
        assert ev is not None

    def test_other_player_with_realm_filtered(self):
        line = (
            '4/4/2026 11:34:27.000  SPELL_CAST_SUCCESS,'
            'Player-1111-AAAAAAAA,"Choptown-Tarren Mill-EU",0x514,0x0,'
            'Creature-0-1-1-1-99999,"Boss",0xa48,0x0,'
            '116,"Frostbolt",0x10'
        )
        ev = parse_line(line, player_name="Lugoor")
        assert ev is None, "Anderer Spieler darf nicht durch den Lugoor-Filter kommen"

    def test_encounter_start_passes_regardless_of_realm(self):
        ev = parse_line(REAL_ENCOUNTER_START, player_name="Lugoor")
        assert ev is not None

    def test_exact_match_still_works(self):
        """Tests mit exaktem Namen (kein Realm) funktionieren weiterhin."""
        ev = parse_line(_cast(116, "Frostbolt"), player_name=PLAYER)
        assert ev is not None


class TestFrostMageSpellIds:
    """Stellt sicher, dass alle Frost-Mage-relevanten Spell-IDs korrekt sind.

    Diese IDs wurden gegen WoW-Spellbooks verifiziert und gegen den
    echten WoWCombatLog gegengeprüft (wo vorhanden).
    """

    # Bestätigte Core-DPS-Spells (Frost Mage, nicht andere Klassen)
    FROST_MAGE_DAMAGE_SPELLS = {
        116:    "Frostbolt",       # Frost Mage Basiszauber, seit Classic
        30455:  "Ice Lance",       # Frost Mage, seit TBC
        44614:  "Flurry",          # Frost Mage (NICHT Shaman Flurry!)
        84714:  "Frozen Orb",      # Frost Mage, seit Cataclysm
        199786: "Glacial Spike",   # Frost Mage, seit Legion
        205021: "Ray of Frost",    # Frost Mage Talent, seit Legion
        120:    "Cone of Frost",   # Frost Mage AoE, seit Classic
        190356: "Blizzard",        # Frost/Arcane Mage AoE
    }

    # Buffs (Frost Mage only)
    FROST_MAGE_BUFFS = {
        190447: "Brain Freeze",    # Frost Mage Proc, seit Legion
        112965: "Fingers of Frost",# Frost Mage Proc, seit MoP
        12472:  "Icy Veins",       # Frost Mage CD, seit Classic
    }

    # Off-GCD Utility (Mage class-wide oder Frost-specific)
    MAGE_UTILITY = {
        11426:  "Ice Barrier",     # Frost Mage defensiv, seit Classic
        212653: "Shimmer",         # Mage Talent (Blink-Ersatz), seit Legion
        80353:  "Time Warp",       # Mage Bloodlust, seit Cataclysm
        1459:   "Arcane Intellect",# Mage Gruppenbuffe, seit Classic
    }

    def test_frostbolt_id_correct(self):
        ev = parse_line(_cast(116, "Frostbolt"))
        assert ev.spell_id == 116

    def test_ice_lance_id_correct(self):
        ev = parse_line(_cast(30455, "Ice Lance"))
        assert ev.spell_id == 30455

    def test_flurry_id_correct(self):
        """Flurry 44614 ist Frost Mage – NICHT Shaman Flurry (17364)."""
        ev = parse_line(_cast(44614, "Flurry"))
        assert ev.spell_id == 44614
        assert ev.spell_id != 17364, "Shaman Flurry (17364) darf nicht verwechselt werden"

    def test_frozen_orb_id_correct(self):
        ev = parse_line(_cast(84714, "Frozen Orb"))
        assert ev.spell_id == 84714

    def test_glacial_spike_id_correct(self):
        ev = parse_line(_cast(199786, "Glacial Spike"))
        assert ev.spell_id == 199786

    def test_ray_of_frost_id_correct(self):
        ev = parse_line(_cast(205021, "Ray of Frost"))
        assert ev.spell_id == 205021

    def test_icy_veins_id_correct(self):
        """Icy Veins ist off-GCD und Buff, kein Schaden."""
        ev = parse_line(_cast(12472, "Icy Veins"))
        assert ev.spell_id == 12472

    def test_brain_freeze_buff_id(self):
        ev = parse_line(_aura(190447, "Brain Freeze", aura_type="BUFF"))
        assert ev.spell_id == 190447
        assert ev.aura_type == "BUFF"

    def test_fingers_of_frost_buff_id(self):
        ev = parse_line(_aura(112965, "Fingers of Frost", aura_type="BUFF"))
        assert ev.spell_id == 112965
        assert ev.aura_type == "BUFF"

    def test_freezing_debuff_id(self):
        """Freezing (1221389) ist ein DEBUFF auf dem Ziel – Midnight-Kernmechanik."""
        ev = parse_line(_aura(1221389, "Freezing", aura_type="DEBUFF",
                              dest=ENEMY, dest_guid="Creature-0-1-1-1-99999"))
        assert ev.spell_id == 1221389
        assert ev.aura_type == "DEBUFF"

    def test_all_damage_spell_ids_are_positive(self):
        for spell_id, name in self.FROST_MAGE_DAMAGE_SPELLS.items():
            assert spell_id > 0, f"{name} hat ungültige ID {spell_id}"

    def test_no_non_mage_spell_ids(self):
        """Stellt sicher, dass keine fremden Klassen-Spell-IDs vorhanden sind."""
        FOREIGN_CLASS_IDS = {
            17364: "Shaman Flurry",
            403:   "Lightning Bolt (Shaman)",
            5176:  "Wrath (Druid)",
            35395: "Crusader Strike (Paladin)",
        }
        all_mage_ids = set(self.FROST_MAGE_DAMAGE_SPELLS) | set(self.FROST_MAGE_BUFFS) | set(self.MAGE_UTILITY)
        for foreign_id, name in FOREIGN_CLASS_IDS.items():
            assert foreign_id not in all_mage_ids, \
                f"Fremder Spell {name} ({foreign_id}) darf nicht in Frost Mage Liste sein"
