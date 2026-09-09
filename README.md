# ECOCO 月報自動化系統 — 使用說明

本系統**不呼叫任何付費 AI API，不需要申請金鑰**，完全免費。彙整方式與 `weekly-report-skill` 同樣邏輯：
用程式規則直接解析週報 MD 裡的表格與數字，加總、分類、去重、套入樣板。

## 一、安裝位置

請將以下 4 個檔案放到：

```
D:\info\0507_weekly-report-skill\monthly-report-skill\
├── generate_monthly_report.py        ← 核心程式（產出月報）
├── upload_monthly_report.py          ← 月報自動上傳至工作日誌系統（含真實 API Token，勿上傳 GitHub）
├── Run-MonthlyReport.ps1             ← PowerShell 執行包裝（依序呼叫上面兩支程式）
├── Setup-TaskScheduler-Monthly.ps1   ← 排程設定（只需執行一次）
├── _calendar_cache\                  ← 政府行事曆快取（自動產生）
├── monthly_report_log.txt            ← 程式執行日誌（自動產生）
└── monthly_reports\                  ← 月報成品存放處（自動產生）
    └── monthly_2026-M08.md
```

程式會自動讀取 `D:\info\0507_weekly-report-skill\reports\` 底下的 `weekly_*.md` 檔案，
並將產出的月報存到 `D:\info\0507_weekly-report-skill\monthly-report-skill\monthly_reports\monthly_YYYY-MXX.md`。

## 二、初次安裝步驟

### 1. 確認 Python 環境

不需要安裝任何額外套件（只用 Python 內建函式庫）：

```powershell
python --version
```

### 2. 測試執行（強制模式）

```powershell
cd "D:\info\0507_weekly-report-skill\monthly-report-skill"
python generate_monthly_report.py --force --month 2026-08
```

第一次執行會自動下載當年度政府行事曆資料並快取在 `_calendar_cache` 資料夾，之後執行不需重複下載。

### 3. 確認產出的月報內容無誤後，註冊排程（以系統管理員身分執行 PowerShell）

```powershell
cd "D:\info\0507_weekly-report-skill\monthly-report-skill"
Unblock-File -Path ".\Setup-TaskScheduler-Monthly.ps1"
Unblock-File -Path ".\Run-MonthlyReport.ps1"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\Setup-TaskScheduler-Monthly.ps1
```

> 若執行 `.ps1` 檔出現「未經數位簽署」「UnauthorizedAccess」錯誤，是 Windows 執行原則擋下未簽署腳本，
> 上面的 `Unblock-File` + `Set-ExecutionPolicy -Scope Process` 只在當次 PowerShell 視窗生效，不影響其他系統設定。

之後每天 17:30 會自動觸發檢查，只有在「當月最後上班日」才會真正產出月報，其他天自動跳過不執行。

## 三、日期判斷邏輯

1. 程式抓當月最後一天，往前逐日檢查
2. 依序排除：週六日 → 政府行政機關辦公日曆表列為假日的日子（國定假日、補假）
3. 找到的第一個「上班日」就是當月最後上班日
4. 每天 17:30 執行時，比對「今天」是否等於這個日期，符合才繼續產出月報，否則直接結束

> ⚠️ **關於颱風假/豪雨假**：政府行事曆開放資料只有國定假日，沒有颱風/豪雨假（各縣市當天臨時公告，無官方 API
> 可提前查詢）。若當月最後上班日恰好遇到臨時停班，程式仍會照常執行——建議事後用 `--force` 補跑一次即可。

政府行事曆資料來源：`TaiwanCalendar` 開源專案（同步自人事行政總處官方資料）。

## 四、週報自動篩選邏輯

程式掃描 `reports` 資料夾內所有 `weekly_*.md`，讀取「期間：YYYY/MM/DD ~ YYYY/MM/DD」這行，
只要**結束日期**落在目標月份即納入彙整範圍，不需手動指定週次。

## 五、內容彙整規則說明（目前版本）

| 段落 | 產出方式 | 說明 |
| --- | --- | --- |
| 客服統計、AI導入效益數字、關鍵數據 | 表格數字自動加總 | 100% 精準加總，無「未結案件」列（已移除） |
| 月度重點成果 | 表格標題為「項目/成果/**完成進度**/創造價值」；「成果」欄位內容與「專案進度總覽」的月底進度一致（取最新一筆），不再合併多週舊資訊 | 若當月有抓到出貨資料，固定顯示「ECOCO商城商品包裝出貨」一列 |
| 專案進度總覽 | 表格為「專案/月初進度/月底進度」**3 欄**（已移除「成長幅度」欄）；專案名稱前會加上執行工具（如「Claude：」），同一專案跨週工具不一致時不加前綴；`PROJECT_FORCED_TOOL` 可指定特定專案固定顯示的工具名稱；本月只出現一次的專案，月初欄留空、內容放月底欄；同一專案若內容出現「第一版/第二版」等版本字樣會自動拆成獨立列 | 內容不使用 `<br>`、不重複顯示工具名稱、不重複顯示專案名稱、不留括號 |
| 跨部門合作成果 | 表格為「專案/協作部門/狀態」**3 欄**（已移除「完成成果」欄），**只列出真正已完成（達成/完成）的項目**，避免跟風險表重複 | 同一人/項目跨週重複出現會自動合併成一筆 |
| 行政支援與其他事項 | 新增區塊：彙整「本週完成工作」表格中「其他」欄位的內容，依「；」拆成個別事項 | 提到已知人名（見 `KNOWN_NAMES`）會合併成一句，並保留代表性的上下文詞（如「AI客服系統」）；內容相似度高的事項會模糊比對合併（`dedupe_fuzzy`）；提到已知人名/部門會加上「」標明 |
| 本月三大貢獻 | 依「AI工具→系統優化→流程改善→客服營運→行銷專案→行政支援」優先順序，從各週「本週三大成果」挑選，同一週優先取最新一週 | 同一個專案的舊資訊不會重複入選（`mentioned_project` 去重）；文字會移除括號、修正標點殘留（如「：，」） |
| 風險與待協調事項 | 表格為「項目/協作部門/預計完成日」**3 欄**（已移除「影響範圍」欄） | 項目欄位盡量顯示需協助的具體內容而非人名，協作部門欄位盡量顯示人名；若項目本身只是人名、沒有實際內容記錄，不會顯示在表格中（但仍計入合計數）；能解析出多個預計完成日時顯示「預計M/D~M/D完成」起訖日格式 |
| ECOCO商城商品包裝出貨 | 支援兩種寫法：①「彙整結果X個：Y筆…總出貨數量Z個(+N個退貨補件)」（可一次列多組，訂單筆數會全部加總）②「商品包裝…訂單共X筆」（不拆品項，直接採用該數字）；只在「商品包裝」附近才比對，避免誤抓瑕疵退換貨等其他情境的「訂單共X筆」 | 月度重點成果欄位顯示簡化為「本月累計彙整訂單 X 筆」 |
| 本月價值總結 | 套入固定句型模板，帶入實際彙整數字 | 語句固定，可依需要潤飾 |

輸出的月報檔案最上方會固定加註提醒文字，說明本月報為規則式自動彙整，建議送主管審閱前花 1-2 分鐘複核。

## 六、可自行調整的設定項目

程式開頭有幾個清單可以直接編輯，不需要改動邏輯：

| 常數名稱 | 用途 |
| --- | --- |
| `PROJECT_KEYWORDS` | 專案關鍵字對照表（比對到才會出現在「專案進度總覽」「月度重點成果」） |
| `PROJECT_CATEGORY` | 指定專案固定分類（影響「創造價值」欄位文字） |
| `PROJECT_FORCED_TOOL` | 指定專案固定顯示的工具名稱（跨週工具不一致或未標明工具時使用） |
| `KNOWN_TOOL_PREFIXES` | 可辨識的 AI 工具名稱（Claude、CODEX、CURSOR 等） |
| `KNOWN_NAMES` / `KNOWN_DEPTS` | 「行政支援與其他事項」用於人名合併、人名/部門加註「」的清單 |
| `CATEGORY_KEYWORDS` | 「新增/修復/優化」分類判斷關鍵字 |

## 七、月報自動上傳至工作日誌系統

月報產出成功後，`Run-MonthlyReport.ps1` 會自動接著呼叫 `upload_monthly_report.py`，
把月報 MD 上傳到 ECOCO 工作日誌系統（`https://report-a.ecocogroup.com`）存為草稿。

