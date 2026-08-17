<#
    The launcher engine. Both start_all.bat and start_eval.bat call this;
    there is exactly one implementation of "bring services up".

    Everything it launches lands in ONE Windows Terminal window, one tab per
    service, with the control tab last. The control tab owns shutdown.

    Two implementation notes, both learned the hard way:

    1. Shutdown is by PID, not by window title. On Windows 11 a console
       window's title belongs to the terminal HOST (WindowsTerminal.exe), so
       `taskkill /FI "WINDOWTITLE eq ..."` can take down the entire terminal -
       control tab and unrelated tabs included. Each pane reports its own PID
       to .run\<id>.pid instead (see pane.ps1).

    2. Tabs are added one call at a time to a NAMED window (`wt -w <name>`),
       not as one `wt ... ; new-tab ... ; new-tab ...` command line. The `;`
       separators would need escaping through both cmd and PowerShell, and the
       first failure mode is a stray tab in somebody else's window.

    ASCII only, deliberately: Windows PowerShell 5.1 reads an unsigned .ps1 as
    ANSI unless it carries a BOM, and a stray em dash becomes a parse error
    rather than a typo.

    Usage (normally through the .bat wrappers):

        launch.ps1                      every service in services.txt
        launch.ps1 -Only m15            just this module
        launch.ps1 -All                 also sibling module repos (M04, M02)
        launch.ps1 -Check               verify prerequisites, launch nothing
        launch.ps1 -Attach <window>     add tabs to an existing window
        launch.ps1 -NoControl           skip the control tab (used when attaching)
#>

[CmdletBinding()]
param(
    # Service id prefixes to include. Empty means every row in the table.
    [string[]] $Only = @(),

    # Verify prerequisites and print the plan; launch nothing.
    [switch] $Check,

    # Also launch sibling module repos declared in module.json depends_on.
    [switch] $All,

    # Name of the Windows Terminal window to use. Attaching to an existing one
    # is how a sibling repo's services join this window.
    [string] $Window = 'ai-interviewer',
    [string] $Attach,

    # Skip the control tab. The parent launcher owns shutdown when attaching.
    [switch] $NoControl,

    # Where PID files go. A sibling repo is handed OUR .run directory so its
    # services can be shut down from this window's control tab.
    [string] $RunDir,

    # Alternate service table. Defaults to scripts\services.txt.
    [string] $Table,

    # Printed in the header. Callers set it so the banner names the module.
    [string] $Title = 'AI Interviewer'
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
if ($Attach) { $Window = $Attach }
if (-not $RunDir) { $RunDir = Join-Path $root '.run' }

# ---------------------------------------------------------------------------
#  Table
# ---------------------------------------------------------------------------

function Read-ServiceTable {
    param([string] $Path)

    if (-not (Test-Path $Path)) { throw "service table not found: $Path" }

    Get-Content -Path $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }

        $f = $line.Split('|')
        if ($f.Count -lt 7) {
            Write-Host "  [skip] malformed row in services.txt: $line" -ForegroundColor Yellow
            return
        }

        [pscustomobject]@{
            Id       = $f[0].Trim()
            Label    = $f[1].Trim()
            Cwd      = $f[2].Trim()
            Requires = $f[3].Trim()
            Command  = $f[4].Trim()
            Url      = $f[5].Trim()
            Health   = $f[6].Trim()
        }
    }
}

function Test-Prerequisite {
    param([pscustomobject] $Service)

    $dir = Join-Path $root $Service.Cwd
    if (-not (Test-Path $dir)) {
        return @{ Ok = $false; Reason = "no directory $($Service.Cwd)" }
    }
    if ($Service.Requires) {
        $needed = Join-Path $dir $Service.Requires
        if (-not (Test-Path $needed)) {
            return @{ Ok = $false; Reason = "missing $($Service.Cwd)\$($Service.Requires)" }
        }
    }
    return @{ Ok = $true; Reason = '' }
}

function Get-HelpFor {
    param([string] $Id)

    if ($Id -like '*-api') {
        return @(
            'cd Backend',
            'python -m venv .venv',
            '.venv\Scripts\python -m pip install -e ".[dev]"'
        )
    }
    if ($Id -like '*-web') {
        return @('cd Frontend', 'npm install')
    }
    return @()
}

# ---------------------------------------------------------------------------
#  PID bookkeeping
# ---------------------------------------------------------------------------

function Test-ProcessAlive {
    param([int] $ProcessId)
    if (-not $ProcessId) { return $false }
    try { $null = Get-Process -Id $ProcessId -ErrorAction Stop; return $true }
    catch { return $false }
}

