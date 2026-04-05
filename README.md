# WoW Coach

Real-time World of Warcraft combat log analyzer with an always-on-top overlay. Reads your combat log as you play and gives you live rotation hints, opener scoring, GCD efficiency tracking, and post-fight error summaries.

## Supported Specs

| Class | Spec | Talents |
|-------|------|---------|
| Mage | Frost | Frostfire, Spellslinger |
| Mage | Arcane | — |
| Evoker | Devastation | — |
| Evoker | Augmentation | — |

Rules are defined in `rules/*.json` and cover the **Midnight (12.x / Season 1)** patch.

## Features

- **Live hints** — fires alerts when you break rotation rules (e.g. Flurry without Brain Freeze)
- **Opener scoring** — tracks your first 10 seconds against the ideal sequence
- **GCD efficiency** — measures gaps between casts and shows the worst offenders
- **Rotation errors** — timestamped log of every mistake with severity
- **Cooldown alerts** — periodic reminders if a major cooldown is sitting unused
- **Segment analysis** — replay any past encounter from your log and get a full breakdown
- **Live / Replay / Summary modes** — switch between watching live and analyzing old pulls

## Requirements

- Python 3.12+
- `tkinter` (included in standard CPython on Windows)

```
pip install -r requirements.txt
```

## Usage

```
# Live mode (watches the current WoWCombatLog.txt)
python main.py --player YourCharacterName --talent frostfire

# Replay a log file
python main.py --player YourCharacterName --replay --log "C:/path/to/WoWCombatLog.txt"

# Pick spec explicitly
python main.py --player YourCharacterName --spec frost_mage
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--player` | *(prompt on start)* | Character name (realm suffix optional) |
| `--talent` | `frostfire` | `frostfire` or `spellslinger` (Frost Mage only) |
| `--spec` | auto | `frost_mage`, `arcane_mage`, `devastation_evoker`, `augmentation_evoker` |
| `--log` | auto-detect | Path to WoWCombatLog.txt |
| `--replay` | off | Replay mode instead of live |
| `--replay-speed` | `5.0` | Playback speed multiplier (0 = instant) |

If `--player` is omitted, a dialog will prompt you on startup.

## Overlay Controls

- **Drag** the title bar to reposition
- **⚙ Settings** — change player, spec, log path, and replay speed at runtime
- **Mode switcher** — toggle between 🔴 Live, ⏵ Replay, and 📊 Summary
- **Ctrl+Q** or close button to quit

## Running Tests

```
pytest
# or
run_tests.bat
```

144 tests covering the parser, engine, log scanner, and all four specs.

## Log File Location

WoW writes its combat log to:
```
C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog.txt
```

Enable **Advanced Combat Logging** in WoW under System → Network for full event coverage.

---

> See [DISCLAIMER.md](DISCLAIMER.md) for important notes about this project.
