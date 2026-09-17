# -*- coding: utf-8 -*-
"""
upload_monthly_report.example.py（ecowork 版範本）
複製這份檔案為 upload_monthly_report.py，並把 CONFIG["api_token"] 換成你自己的月報專用 PAT 後即可使用。
本範本檔不含真實 Token，可安全放進版本控制；upload_monthly_report.py（含真實 Token）已在 .gitignore 中排除。

產出月報後，自動上傳至 ECOwork 彙報中心，直接送出審核

流程（ecowork 新 API 規定必須依序呼叫）：
  1. GET  /api/reports/periods?type=monthly   → 抓「本期」的期別代號
  2. POST /api/reports/drafts                 → 建立（或取得既有）草稿
  3. PATCH /api/reports/{id}                  → 填入內容與 AI 協作說明
  4. POST /api/reports/{id}/submit            → 送出審核（送出後不可再修改）

用法：
  python upload_monthly_report.py             # 上傳「本月」的月報（依系統日期判斷）
  python upload_monthly_report.py 2026-08     # 指定月份上傳（測試/補傳用）

⚠️ 第一次正式排程執行前，建議先手動跑一次確認：
   - CONFIG["api_token"] 要換成你自己的個人 API Token（ecw_ 開頭），
     且該 token 需要有 reports:read（查期別）與 reports:write（建草稿/送出）兩個權限
   - 期別自動判斷（get_current_period）用了多種常見欄位名稱去猜，
     若你們的期別清單格式不同，程式會印出原始回應內容，方便你回報調整
"""

import os
import sys
import json
import gzip
import zlib
import datetime
import urllib.request
import urllib.error

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
CONFIG = {
    "api_base": "https://space.ecocogroup.com/api/reports",
    "api_token": "YOUR_ECOWORK_API_TOKEN_HERE",  # 請填入你自己的月報專用PAT（ecw_開頭），需要 reports:read + reports:write 權限，切勿直接 commit 真實金鑰
    "monthly_reports_dir": r"D:\info\0507_weekly-report-skill\monthly-report-skill\monthly_reports",
    "ai_contribution": "使用內部規則式腳本彙整週報產生月報，未使用付費AI API",
    "content_key": "報表內容",  # 自由撰寫模式下 PATCH content 物件的固定鍵（已用瀏覽器 Network 實測確認）
    "web_url": "https://space.ecocogroup.com/#reports",
}

# ─────────────────────────────────────────
# 檔案處理（沿用舊邏輯）
# ─────────────────────────────────────────
def get_current_month_id():
    """回傳 API 用的期別格式 YYYY-MM"""
    today = datetime.date.today()
    return "{}-{:02d}".format(today.year, today.month)


def month_id_to_filename(month_id):
    year, month = month_id.split("-")
    return "monthly_{}-M{}.md".format(year, month)


def find_report_file(month_id):
    filename = month_id_to_filename(month_id)
    path = os.path.join(CONFIG["monthly_reports_dir"], filename)
    return path if os.path.exists(path) else None