### 檔案與設定

`upload_monthly_report.py` 裡的 `CONFIG` 需要填入：`api_token`（API Token）、`author_id`（你的使用者 ID）、
`author_name`、`department`。這支腳本**含有真實 API Token，切勿上傳到 GitHub 或任何版本控制系統**，
`.gitignore` 已將它排除；repo 裡只放了 `upload_monthly_report.py.example` 範本版（Token 為佔位符）。

### 運作邏輯

1. 讀取當月的 `monthly_YYYY-MXX.md`，把完整內容放進 `highlights` 欄位，`POST` 到 `/api/reports`
2. 驗證方式為 `Authorization: Bearer <token>` + `X-Caller-Id: <author_id>`（不需要瀏覽器 Session Cookie）
3. 若該期別（`period`）已經有報表存在，`API` 會回傳 `409` 衝突：
   - 若為**草稿狀態** → 自動改用 `PATCH` 覆蓋更新
   - 若為**審核中／已核准等非草稿狀態** → 跳出明顯的通知訊息，**不會覆蓋**，需自行至系統網頁確認處理

### 手動測試

```powershell
cd "D:\info\0507_weekly-report-skill\monthly-report-skill"
python upload_monthly_report.py 2026-08
```

### Exit code 對照表（供排程／自動化判斷用）

| 腳本 | Exit code | 意義 |
| --- | --- | --- |
| `generate_monthly_report.py` | 0 | 成功產出月報 |
| `generate_monthly_report.py` | 2 | 今天非本月最後上班日，正常跳過（非錯誤） |
| `generate_monthly_report.py` | 1 | 執行錯誤（如找不到週報檔案） |
| `upload_monthly_report.py` | 0 | 上傳／覆蓋成功 |
| `upload_monthly_report.py` | 3 | 主動保護不覆蓋（既有報表非草稿狀態），正常情況，非錯誤 |
| `upload_monthly_report.py` | 1 | 真正的上傳錯誤（如 Token 失效、網路問題） |

