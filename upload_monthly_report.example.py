# -*- coding: utf-8 -*-
"""
upload_monthly_report.py
產出月報後，自動上傳至 ECOCO 工作日誌系統並儲存為草稿
POST https://report-a.ecocogroup.com/api/reports

用法：
  python upload_monthly_report.py             # 上傳「本月」的月報（依系統日期判斷）
  python upload_monthly_report.py 2026-08     # 指定月份上傳（測試/補傳用）
"""

import os
import sys
import json
import datetime
import urllib.request
import urllib.error

# ─────────────────────────────────────────
# CONFIG（跟 upload_report.py 使用同一組帳號資訊）
# ─────────────────────────────────────────
CONFIG = {
    "api_url": "https://report-a.ecocogroup.com/api/reports",
    "api_token": "YOUR_API_TOKEN_HERE",  # 請填入你自己的 API Token，切勿直接 commit 真實金鑰
    "author_id": "YOUR_AUTHOR_ID",
    "author_name": "YOUR_NAME",
    "author_role": "employee",
    "department": "行銷部",
    "monthly_reports_dir": r"D:\info\0507_weekly-report-skill\monthly-report-skill\monthly_reports",
}

# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
def get_current_month_id():
    """回傳 API 用的期別格式 YYYY-MM（不是檔名格式）"""
    today = datetime.date.today()
    return "{}-{:02d}".format(today.year, today.month)


def month_id_to_filename(month_id):
    """把 API 期別格式 YYYY-MM 轉成月報檔名格式 monthly_YYYY-MXX.md"""
    year, month = month_id.split("-")
    return "monthly_{}-M{}.md".format(year, month)


def find_report_file(month_id):
    filename = month_id_to_filename(month_id)
    path = os.path.join(CONFIG["monthly_reports_dir"], filename)
    if os.path.exists(path):
        return path
    return None


def read_md(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_headers(month_id):
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Authorization": "Bearer {}".format(CONFIG["api_token"]),
        "X-Caller-Id": CONFIG["author_id"],
        "Origin": "https://report-a.ecocogroup.com",
        "Referer": "https://report-a.ecocogroup.com/write?type=monthly&period={}".format(month_id),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
        "Sec-Ch-Ua": '"Not;A=Brand";v="8", "Chromium";v="150"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


def build_payload(month_id, md_content):
    return {
        "authorId": CONFIG["author_id"],
        "authorName": CONFIG["author_name"],
        "authorRole": CONFIG["author_role"],
        "department": CONFIG["department"],
        "period": month_id,
        "reportType": "monthly",
        "templateMode": "free",       # 自由填寫格式
        "isMDraft": True,             # 儲存為草稿
        "visibility": "private",
        "highlights": md_content,     # 完整月報 MD 內容放在 highlights
        "notes": "",
        "nextPlan": "",
        "summary": "",
        "aiContribution": "",
        "issues": "",
        "attachmentIds": [],
        "mentionUserIds": [],
        "mentionDeptIds": [],
        "recipientsTo": [],
        "recipientsCc": [],
    }


def check_report_status(existing_id, month_id):
    """查詢既有報表目前狀態，回傳 True=草稿（可覆蓋）、False=非草稿如審核中（不可覆蓋）、None=無法判斷"""
    url = "{}/{}".format(CONFIG["api_url"], existing_id)
    req = urllib.request.Request(url, method="GET", headers=build_headers(month_id))
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print("[警告] 查詢既有報表狀態失敗：{}".format(e))
        return None

    # 不同 API 可能用不同欄位名稱標示草稿狀態，逐一嘗試判斷
    for key in ("isDraft", "isMDraft"):
        if key in data:
            return bool(data[key])
    for key in ("status", "reviewStatus", "state"):
        if key in data:
            value = str(data[key])
            if "draft" in value.lower() or "草稿" in value:
                return True
            return False

    print("[警告] 無法從回應中判斷報表狀態，回應內容：{}".format(json.dumps(data, ensure_ascii=False)[:300]))
    return None


def update_existing_report(existing_id, month_id, md_content):
    """更新既有草稿內容（只有確認是草稿狀態才會呼叫這個函式）"""
    url = "{}/{}".format(CONFIG["api_url"], existing_id)
    # PATCH 只需要帶內容欄位，不需要 authorId/reportType 這類建立時才需要的欄位
    payload = build_payload(month_id, md_content)
    for key in ["authorId", "authorName", "authorRole", "department", "reportType"]:
        payload.pop(key, None)

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="PATCH", headers=build_headers(month_id))

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            print("[OK] 草稿已覆蓋更新！狀態碼: {}".format(status))
            print("[OK] 報表ID: {}".format(existing_id))
            print("[OK] 連結: https://report-a.ecocogroup.com/write?type=monthly&period={}".format(month_id))
            return True
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print("[ERROR] 更新既有草稿失敗 HTTP {}: {}".format(e.code, err_body))
        return False
    except Exception as e:
        print("[ERROR] 更新既有草稿失敗: {}".format(e))
        return False


