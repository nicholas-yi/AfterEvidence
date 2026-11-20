param(
    [Parameter(Mandatory = $true)][string]$Study,
    [Parameter(Mandatory = $true)][string]$Worktree,
    [Parameter(Mandatory = $true)][string]$Stage,
    [Parameter(Mandatory = $true)][int]$Approved,
    [Parameter(Mandatory = $true)][string]$Note,
    [string]$Model = "claude-haiku-5.5",
    [int]$GatewayPort = 8900,
    [hashtable]$Shims = @{},
    [string]$Workspace = "",
    [string[]]$Phases = @('session1', 'providers', 'sessions'),
    [string]$RecoveryDecision = "",
    [int]$Tries = 4,
    [ValidateSet('followups', 'gaps')][string]$Runner = 'followups',
    [ValidateSet('dev', 'eval')][string]$RunStage = 'eval',
    [hashtable]$WorkspaceByPrefix = @{}
)
<#
Detached driver for `research.followups` (-Study wd|m3|pz) and `research.gaps` (-Runner gaps;
-Study gx|lh|ac) dev checks and evaluations. Run it from a frozen tag worktree
(scripts/frozen-worktree.ps1); dev checks run from the working tree. It starts the study's Copilot shims (-Shims label = "port,cap") and
the memory gateway, runs the phases in order under the keep-awake guard, then stops its services.

A phase that exits non-zero stops the driver, with one exception: if its log shows a Copilot
credential failure AND -RecoveryDecision records an owner decision, sessions cut mid-call are closed
as infrastructure failures (research.run_recovery) and the phase is retried, at most -Tries times.
Without a recorded decision nothing is recovered. Logs go to research/runs/commitment/<Stage>.

Example:
  scripts/run-eval.ps1 -Study wd -Worktree <tag worktree> -Stage wd-eval-v1 -Approved 2264 `
    -Note "owner approval ..." -Workspace wd-eval-v1 -Shims @{ mem0 = '8811,96'; honcho = '8814,312' }
#>
$ErrorActionPreference = 'Stop'
Set-Location $Worktree
$py = Join-Path $Worktree 'research\.venv\Scripts\python.exe'
$pyp = Join-Path $Worktree 'research\.venv-providers\Scripts\python.exe'
$run = Join-Path $Worktree ("research\runs\commitment\" + $Stage)
New-Item -ItemType Directory -Force (Join-Path $run 'shims') | Out-Null
$log = Join-Path $run 'driver.log'
function Say($m) { Add-Content $log ("{0:u} {1}" -f (Get-Date).ToUniversalTime(), $m) }
$credential = 'token lookup timed out|Not authenticated|credential authority'
$token = (Get-Content (Join-Path $Worktree 'research\providers\shim-token.txt') -Raw).Trim()
$procs = @()
foreach ($label in $Shims.Keys) {
    $port, $cap = $Shims[$label].Split(',')
    $shimArgs = @('-m', 'research.copilot_shim', '--label', $label, '--port', $port, '--requests', $cap,
        '--journal', ('"' + (Join-Path $run "shims\$label.calls.jsonl") + '"'), '--token', $token, '--model', $Model)
    if ($label -in 'honcho', 'hindsight') { $shimArgs += @('--host', '0.0.0.0') }  # reached from Docker
    $procs += Start-Process $py -ArgumentList $shimArgs -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $run "shims\$label.log") -RedirectStandardError (Join-Path $run "shims\$label.err")
    Start-Sleep 3
}
$config = Get-Content (Join-Path $Worktree 'research\providers\gateway.json') -Raw | ConvertFrom-Json
$config.model = $Model
$config | Add-Member -NotePropertyName state -NotePropertyValue (Join-Path $run 'mem0') -Force
$config | Add-Member -NotePropertyName honcho_workspace -NotePropertyValue $Workspace -Force
$config | Add-Member -NotePropertyName honcho_reasoning_level -NotePropertyValue $null -Force
$config | Add-Member -NotePropertyName honcho_workspace_by_prefix -NotePropertyValue $WorkspaceByPrefix -Force
foreach ($label in 'mem0', 'graphiti') {
    if ($Shims.ContainsKey($label)) { $config.shims.$label = "http://127.0.0.1:$($Shims[$label].Split(',')[0])/v1" }
}
$gwConfig = Join-Path $run "gateway-$Stage.json"
[IO.File]::WriteAllText($gwConfig, ($config | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding $false))
$env:MEM0_TELEMETRY = 'False'
$env:AFTEREVIDENCE_GATEWAY = "http://127.0.0.1:$GatewayPort"
if ($Shims.ContainsKey('app')) { $env:AFTEREVIDENCE_APP_SHIM = "http://127.0.0.1:$($Shims['app'].Split(',')[0])/v1/chat/completions" }
$procs += Start-Process $pyp -ArgumentList @('-m', 'research.memory_gateway', '--config', ('"' + $gwConfig + '"'), '--port', $GatewayPort) `
    -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $run 'gateway.log') -RedirectStandardError (Join-Path $run 'gateway.err')
Start-Sleep 30
$ErrorActionPreference = 'Continue'  # Python logs to stderr; that must not stop the driver
Say ("services: " + (($procs | ForEach-Object Id) -join ','))
$status = 0
foreach ($phase in $Phases) {
    Start-Process powershell -WindowStyle Hidden -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        ('"' + (Join-Path $Worktree 'scripts\keep-awake.ps1') + '"'), '-Minutes', '240') | Out-Null
    Say "phase $phase start"
    for ($try = 1; $try -le $Tries; $try++) {
        $plog = Join-Path $run ("$phase-try$try.log")
        $selector = if ($Runner -eq 'gaps') { '--design' } else { '--study' }
        & $py -m "research.$Runner" $selector $Study --stage $RunStage --phase $phase --approved-requests $Approved --note $Note *> $plog
        $status = $LASTEXITCODE
        Say "phase $phase try $try exit $status"
        if ($status -eq 0 -or $try -eq $Tries -or -not $RecoveryDecision) { break }
        if (-not (Select-String -Path $plog -Pattern $credential -Quiet)) { break }
        & $py -m research.run_recovery recover $run 'process stopped by a Copilot SDK credential error' $RecoveryDecision | Out-Null
        Say "recovered cut sessions; retrying after a pause"
        Start-Sleep 180
    }
    if ($status -ne 0) { break }
}
foreach ($p in $procs) { if (-not $p.HasExited) { Stop-Process -Id $p.Id } }
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Worktree 'scripts\keep-awake.ps1') -Stop | Out-Null
Say "done status $status"