function Get-RecordedPid {
    param([string] $Id)
    $file = Join-Path $RunDir "$Id.pid"
    if (-not (Test-Path $file)) { return 0 }
    $parsed = 0
    if ([int]::TryParse((Get-Content -Path $file -Raw).Trim(), [ref] $parsed)) { return $parsed }
    return 0
}

function Clear-StalePid {
    if (-not (Test-Path $RunDir)) { return }
    Get-ChildItem -Path $RunDir -Filter '*.pid' -ErrorAction SilentlyContinue | ForEach-Object {
        $recorded = 0
        [void][int]::TryParse((Get-Content -Path $_.FullName -Raw).Trim(), [ref] $recorded)
        if (-not (Test-ProcessAlive -ProcessId $recorded)) {
            Remove-Item -Path $_.FullName -Force -ErrorAction SilentlyContinue
        }
    }
}

# ---------------------------------------------------------------------------
#  Launch
# ---------------------------------------------------------------------------

function Start-Pane {
    param(
        [string] $Id,
        [string] $Label,
        [string] $WorkingDirectory,
        [string] $Command,
        [bool]   $HaveWt
    )

    # The command travels via a file, not the command line: `wt` re-parses its
    # arguments, and a command containing quotes does not survive that.
    Set-Content -Path (Join-Path $RunDir "$Id.cmd") -Value $Command -Encoding ascii -Force

    $pane = Join-Path $PSScriptRoot 'pane.ps1'
    $psArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $pane, '-Id', $Id, '-RunDir', $RunDir)

    if ($HaveWt) {
        & wt.exe -w $Window new-tab --title $Label -d $WorkingDirectory powershell @psArgs
    }
    else {
        $null = Start-Process -FilePath 'powershell' -ArgumentList $psArgs `
            -WorkingDirectory $WorkingDirectory -PassThru
    }

    # Wait for the pane to report its own PID. This also serialises tab
    # creation: the named window must exist before the next `wt -w` call, or
    # Terminal opens a second window.
    $deadline = (Get-Date).AddSeconds(8)
    while ((Get-Date) -lt $deadline) {
        $recorded = Get-RecordedPid -Id $Id
        if ($recorded -and (Test-ProcessAlive -ProcessId $recorded)) { return $recorded }
        Start-Sleep -Milliseconds 120
    }
    return 0
}

# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------

if (-not $Table) { $Table = Join-Path $PSScriptRoot 'services.txt' }
$services = @(Read-ServiceTable -Path $Table)
if ($Only.Count -gt 0) {
    $services = @($services | Where-Object {
            $svc = $_
            ($Only | Where-Object { $svc.Id.StartsWith($_) }).Count -gt 0
        })
}

if (-not (Test-Path $RunDir)) { $null = New-Item -ItemType Directory -Path $RunDir -Force }
Clear-StalePid

$haveWt = [bool](Get-Command 'wt.exe' -ErrorAction SilentlyContinue)

if (-not $Attach) {
    Write-Host ''
    Write-Host '  ==========================================================' -ForegroundColor DarkGray
    Write-Host "   $Title" -ForegroundColor Cyan
    Write-Host '  ==========================================================' -ForegroundColor DarkGray
    Write-Host ''
    if (-not $haveWt) {
        Write-Host '  [note]    Windows Terminal (wt.exe) not found - falling back' -ForegroundColor Yellow
        Write-Host '            to one window per service. Shutdown is unaffected.' -ForegroundColor Yellow
        Write-Host ''
    }
}

if ($services.Count -eq 0) {
    Write-Host '  Nothing matched. Check scripts\services.txt and the -Only filter.' -ForegroundColor Red
    exit 1
}

# -- prerequisites ----------------------------------------------------------

$runnable = @()
foreach ($svc in $services) {
    # NOT $check: PowerShell variable names are case-insensitive, so that
    # would assign a hashtable to the [switch] $Check parameter and fail.
    $prereq = Test-Prerequisite -Service $svc
    if ($prereq.Ok) {
        Write-Host ("  [ok]      {0,-9} ready" -f $svc.Id) -ForegroundColor Green
        $runnable += $svc
    }
    else {
        Write-Host ("  [MISSING] {0,-9} {1}" -f $svc.Id, $prereq.Reason) -ForegroundColor Red
        foreach ($line in (Get-HelpFor -Id $svc.Id)) {
            Write-Host "                      $line" -ForegroundColor DarkGray
        }
    }
}

# A database that does not exist yet is not an error - it is a blank page, and
# the developer deserves to be told which of the two they are looking at.
$devDb = Join-Path $root 'Backend\dev.db'
if (($runnable | Where-Object { $_.Id -eq 'm15-api' }) -and -not (Test-Path $devDb)) {
    Write-Host '  [empty]   database  no Backend\dev.db yet - every page will be blank' -ForegroundColor Yellow
    Write-Host '                      seed it with:  cd Backend' -ForegroundColor DarkGray
    Write-Host '                                     .venv\Scripts\python seed.py' -ForegroundColor DarkGray
}

Write-Host ''

if ($Check) {
    Write-Host '  Check mode - nothing was launched.' -ForegroundColor DarkGray
    Write-Host ''
    exit 0
}

if ($runnable.Count -eq 0) {
    Write-Host '  Nothing can be started. Fix the items above and re-run.' -ForegroundColor Red
    Write-Host ''
    exit 1
}

# -- launch -----------------------------------------------------------------

Write-Host '  Starting...' -ForegroundColor DarkGray
Write-Host ''

$launched = @()
foreach ($svc in $runnable) {
    $existing = Get-RecordedPid -Id $svc.Id
    if ($existing -and (Test-ProcessAlive -ProcessId $existing)) {
        Write-Host ("    {0,-9} already running   [pid {1}]" -f $svc.Id, $existing) -ForegroundColor DarkGray
        $launched += [pscustomobject]@{ Id = $svc.Id; Label = $svc.Label; Url = $svc.Url; Health = $svc.Health; Pid = $existing }
        continue
    }

    $servicePid = Start-Pane -Id $svc.Id -Label $svc.Label `
        -WorkingDirectory (Join-Path $root $svc.Cwd) -Command $svc.Command -HaveWt $haveWt

    if ($servicePid) {
        $where = if ($svc.Url) { $svc.Url } else { '(no url)' }
        Write-Host ("    {0,-9} {1,-24} [pid {2}]" -f $svc.Id, $where, $servicePid) -ForegroundColor Green
    }
    else {
        Write-Host ("    {0,-9} FAILED to launch" -f $svc.Id) -ForegroundColor Red
    }

    $launched += [pscustomobject]@{ Id = $svc.Id; Label = $svc.Label; Url = $svc.Url; Health = $svc.Health; Pid = $servicePid }
}

