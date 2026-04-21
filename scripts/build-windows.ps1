$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$AppName = "wowcoach"
$OutputDir = Join-Path $RootDir "build/windows"
$Arch = if ($args.Count -gt 0) { $args[0] } else { $env:PROCESSOR_ARCHITECTURE.ToLower() }
if ([string]::IsNullOrWhiteSpace($Arch)) {
    $Arch = "amd64"
}

switch ($Arch) {
    "amd64" { }
    "arm64" { }
    default { throw "Unsupported Windows arch: $Arch. Use amd64 or arm64." }
}

$Version = $env:VERSION
if ([string]::IsNullOrWhiteSpace($Version)) {
    try {
        $Version = (git -C $RootDir rev-parse --short HEAD).Trim()
    } catch {
        $Version = "dev"
    }
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "==> Verifying test suite"
Push-Location $RootDir
try {
    go test ./...

    Write-Host "==> Building $AppName for Windows ($Arch)"
    $Env:GOOS = "windows"
    $Env:GOARCH = $Arch
    go build `
        -tags production `
        -trimpath `
        -ldflags "-s -w -X main.Version=$Version" `
        -o (Join-Path $OutputDir "$AppName-$Arch.exe") `
        .
} finally {
    Remove-Item Env:GOOS -ErrorAction SilentlyContinue
    Remove-Item Env:GOARCH -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Host "Built $(Join-Path $OutputDir "$AppName-$Arch.exe")"
