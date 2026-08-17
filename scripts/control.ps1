<#
    The control tab. Always the last tab in the window.

    Two jobs:

    1. Tell you what is happening while you wait. Rule 1 of this platform is
       that the user is never confused about what is happening - every wait
       has a name. That applies to the developer at 11 p.m. too, so this polls
       each service's health endpoint and names what it is waiting for, rather
       than printing a URL that will not answer for another six seconds.

    2. Shut down exactly what was opened, by PID. Never by window title: on
       Windows 11 the title belongs to the terminal host, so a title-matched
       taskkill can close this tab, the service tabs, and whatever else you
       had open in Terminal.

    ASCII only, deliberately: Windows PowerShell 5.1 reads an unsigned .ps1 as
    ANSI unless it carries a BOM, and a stray em dash becomes a parse error
    rather than a typo.
#>

[CmdletBinding()]
param(
    [string] $RunDir
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
if (-not $RunDir) { $RunDir = Join-Path $root '.run' }

$sessionFile = Join-Path $RunDir 'session.json'
if (-not (Test-Path $sessionFile)) {
    Write-Host ''
    Write-Host '  No session to control (.run\session.json is missing).' -ForegroundColor Red
    Write-Host '  Start things with start_all.bat or start_eval.bat.' -ForegroundColor DarkGray
    Write-Host ''
    [void](Read-Host '  Press Enter to close')
    exit 1
}

$session = Get-Content -Raw -Path $sessionFile | ConvertFrom-Json
$host.UI.RawUI.WindowTitle = 'control'

# ---------------------------------------------------------------------------
#  Readiness
# ---------------------------------------------------------------------------

function Get-UrlPort {
    param([string] $Url)
    try { return ([uri] $Url).Port } catch { return 0 }
}

function Get-UrlHost {
    param([string] $Url)
    try { return ([uri] $Url).Host } catch { return '127.0.0.1' }
}

function Test-Port {
    param([string] $Address, [int] $Port, [int] $TimeoutMs = 400)
    if (-not $Port) { return $false }
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($Address, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($async)
        return $true
    }
    catch { return $false }
    finally { $client.Close() }
}

function Test-Ready {
    param([pscustomobject] $Service)

    if (-not $Service.Url) { return $true }

    if ($Service.Health) {
        try {
            $probe = "$($Service.Url.TrimEnd('/'))$($Service.Health)"
            $response = Invoke-WebRequest -Uri $probe -UseBasicParsing -TimeoutSec 2
            return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
        }
        catch { return $false }
    }

    return (Test-Port -Address (Get-UrlHost $Service.Url) -Port (Get-UrlPort $Service.Url))
}

function Get-RecordedPid {
    param([string] $Id)
    $file = Join-Path $RunDir "$Id.pid"
    if (-not (Test-Path $file)) { return 0 }
    $parsed = 0
    [void][int]::TryParse((Get-Content -Path $file -Raw).Trim(), [ref] $parsed)
    return $parsed
}

function Test-ProcessAlive {
    param([int] $ProcessId)
    if (-not $ProcessId) { return $false }
    try { $null = Get-Process -Id $ProcessId -ErrorAction Stop; return $true }
    catch { return $false }
}

Write-Host ''
Write-Host "  $($session.title)" -ForegroundColor Cyan
Write-Host ''

$pending = @($session.services | Where-Object { $_.Url })
$started = Get-Date
$deadline = $started.AddSeconds(45)
$ready = @{}

while ($pending.Count -gt 0 -and (Get-Date) -lt $deadline) {
    foreach ($svc in @($pending)) {
        if (Test-Ready -Service $svc) {
            $seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
            $ready[$svc.Id] = $seconds
            Write-Host ("`r    {0,-9} ready in {1}s                    " -f $svc.Id, $seconds) -ForegroundColor Green
            $pending = @($pending | Where-Object { $_.Id -ne $svc.Id })
        }
    }
    if ($pending.Count -gt 0) {
        $names = ($pending | ForEach-Object { $_.Id }) -join ', '
        Write-Host ("`r    waiting for {0} ...   " -f $names) -NoNewline -ForegroundColor DarkGray
        Start-Sleep -Milliseconds 700
    }
}
Write-Host ("`r" + (' ' * 60) + "`r") -NoNewline

foreach ($svc in $pending) {
    Write-Host ("    {0,-9} did not answer in 45s - see its tab" -f $svc.Id) -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
#  The table
# ---------------------------------------------------------------------------

Write-Host ''
Write-Host ('    {0,-9}  {1,-26}  {2,-7}  {3}' -f 'service', 'url', 'pid', 'state') -ForegroundColor DarkGray
Write-Host ('    {0,-9}  {1,-26}  {2,-7}  {3}' -f '-------', '---', '---', '-----') -ForegroundColor DarkGray

foreach ($svc in $session.services) {
    $servicePid = Get-RecordedPid -Id $svc.Id
    $state =
    if (-not (Test-ProcessAlive -ProcessId $servicePid)) { 'stopped' }
    elseif ($ready.ContainsKey($svc.Id)) { 'ready' }
    elseif (-not $svc.Url) { 'running' }
    else { 'starting' }

    $colour = 'Yellow'
    if ($state -eq 'ready') { $colour = 'Green' }
    if ($state -eq 'stopped') { $colour = 'Red' }

    $shownPid = if ($servicePid) { $servicePid } else { '-' }
    $shownUrl = if ($svc.Url) { $svc.Url } else { '-' }
    Write-Host ('    {0,-9}  {1,-26}  {2,-7}  {3}' -f $svc.Id, $shownUrl, $shownPid, $state) -ForegroundColor $colour
}

# ---------------------------------------------------------------------------
#  Upstream modules
# ---------------------------------------------------------------------------
#
# Answering "why is this page thin?" here, before the student-facing page
# shows the banner, is the whole point: a missing upstream narrows the SCOPE
# of what the page shows, never its quality, and never silently.

$api = $session.services | Where-Object { $_.Id -like '*-api' } | Select-Object -First 1
if ($api -and $api.Url -and $ready.ContainsKey($api.Id)) {
    try {
        $deps = Invoke-RestMethod -Uri "$($api.Url.TrimEnd('/'))/v1/deps" -TimeoutSec 3
        if ($deps) {
            Write-Host ''
            Write-Host '    upstream modules (all optional)' -ForegroundColor DarkGray
            foreach ($dep in $deps) {
                if ($dep.available) {
                    Write-Host ("    {0,-9}  up" -f $dep.module_id) -ForegroundColor Green
                }
                else {
                    Write-Host ("    {0,-9}  not running" -f $dep.module_id) -ForegroundColor Yellow
                    Write-Host ("               {0} - the page will say so" -f $dep.name) -ForegroundColor DarkGray
                }
            }
        }
    }
    catch {
        # /v1/deps is a convenience. Its absence is not the developer's problem.
    }
}

# ---------------------------------------------------------------------------
#  Shutdown
# ---------------------------------------------------------------------------

function Stop-Pane {
    param([string] $Id)

    $servicePid = Get-RecordedPid -Id $Id
    if (-not (Test-ProcessAlive -ProcessId $servicePid)) {
        Write-Host ("    {0,-9} already closed" -f $Id) -ForegroundColor DarkGray
    }
    else {
        # /T for the tree: the pane is powershell -> cmd -> the real service.
        $null = & taskkill.exe /PID $servicePid /T /F 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host ("    {0,-9} closed  [pid {1}]" -f $Id, $servicePid) -ForegroundColor Green
        }
        else {
            Write-Host ("    {0,-9} would not close  [pid {1}]" -f $Id, $servicePid) -ForegroundColor Red
        }
    }
    Remove-Item -Path (Join-Path $RunDir "$Id.pid") -Force -ErrorAction SilentlyContinue
    Remove-Item -Path (Join-Path $RunDir "$Id.cmd") -Force -ErrorAction SilentlyContinue
}

Write-Host ''
while ($true) {
    $answer = (Read-Host '  Close all service tabs? (Y/N)').Trim()

    if ($answer -match '^(?i)y(es)?$') {
        Write-Host ''
        Write-Host '  Closing services...' -ForegroundColor DarkGray
        foreach ($svc in $session.services) { Stop-Pane -Id $svc.Id }
        Remove-Item -Path $sessionFile -Force -ErrorAction SilentlyContinue
        Write-Host ''
        Write-Host '  Done.' -ForegroundColor Green
        Start-Sleep -Seconds 2
        exit 0
    }

    if ($answer -match '^(?i)n(o)?$') {
        Write-Host ''
        Write-Host '  Leaving services running.' -ForegroundColor DarkGray
        foreach ($svc in $session.services) {
            $servicePid = Get-RecordedPid -Id $svc.Id
            if ($servicePid) { Write-Host ("    {0,-9} pid {1}" -f $svc.Id, $servicePid) }
        }
        Write-Host ''
        Write-Host '  Close their tabs yourself, or:  taskkill /PID <pid> /T /F' -ForegroundColor DarkGray
        Write-Host '  Re-open this tab any time with:  scripts\control.ps1' -ForegroundColor DarkGray
        Write-Host ''
        Start-Sleep -Seconds 4
        exit 0
    }

    Write-Host '  Please answer Y or N.' -ForegroundColor Yellow
}
