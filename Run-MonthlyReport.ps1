# Run-MonthlyReport.ps1
# ECOCO Monthly Report Automation - Wrapper Script
# Runs daily via Task Scheduler at 17:30.
# The Python script itself checks whether today is the last workday of the month
# (excluding weekends, national holidays, and manually registered typhoon/rain days).
# If today does not qualify, it exits without generating anything.

# Force UTF-8 to avoid cp950 encoding errors (known issue on this machine)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$BaseDir = "D:\info\0507_weekly-report-skill"
$ScriptPath = Join-Path $BaseDir "monthly-report-skill\generate_monthly_report.py"
$LogDir = Join-Path $BaseDir "monthly-report-skill"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$LogFile = Join-Path $LogDir "monthly_report_run.log"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

Add-Content -Path $LogFile -Value "===== Run started: $Timestamp =====" -Encoding UTF8

try {
    $pythonExe = "python"
    & $pythonExe $ScriptPath 2>&1 | Tee-Object -FilePath $LogFile -Append
    Add-Content -Path $LogFile -Value "Run finished successfully." -Encoding UTF8
}
catch {
    Add-Content -Path $LogFile -Value "ERROR: $_" -Encoding UTF8
}
