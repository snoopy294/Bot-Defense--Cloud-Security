# Registers a Windows Scheduled Task that runs the monitor 24/7:
#   - starts automatically at logon
#   - restarts automatically if it ever crashes
#   - starts as soon as possible if a scheduled start was missed
#
# Usage:   .\install-task.ps1            (install/update)
#          .\install-task.ps1 -Uninstall (remove)
#
# No admin rights or extra software required; runs as the current user.

param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$TaskName = "PokemonStockMonitor"
$runScript = Join-Path $PSScriptRoot "run.ps1"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName'."
    return
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runScript`""

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Pokemon stock-notification monitor (alerts only; no auto-buy)" `
    -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName'."
Write-Host "Start now with:  Start-ScheduledTask -TaskName $TaskName"
Write-Host "Check status:    Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Remove with:     .\install-task.ps1 -Uninstall"
