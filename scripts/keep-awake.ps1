<#
.SYNOPSIS
Keep Windows awake for a bounded time during long runs (Windows only).

.DESCRIPTION
Starts a background guard that holds the system awake for -Minutes (at most 240), on AC power
unless -ContinueOnBattery. -Status shows the guard; -Stop releases it. Sleep requested by another
program can still happen; record any such interruption in the run record.
#>
param(
    [ValidateRange(1, 240)][int]$Minutes = 120,
    [switch]$ContinueOnBattery,
    [switch]$Stop,
    [switch]$Status
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') {
    throw 'This temporary sleep guard requires Windows.'
}

$directory = Join-Path $env:LOCALAPPDATA 'AfterEvidence'
$statePath = Join-Path $directory 'awake-guard.json'
if ($Status -or $Stop) {
    if (-not (Test-Path -LiteralPath $statePath)) {
        Write-Output 'No AfterEvidence sleep guard has been started.'
        return
    }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $guardPid = [int]$state.pid
    if ($guardPid -le 0) { throw 'Invalid sleep-guard process ID.' }
    if ($Stop) {
        $stopPath = Join-Path $directory ('awake-stop-' + $guardPid)
        [IO.File]::WriteAllText($stopPath, '')
        Write-Output ('Stop requested for the temporary guard ' + $guardPid + '.')
    } else {
        $state | ConvertTo-Json
    }
    return
}

if (Test-Path -LiteralPath $statePath) {
    $previous = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($previous.status -eq 'active' -and (Get-Process -Id ([int]$previous.pid) -ErrorAction SilentlyContinue)) {
        throw 'A guard is already active. Use -Status or -Stop instead of starting another.'
    }
}

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace AfterEvidence {
    public static class PowerGuard {
        [StructLayout(LayoutKind.Sequential)]
        public struct SystemPowerStatus {
            public byte ACLineStatus;
            public byte BatteryFlag;
            public byte BatteryLifePercent;
            public byte SystemStatusFlag;
            public uint BatteryLifeTime;
            public uint BatteryFullLifeTime;
        }
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern uint SetThreadExecutionState(uint flags);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool GetSystemPowerStatus(out SystemPowerStatus status);
    }
}
'@

[IO.Directory]::CreateDirectory($directory) | Out-Null
$stopPath = Join-Path $directory ('awake-stop-' + $PID)
$expires = [DateTime]::UtcNow.AddMinutes($Minutes)
$state = [ordered]@{
    pid = $PID
    status = 'starting'
    expires_utc = $expires.ToString('o')
    mode = 'temporary-manual-hold'
    chat_activity_detection = $false
    display_may_turn_off = $true
    release_on_battery = -not $ContinueOnBattery.IsPresent
}
$acquired = $false
try {
    while ([DateTime]::UtcNow -lt $expires) {
        if (Test-Path -LiteralPath $stopPath) {
            $state.status = 'stopped'
            break
        }
        $power = New-Object AfterEvidence.PowerGuard+SystemPowerStatus
        if (-not [AfterEvidence.PowerGuard]::GetSystemPowerStatus([ref]$power)) {
            throw 'Windows could not report AC power status; no unconditional hold will be applied.'
        }
        if (-not $ContinueOnBattery -and $power.ACLineStatus -ne 1) {
            $state.status = 'released-no-ac-power'
            Write-Output 'Sleep protection released because AC power is disconnected or unknown.'
            break
        }
        if (-not $acquired) {
            $flags = [Convert]::ToUInt32('80000001', 16)
            if ([AfterEvidence.PowerGuard]::SetThreadExecutionState($flags) -eq 0) {
                throw 'Windows rejected the automatic-sleep inhibition request.'
            }
            $acquired = $true
            $state.status = 'active'
            $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
            Write-Output ('Automatic idle sleep is temporarily inhibited until ' + $state.expires_utc + '. The display may turn off.')
        }
        Start-Sleep -Seconds 5
    }
    if ($state.status -eq 'active') { $state.status = 'expired' }
} finally {
    if ($acquired) {
        if ([AfterEvidence.PowerGuard]::SetThreadExecutionState([Convert]::ToUInt32('80000000', 16)) -eq 0) {
            Write-Error 'Windows did not acknowledge release of the temporary sleep request.'
        }
    }
    if (Test-Path -LiteralPath $stopPath) { Remove-Item -LiteralPath $stopPath }
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
}
