#Requires -Version 5.1
<#
.SYNOPSIS
    Drives the v2 rebuild swarm until the route is finished or something blocks it.

.DESCRIPTION
    Re-invokes the /rebuild orchestrator headlessly, one fresh context per run, reading the
    ledger between runs to decide whether to go again. This is what makes the workflow
    long-running: no run needs to survive its own context, because all state lives in
    docs/plans/rebuild-progress.md and is reconciled against git at the start of each run.

    Autonomy comes from the committed allowlist in .claude/settings.json, not from disabling
    the permission system. The default mode still refuses anything the allowlist does not
    name, which is how the hard-stop list stays enforceable rather than advisory.

    Authority and limits: docs/adr/0009-autonomous-swarm-delivery.md.

.PARAMETER Phase
    Start at this phase. Passed only to the first run; later runs resume from the ledger.
    Omit to resume wherever the ledger left off.

.PARAMETER PermissionMode
    Passed straight to the CLI. 'acceptEdits' plus the committed allowlist is the intended
    setting.

.PARAMETER MaxRuns
    Safety stop on the number of orchestrator invocations. Default 200.

.PARAMETER MaxHours
    Safety stop on wall-clock hours. Default 12.

.PARAMETER DryRun
    Print what would be invoked and exit.

.EXAMPLE
    ./scripts/swarm.ps1
    Resume the rebuild and run until complete or blocked.

.EXAMPLE
    ./scripts/swarm.ps1 -Phase 1 -MaxHours 4
    Start at phase 1, give up after four hours.

.NOTES
    Exit codes: 0 complete - 2 blocked, a human is needed - 3 safety stop reached
                4 ledger state unreadable - 5 prerequisite missing
#>
[CmdletBinding()]
param(
    [int]$Phase = -1,
    [ValidateSet('default', 'acceptEdits', 'plan')]
    [string]$PermissionMode = 'acceptEdits',
    [int]$MaxRuns = 200,
    [int]$MaxHours = 12,
    [string]$Model = 'opus',
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Ledger   = Join-Path $RepoRoot 'docs\plans\rebuild-progress.md'
$LogDir   = Join-Path $RepoRoot '.swarm-logs'

function Write-Banner([string]$Text) {
    Write-Host ''
    Write-Host ('=' * 78) -ForegroundColor DarkGray
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 78) -ForegroundColor DarkGray
}

function Get-SwarmState {
    # The ledger is authoritative. No ledger at all means nothing has run yet.
    if (-not (Test-Path -LiteralPath $Ledger)) { return 'CONTINUE' }
    $hit = Select-String -LiteralPath $Ledger -Pattern '^Swarm state:\s*([A-Za-z]+)' |
           Select-Object -First 1
    if (-not $hit) { return 'UNKNOWN' }
    return $hit.Matches[0].Groups[1].Value.ToUpperInvariant()
}

function Get-SentinelFromLog([string]$Path) {
    # Fallback for a run that exited without updating the ledger's header.
    if (-not (Test-Path -LiteralPath $Path)) { return 'UNKNOWN' }
    $hit = Select-String -LiteralPath $Path -Pattern 'SWARM:\s*(CONTINUE|BLOCKED|COMPLETE)' |
           Select-Object -Last 1
    if (-not $hit) { return 'UNKNOWN' }
    return $hit.Matches[0].Groups[1].Value.ToUpperInvariant()
}

# --- prerequisites ------------------------------------------------------------------------

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host 'claude CLI not found on PATH. Install Claude Code, or run the orchestrator interactively with /rebuild.' -ForegroundColor Red
    exit 5
}

