"""
main.py - WoW Combat Log Analyzer – Frost Mage Overlay

Usage:
    python main.py --player <CharacterName> [--talent frostfire|spellslinger] [--log <path>]

Keyboard:
    Ctrl+Q or close window to quit.
    Click and drag the title bar to reposition.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import font as tkfont, filedialog, messagebox

# Local imports
import importlib as _importlib
from watcher import CombatLogWatcher, CombatLogReplayer, DEFAULT_LOG_PATH
from log_scanner import scan_players_in_log, scan_log, EncounterSegment
_parser_mod = _importlib.import_module("parser")
CombatLogParser = _parser_mod.CombatLogParser
from engine import FrostMageEngine, FightSummary

KNOWN_SPECS = [
    "frost_mage",
    "arcane_mage",
    "devastation_evoker",
    "augmentation_evoker",
]

# ---------------------------------------------------------------------------
# Theme constants
# ---------------------------------------------------------------------------

BG_DARK      = "#1a1a1a"
BG_SECTION   = "#242424"
BG_HEADER    = "#2d2d2d"
FG_PRIMARY   = "#e8e8e8"
FG_DIM       = "#8a8a8a"
FG_HINT      = "#ffd700"      # gold
FG_GOOD      = "#4caf50"      # green
FG_BAD       = "#ef5350"      # red
FG_WARN      = "#ff9800"      # orange
FG_TITLE     = "#90caf9"      # light blue
FG_MAJOR     = "#ef5350"
FG_MODERATE  = "#ff9800"
FG_MINOR     = "#ffe082"
FG_INFO      = "#80deea"

FONT_FAMILY  = "Consolas"
FONT_SIZE_SM = 9
FONT_SIZE_MD = 10
FONT_SIZE_LG = 12
FONT_TITLE   = 11

WINDOW_ALPHA = 0.92
WINDOW_W     = 520
WINDOW_H     = 700

CD_CHECK_INTERVAL_MS = 5000   # 5 seconds

# ---------------------------------------------------------------------------
# Helper: severity -> colour
# ---------------------------------------------------------------------------

def _severity_color(severity: str) -> str:
    mapping = {
        "major":    FG_MAJOR,
        "moderate": FG_MODERATE,
        "minor":    FG_MINOR,
        "info":     FG_INFO,
    }
    return mapping.get(severity, FG_DIM)


# ---------------------------------------------------------------------------
# Scrollable text widget helper
# ---------------------------------------------------------------------------

class ScrollText(tk.Frame):
    """A compact read-only Text widget with a scrollbar."""

    def __init__(self, parent, height: int = 5, **kwargs) -> None:
        super().__init__(parent, bg=BG_SECTION)
        self._text = tk.Text(
            self,
            height=height,
            bg=BG_SECTION,
            fg=FG_PRIMARY,
            insertbackground=FG_PRIMARY,
            font=(FONT_FAMILY, FONT_SIZE_SM),
            wrap=tk.WORD,
            state=tk.DISABLED,
            relief=tk.FLAT,
            bd=0,
            **kwargs,
        )
        scrollbar = tk.Scrollbar(self, command=self._text.yview, width=10)
        self._text.configure(yscrollcommand=scrollbar.set)
        self._text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def clear(self) -> None:
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.configure(state=tk.DISABLED)

    def append(self, text: str, color: str = FG_PRIMARY, newline: bool = True) -> None:
        self._text.configure(state=tk.NORMAL)
        tag = f"color_{color.replace('#','')}"
        self._text.tag_configure(tag, foreground=color)
        self._text.insert(tk.END, text + ("\n" if newline else ""), tag)
        self._text.see(tk.END)
        self._text.configure(state=tk.DISABLED)

    def set_text(self, text: str, color: str = FG_PRIMARY) -> None:
        self.clear()
        self.append(text, color, newline=False)


# ---------------------------------------------------------------------------
# Section widget
# ---------------------------------------------------------------------------

class Section(tk.Frame):
    """A labelled collapsible section frame."""

    def __init__(self, parent, title: str, **kwargs) -> None:
        super().__init__(parent, bg=BG_DARK, **kwargs)
        header = tk.Frame(self, bg=BG_HEADER)
        header.pack(fill=tk.X)
        self._title_var = tk.StringVar(value=f"  {title}")
        self._title_label = tk.Label(
            header,
            textvariable=self._title_var,
            bg=BG_HEADER,
            fg=FG_TITLE,
            font=(FONT_FAMILY, FONT_TITLE, "bold"),
            anchor="w",
        )
        self._title_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=3)
        self.content = tk.Frame(self, bg=BG_SECTION, pady=4, padx=6)
        self.content.pack(fill=tk.BOTH, expand=True)

    def set_title(self, title: str) -> None:
        self._title_var.set(f"  {title}")


# ---------------------------------------------------------------------------
# Main overlay window
# ---------------------------------------------------------------------------

class OverlayApp:
    """The primary tkinter window."""

    def __init__(
        self,
        root: tk.Tk,
        player_name: str,
        talent: str,
        log_path: Path,
        replay: bool = False,
        replay_speed: float = 5.0,
        spec: str = None,
    ) -> None:
        self.root = root
        self.player_name = player_name
        self.talent = talent
        self.log_path = log_path
        self.replay = replay
        self.replay_speed = replay_speed

        # Cached segments from log scanner (filled on demand)
        self._segments: list[EncounterSegment] = []
        # Track live encounter label to avoid spurious dropdown updates
        self._live_encounter_name: str = ""

        # Engine & parser
        self.engine = FrostMageEngine(talent=talent, spec=spec, player_name=player_name)
        self.parser = CombatLogParser(player_name=player_name if player_name else None)

        # Thread safety: events processed from watcher thread, UI updated on main
        self._hint_lock = threading.Lock()

        self._setup_window()
        self._build_ui()
        self._start_watcher()
        self._schedule_cd_check()
        self._schedule_ui_refresh()

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.root.title("WoW Coach – Frost Mage")
        self.root.configure(bg=BG_DARK)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", WINDOW_ALPHA)
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}+20+20")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Control-q>", lambda e: self._on_close())

        # Drag support
        self.root.bind("<ButtonPress-1>", self._on_drag_start)
        self.root.bind("<B1-Motion>", self._on_drag_motion)
        self._drag_x = 0
        self._drag_y = 0

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _on_drag_motion(self, event: tk.Event) -> None:
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Title bar
        title_bar = tk.Frame(self.root, bg="#0d47a1", height=30)
        title_bar.pack(fill=tk.X)
        title_bar.bind("<ButtonPress-1>", self._on_drag_start)
        title_bar.bind("<B1-Motion>", self._on_drag_motion)

        self._status_var = tk.StringVar(value="Watching log…")

        tk.Label(
            title_bar,
            text="  WoW Coach",
            bg="#0d47a1",
            fg="white",
            font=(FONT_FAMILY, FONT_TITLE, "bold"),
            anchor="w",
        ).pack(side=tk.LEFT, padx=4)

        tk.Label(
            title_bar,
            textvariable=self._status_var,
            bg="#0d47a1",
            fg="#bbdefb",
            font=(FONT_FAMILY, FONT_SIZE_SM),
            anchor="e",
        ).pack(side=tk.RIGHT, padx=8)

        # Settings button
        tk.Button(
            title_bar, text="⚙", bg="#1565c0", fg="white",
            font=(FONT_FAMILY, FONT_SIZE_SM, "bold"),
            relief=tk.FLAT, cursor="hand2",
            command=self._open_settings,
        ).pack(side=tk.RIGHT, padx=2)

        # Mode switcher: Live / Replay / Summary
        self._mode_var = tk.StringVar(value="live" if not self.replay else "replay")
        mode_frame = tk.Frame(title_bar, bg="#0d47a1")
        mode_frame.pack(side=tk.RIGHT, padx=6)
        for mode_val, mode_label in [
            ("live",    "🔴 Live"),
            ("replay",  "⏵ Replay"),
            ("summary", "📊 Summary"),
        ]:
            tk.Radiobutton(
                mode_frame,
                text=mode_label,
                variable=self._mode_var,
                value=mode_val,
                command=self._on_mode_change,
                bg="#0d47a1",
                fg="white",
                selectcolor="#1565c0",
                activebackground="#1565c0",
                activeforeground="white",
                font=(FONT_FAMILY, FONT_SIZE_SM),
                relief=tk.FLAT,
                indicatoron=False,
                cursor="hand2",
                padx=6,
                pady=2,
            ).pack(side=tk.LEFT, padx=1)

        # Player / talent info
        info_bar = tk.Frame(self.root, bg=BG_HEADER)
        info_bar.pack(fill=tk.X)
        self._player_info_var = tk.StringVar(
            value=f"  Player: {self.player_name or 'Any'}   Talent: {self.talent.title()}"
        )
        tk.Label(
            info_bar,
            textvariable=self._player_info_var,
            bg=BG_HEADER,
            fg=FG_DIM,
            font=(FONT_FAMILY, FONT_SIZE_SM),
            anchor="w",
        ).pack(side=tk.LEFT, padx=4, pady=2)

        self._encounter_var = tk.StringVar(value="No active encounter")
        tk.Label(
            info_bar,
            textvariable=self._encounter_var,
            bg=BG_HEADER,
            fg=FG_WARN,
            font=(FONT_FAMILY, FONT_SIZE_SM, "bold"),
            anchor="e",
        ).pack(side=tk.RIGHT, padx=8, pady=2)

        # Scrollable main area
        canvas = tk.Canvas(self.root, bg=BG_DARK, highlightthickness=0)
        vscroll = tk.Scrollbar(self.root, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._inner = tk.Frame(canvas, bg=BG_DARK)
        canvas_window = canvas.create_window((0, 0), window=self._inner, anchor="nw")

        def on_frame_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(e):
            canvas.itemconfig(canvas_window, width=e.width)

        self._inner.bind("<Configure>", on_frame_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._build_sections(self._inner)

    def _build_sections(self, parent: tk.Frame) -> None:
        pad = dict(fill=tk.X, padx=6, pady=4)

        # ---- Section 0: Encounter-Auswahl ----
        sec_enc_sel = Section(parent, "Encounter auswählen")
        sec_enc_sel.pack(**pad)
        enc_top = tk.Frame(sec_enc_sel.content, bg=BG_SECTION)
        enc_top.pack(fill=tk.X)

        self._segment_var = tk.StringVar(value="(Log scannen…)")
        self._segment_dropdown = tk.OptionMenu(enc_top, self._segment_var, "(kein)")
        self._segment_dropdown.configure(
            bg=BG_HEADER, fg=FG_PRIMARY,
            font=(FONT_FAMILY, FONT_SIZE_SM),
            highlightthickness=0, relief=tk.FLAT
        )
        self._segment_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Button(
            enc_top, text="🔍 Scannen", bg=BG_HEADER, fg=FG_PRIMARY,
            font=(FONT_FAMILY, FONT_SIZE_SM), relief=tk.FLAT, cursor="hand2",
            command=self._scan_log_segments,
        ).pack(side=tk.LEFT, padx=4)

        tk.Button(
            enc_top, text="▶ Analysieren", bg="#1b5e20", fg="white",
            font=(FONT_FAMILY, FONT_SIZE_SM), relief=tk.FLAT, cursor="hand2",
            command=self._analyse_selected_segment,
        ).pack(side=tk.LEFT, padx=2)

        # Time-range sub-selector – nur im Replay-Modus
        self._time_from_var = tk.DoubleVar(value=0.0)
        self._time_to_var = tk.DoubleVar(value=600.0)
        self._time_from_scale = None
        self._time_to_scale = None
        if self.replay:
            time_frame = tk.Frame(sec_enc_sel.content, bg=BG_SECTION)
            time_frame.pack(fill=tk.X, pady=(4, 0))
            tk.Label(time_frame, text="Von:", bg=BG_SECTION, fg=FG_DIM,
                     font=(FONT_FAMILY, FONT_SIZE_SM)).pack(side=tk.LEFT)
            self._time_from_scale = tk.Scale(
                time_frame, variable=self._time_from_var,
                from_=0, to=600, resolution=1, orient=tk.HORIZONTAL,
                bg=BG_SECTION, fg=FG_PRIMARY, highlightthickness=0,
                font=(FONT_FAMILY, FONT_SIZE_SM), length=120,
            )
            self._time_from_scale.pack(side=tk.LEFT)
            tk.Label(time_frame, text="s  Bis:", bg=BG_SECTION, fg=FG_DIM,
                     font=(FONT_FAMILY, FONT_SIZE_SM)).pack(side=tk.LEFT)
            self._time_to_scale = tk.Scale(
                time_frame, variable=self._time_to_var,
                from_=0, to=600, resolution=1, orient=tk.HORIZONTAL,
                bg=BG_SECTION, fg=FG_PRIMARY, highlightthickness=0,
                font=(FONT_FAMILY, FONT_SIZE_SM), length=120,
            )
            self._time_to_scale.pack(side=tk.LEFT)
            tk.Label(time_frame, text="s", bg=BG_SECTION, fg=FG_DIM,
                     font=(FONT_FAMILY, FONT_SIZE_SM)).pack(side=tk.LEFT)
            tk.Button(
                time_frame, text="↺ Neu", bg=BG_HEADER, fg=FG_PRIMARY,
                font=(FONT_FAMILY, FONT_SIZE_SM), relief=tk.FLAT, cursor="hand2",
                command=self._analyse_selected_segment,
            ).pack(side=tk.LEFT, padx=4)

        # Markers text
        self._markers_text = ScrollText(sec_enc_sel.content, height=3)
        self._markers_text.pack(fill=tk.BOTH, expand=True)
        self._markers_text.append("Scanne Log für Encounter-Übersicht…", FG_DIM)

        # ---- Section 1: Live Hints ----
        sec_hints = Section(parent, "Live Hints")
        sec_hints.pack(**pad)
        self._hints_text = ScrollText(sec_hints.content, height=6)
        self._hints_text.pack(fill=tk.BOTH, expand=True)
        self._hints_text.append(
            "Waiting for combat events…", FG_DIM
        )

        # ---- Section 2: Opener ----
        sec_opener = Section(parent, "Opener  (first 10s)")
        sec_opener.pack(**pad)

        score_frame = tk.Frame(sec_opener.content, bg=BG_SECTION)
        score_frame.pack(fill=tk.X)
        tk.Label(score_frame, text="Score:", bg=BG_SECTION, fg=FG_DIM,
                 font=(FONT_FAMILY, FONT_SIZE_SM)).pack(side=tk.LEFT)
        self._opener_score_var = tk.StringVar(value="—")
        self._opener_score_lbl = tk.Label(
            score_frame, textvariable=self._opener_score_var,
            bg=BG_SECTION, fg=FG_PRIMARY,
            font=(FONT_FAMILY, FONT_SIZE_LG, "bold")
        )
        self._opener_score_lbl.pack(side=tk.LEFT, padx=6)

        tk.Label(sec_opener.content, text="Actual sequence:", bg=BG_SECTION,
                 fg=FG_DIM, font=(FONT_FAMILY, FONT_SIZE_SM), anchor="w"
                 ).pack(fill=tk.X)
        self._opener_actual_text = ScrollText(sec_opener.content, height=3)
        self._opener_actual_text.pack(fill=tk.BOTH, expand=True)

        tk.Label(sec_opener.content, text="Expected sequence:", bg=BG_SECTION,
                 fg=FG_DIM, font=(FONT_FAMILY, FONT_SIZE_SM), anchor="w"
                 ).pack(fill=tk.X)
        self._opener_expected_text = ScrollText(sec_opener.content, height=2)
        self._opener_expected_text.pack(fill=tk.BOTH, expand=True)

        tk.Label(sec_opener.content, text="Missed steps:", bg=BG_SECTION,
                 fg=FG_DIM, font=(FONT_FAMILY, FONT_SIZE_SM), anchor="w"
                 ).pack(fill=tk.X)
        self._opener_missed_text = ScrollText(sec_opener.content, height=2)
        self._opener_missed_text.pack(fill=tk.BOTH, expand=True)

        # ---- Section 3: GCD Efficiency ----
        sec_gcd = Section(parent, "GCD Efficiency")
        sec_gcd.pack(**pad)

        gcd_stats = tk.Frame(sec_gcd.content, bg=BG_SECTION)
        gcd_stats.pack(fill=tk.X)

        self._gcd_casts_var  = tk.StringVar(value="Casts: 0")
        self._gcd_waste_var  = tk.StringVar(value="Waste: 0ms (0.0%)")
        tk.Label(gcd_stats, textvariable=self._gcd_casts_var,
                 bg=BG_SECTION, fg=FG_PRIMARY,
                 font=(FONT_FAMILY, FONT_SIZE_SM)).pack(side=tk.LEFT, padx=4)
        tk.Label(gcd_stats, textvariable=self._gcd_waste_var,
                 bg=BG_SECTION, fg=FG_WARN,
                 font=(FONT_FAMILY, FONT_SIZE_SM, "bold")).pack(side=tk.LEFT, padx=4)

        tk.Label(sec_gcd.content, text="Top 3 worst gaps:", bg=BG_SECTION,
                 fg=FG_DIM, font=(FONT_FAMILY, FONT_SIZE_SM), anchor="w"
                 ).pack(fill=tk.X)
        self._gcd_gaps_text = ScrollText(sec_gcd.content, height=4)
        self._gcd_gaps_text.pack(fill=tk.BOTH, expand=True)

        # ---- Section 4: Rotation Errors ----
        sec_err = Section(parent, "Rotation Errors")
        sec_err.pack(**pad)
        self._errors_text = ScrollText(sec_err.content, height=8)
        self._errors_text.pack(fill=tk.BOTH, expand=True)
        self._errors_text.append("No errors yet.", FG_GOOD)

    # ------------------------------------------------------------------
    # Watcher + parser wiring
    # ------------------------------------------------------------------

    def _start_watcher(self) -> None:
        if self.replay:
            # Scan players in log and show selection dialog if player not set
            if not self.player_name:
                players = scan_players_in_log(self.log_path)
                if players:
                    selected = self._ask_player_selection(players)
                    if selected:
                        self.player_name = selected.split("-")[0]
                        self.parser = CombatLogParser(player_name=self.player_name)
            speed_str = f"{self.replay_speed}×" if self.replay_speed > 0 else "instant"
            self._update_status(f"REPLAY {speed_str}: {self.log_path.name}")
            self._watcher = CombatLogReplayer(
                on_line=self._on_line,
                log_path=self.log_path,
                speed=self.replay_speed,
                on_done=self._on_replay_done,
            )
            self._watcher.start()
        else:
            # Live mode: ask for player name if not set
            if not self.player_name:
                name = self._ask_player_name()
                if name:
                    self.player_name = name
                    self.parser = CombatLogParser(player_name=self.player_name)
                    # Update info bar label
                    self.root.after(0, self._refresh_player_label)
            self._watcher = CombatLogWatcher(
                on_line=self._on_line,
                log_path=self.log_path,
                on_rotation=self._on_log_rotated,
            )
            self._watcher.start()
            self._update_status(f"Watching: {self.log_path.name}")
            # Auto-scan existing log for encounter history (background thread)
            self._scan_log_segments()

    def _on_line(self, line: str) -> None:
        """Called from watcher background thread – keep it fast."""
        try:
            ev = self.parser.feed(line)
            if ev:
                self.engine.process_event(ev)
        except Exception:
            logging.getLogger("wowcoach.main").exception(
                "Error processing line: %.80r", line
            )

    def _on_log_rotated(self) -> None:
        self.root.after(0, lambda: self._update_status("Log rotated – reconnected"))

    def _on_replay_done(self) -> None:
        self.root.after(0, lambda: self._update_status("✔ Replay abgeschlossen"))

    # ------------------------------------------------------------------
    # Periodic UI refresh (100ms)
    # ------------------------------------------------------------------

    def _schedule_ui_refresh(self) -> None:
        self.root.after(100, self._refresh_ui)

    def _refresh_ui(self) -> None:
        try:
            self._refresh_encounter()
            self._refresh_hints()
            self._refresh_opener()
            self._refresh_gcd()
            self._refresh_errors()
        except Exception:
            pass
        self.root.after(100, self._refresh_ui)

    def _refresh_encounter(self) -> None:
        if self.engine.in_encounter:
            self._encounter_var.set(f"IN COMBAT: {self.engine.encounter_name}")
            if not self.replay:
                live_label = f"🔴 LIVE: {self.engine.encounter_name}"
                if self._segment_var.get() != live_label:
                    self._segment_var.set(live_label)
        else:
            self._encounter_var.set("No active encounter")
            if not self.replay and self._segment_var.get().startswith("🔴 LIVE:"):
                self._segment_var.set("(kein aktiver Encounter)")

    def _refresh_hints(self) -> None:
        hints = self.engine.live_hints
        if hints:
            for h in hints:
                self._hints_text.append(h, FG_HINT)

    def _refresh_opener(self) -> None:
        actual, expected = self.engine.current_opener_state()

        # Score: intersection-count (each expected spell counts only once)
        remaining = list(expected)
        matched = 0
        for a in actual:
            if a in remaining:
                matched += 1
                remaining.remove(a)
        live_score = min(100, int(matched / max(len(expected), 1) * 100))
        score_color = FG_GOOD if live_score >= 80 else (FG_WARN if live_score >= 50 else FG_BAD)
        self._opener_score_var.set(f"{live_score}/100")
        self._opener_score_lbl.configure(fg=score_color)

        # Actual
        self._opener_actual_text.set_text(
            " → ".join(actual) if actual else "(no casts yet)",
            FG_PRIMARY if actual else FG_DIM,
        )

        # Expected
        self._opener_expected_text.set_text(
            " → ".join(expected),
            FG_DIM,
        )

        # Missed
        missed = [e for e in expected if e not in actual]
        self._opener_missed_text.set_text(
            ", ".join(missed) if missed else "None",
            FG_BAD if missed else FG_GOOD,
        )

    def _refresh_gcd(self) -> None:
        casts, waste_ms, waste_pct = self.engine.current_gcd_stats()
        self._gcd_casts_var.set(f"Casts: {casts}")
        waste_s = waste_ms / 1000.0
        self._gcd_waste_var.set(f"Waste: {waste_s:.1f}s ({waste_pct:.1f}%)")

        # Rebuild worst gaps
        summary = self.engine.build_summary()
        self._gcd_gaps_text.clear()
        if summary.worst_gaps:
            for i, gap in enumerate(summary.worst_gaps, 1):
                waste = max(0, gap.gap_ms - 1500)
                line = (
                    f"#{i}: {gap.start_spell} → {gap.end_spell}  "
                    f"gap={gap.gap_ms/1000:.1f}s  waste={waste/1000:.1f}s"
                )
                color = FG_BAD if waste > 1000 else FG_WARN
                self._gcd_gaps_text.append(line, color)
        else:
            self._gcd_gaps_text.append("No significant gaps yet.", FG_GOOD)

    def _refresh_errors(self) -> None:
        errors = self.engine.current_rotation_errors()
        self._errors_text.clear()
        if not errors:
            self._errors_text.append("No errors detected.", FG_GOOD)
            return
        # Show last 20 errors, most recent first
        for err in reversed(errors[-20:]):
            ts_str = err.timestamp.strftime("%H:%M:%S")
            line = f"[{ts_str}] [{err.severity.upper()}] {err.message}"
            self._errors_text.append(line, _severity_color(err.severity))

    # ------------------------------------------------------------------
    # Periodic cooldown check (every 5s)
    # ------------------------------------------------------------------

    def _schedule_cd_check(self) -> None:
        self.root.after(CD_CHECK_INTERVAL_MS, self._run_cd_check)

    def _run_cd_check(self) -> None:
        hints = self.engine.check_cooldowns(current_time=datetime.utcnow())
        for h in hints:
            self._hints_text.append(f"[CD] {h}", FG_WARN)
        self.root.after(CD_CHECK_INTERVAL_MS, self._run_cd_check)

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _update_status(self, msg: str) -> None:
        self._status_var.set(msg)

    # ------------------------------------------------------------------
    # Player name / selection dialogs
    # ------------------------------------------------------------------

    def _ask_player_name(self) -> Optional[str]:
        """Show a simple modal dialog to enter the character name (live mode)."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Spieler eingeben")
        dialog.configure(bg=BG_DARK)
        dialog.geometry("300x150")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Charakter-Name:", bg=BG_DARK, fg=FG_PRIMARY,
                 font=(FONT_FAMILY, FONT_SIZE_MD)).pack(pady=(14, 4))
        entry = tk.Entry(dialog, bg=BG_SECTION, fg=FG_PRIMARY,
                         insertbackground=FG_PRIMARY,
                         font=(FONT_FAMILY, FONT_SIZE_MD), relief=tk.FLAT)
        entry.pack(fill=tk.X, padx=20, pady=4)
        entry.focus_set()

        result = [None]

        def on_ok(e=None):
            v = entry.get().strip()
            if v:
                result[0] = v
            dialog.destroy()

        entry.bind("<Return>", on_ok)
        tk.Button(dialog, text="OK", command=on_ok, bg="#1565c0", fg="white",
                  font=(FONT_FAMILY, FONT_SIZE_SM), relief=tk.FLAT, width=10).pack(pady=8)

        dialog.wait_window()
        return result[0]

    def _ask_player_selection(self, players: list[str]) -> Optional[str]:
        """Show a modal dialog to pick a player from the scanned list."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Spieler auswählen")
        dialog.configure(bg=BG_DARK)
        dialog.geometry("320x280")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Spieler im Log:", bg=BG_DARK, fg=FG_PRIMARY,
                 font=(FONT_FAMILY, FONT_SIZE_MD)).pack(pady=(10, 4))

        listbox = tk.Listbox(dialog, bg=BG_SECTION, fg=FG_PRIMARY,
                             font=(FONT_FAMILY, FONT_SIZE_SM), height=8,
                             selectbackground="#1565c0")
        for p in players:
            listbox.insert(tk.END, p)
        if players:
            listbox.selection_set(0)
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        result = [None]

        def on_ok():
            sel = listbox.curselection()
            if sel:
                result[0] = players[sel[0]]
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, pady=8)
        tk.Button(btn_frame, text="OK", command=on_ok, bg="#1565c0", fg="white",
                  font=(FONT_FAMILY, FONT_SIZE_SM), relief=tk.FLAT, width=8).pack(side=tk.LEFT, padx=8)
        tk.Button(btn_frame, text="Abbrechen", command=on_cancel, bg=BG_HEADER, fg=FG_PRIMARY,
                  font=(FONT_FAMILY, FONT_SIZE_SM), relief=tk.FLAT, width=10).pack(side=tk.LEFT)

        dialog.wait_window()
        return result[0]

    # ------------------------------------------------------------------
    # Log segment scanning
    # ------------------------------------------------------------------

    def _scan_log_segments(self) -> None:
        """Scan the log file and populate the segment dropdown."""
        self._markers_text.clear()
        self._markers_text.append("Scanne…", FG_DIM)

        def _do_scan():
            try:
                segments = scan_log(self.log_path)
            except Exception as exc:
                self.root.after(0, lambda: self._markers_text.set_text(f"Fehler: {exc}", FG_BAD))
                return
            self.root.after(0, lambda: self._on_segments_scanned(segments))

        threading.Thread(target=_do_scan, daemon=True).start()

    def _on_segments_scanned(self, segments: list[EncounterSegment]) -> None:
        self._segments = segments
        self._markers_text.clear()
        if not segments:
            self._markers_text.append("Keine Encounter im Log gefunden.", FG_DIM)
            return

        # Update dropdown
        names = [s.display_name() for s in segments]
        menu = self._segment_dropdown["menu"]
        menu.delete(0, "end")
        for n in names:
            menu.add_command(label=n, command=lambda v=n: self._segment_var.set(v))
        # Don't overwrite the live encounter label if one is currently active
        if not self._segment_var.get().startswith("🔴 LIVE:"):
            self._segment_var.set(names[0] if names else "(kein)")

        # Update time sliders for first segment
        self._update_time_sliders(segments[0] if segments else None)

        # Show markers summary
        for seg in segments:
            self._markers_text.append(seg.display_name(), FG_TITLE)
            for m in seg.markers:
                icon = {"boss": "👑", "trash_pack": "🗡", "challenge_start": "🔑", "challenge_end": "✔"}.get(m.marker_type, "•")
                self._markers_text.append(f"  {icon} {m.label}", FG_DIM)

        self._markers_text.append(f"\n{len(segments)} Segmente gefunden.", FG_GOOD)

    # ------------------------------------------------------------------
    # Time sliders
    # ------------------------------------------------------------------

    def _update_time_sliders(self, segment: Optional[EncounterSegment]) -> None:
        if segment is None:
            return
        dur = max(int(segment.duration_s), 1)
        self._time_from_var.set(0)
        self._time_to_var.set(dur)
        if self._time_from_scale:
            self._time_from_scale.configure(from_=0, to=dur)
        if self._time_to_scale:
            self._time_to_scale.configure(from_=0, to=dur)

    # ------------------------------------------------------------------
    # Segment analysis
    # ------------------------------------------------------------------

    def _analyse_selected_segment(self) -> None:
        """Replay the selected encounter segment through the engine."""
        seg_name = self._segment_var.get()
        if not self._segments or seg_name in ("(kein)", "(Log scannen…)"):
            messagebox.showinfo("Kein Segment", "Bitte zuerst Log scannen und Segment auswählen.")
            return

        # Find segment by display name
        seg = next((s for s in self._segments if s.display_name() == seg_name), None)
        if seg is None:
            messagebox.showerror("Fehler", f"Segment nicht gefunden: {seg_name}")
            return

        from_s = self._time_from_var.get()
        to_s = self._time_to_var.get()

        # Stop any running watcher/replayer before starting analysis
        try:
            self._watcher.stop()
        except Exception:
            pass

        # Reset engine
        self.engine.reset()
        self._hints_text.clear()
        self._errors_text.clear()
        self._errors_text.append("Analysiere…", FG_DIM)

        def _replay_segment():
            try:
                import importlib as _il
                _pm = _il.import_module("parser")
                _parse_line = _pm.parse_line

                seg_start = seg.start
                seg_end = seg.end

                with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                    for raw in f:
                        line = raw.rstrip("\r\n")
                        if not line:
                            continue
                        ev = _parse_line(line, player_name=self.player_name if self.player_name else None)
                        if ev is None:
                            continue
                        # Filter by segment time range
                        if ev.timestamp < seg_start:
                            continue
                        if seg_end and ev.timestamp > seg_end:
                            break
                        # Filter by user-selected time offset within segment
                        offset_s = (ev.timestamp - seg_start).total_seconds()
                        if offset_s < from_s or offset_s > to_s:
                            continue
                        self.engine.process_event(ev)
            except Exception as exc:
                self.root.after(0, lambda: self._errors_text.set_text(f"Fehler: {exc}", FG_BAD))
                return
            self.root.after(0, lambda: self._update_status(f"✔ Analyse: {seg_name}"))

        threading.Thread(target=_replay_segment, daemon=True).start()

    # ------------------------------------------------------------------
    # Replay from here
    # ------------------------------------------------------------------

    def _replay_from_here(self) -> None:
        """Stop live watcher and start a replay from the current log position."""
        # Get last known timestamp from engine as start offset
        start_ts = None
        if hasattr(self.engine, '_last_cast_time') and self.engine._last_cast_time:
            start_ts = self.engine._last_cast_time

        # Stop current watcher
        try:
            self._watcher.stop()
        except Exception:
            pass

        # If we have a timestamp, convert to seconds-of-day for start_offset_s
        start_offset_s = 0.0
        if start_ts:
            start_offset_s = start_ts.hour * 3600 + start_ts.minute * 60 + start_ts.second + start_ts.microsecond / 1e6

        self.engine.reset()
        self._watcher = CombatLogReplayer(
            on_line=self._on_line,
            log_path=self.log_path,
            speed=self.replay_speed,
            on_done=self._on_replay_done,
            start_offset_s=start_offset_s,
        )
        self._watcher.start()
        speed_str = f"{self.replay_speed}×" if self.replay_speed > 0 else "instant"
        self._update_status(f"REPLAY ab {start_offset_s:.0f}s  {speed_str}")

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        """Open the settings dialog."""
        dialog = tk.Toplevel(self.root)
        dialog.title("⚙ Einstellungen")
        dialog.configure(bg=BG_DARK)
        dialog.geometry("420x300")
        dialog.transient(self.root)
        dialog.grab_set()

        def _row(label, widget_factory):
            row = tk.Frame(dialog, bg=BG_DARK)
            row.pack(fill=tk.X, padx=16, pady=4)
            tk.Label(row, text=label, bg=BG_DARK, fg=FG_DIM,
                     font=(FONT_FAMILY, FONT_SIZE_SM), width=16, anchor="w").pack(side=tk.LEFT)
            w = widget_factory(row)
            w.pack(side=tk.LEFT, fill=tk.X, expand=True)
            return w

        tk.Label(dialog, text="Einstellungen", bg=BG_DARK, fg=FG_TITLE,
                 font=(FONT_FAMILY, FONT_SIZE_LG, "bold")).pack(pady=(12, 8))

        # Player
        player_var = tk.StringVar(value=self.player_name)
        _row("Spieler:", lambda p: tk.Entry(p, textvariable=player_var, bg=BG_SECTION,
                                            fg=FG_PRIMARY, insertbackground=FG_PRIMARY,
                                            font=(FONT_FAMILY, FONT_SIZE_SM), relief=tk.FLAT))

        # Spec
        spec_var = tk.StringVar(value=self.talent)
        _row("Spec:", lambda p: tk.OptionMenu(p, spec_var, *KNOWN_SPECS))

        # Log file
        log_var = tk.StringVar(value=str(self.log_path))
        log_row = tk.Frame(dialog, bg=BG_DARK)
        log_row.pack(fill=tk.X, padx=16, pady=4)
        tk.Label(log_row, text="Log-Datei:", bg=BG_DARK, fg=FG_DIM,
                 font=(FONT_FAMILY, FONT_SIZE_SM), width=16, anchor="w").pack(side=tk.LEFT)
        tk.Entry(log_row, textvariable=log_var, bg=BG_SECTION, fg=FG_PRIMARY,
                 insertbackground=FG_PRIMARY, font=(FONT_FAMILY, FONT_SIZE_SM),
                 relief=tk.FLAT).pack(side=tk.LEFT, fill=tk.X, expand=True)
        def _browse():
            path = filedialog.askopenfilename(
                title="WoWCombatLog auswählen",
                filetypes=[("Log-Dateien", "WoWCombatLog*.txt"), ("Alle Dateien", "*.*")],
            )
            if path:
                log_var.set(path)
        tk.Button(log_row, text="…", command=_browse, bg=BG_HEADER, fg=FG_PRIMARY,
                  font=(FONT_FAMILY, FONT_SIZE_SM), relief=tk.FLAT, width=3).pack(side=tk.LEFT, padx=2)

        # Replay speed
        speed_var = tk.DoubleVar(value=self.replay_speed)
        speed_row = tk.Frame(dialog, bg=BG_DARK)
        speed_row.pack(fill=tk.X, padx=16, pady=4)
        tk.Label(speed_row, text="Replay-Speed:", bg=BG_DARK, fg=FG_DIM,
                 font=(FONT_FAMILY, FONT_SIZE_SM), width=16, anchor="w").pack(side=tk.LEFT)
        tk.Scale(speed_row, variable=speed_var, from_=0, to=20, resolution=0.5,
                 orient=tk.HORIZONTAL, bg=BG_SECTION, fg=FG_PRIMARY,
                 highlightthickness=0, font=(FONT_FAMILY, FONT_SIZE_SM), length=180).pack(side=tk.LEFT)

        def on_apply():
            self.player_name = player_var.get().strip()
            self.talent = spec_var.get()
            self.replay_speed = speed_var.get()
            new_log = Path(log_var.get().strip())
            if new_log != self.log_path:
                self.log_path = new_log
            # Restart engine and watcher
            try:
                self._watcher.stop()
            except Exception:
                pass
            self.parser = CombatLogParser(player_name=self.player_name if self.player_name else None)
            self.engine = FrostMageEngine(talent=self.talent, spec=self.talent, player_name=self.player_name)
            self._start_watcher()
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, pady=12)
        tk.Button(btn_frame, text="✔ Übernehmen", command=on_apply, bg="#1b5e20", fg="white",
                  font=(FONT_FAMILY, FONT_SIZE_SM), relief=tk.FLAT, width=14).pack(side=tk.LEFT, padx=16)
        tk.Button(btn_frame, text="Abbrechen", command=dialog.destroy, bg=BG_HEADER, fg=FG_PRIMARY,
                  font=(FONT_FAMILY, FONT_SIZE_SM), relief=tk.FLAT, width=12).pack(side=tk.LEFT)

        dialog.wait_window()

    def _refresh_player_label(self) -> None:
        """Update the player/talent info bar after player name changes."""
        self._player_info_var.set(
            f"  Player: {self.player_name or 'Any'}   Talent: {self.talent.title()}"
        )

    # ------------------------------------------------------------------
    # Mode switch: Live / Replay / Summary
    # ------------------------------------------------------------------

    def _on_mode_change(self) -> None:
        """Switch between Live, Replay, and Summary modes."""
        mode = self._mode_var.get()
        try:
            self._watcher.stop()
        except Exception:
            pass
        self.engine.reset()

        if mode == "live":
            self.replay = False
            self._watcher = CombatLogWatcher(
                on_line=self._on_line,
                log_path=self.log_path,
                on_rotation=self._on_log_rotated,
            )
            self._watcher.start()
            self._update_status(f"Watching: {self.log_path.name}")
            self._scan_log_segments()

        elif mode == "replay":
            self.replay = True
            self._scan_log_segments()
            self._update_status("Replay – Segment auswählen und Analysieren klicken")

        elif mode == "summary":
            self.replay = False
            self._analyse_selected_segment()
            self._update_status("Zusammenfassung")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        try:
            self._watcher.stop()
        except Exception:
            pass
        self.root.destroy()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WoW Combat Log Analyzer – Frost Mage Overlay"
    )
    parser.add_argument(
        "--player",
        default="",
        help="Character name to filter events by (e.g. Frostmage)",
    )
    parser.add_argument(
        "--talent",
        choices=["frostfire", "spellslinger"],
        default="frostfire",
        help="Talent build to use for analysis (default: frostfire)",
    )
    parser.add_argument(
        "--spec",
        choices=["frost_mage", "arcane_mage", "devastation_evoker", "augmentation_evoker"],
        default=None,
        help="Spec to use for analysis (overrides --talent)",
    )
    parser.add_argument(
        "--log",
        default=None,
        help="Path to WoWCombatLog.txt (default: neueste Datei in Retail-Logs-Ordner)",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Replay-Modus: liest das Log von Anfang an durch (zum Testen)",
    )
    parser.add_argument(
        "--replay-speed",
        type=float,
        default=5.0,
        metavar="X",
        help="Replay-Geschwindigkeit: 1.0=Echtzeit, 5.0=5x schneller, 0=instant (Standard: 5.0)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # Set up file logging before anything else
    _log_file = Path(__file__).parent / "wowcoach.log"
    logging.basicConfig(
        level=logging.DEBUG,
        filename=str(_log_file),
        filemode="w",
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("wowcoach.main").info(
        "Starting – player=%r talent=%r replay=%s", args.player, args.talent, args.replay
    )

    log_path = Path(args.log) if args.log else DEFAULT_LOG_PATH

    root = tk.Tk()
    app = OverlayApp(
        root=root,
        player_name=args.player,
        talent=args.talent,
        spec=args.spec,
        log_path=log_path,
        replay=args.replay,
        replay_speed=args.replay_speed,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
