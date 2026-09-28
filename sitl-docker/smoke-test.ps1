<#
.SYNOPSIS
  Verify a fresh build of the SITL container end to end on Windows.

.EXAMPLE
  .\smoke-test.ps1
  .\smoke-test.ps1 -NoCache     # full rebuild, ~25 minutes
#>
param([switch]$NoCache)

$ErrorActionPreference = "Continue"
$container = "ardupilot-sitl"
$script:pass = 0
$script:fail = 0

function Check($label, [scriptblock]$body) {
    try {
        $out = & $body 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ok   $label" -ForegroundColor Green
            $script:pass++
        } else {
            Write-Host "  FAIL $label" -ForegroundColor Red
            ($out | Select-Object -First 10) | ForEach-Object { Write-Host "       $_" }
            $script:fail++
        }
    } catch {
        Write-Host "  FAIL $label - $_" -ForegroundColor Red
        $script:fail++
    }
}

function InContainer($cmd) {
    docker compose run --rm --no-deps sitl bash -c $cmd | Out-Null
}

try {
    Write-Host "== 0. docker daemon ==" -ForegroundColor Cyan
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Docker Desktop is not running. Start it and try again." -ForegroundColor Red
        exit 1
    }
    Write-Host "  ok   daemon reachable" -ForegroundColor Green

    Write-Host "== 1. compose file parses ==" -ForegroundColor Cyan
    Check "docker compose config" { docker compose config -q }

    Write-Host "== 2. build ==" -ForegroundColor Cyan
    if ($NoCache) { docker compose build --no-cache --progress plain }
    else          { docker compose build }
    if ($LASTEXITCODE -ne 0) { Write-Host "build failed" -ForegroundColor Red; exit 1 }
    docker compose run --rm --no-deps -T sitl build
    if ($LASTEXITCODE -ne 0) { Write-Host "ArduPilot build failed" -ForegroundColor Red; exit 1 }

    Write-Host "== 3. image contents ==" -ForegroundColor Cyan
    Check "JSBSim on PATH"        { InContainer 'command -v JSBSim' }
    Check "arduplane built"       { InContainer 'test -x /opt/ardupilot/build/sitl/bin/arduplane' }
    Check "autotest writable"     { InContainer 'test -w /opt/ardupilot/Tools/autotest' }
    Check "not running as root"   { InContainer '[ "$(id -u)" -ne 0 ]' }
    Check "pymavlink present"     { InContainer 'python3 -c "import pymavlink"' }
    Check "entrypoint has LF endings" { InContainer '! grep -q "\r" /usr/local/bin/entrypoint.sh' }

    Write-Host "== 4. start the simulator ==" -ForegroundColor Cyan
    docker compose up -d
    if ($LASTEXITCODE -ne 0) { Write-Host "compose up failed" -ForegroundColor Red; exit 1 }

    Write-Host -NoNewline "  waiting for SERIAL0 to bind"
    $bound = $false
    for ($i = 0; $i -lt 60; $i++) {
        if ((docker compose logs 2>&1 | Out-String) -match "SERIAL0 on TCP port 5760") { $bound = $true; break }
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 2
    }
    Write-Host ""
    if ($bound) { Write-Host "  ok   SERIAL0 bound" -ForegroundColor Green; $script:pass++ }
    else        { Write-Host "  FAIL SERIAL0 never bound" -ForegroundColor Red; $script:fail++ }

    $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 5760 -WarningAction SilentlyContinue
    if ($tcp.TcpTestSucceeded) { Write-Host "  ok   port 5760 reachable from host" -ForegroundColor Green; $script:pass++ }
    else { Write-Host "  FAIL port 5760 not reachable from host" -ForegroundColor Red; $script:fail++ }

    Write-Host "== 5. flight test (arms and climbs) ==" -ForegroundColor Cyan
    docker cp smoke_test.py "${container}:/tmp/smoke_test.py" | Out-Null
    docker exec $container python3 /tmp/smoke_test.py
    if ($LASTEXITCODE -eq 0) { Write-Host "  ok   flight test" -ForegroundColor Green; $script:pass++ }
    else { Write-Host "  FAIL flight test" -ForegroundColor Red; $script:fail++ }

    Write-Host "== 6. JSBSim really started ==" -ForegroundColor Cyan
    $logs = docker compose logs 2>&1 | Out-String
    foreach ($needle in @("JSBSim backend started", "JSBSim Execution beginning")) {
        if ($logs -match $needle) { Write-Host "  ok   '$needle'" -ForegroundColor Green; $script:pass++ }
        else { Write-Host "  FAIL '$needle' not in logs" -ForegroundColor Red; $script:fail++ }
    }
}
finally {
    docker compose down -v *> $null
}

Write-Host ""
Write-Host "passed $script:pass, failed $script:fail"
if ($script:fail -gt 0) { exit 1 }
Write-Host "Container is good to go." -ForegroundColor Green
