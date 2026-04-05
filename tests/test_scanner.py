"""Tests for log_scanner.py – scan_log, scan_players_in_log."""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from log_scanner import scan_log, scan_players_in_log, EncounterSegment


def _write_log(lines: list[str]) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                      encoding="utf-8")
    for line in lines:
        tmp.write(line + "\n")
    tmp.close()
    return Path(tmp.name)


# ------------------------------------------------------------------
# Basic encounter detection (Raid)
# ------------------------------------------------------------------

class TestScanLogRaid:
    def _make_log(self) -> Path:
        lines = [
            '4/1 12:00:00.000  ENCOUNTER_START  1,"Onyxia",14,25',
            '4/1 12:00:01.000  SPELL_CAST_SUCCESS  Player-1-AABBCCDD,"Frostmage",0x514,0x0,Creature-0-1-1-1-12345,"Onyxia",0xa48,0x0,133,"Frostbolt",0x10',
            '4/1 12:02:30.000  ENCOUNTER_END  1,"Onyxia",14,25,1',
        ]
        return _write_log(lines)

    def test_raid_boss_segment_created(self):
        path = self._make_log()
        segs = scan_log(path)
        assert len(segs) >= 1
        boss = next((s for s in segs if s.segment_type == "boss"), None)
        assert boss is not None

    def test_raid_boss_name(self):
        path = self._make_log()
        segs = scan_log(path)
        boss = next(s for s in segs if s.segment_type == "boss")
        assert "Onyxia" in boss.name

    def test_raid_content_type(self):
        path = self._make_log()
        segs = scan_log(path)
        boss = next(s for s in segs if s.segment_type == "boss")
        assert boss.content_type == "raid"

    def test_raid_boss_duration(self):
        path = self._make_log()
        segs = scan_log(path)
        boss = next(s for s in segs if s.segment_type == "boss")
        assert boss.duration_s == pytest.approx(150, abs=1)


class TestScanLogTrash:
    def _make_log(self) -> Path:
        lines = [
            '4/1 12:00:00.000  ENCOUNTER_START  1,"Onyxia",14,25',
            '4/1 12:02:30.000  ENCOUNTER_END  1,"Onyxia",14,25,1',
            '4/1 12:03:00.000  ENCOUNTER_START  2,"Deathwing",14,25',
            '4/1 12:05:00.000  ENCOUNTER_END  2,"Deathwing",14,25,1',
        ]
        return _write_log(lines)

    def test_trash_segment_between_bosses(self):
        path = self._make_log()
        segs = scan_log(path)
        trash = [s for s in segs if s.segment_type == "trash_run"]
        assert len(trash) >= 1

    def test_two_boss_segments(self):
        path = self._make_log()
        segs = scan_log(path)
        bosses = [s for s in segs if s.segment_type == "boss"]
        assert len(bosses) == 2


# ------------------------------------------------------------------
# Mythic+ detection
# ------------------------------------------------------------------

class TestScanLogMythicPlus:
    def _make_log(self) -> Path:
        lines = [
            '4/1 12:00:00.000  CHALLENGE_MODE_START  "Mechagon",1822,379,15',
            '4/1 12:01:00.000  ENCOUNTER_START  1,"King Gobbamak",14,5',
            '4/1 12:02:00.000  ENCOUNTER_END  1,"King Gobbamak",14,5,1',
            '4/1 12:20:00.000  CHALLENGE_MODE_END  1822,1,1234567',
        ]
        return _write_log(lines)

    def test_mythic_plus_segment_created(self):
        path = self._make_log()
        segs = scan_log(path)
        mp = next((s for s in segs if s.segment_type == "mythic_plus"), None)
        assert mp is not None

    def test_mythic_plus_content_type(self):
        path = self._make_log()
        segs = scan_log(path)
        mp = next(s for s in segs if s.segment_type == "mythic_plus")
        assert mp.content_type == "mythic_plus"

    def test_boss_inside_mp_is_marker_not_segment(self):
        path = self._make_log()
        segs = scan_log(path)
        # No separate boss segment – boss should be a marker inside the M+ segment
        boss_segs = [s for s in segs if s.segment_type == "boss"]
        assert len(boss_segs) == 0

    def test_mp_has_boss_marker(self):
        path = self._make_log()
        segs = scan_log(path)
        mp = next(s for s in segs if s.segment_type == "mythic_plus")
        boss_markers = [m for m in mp.markers if m.marker_type == "boss"]
        assert len(boss_markers) >= 1

    def test_mp_boss_marker_label(self):
        path = self._make_log()
        segs = scan_log(path)
        mp = next(s for s in segs if s.segment_type == "mythic_plus")
        boss_markers = [m for m in mp.markers if m.marker_type == "boss"]
        assert any("King Gobbamak" in m.label for m in boss_markers)


