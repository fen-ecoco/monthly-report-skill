# Setup-TaskScheduler-Monthly.ps1
# One-time setup script: registers a daily 17:30 Windows Task Scheduler task.
# The task runs every workday at 17:30; the underlying Python script decides
# whether today actually qualifies (last workday of month, not a holiday)
# and only generates the report on the correct day.
#
# Run this script ONCE as Administrator (right-click PowerShell -> Run as Administrator).

$TaskName = "ECOCO-MonthlyReport"
$BaseDir = "D:\info\0507_weekly-report-skill"
$ScriptPath = Join-Path $BaseDir "monthly-report-skill\Run-MonthlyReport.ps1"

if (-not (Test-Path $ScriptPath)) {
    Write-Host "ERROR: Cannot find $ScriptPath" -ForegroundColor Red
    Write-Host "Please make sure Run-MonthlyReport.ps1 is placed in the monthly-report-skill folder first." -ForegroundColor Red
    exit 1
}

$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""

# Trigger: every day at 17:30. The Python script itself filters for
# "last workday of month, excluding holidays" so it is safe to trigger daily.
$Trigger = New-ScheduledTaskTrigger -Daily -At 17:30

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

# Remove existing task with the same name if present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Existing task '$TaskName' found. Removing before re-registering..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal `
    -Description "ECOCO monthly report auto-generation. Runs daily 17:30; only produces output on the last workday of each month (holidays excluded)."

Write-Host ""
Write-Host "Task '$TaskName' registered successfully." -ForegroundColor Green
Write-Host "It will run every day at 17:30 and check whether today is the last workday of the month."
Write-Host ""
Write-Host "To test immediately, run in PowerShell:"
Write-Host "  Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host ""
Write-Host "To view run history, open Task Scheduler (taskschd.msc) and find '$TaskName' under Task Scheduler Library."
