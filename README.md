# WoW Coach

Offline-first desktop analyzer for World of Warcraft combat logs, with
Windows as the primary target and macOS support built in.

This repository is a Go/Wails desktop app focused on a wowanalyzer-style
post-fight workflow:

- import a `WoWCombatLog.txt`
- detect raid and Mythic+ fights
- choose a fight
- choose a player
- choose a spec
- render a structured report inside the desktop app

## Supported Specs

- Frost Mage
- Arcane Mage
- Devastation Evoker
- Augmentation Evoker
- Unholy Death Knight
- Feral Druid

## App Stack

- Go `1.24`
- [Wails v2](https://wails.io/) for the desktop shell on Windows and macOS
- Embedded static frontend in `frontend/dist`

## Project Layout

- `main.go`, `app.go`: Wails entrypoint and desktop API surface
- `internal/logparser`: WoW combat log parser
- `internal/segments`: fight segmentation and actor detection
- `internal/analyzer`: generic fight analysis engine
- `internal/specs`: spec catalog, detection, thresholds and findings
- `internal/report`: HTML export helpers
- `frontend/dist`: embedded app UI
- `testdata`: sample combat logs used by the Go tests

## Backend API

The desktop app exposes these methods to the frontend:

- `OpenLog(path)`
- `ListFights()`
- `ListActors(fightID)`
- `AnalyzeFight(fightID, actorID, specID)`
- `ExportReport(fightID, actorID, specID, format)`

There is also `SelectLogFile()` for a native file dialog in Wails.

## Development

Install Go and Node. Wails CLI is optional for `go test`, but recommended for
desktop development on both Windows and macOS.

```bash
go mod download
go test ./...
```

For direct app builds outside the helper scripts, Wails requires build tags:

```bash
go build -tags production .
```

If you want to run the desktop app with the Wails tooling:

```bash
go install github.com/wailsapp/wails/v2/cmd/wails@latest
wails dev
```

## Build Scripts

The repository includes simple platform-specific build scripts. Each script
runs `go test ./...` first and only builds if the test suite passes.

macOS:

```bash
./scripts/build-macos.sh
./scripts/build-macos.sh arm64
./scripts/build-macos.sh amd64
```

Windows:

```powershell
.\scripts\build-windows.ps1
.\scripts\build-windows.ps1 amd64
.\scripts\build-windows.ps1 arm64
```

Windows wrapper:

```bat
scripts\build-windows.bat
```

Artifacts are written to:

- `build/macos`
- `build/windows`

## Current Scope

Implemented in the rewrite:

- Retail-style log parsing with common event types
- Raid and Mythic+ fight detection
- Actor detection inside the selected fight
- Manual spec selection with spell-based spec suggestions
- Structured report with summary, scores, findings, uptime, cooldowns and timeline
- HTML export of the generated report

Not yet at full wowanalyzer parity:

- spec logic is substantial but still heuristic
- no Warcraft Logs import
- no live overlay, no live watcher, no replay mode

## Tests

The new Go implementation is covered with package-level tests for:

- parser behavior
- fight segmentation
- actor detection
- analysis result shape

Run:

```bash
go test ./...
```

Regression fixtures are based on standard `WoWCombatLog.txt` style logs under
`testdata/`.
