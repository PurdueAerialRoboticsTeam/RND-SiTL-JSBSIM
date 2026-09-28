<#
.SYNOPSIS
  Start FlightGear on Windows as a view-only window for ArduPilot SITL.

.DESCRIPTION
  Run this BEFORE starting the container. FlightGear listens on UDP 5503 for
  flight dynamics packets from SITL and only draws the aircraft; the physics
  come from JSBSim inside the container.

.EXAMPLE
  .\fgview.ps1
  .\fgview.ps1 -Aircraft Rascal110-JSBSim -Airport KSFO
#>
param(
    [string]$Aircraft = "c172p",   # purely cosmetic: --fdm=external drives it
    [string]$Airport  = "YSCB",    # YSCB = Canberra, nearest to the CMAC default
    [int]   $Rate     = 30,        # Hz. 10 is the old default and looks jerky.
    [string]$Fgfs     = ""
)

$ErrorActionPreference = "Stop"

if (-not $Fgfs) {
    $candidates = @(
        "$env:ProgramFiles\FlightGear*\bin\fgfs.exe",
        "${env:ProgramFiles(x86)}\FlightGear*\bin\fgfs.exe",
        "$env:LOCALAPPDATA\Programs\FlightGear*\bin\fgfs.exe"
    )
    foreach ($pattern in $candidates) {
        $hit = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue |
               Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { $Fgfs = $hit.FullName; break }
    }
}

if (-not $Fgfs -or -not (Test-Path $Fgfs)) {
    Write-Error "fgfs.exe not found. Install FlightGear, or pass -Fgfs 'C:\path\to\fgfs.exe'."
    exit 1
}

Write-Host "Using $Fgfs"

# Launching fgfs.exe directly bypasses the launcher that sets FG_ROOT, so point
# at the data directory that sits alongside bin\ in the install.
$fgRoot = Join-Path (Split-Path (Split-Path $Fgfs -Parent) -Parent) "data"
$rootArgs = @()
if (Test-Path $fgRoot) { $rootArgs = @("--fg-root=$fgRoot") }

Write-Host "Listening for SITL FDM on UDP 5503 at $Rate Hz"
Write-Host "If nothing moves, allow fgfs.exe through Windows Defender Firewall (private networks)."

# The empty field between the two commas is the bind address; leaving it blank
# binds all interfaces, which is required to accept packets from the Docker VM.
$fgArgs = $rootArgs + @(
    "--native-fdm=socket,in,$Rate,,5503,udp",
    "--fdm=external",
    "--aircraft=$Aircraft",
    "--airport=$Airport",
    "--enable-terrasync",
    "--timeofday=noon",
    "--disable-sound",
    "--disable-hud-3d",
    "--disable-random-objects",
    "--disable-ai-models",
    "--geometry=1000x700"
)

& $Fgfs @fgArgs
