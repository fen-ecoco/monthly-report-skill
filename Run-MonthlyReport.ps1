# Run-MonthlyReport.ps1
# ECOCO Monthly Report Automation - Wrapper Script
# Runs daily via Task Scheduler at 17:30.
# The Python script itself checks whether today is the last workday of the month
# (excluding weekends and national holidays). If today does not qualify, it exits
# with code 2 and generates nothing. On success it exits 0, and this wrapper then
# uploads the generated report to ecowork and submits it for approval.

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

# 先把「開始執行」寫進 log，確保就算後面任何一步出錯，至少留得下這次有被觸發過的紀錄
Add-Content -Path $LogFile -Value "===== Run started: $Timestamp =====" -Encoding UTF8

# Force UTF-8 to avoid cp950 encoding errors (known issue on this machine)
# 用 try/catch 包起來：Task Scheduler 在非完全互動的工作階段觸發時，[Console]::OutputEncoding
# 可能因為沒有真正附加的主控台 handle 而直接拋出例外（"The handle is invalid"），
# 若不攔截，整支腳本會在這裡就終止，且完全不會留下任何 log（這正是 9/30 當天發生的狀況）。
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
    chcp 65001 > $null
} catch {
    Add-Content -Path $LogFile -Value "提示：設定主控台 UTF-8 編碼失敗（非互動工作階段常見，可忽略）：$_" -Encoding UTF8
}

# 強制 Python 子程序本身也用 UTF-8 輸出中文，避免 print() 用到系統 cp950 造成 log 亂碼
$env:PYTHONIOENCODING = "utf-8"

$pythonExe = "python"

try {
    $genOutput = & $pythonExe $GenerateScript 2>&1
    $genExitCode = $LASTEXITCODE
    if ($genOutput) { $genOutput | Add-Content -Path $LogFile -Encoding UTF8 }

    if ($genExitCode -eq 0) {
        Add-Content -Path $LogFile -Value "月報產出成功，接著上傳至 ecowork 並送出審核..." -Encoding UTF8

        # 備份一份到 Google Drive 同步資料夾（純複製檔案，實際同步由 Google Drive 桌面版自行處理）
        try {
            $MonthId = Get-Date -Format "yyyy-MM"
            $YearPart, $MonthPart = $MonthId -split "-"
            $ReportFileName = "monthly_{0}-M{1}.md" -f $YearPart, $MonthPart
            $ReportSourcePath = Join-Path $SkillDir "monthly_reports\$ReportFileName"
            $DriveBackupDir = "D:\AI報告雲端備份"

            if (Test-Path $ReportSourcePath) {
                if (-not (Test-Path $DriveBackupDir)) {
                    New-Item -ItemType Directory -Path $DriveBackupDir -Force | Out-Null
                }
                Copy-Item -Path $ReportSourcePath -Destination $DriveBackupDir -Force
                Add-Content -Path $LogFile -Value "已備份月報至 Google Drive：$DriveBackupDir\$ReportFileName" -Encoding UTF8
            } else {
                Add-Content -Path $LogFile -Value "警告：找不到月報檔案，無法備份至 Google Drive：$ReportSourcePath" -Encoding UTF8
            }
        } catch {
            Add-Content -Path $LogFile -Value "警告：備份至 Google Drive 失敗：$_" -Encoding UTF8
        }

        if (Test-Path $UploadScript) {
            $uploadOutput = & $pythonExe $UploadScript 2>&1
            $uploadExitCode = $LASTEXITCODE
            if ($uploadOutput) { $uploadOutput | Add-Content -Path $LogFile -Encoding UTF8 }
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