## 八、常見問題排除

| 問題 | 解決方式 |
| --- | --- |
| PowerShell 顯示亂碼 | 已在 `Run-MonthlyReport.ps1` 內強制設定 UTF-8，若仍有問題，執行 `chcp 65001` 後再測試 |
| `.ps1` 執行出現 UnauthorizedAccess / 未經數位簽署 | 見「二、3.」的 `Unblock-File` + `Set-ExecutionPolicy` 指令 |
| 排程沒有執行 | 開啟工作排程器（`taskschd.msc`）找到 `ECOCO-MonthlyReport`，檢查「歷程記錄」分頁 |
| 想立即手動觸發排程測試 | `Start-ScheduledTask -TaskName "ECOCO-MonthlyReport"` |
| 某個專案沒有出現在「專案進度總覽」 | 程式用固定關鍵字比對（見程式開頭 `PROJECT_KEYWORDS`），可自行增減關鍵字 |
| 某週報表格解析不到資料 | 確認週報 MD 的表格標題文字與程式裡比對的字串完全一致（例如「### 客服營運數據」）；表格若不小心多打一個空白欄位，程式會自動嘗試修正對齊 |
| 想新增/修改可辨識的工具名稱 | 修改程式開頭 `KNOWN_TOOL_PREFIXES` 清單即可 |
| 想新增可辨識的人名/部門 | 修改程式開頭 `KNOWN_NAMES` / `KNOWN_DEPTS` 清單即可 |
| 同一件事在不同週描述文字差異較大，沒被合併 | 目前僅對「行政支援與其他事項」套用模糊相似度合併，「風險與待協調事項」尚未套用（可視需要再加） |
| 月報上傳失敗 | 確認 `upload_monthly_report.py` 裡的 `api_token`／`author_id` 是否正確、Token 是否已過期 |

## 九、費用

完全免費。整個流程（判斷日期、下載政府行事曆、解析週報、產出月報、上傳草稿）都在你自己的電腦上執行，
不呼叫任何付費 AI API（週/月報系統本身的 API 屬於公司內部系統，非本文所指的付費 AI API）。

## 十、版本紀錄

| 版本 | 日期 | 調整內容 |
| --- | --- | --- |
| v1.0 | 2026-07 | 首版，使用 Claude API 彙整（需金鑰，付費） |
| v2.0 | 2026-07 | 改為純規則式彙整，移除 API 依賴，完全免費 |
| v2.1 | 2026-07 | 修正表格跨行儲存格解析、AI工具數量統計邏輯 |
| v2.2 | 2026-07 | 「月度重點成果」改為彙整跨週重點，不使用省略號截斷 |
| v2.3 | 2026-07 | 移除 `<br>` 換行標籤，改為自然段落；避免同一列重複填寫工具名稱 |
| v2.4 | 2026-07 | 支援颱風假移除、改用政府行事曆自動判斷國定假日 |
| v2.5 | 2026-08 | 出貨數量統計：支援「彙整結果…總出貨數量…個」與「訂單共X筆」兩種寫法，正確計算含退貨補件的總量 |
| v2.6 | 2026-08 | 跨部門合作/風險事項：同一人/項目合併去重、依部門或項目欄位判斷人名與需協助內容 |
| v2.7 | 2026-08 | 新增「ECOCO客訴分析平台第二版」等版本自動拆分邏輯（偵測「第一版/第二版」字樣） |
| v2.8 | 2026-08 | 移除全部括號、「新增/修復/優化」內容依關鍵字分類合併，不重複顯示分類關鍵字本身 |
| v2.9 | 2026-08 | 月報輸出路徑改存至 `monthly_reports` 子資料夾 |
| v3.0 | 2026-08 | 「跨部門合作成果」「風險與待協調事項」「專案進度總覽」表格欄位簡化（拿掉冗餘欄位）；新增「行政支援與其他事項」區塊，支援人名合併與模糊相似度去重；三大貢獻避免同一專案重複入選；新增 `PROJECT_FORCED_TOOL` 指定專案固定工具顯示 |
| v3.1 | 2026-09 | 新增 `upload_monthly_report.py`：月報產出後自動上傳至 ECOCO 工作日誌系統（`report-a.ecocogroup.com`）存為草稿；處理該期別已有報表時的 409 衝突（草稿自動覆蓋、審核中／非草稿則跳出通知不覆蓋）；`generate_monthly_report.py` 的「非最後上班日跳過」情況改用 exit code 2、`upload_monthly_report.py` 的「主動保護不覆蓋」情況改用 exit code 3，兩者都與真正的錯誤（exit code 1）區分；`Run-MonthlyReport.ps1` 串接產出＋上傳兩步驟，並依 exit code 分別記錄對應的日誌訊息 |

---

*最後更新：2026-09-07*