def read_md(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────
# API 共用函式
# ─────────────────────────────────────────
def build_headers():
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Authorization": "Bearer {}".format(CONFIG["api_token"]),
        "Origin": "https://space.ecocogroup.com",
        "Referer": CONFIG["web_url"],
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
        "Sec-Ch-Ua": '"Not;A=Brand";v="8", "Chromium";v="150"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


def decode_body(raw_bytes, content_encoding):
    """依 Content-Encoding 標頭做解壓縮，urllib 不會自動處理"""
    encoding = (content_encoding or "").lower()
    try:
        if "gzip" in encoding:
            raw_bytes = gzip.decompress(raw_bytes)
        elif "deflate" in encoding:
            raw_bytes = zlib.decompress(raw_bytes)
    except Exception as e:
        print("[警告] 解壓縮回應內容失敗（Content-Encoding: {}）：{}".format(content_encoding, e))
    return raw_bytes.decode("utf-8", errors="replace")


def api_request(method, url, payload=None):
    """統一呼叫函式，回傳 (status_code, parsed_json_or_None, raw_body_str)"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=build_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = decode_body(resp.read(), resp.headers.get("Content-Encoding"))
    except urllib.error.HTTPError as e:
        raw = decode_body(e.read(), e.headers.get("Content-Encoding"))
        status = e.code
        try:
            return status, (json.loads(raw) if raw else {}), raw
        except Exception:
            return status, None, raw
    else:
        try:
            return resp.status, (json.loads(raw) if raw else {}), raw
        except Exception:
            return resp.status, None, raw


def extract_id(data):
    """從回應中盡量找出報表ID，欄位名稱不確定所以多嘗試幾種"""
    if not isinstance(data, dict):
        return None
    for key in ("id", "reportId", "draftId"):
        if data.get(key):
            return data[key]
    for wrapper in ("data", "report", "draft"):
        inner = data.get(wrapper)
        if isinstance(inner, dict):
            for key in ("id", "reportId"):
                if inner.get(key):
                    return inner[key]
    return None


# ─────────────────────────────────────────
# Step 1：抓「本期」期別代號
# ─────────────────────────────────────────
def get_current_period():
    url = "{}/periods?type=monthly".format(CONFIG["api_base"])
    status, data, raw = api_request("GET", url)
    if status != 200 or data is None:
        print("[ERROR] 取得期別清單失敗 HTTP {}: {}".format(status, raw[:300]))
        return None

    periods = data if isinstance(data, list) else (data.get("periods") or data.get("data") or [])
    if not periods:
        print("[ERROR] 期別清單是空的，回應內容：{}".format(raw[:300]))
        return None

    fallback = get_current_month_id()

    # 優先找標示為「本期／目前」的項目
    for item in periods:
        if not isinstance(item, dict):
            continue
        if any(item.get(k) is True for k in ("isCurrent", "current", "isActive")):
            code = item.get("period") or item.get("code") or item.get("value")
            if code:
                return code
        label = str(item.get("label") or item.get("name") or "")
        if "本期" in label:
            code = item.get("period") or item.get("code") or item.get("value")
            if code:
                return code

    # 找不到明確標示，退而求其次比對系統日期算出的月份代號
    for item in periods:
        if not isinstance(item, dict):
            continue
        code = item.get("period") or item.get("code") or item.get("value")
        if code == fallback:
            return code

    print("[警告] 無法自動判斷「本期」，期別清單原始內容：{}".format(json.dumps(periods, ensure_ascii=False)[:500]))
    print("[警告] 改用系統日期推算的期別代號作為備援：{}".format(fallback))
    return fallback


# ─────────────────────────────────────────
# Step 2：建立/取得草稿
# ─────────────────────────────────────────
def create_draft(period):
    url = "{}/drafts".format(CONFIG["api_base"])
    payload = {"reportType": "monthly", "period": period, "templateMode": "free"}
    status, data, raw = api_request("POST", url, payload)

    if status in (200, 201):
        draft_id = extract_id(data)
        if not draft_id:
            print("[ERROR] 建立草稿成功但抓不到報表ID，回應內容：{}".format(raw[:300]))
            return None
        print("[OK] 草稿已建立/取得，報表ID: {}".format(draft_id))
        return draft_id

    if status == 409:
        existing_id = (data or {}).get("reportId") or (data or {}).get("existingId")
        print("\n" + "=" * 60)
        print("⚠️  通知：期別「{}」已有送出的報表，本次不會覆蓋".format(period))
        if existing_id:
            print("    既有報表ID：{}".format(existing_id))
        print("    請至網頁確認：{}".format(CONFIG["web_url"]))
        print("=" * 60 + "\n")
        return "blocked"

    print("[ERROR] 建立草稿失敗 HTTP {}: {}".format(status, raw[:300]))
    return None


# ─────────────────────────────────────────
# Step 3：填入內容
# ─────────────────────────────────────────
def patch_content(report_id, md_content):
    url = "{}/{}".format(CONFIG["api_base"], report_id)
    payload = {
        "content": {CONFIG["content_key"]: md_content},
        "aiContribution": CONFIG["ai_contribution"],
    }
    status, data, raw = api_request("PATCH", url, payload)

    if status == 200:
        print("[OK] 內容已填入草稿")
        return True
    if status == 409:
        print("[ERROR] HTTP 409：該報表狀態已非草稿（可能待審或已核准），無法修改內容。{}".format(raw[:300]))
        return False
    print("[ERROR] 填入內容失敗 HTTP {}: {}".format(status, raw[:300]))
    return False


# ─────────────────────────────────────────
# Step 4：送出審核
# ─────────────────────────────────────────
def submit_report(report_id):
    url = "{}/{}/submit".format(CONFIG["api_base"], report_id)
    status, data, raw = api_request("POST", url, {})

    if status == 200:
        print("[OK] 已送出審核！報表ID: {}".format(report_id))
        return True
    if status == 400:
        print("[ERROR] 送出失敗 HTTP 400（可能是 aiContribution 空白，或必填欄位缺漏）：{}".format(raw[:300]))
        return False
    if status == 409:
        print("[ERROR] 送出失敗 HTTP 409：該期別已送出或已排程。{}".format(raw[:300]))
        return False
    print("[ERROR] 送出失敗 HTTP {}: {}".format(status, raw[:300]))
    return False


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────
def main():
    month_id = sys.argv[1] if len(sys.argv) > 1 else get_current_month_id()

    print("\n=== ECOCO 月報上傳（ecowork）===")

    report_path = find_report_file(month_id)
    if not report_path:
        print("[ERROR] 找不到月報檔案: {}".format(month_id_to_filename(month_id)))
        print("       路徑: {}".format(CONFIG["monthly_reports_dir"]))
        sys.exit(1)

    print("[OK] 讀取月報: {}".format(report_path))
    md_content = read_md(report_path)
    print("[OK] 月報字數: {} 字".format(len(md_content)))

    period = get_current_period()
    if not period:
        print("\n[FAIL] 無法判斷期別，中止上傳")
        sys.exit(1)
    print("[OK] 期別: {}".format(period))

    draft_id = create_draft(period)
    if draft_id == "blocked":
        sys.exit(3)  # exit code 3 = 主動保護不覆蓋，區別於真正的錯誤
    if not draft_id:
        print("\n[FAIL] 建立草稿失敗")
        sys.exit(1)

    if not patch_content(draft_id, md_content):
        print("\n[FAIL] 填入內容失敗，草稿已建立但內容未更新，請至網頁手動確認：")
        print(CONFIG["web_url"])
        sys.exit(1)

    if submit_report(draft_id):
        print("\n完成！月報已送出審核。")
        sys.exit(0)
    else:
        print("\n[FAIL] 送出審核失敗，草稿內容已儲存，請至網頁確認後手動送出：")
        print(CONFIG["web_url"])
        sys.exit(1)


if __name__ == "__main__":
    main()
