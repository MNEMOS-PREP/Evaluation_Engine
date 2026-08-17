<#
    One service, one tab.

    Runs as the tab's own process, so the FIRST thing it does is record its
    PID. That is the whole trick behind the launcher:

    Windows Terminal owns the tab processes, so `Start-Process wt -PassThru`
    hands back the PID of WindowsTerminal.exe - useless for shutdown, and
    lethal if you fall back to killing by window title (on Windows 11 the
    title belongs to the terminal HOST, so a title-matched taskkill can take
    down the control tab and unrelated tabs with it).

    So each pane reports its own PID to .run\<id>.pid, and the control tab
    kills that PID tree. Shutdown closes exactly what was opened.

    The command itself is read from .run\<id>.cmd rather than passed as an
    argument - `wt` re-parses its command line, and a command containing
    quotes and backslashes does not survive that round trip intact.

    ASCII only, deliberately: Windows PowerShell 5.1 reads an unsigned .ps1
    as ANSI unless it carries a BOM, and a stray em dash becomes a parse
    error rather than a typo.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $Id,

    # Where to report the PID. A sibling module repo is handed the launching
    # repo's .run directory, so one control tab can shut down every tab in the
    # window regardless of which repo started it.
    [string] $RunDir
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
if (-not $RunDir) { $RunDir = Join-Path $root '.run' }
$pidFile = Join-Path $RunDir "$Id.pid"
$cmdFile = Join-Path $RunDir "$Id.cmd"

if (-not (Test-Path $cmdFile)) {
    Write-Host "[$Id] no command file at $cmdFile - nothing to run." -ForegroundColor Red
    [void](Read-Host 'Press Enter to close')
    exit 1
}

# Record the PID before anything can fail. The launcher polls for this file.
$PID | Out-File -FilePath $pidFile -Encoding ascii -Force

$command = (Get-Content -Raw -Path $cmdFile).Trim()

$host.UI.RawUI.WindowTitle = $Id
Write-Host ''
Write-Host "  $Id  [pid $PID]" -ForegroundColor Cyan
Write-Host "  $command" -ForegroundColor DarkGray
Write-Host ''

# cmd.exe so the table can use batch syntax. The real service ends up a
# grandchild of this process; `taskkill /T` takes the whole tree.
& cmd.exe /c $command
$code = $LASTEXITCODE

# Do not vanish on crash - the exit code is the most useful thing on screen.
Write-Host ''
if ($code -eq 0) {
    Write-Host "  $Id exited cleanly." -ForegroundColor DarkGray
}
else {
    Write-Host "  $Id exited with code $code." -ForegroundColor Red
}
Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
[void](Read-Host '  Press Enter to close this tab')