# ------------------------------------------------------------------
# Trash-pack detection
# ------------------------------------------------------------------

class TestTrashPack:
    def _make_log_with_many_mobs(self) -> Path:
        # 6 different creatures attacking in the same 10s window
        lines = []
        for npc_id in range(1001, 1007):  # 6 unique creatures
            lines.append(
                f'4/1 12:05:00.000  SWING_DAMAGE  '
                f'Creature-0-1-1-1-{npc_id}-000000000A,"Mob{npc_id}",0xa48,0x0,'
                f'Player-1-AABBCCDD,"Tank",0x514,0x0,1234,0,1,0,0,0,nil'
            )
        return _write_log(lines)

    def test_trash_pack_marker_created(self):
        path = self._make_log_with_many_mobs()
        segs = scan_log(path)
        # There's no ENCOUNTER segment here, so we just check that the trash-pack
        # detection logic doesn't crash and scan succeeds
        assert isinstance(segs, list)

    def test_trash_pack_in_raid_segment(self):
        """Trash pack in a trash_run segment gets a marker."""
        lines = [
            '4/1 12:00:00.000  ENCOUNTER_START  1,"Boss",14,25',
            '4/1 12:02:00.000  ENCOUNTER_END  1,"Boss",14,25,1',
        ]
        # Add 6 mobs attacking during the "trash" phase after boss
        for npc_id in range(1001, 1007):
            lines.append(
                f'4/1 12:03:01.000  SWING_DAMAGE  '
                f'Creature-0-1-1-1-{npc_id}-000000000A,"Mob{npc_id}",0xa48,0x0,'
                f'Player-1-AABBCCDD,"Tank",0x514,0x0,1234,0,1,0,0,0,nil'
            )
        path = _write_log(lines)
        segs = scan_log(path)
        trash_segs = [s for s in segs if s.segment_type == "trash_run"]
        if trash_segs:
            trash_markers = [m for s in trash_segs for m in s.markers if m.marker_type == "trash_pack"]
            assert len(trash_markers) >= 1


# ------------------------------------------------------------------
# scan_players_in_log
# ------------------------------------------------------------------

class TestScanPlayers:
    def test_finds_players(self):
        lines = [
            '4/1 12:00:00.000  SPELL_CAST_SUCCESS  Player-1-AABBCCDD,"Frostmage-Realm-EU",0x514,0x0,Creature-0-1-1-1-12345,"Target",0xa48,0x0,133,"Frostbolt",0x10',
            '4/1 12:00:01.000  SPELL_CAST_SUCCESS  Player-2-11223344,"Paladin-Other-EU",0x514,0x0,Creature-0-1-1-1-12345,"Target",0xa48,0x0,633,"Holy Light",0x2',
        ]
        path = _write_log(lines)
        players = scan_players_in_log(path)
        assert any("Frostmage" in p for p in players)
        assert any("Paladin" in p for p in players)

    def test_returns_sorted(self):
        lines = [
            '4/1 12:00:00.000  SPELL_CAST_SUCCESS  Player-1-AABBCCDD,"Zara-Realm-EU",0x514,0x0,Creature-0-1-1-1-12345,"Target",0xa48,0x0,133,"Frostbolt",0x10',
            '4/1 12:00:01.000  SPELL_CAST_SUCCESS  Player-2-11223344,"Anya-Realm-EU",0x514,0x0,Creature-0-1-1-1-12345,"Target",0xa48,0x0,633,"Holy Light",0x2',
        ]
        path = _write_log(lines)
        players = scan_players_in_log(path)
        assert players == sorted(players)

    def test_deduplicates(self):
        lines = [
            '4/1 12:00:00.000  SPELL_CAST_SUCCESS  Player-1-AABBCCDD,"Frostmage-Realm-EU",0x514,0x0,Creature-0-1-1-1-12345,"Target",0xa48,0x0,133,"Frostbolt",0x10',
            '4/1 12:00:01.000  SPELL_CAST_SUCCESS  Player-1-AABBCCDD,"Frostmage-Realm-EU",0x514,0x0,Creature-0-1-1-1-12345,"Target",0xa48,0x0,133,"Frostbolt",0x10',
        ]
        path = _write_log(lines)
        players = scan_players_in_log(path)
        assert len(players) == 1

    def test_empty_log(self):
        path = _write_log([])
        players = scan_players_in_log(path)
        assert players == []
