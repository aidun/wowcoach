"""
watcher.py - Watches WoWCombatLog.txt for new lines using 50ms polling.

Detects file rotation (inode/size change) and skips to end on startup.
Uses a callback pattern: new lines are delivered via on_line(line: str).

Replay mode: CombatLogReplayer reads from the beginning of the file and
replays lines at the correct relative timing (scaled by speed multiplier).
"""

from __future__ import annotations

import logging
import os
import re
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

_log = logging.getLogger("wowcoach.watcher")


LOG_DIR = Path("C:/Program Files (x86)/World of Warcraft/_retail_/Logs")
POLL_INTERVAL = 0.05  # 50ms

# Re-export for convenience (callers can import from watcher)
from log_scanner import scan_players_in_log, scan_log  # noqa: E402,F401


def find_latest_combat_log(log_dir: Path = LOG_DIR) -> Path:
    """Return the most recently modified WoWCombatLog* file in log_dir.
    Falls back to a default path if none is found."""
    try:
        candidates = sorted(
            log_dir.glob("WoWCombatLog*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]
    except Exception:
        pass
    return log_dir / "WoWCombatLog.txt"


DEFAULT_LOG_PATH = find_latest_combat_log()


class CombatLogWatcher:
    """
    Polls WoWCombatLog.txt every 50ms for new lines.

    On startup, seeks to the end of the file so only new events are
    delivered. Detects file rotation by checking inode (UNIX) or size
    shrinkage (Windows, where inodes are not meaningful).
    """

    def __init__(
        self,
        on_line: Callable[[str], None],
        log_path: Optional[Path] = None,
        on_rotation: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_line = on_line
        self._on_rotation = on_rotation
        self._log_path: Path = log_path or DEFAULT_LOG_PATH
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._file = None
        self._inode: Optional[int] = None
        self._last_size: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background polling thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="CombatLogWatcher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the polling thread to stop and wait for it to exit."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._close_file()

    @property
    def log_path(self) -> Path:
        return self._log_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self) -> None:
        self._open_and_seek_end()
        self._check_newer_counter = 0
        self._line_count = 0
        while not self._stop_event.is_set():
            try:
                # Every ~5 seconds check if a newer WoWCombatLog* file appeared
                self._check_newer_counter += 1
                if self._check_newer_counter >= 100:
                    self._check_newer_counter = 0
                    self._switch_if_newer_log()
                self._poll()
            except Exception:
                _log.exception("Unexpected error in watcher loop")
            self._stop_event.wait(POLL_INTERVAL)

    def _switch_if_newer_log(self) -> None:
        """Switch to a newer WoWCombatLog* file if one appeared."""
        latest = find_latest_combat_log(LOG_DIR)
        if latest != self._log_path:
            self._close_file()
            self._log_path = latest
            self._open_and_seek_end()
            if self._on_rotation:
                self._on_rotation()

    def _open_and_seek_end(self) -> None:
        """Open the log file and seek to its current end."""
        try:
            self._file = open(self._log_path, "r", encoding="utf-8", errors="replace")
            self._file.seek(0, 2)  # seek to end
            stat = os.stat(self._log_path)
            self._last_size = stat.st_size
            self._inode = stat.st_ino  # 0 on Windows, still usable for rotation
            _log.info("Watching: %s (size=%d)", self._log_path, self._last_size)
        except FileNotFoundError:
            _log.error("Log file not found: %s", self._log_path)
            self._file = None
            self._inode = None
            self._last_size = 0

    def _poll(self) -> None:
        if self._file is None:
            # File didn't exist at start – keep trying to open it.
            if self._log_path.exists():
                self._open_and_seek_end()
            return

        # Check for file rotation: inode changed or file shrank.
        try:
            stat = os.stat(self._log_path)
            current_inode = stat.st_ino
            current_size = stat.st_size
        except FileNotFoundError:
            # File disappeared; close and wait for it to reappear.
            self._close_file()
            return

        rotated = False
        if current_inode != 0 and self._inode != 0:
            rotated = current_inode != self._inode
        if not rotated and current_size < self._last_size:
            rotated = True

        if rotated:
            self._close_file()
            if self._on_rotation:
                self._on_rotation()
            self._open_and_seek_end()
            return

        self._last_size = current_size

        # Read any new lines.
        while True:
            line = self._file.readline()
            if not line:
                break
            line = line.rstrip("\r\n")
            if line:
                self._line_count += 1
                if self._line_count % 100 == 0:
                    _log.debug("Lines delivered to engine: %d", self._line_count)
                self._on_line(line)

    def _close_file(self) -> None:
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
        self._inode = None
        self._last_size = 0


# ---------------------------------------------------------------------------
# Replay mode
# ---------------------------------------------------------------------------

# WoW combat log timestamp: "4/4 11:23:45.123  EVENT,..."
_TS_RE = re.compile(r"^(\d{1,2})/(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})\.(\d+)")


def _parse_log_time(line: str) -> Optional[float]:
    """Parse the leading timestamp of a WoW combat log line into seconds."""
    m = _TS_RE.match(line)
    if not m:
        return None
    mo, day, hh, mm, ss, frac = m.groups()
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + float(f"0.{frac}")


class CombatLogReplayer:
    """
    Reads a WoWCombatLog file from the beginning (or a given offset) and
    replays lines at the correct relative timing, scaled by `speed`.

    speed=1.0        → real-time replay
    speed=5.0        → 5× faster than real-time
    speed=0          → instant (no delay between lines)
    start_offset_s   → skip all lines whose timestamp < this many seconds-of-day
    """

    def __init__(
        self,
        on_line: Callable[[str], None],
        log_path: Optional[Path] = None,
        speed: float = 5.0,
        on_done: Optional[Callable[[], None]] = None,
        start_offset_s: float = 0.0,
    ) -> None:
        self._on_line = on_line
        self._log_path = log_path or DEFAULT_LOG_PATH
        self._speed = max(speed, 0.0)
        self._on_done = on_done
        self._start_offset_s = start_offset_s
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def log_path(self) -> Path:
        return self._log_path

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="CombatLogReplayer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        try:
            f = open(self._log_path, "r", encoding="utf-8", errors="replace")
        except FileNotFoundError:
            _log.error("Replay: file not found: %s", self._log_path)
            return
        _log.info("Replay: %s (speed=%.1f)", self._log_path, self._speed)

        prev_log_time: Optional[float] = None
        prev_wall_time: float = time.monotonic()
        skipping = self._start_offset_s > 0.0

        with f:
            for raw in f:
                if self._stop_event.is_set():
                    break

                line = raw.rstrip("\r\n")
                if not line:
                    continue

                # Skip lines before start_offset_s
                if skipping:
                    t = _parse_log_time(line)
                    if t is not None and t < self._start_offset_s:
                        continue
                    else:
                        skipping = False   # reached the desired start point

                if self._speed > 0:
                    log_t = _parse_log_time(line)
                    if log_t is not None:
                        if prev_log_time is not None:
                            log_delta = log_t - prev_log_time
                            # Handle midnight rollover
                            if log_delta < -3600:
                                log_delta += 86400
                            if log_delta > 0:
                                wall_delta = log_delta / self._speed
                                elapsed = time.monotonic() - prev_wall_time
                                sleep_for = wall_delta - elapsed
                                if sleep_for > 0:
                                    self._stop_event.wait(sleep_for)
                        prev_log_time = log_t
                        prev_wall_time = time.monotonic()

                self._on_line(line)

        if not self._stop_event.is_set() and self._on_done:
            self._on_done()


# ---------------------------------------------------------------------------
# Quick smoke-test / demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LOG_PATH

    def _print(line: str) -> None:
        print(f"[LINE] {line}")

    def _rotation() -> None:
        print("[WATCHER] Log file rotated!")

    watcher = CombatLogWatcher(on_line=_print, log_path=path, on_rotation=_rotation)
    print(f"[WATCHER] Watching {path} – press Ctrl+C to stop.")
    watcher.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        watcher.stop()