def upload_report(month_id, md_content):
    payload = build_payload(month_id, md_content)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        CONFIG["api_url"],
        data=body,
        method="POST",
        headers=build_headers(month_id),
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            resp_body = resp.read().decode("utf-8")
            resp_data = json.loads(resp_body)
            report_id = resp_data.get("id", "")
            print("[OK] 上傳成功！狀態碼: {}".format(status))
            print("[OK] 月報ID: {}".format(report_id))
            print("[OK] 草稿連結: https://report-a.ecocogroup.com/write?type=monthly&period={}".format(month_id))
            return True
    except urllib.error.HTTPError as e:
        err_body_raw = e.read().decode("utf-8")
        if e.code == 409:
            try:
                err_data = json.loads(err_body_raw)
                existing_id = err_data.get("existingId")
                error_msg = err_data.get("error", "")
            except Exception:
                existing_id = None
                error_msg = err_body_raw

            if not existing_id:
                print("[ERROR] HTTP 409，但回應中找不到 existingId，無法自動處理：{}".format(err_body_raw))
                return False

            # 錯誤訊息裡若已明確提到「審核」，直接判定為審核中，不用再查一次
            if "審核" in error_msg:
                print("\n" + "=" * 60)
                print("⚠️  通知：該期別（{}）的報表目前為「審核中」狀態".format(month_id))
                print("    報表ID：{}".format(existing_id))
                print("    為避免影響審核流程，本次不會覆蓋，請至系統網頁確認：")
                print("    https://report-a.ecocogroup.com/write?type=monthly&period={}".format(month_id))
                print("=" * 60 + "\n")
                return "blocked"

            print("[提示] 該期別已存在報表（ID: {}），查詢目前狀態...".format(existing_id))
            is_draft = check_report_status(existing_id, month_id)

            if is_draft is True:
                print("[提示] 確認為草稿狀態，直接覆蓋更新。")
                return update_existing_report(existing_id, month_id, md_content)
            elif is_draft is False:
                print("\n" + "=" * 60)
                print("⚠️  通知：該期別（{}）已有報表，且非草稿狀態（可能審核中或已核准）".format(month_id))
                print("    報表ID：{}".format(existing_id))
                print("    為避免覆蓋掉正式送出的內容，本次不會自動覆蓋，請至系統網頁確認：")
                print("    https://report-a.ecocogroup.com/write?type=monthly&period={}".format(month_id))
                print("=" * 60 + "\n")
                return "blocked"
            else:
                print("\n" + "=" * 60)
                print("⚠️  通知：該期別（{}）已有報表，但無法自動判斷是否為草稿".format(month_id))
                print("    報表ID：{}".format(existing_id))
                print("    為安全起見，本次不會自動覆蓋，請至系統網頁確認狀態後再手動處理：")
                print("    https://report-a.ecocogroup.com/write?type=monthly&period={}".format(month_id))
                print("=" * 60 + "\n")
                return "blocked"

        print("[ERROR] HTTP {}: {}".format(e.code, err_body_raw))
        return False
    except Exception as e:
        print("[ERROR] 上傳失敗: {}".format(e))
        return False


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────
def main():
    # 支援指定月份：python upload_monthly_report.py 2026-08
    if len(sys.argv) > 1:
        month_id = sys.argv[1]
    else:
        month_id = get_current_month_id()

    print("\n=== ECOCO 月報上傳 ===")
    print("期別: {}".format(month_id))

    report_path = find_report_file(month_id)
    if not report_path:
        print("[ERROR] 找不到月報檔案: {}".format(month_id_to_filename(month_id)))
        print("       路徑: {}".format(CONFIG["monthly_reports_dir"]))
        sys.exit(1)

    print("[OK] 讀取月報: {}".format(report_path))
    md_content = read_md(report_path)
    print("[OK] 月報字數: {} 字".format(len(md_content)))

    print("[...] 上傳至 {} ...".format(CONFIG["api_url"]))

    result = upload_report(month_id, md_content)

    if result is True:
        print("\n完成！請至以下網址確認草稿：")
        print("https://report-a.ecocogroup.com/write?type=monthly&period={}".format(month_id))
        sys.exit(0)
    elif result == "blocked":
        print("\n[提示] 本次未上傳／未覆蓋（既有報表非草稿狀態，已跳出通知，屬正常保護機制，非程式錯誤）。")
        sys.exit(3)  # exit code 3 = 主動保護不覆蓋，區別於真正的錯誤
    else:
        print("\n[FAIL] 上傳失敗，請檢查 API Token 或網路連線")
        sys.exit(1)


if __name__ == "__main__":
    main()