Push-Location $RepoRoot
try {
    $branch = (& git rev-parse --abbrev-ref HEAD).Trim()
    if ($branch -ne 'main') {
        # A leftover task branch is what a killed run looks like, and reconciling that is the
        # orchestrator's first job - refusing to start would make a human do it instead.
        if ($branch -like 'feature/phase-*') {
            Write-Host "Starting on leftover task branch '$branch'; the orchestrator will reconcile it against the ledger." -ForegroundColor Yellow
        }
        else {
            Write-Host "The swarm integrates into main and must be started from it. You are on '$branch'." -ForegroundColor Red
            exit 5
        }
    }
    if (& git status --porcelain) {
        Write-Host 'Working tree is dirty. Commit or stash first - the swarm reconciles the ledger against git and a dirty tree makes that ambiguous.' -ForegroundColor Red
        exit 5
    }

    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $deadline = (Get-Date).AddHours($MaxHours)

    Write-Banner "BorrelBeurs v2 swarm - repo $RepoRoot"
    Write-Host ("Deadline   : {0}" -f $deadline)
    Write-Host ("Max runs   : {0}" -f $MaxRuns)
    Write-Host ("Permissions: {0} + .claude/settings.json allowlist" -f $PermissionMode)
    Write-Host ("Ledger     : {0}" -f $Ledger)
    Write-Host  'Stop it with Ctrl-C at any time; the ledger is written after every transition.'

    if ($DryRun) {
        $p = if ($Phase -ge 0) { "/rebuild $Phase" } else { '/rebuild' }
        Write-Host ''
        Write-Host "Would invoke: claude -p `"$p`" --model $Model --permission-mode $PermissionMode"
        exit 0
    }

    $state = 'CONTINUE'

    # Progress is commits on main plus writes to the ledger. A run that produces neither has
    # achieved nothing, and three of those in a row is a livelock - the swarm shipping nothing
    # for 200 runs is the expensive failure this catches, not a blocked one.
    function Get-Progress {
        $head = (& git rev-parse HEAD).Trim()
        $stamp = if (Test-Path -LiteralPath $Ledger) {
            (Get-FileHash -LiteralPath $Ledger -Algorithm MD5).Hash
        } else { 'no-ledger' }
        return "$head/$stamp"
    }

    $progress = Get-Progress
    $idleRuns = 0
    $unknownRetries = 0

    for ($run = 1; $run -le $MaxRuns; $run++) {

        if ((Get-Date) -gt $deadline) {
            Write-Banner "Safety stop: $MaxHours h reached after $($run - 1) runs."
            exit 3
        }

        # The phase argument belongs to the first run only. After that the ledger knows
        # better, and re-pinning a finished phase would make the swarm redo it.
        $prompt = if ($run -eq 1 -and $Phase -ge 0) { "/rebuild $Phase" } else { '/rebuild' }
        $log = Join-Path $LogDir ('run-{0:yyyyMMdd-HHmmss}-{1:d3}.log' -f (Get-Date), $run)

        Write-Banner "Run $run/$MaxRuns - $prompt - $(Get-Date -Format 'HH:mm:ss')"

        # claude.exe writes warnings to stderr. Merging them with 2>&1 while
        # $ErrorActionPreference is 'Stop' makes PowerShell treat the first warning as a
        # terminating error and kill the swarm, so relax it for this one call.
        $ErrorActionPreference = 'Continue'
        & claude -p $prompt --model $Model --permission-mode $PermissionMode 2>&1 |
            Tee-Object -FilePath $log
        $ErrorActionPreference = 'Stop'

        $state = Get-SwarmState
        if ($state -eq 'UNKNOWN') {
            $state = Get-SentinelFromLog $log
            Write-Host "Ledger header unreadable; fell back to the run's sentinel: $state" -ForegroundColor Yellow
        }

        Write-Host ''
        Write-Host ("Run {0} finished - swarm state: {1}" -f $run, $state) -ForegroundColor Green

        switch ($state) {
            'COMPLETE' {
                Write-Banner 'COMPLETE - every phase has met its exit criterion.'
                Write-Host 'Read the digests in docs/plans/digests/ and the merged PRs.'
                exit 0
            }
            'BLOCKED' {
                Write-Banner 'BLOCKED - a decision needs you.'
                Write-Host 'The question, the evidence and the recommended answer are at the'
                Write-Host 'bottom of docs/plans/rebuild-progress.md.'
                exit 2
            }
            'CONTINUE' {
                $now = Get-Progress
                if ($now -eq $progress) {
                    $idleRuns++
                    Write-Host ("No new commit and no ledger write this run ({0} in a row)." -f $idleRuns) -ForegroundColor Yellow
                    if ($idleRuns -ge 3) {
                        Write-Banner "Safety stop: three runs in a row changed nothing."
                        Write-Host 'The swarm is looping without progressing. Read the last three logs in'
                        Write-Host "$LogDir and the ledger's Now section." -ForegroundColor Yellow
                        exit 3
                    }
                }
                else {
                    $progress = $now
                    $idleRuns = 0
                }
                $unknownRetries = 0
                Start-Sleep -Seconds 5
            }
            default {
                # One unreadable state is usually a run that died before writing its header.
                # Re-invoking costs a few minutes; stopping costs however long until a human looks.
                $unknownRetries++
                if ($unknownRetries -le 2) {
                    Write-Host "Unreadable swarm state after run $run; re-invoking (retry $unknownRetries of 2). Log: $log" -ForegroundColor Yellow
                    Start-Sleep -Seconds 5
                }
                else {
                    Write-Banner "Unreadable swarm state three runs running."
                    Write-Host "Check $log and the ledger by hand before restarting." -ForegroundColor Yellow
                    exit 4
                }
            }
        }
    }

    Write-Banner "Safety stop: $MaxRuns runs reached without COMPLETE."
    Write-Host 'Not necessarily wrong - check the ledger and restart to keep going.'
    exit 3
}
finally {
    Pop-Location
}
