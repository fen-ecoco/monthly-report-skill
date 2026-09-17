# Run-MonthlyReport.ps1
# ECOCO Monthly Report Automation - Wrapper Script
# Runs daily via Task Scheduler at 17:30.
# The Python script itself checks whether today is the last workday of the month
# (excluding weekends and national holidays). If today does not qualify, it exits
# with code 2 and generates nothing. On success it exits 0, and this wrapper then
# uploads the generated report to ecowork and submits it for approval.

# Force UTF-8 to avoid cp950 encoding errors (known issue on this machine)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

# 強制 Python 子程序本身也用 UTF-8 輸出中文，避免 print() 用到系統 cp950 造成 log 亂碼
$env:PYTHONIOENCODING = "utf-8"

$BaseDir = "D:\info\0507_weekly-report-skill"
$SkillDir = Join-Path $BaseDir "monthly-report-skill"
$GenerateScript = Join-Path $SkillDir "generate_monthly_report.py"
$UploadScript = Join-Path $SkillDir "upload_monthly_report.py"
$LogDir = $SkillDir

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$LogFile = Join-Path $LogDir "monthly_report_run.log"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

Add-Content -Path $LogFile -Value "===== Run started: $Timestamp =====" -Encoding UTF8

$pythonExe = "python"

try {
    & $pythonExe $GenerateScript 2>&1 | Tee-Object -FilePath $LogFile -Append
    $genExitCode = $LASTEXITCODE

    if ($genExitCode -eq 0) {
        Add-Content -Path $LogFile -Value "月報產出成功，接著上傳至 ecowork 並送出審核..." -Encoding UTF8
        if (Test-Path $UploadScript) {
            & $pythonExe $UploadScript 2>&1 | Tee-Object -FilePath $LogFile -Append
            $uploadExitCode = $LASTEXITCODE
            if ($uploadExitCode -eq 0) {
                Add-Content -Path $LogFile -Value "上傳並送出審核成功。" -Encoding UTF8
            } elseif ($uploadExitCode -eq 3) {
                Add-Content -Path $LogFile -Value "提示：該期別已有送出的報表，本次不會覆蓋，屬正常保護機制，非錯誤，請自行至 ecowork 網頁確認。" -Encoding UTF8
            } else {
                Add-Content -Path $LogFile -Value "警告：草稿上傳失敗（exit code $uploadExitCode），月報檔案本身已正常產出，可自行手動上傳。" -Encoding UTF8
            }
        } else {
            Add-Content -Path $LogFile -Value "提示：找不到 upload_monthly_report.py，跳過自動上傳步驟。" -Encoding UTF8
        }
    } elseif ($genExitCode -eq 2) {
        Add-Content -Path $LogFile -Value "今天不是本月最後上班日，本次不執行，屬正常情況。" -Encoding UTF8
    } else {
        Add-Content -Path $LogFile -Value "警告：generate_monthly_report.py 執行異常（exit code $genExitCode）。" -Encoding UTF8
    }

    Add-Content -Path $LogFile -Value "Run finished." -Encoding UTF8
}
catch {
    Add-Content -Path $LogFile -Value "ERROR: $_" -Encoding UTF8
}