# -- sibling module repos ---------------------------------------------------
#
# Upstreams are OPTIONAL. If a sibling repo is not on disk that is the normal
# case and not an error - the page degrades and says which module it needed.

if ($All -and -not $Attach) {
    $manifest = Join-Path $root 'module.json'
    if (Test-Path $manifest) {
        $meta = Get-Content -Raw -Path $manifest | ConvertFrom-Json
        $parent = Split-Path -Parent $root
        foreach ($dep in @($meta.depends_on)) {
            if (-not $dep.repo) { continue }
            $leaf = ($dep.repo.TrimEnd('/') -split '/')[-1]
            $sibling = Join-Path $parent $leaf
            $siblingLaunch = Join-Path $sibling 'scripts\launch.ps1'

            if (-not (Test-Path $sibling)) { continue }

            if (Test-Path $siblingLaunch) {
                Write-Host ''
                Write-Host ("  {0}  {1} - attaching to this window" -f $dep.module, $leaf) -ForegroundColor DarkGray
                & $siblingLaunch -Attach $Window -NoControl -RunDir $RunDir -Title $dep.name
            }
            else {
                Write-Host ("  [skip] {0} found at ..\{1} but it has no scripts\launch.ps1 - start it yourself" -f $dep.module, $leaf) -ForegroundColor Yellow
            }
        }
    }
}

# -- control tab ------------------------------------------------------------

if ($NoControl -or $Attach) { exit 0 }

$session = [pscustomobject]@{
    window     = $Window
    started_at = (Get-Date).ToString('o')
    wt         = $haveWt
    root       = $root
    run_dir    = $RunDir
    title      = $Title
    services   = $launched
}
$session | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $RunDir 'session.json') -Encoding utf8 -Force

$control = Join-Path $PSScriptRoot 'control.ps1'
$controlArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $control, '-RunDir', $RunDir)

Write-Host ''
if ($haveWt) {
    & wt.exe -w $Window new-tab --title 'control' -d $root powershell @controlArgs
    Write-Host '  ----------------------------------------------------------' -ForegroundColor DarkGray
    Write-Host '   Last tab is the control tab. Close everything from there.' -ForegroundColor DarkGray
    Write-Host '  ----------------------------------------------------------' -ForegroundColor DarkGray
    Write-Host ''
    Start-Sleep -Milliseconds 400
}
else {
    # No Terminal: this window becomes the control window, as it always was.
    & powershell @controlArgs
}
