# -*- coding: utf-8 -*-
"""
ECOCO 月報自動彙整程式（免費版 / 純規則彙整，不呼叫任何付費 API）
================================================================
功能：
  1. 判斷今天是否為「當月最後一個上班日」（自動排除週末＋政府國定假日）
  2. 若符合條件，讀取當月所有週報 MD 檔
  3. 用規則解析（表格加總、關鍵字分類排序）彙整成月報，套入樣板
  4. 輸出 monthly_YYYY-MM.md 至指定資料夾

說明：
  數字類數據（案件數、工時、比率）為 100% 精準加總。
  「專案進度」「三大貢獻」等語意類段落為關鍵字規則判斷，非AI語意理解，
  建議產出後花 1-2 分鐘檢視微調文字再送主管審閱。

用法：
  python generate_monthly_report.py                     # 正常模式：只有今天是本月最後上班日才會執行
  python generate_monthly_report.py --force              # 強制模式：不管今天是幾號，直接產出「本月」月報（測試用）
  python generate_monthly_report.py --force --month 2026-07   # 強制指定月份產出
"""

import os
import sys
import re
import json
import glob
import argparse
import calendar
import difflib
import urllib.request
from datetime import date, datetime
from collections import OrderedDict

# ============================================================
# 路徑設定（請依實際環境調整）
# ============================================================
BASE_DIR = r"D:\info\0507_weekly-report-skill"
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
OUTPUT_DIR = os.path.join(BASE_DIR, "monthly-report-skill")
MONTHLY_REPORTS_DIR = os.path.join(OUTPUT_DIR, "monthly_reports")
CALENDAR_CACHE_DIR = os.path.join(OUTPUT_DIR, "_calendar_cache")
LOG_PATH = os.path.join(OUTPUT_DIR, "monthly_report_log.txt")

TAIWAN_CALENDAR_URL = "https://raw.githubusercontent.com/ruyut/TaiwanCalendar/master/data/{year}.json"

PRIORITY_ORDER = ["AI工具成果", "系統優化成果", "流程改善成果", "客服營運成果", "行銷專案成果", "行政支援事項"]
PRIORITY_KEYWORDS = [
    ("AI", "AI工具成果"),
    ("Claude", "AI工具成果"),
    ("系統", "系統優化成果"),
    ("平台", "系統優化成果"),
    ("自動化", "系統優化成果"),
    ("流程", "流程改善成果"),
    ("客服", "客服營運成果"),
    ("案件", "客服營運成果"),
    ("回覆率", "客服營運成果"),
    ("行銷", "行銷專案成果"),
]

# 專案關鍵字 -> 顯示用名稱（可自行增減調整）
PROJECT_KEYWORDS = OrderedDict([
    ("ECOCO客訴分析平台", "ECOCO客訴分析平台"),
    ("商城訂單財務發票資訊", "商城訂單財務發票資訊系統"),
    ("ECOCO Chatbot", "ECOCO Chatbot 常見問題銀行版"),
    ("週報自動化", "週報自動化系統"),
    ("營運例會簡報自動化", "營運例會簡報自動化系統"),
    ("商品包材出入庫表", "商品包材出入庫表系統"),
    ("月報自動化", "月報自動化系統"),
])

VALUE_PHRASE_BY_CATEGORY = {
    "AI工具成果": "提升AI導入效益，減少人工作業時間",
    "系統優化成果": "提升系統穩定性與使用體驗",
    "流程改善成果": "簡化作業流程，降低出錯率",
    "客服營運成果": "降低客服人力負擔，提升回覆效率",
    "行銷專案成果": "支援行銷專案推進",
    "行政支援事項": "支援日常營運行政作業",
}

# 各專案固定分類（比逐句關鍵字判斷更準確，避免片段截斷導致誤判）
PROJECT_CATEGORY = {
    "ECOCO客訴分析平台": "系統優化成果",
    "商城訂單財務發票資訊": "系統優化成果",
    "ECOCO Chatbot": "AI工具成果",
    "週報自動化": "AI工具成果",
    "營運例會簡報自動化": "AI工具成果",
}

# 指定專案固定顯示的工具名稱（當跨週工具不一致、或部分週報未標明工具時，仍以此為主）
PROJECT_FORCED_TOOL = {
    "ECOCO客訴分析平台": "Claude",
    "商品包材出入庫表": "Claude",
    "月報自動化": "Claude",
}


# ============================================================
# 基礎工具
# ============================================================
def log(msg):
    line = "[{}] {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_taiwan_calendar(year):
    os.makedirs(CALENDAR_CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CALENDAR_CACHE_DIR, "{}.json".format(year))

    data = None
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None

    if data is None:
        url = TAIWAN_CALENDAR_URL.format(year=year)
        log("下載 {} 年政府行事曆資料：{}".format(year, url))
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(raw)
        except Exception as e:
            log("警告：下載政府行事曆失敗（{}），改用「僅排除週六週日」的保守判斷".format(e))
            return {}

    return {item["date"]: item.get("isHoliday", False) for item in data}


def is_workday(d, gov_calendar):
    date_str = d.strftime("%Y%m%d")
    if date_str in gov_calendar:
        return not gov_calendar[date_str]
    return d.weekday() < 5


def get_last_workday_of_month(year, month, gov_calendar):
    last_day_num = calendar.monthrange(year, month)[1]
    for day_num in range(last_day_num, 0, -1):
        d = date(year, month, day_num)
        if is_workday(d, gov_calendar):
            return d
    return None


# ============================================================
# 週報解析
# ============================================================
def parse_weekly_period(text):
    m = re.search(r"期間[：:]\s*(\d{4})/(\d{2})/(\d{2})\s*~\s*(\d{4})/(\d{2})/(\d{2})", text)
    if not m:
        return None
    return date(int(m.group(4)), int(m.group(5)), int(m.group(6)))


def collect_weekly_reports_for_month(year, month):
    pattern = os.path.join(REPORTS_DIR, "weekly_*.md")
    candidates = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read()
        end_date = parse_weekly_period(text)
        if end_date and end_date.year == year and end_date.month == month:
            candidates.append((end_date, os.path.basename(path), text))
    candidates.sort(key=lambda x: x[0])
    return candidates


def section_after(text, heading):
    idx = text.find(heading)
    if idx == -1:
        return ""
    start = idx + len(heading)
    next_idx = len(text)
    for marker in ["\n## ", "\n### ", "\n---"]:
        m_idx = text.find(marker, start)
        if m_idx != -1 and m_idx < next_idx:
            next_idx = m_idx
    return text[start:next_idx]


def parse_pipe_table(block):
    """解析 markdown 表格。可容忍儲存格內含未跳脫換行的情況（會自動合併回同一列），
    也可容忍多打一個空白儲存格導致欄位數對不齊的情況（自動移除多餘的空白欄位）。"""
    lines = [l for l in block.strip().split("\n") if l.strip()]
    if len(lines) < 2 or not lines[0].strip().startswith("|"):
        return []
    header = [c.strip() for c in lines[0].strip().strip("|").split("|")]
    ncol = len(header)
    rows = []
    buffer = ""
    for line in lines[2:]:  # 跳過分隔線（---）
        buffer = (buffer + " " + line.strip()) if buffer else line.strip()
        cols = [c.strip() for c in buffer.strip().strip("|").split("|")]
        if len(cols) < ncol:
            continue
        if len(cols) > ncol:
            non_empty = [c for c in cols if c != ""]
            if len(non_empty) == ncol:
                cols = non_empty  # 多出來的是空白欄位，移除後正好對齊，避免資料錯位
            else:
                cols = cols[:ncol]  # 無法判斷哪個是多餘欄位，退而求其次取前 ncol 個
        rows.append(dict(zip(header, cols)))
        buffer = ""
    return rows


def extract_number(s):
    if not s:
        return 0.0
    m = re.search(r"[\d.]+", s.replace(",", ""))
    return float(m.group()) if m else 0.0


def classify_bullet(text):
    for kw, label in PRIORITY_KEYWORDS:
        if kw in text:
            return label
    return "行政支援事項"


def strip_parens(text):
    """移除文字中的括號符號（全形／半形），以空白取代避免文字黏在一起，只留內容本身"""
    text = re.sub(r"[（）()]", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def clean_snippet(text):
    """移除表格內殘留的省略號、項目編號前綴、「等N項」等雜訊，不做長度截斷。
    注意：此階段刻意不移除括號，因為後續的重複偵測（dedup_leading_repeat）需要靠括號判斷；
    括號會在最終要顯示的地方才移除，見 strip_parens。"""
    text = (text or "").strip()
    text = re.sub(r"^\d+(-\d+)?\.\s*", "", text)
    text = re.sub(r"（等\d+項）", "", text)
    text = text.replace("…", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def dedup_leading_repeat(text):
    """清除來源文字本身就重複的開頭詞，例如「新增內容（新增內容調整...」→「（新增內容調整...」"""
    m = re.match(r"^(\S{2,10}?)[（(]\1", text)
    if m:
        prefix_len = len(m.group(1))
        return text[prefix_len + 1:].strip()
    return text


def strip_project_name(text, kw):
    """移除內容中重複出現的專案名稱文字（該名稱已顯示於表格「項目」欄位，內文不需要再重複）"""
    bare = kw.replace("ECOCO", "")
    for name in sorted({kw, bare}, key=len, reverse=True):
        if name:
            text = text.replace(name, "")
    text = re.sub(r"^[：:，、\s]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# 已知會出現在週報裡的工具／系統名稱（用於辨識前綴，避免誤把一般詞彙當成工具名）
KNOWN_TOOL_PREFIXES = ["Claude", "CODEX", "CURSOR", "ANTIGRAVITY", "ChatGPT", "Gemini", "GPT"]


def extract_tool_prefix(text):
    """辨識文字開頭是否為已知工具名稱前綴，回傳 (工具名稱或None, 剩餘內容)；
    剩餘內容會清除開頭重複詞（dedup）並移除括號後才回傳"""
    for tool in KNOWN_TOOL_PREFIXES:
        pattern = r"^{}\s*[：:]\s*".format(re.escape(tool))
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            return tool, strip_parens(dedup_leading_repeat(text[m.end():].strip()))
    return None, strip_parens(dedup_leading_repeat(text))


def format_single_point(text, kw):
    """處理單筆重點文字：去除重複專案名稱，工具前綴統一格式化，並移除括號"""
    t = strip_project_name(text, kw)
    tool, rest = extract_tool_prefix(t)
    return "{}：{}".format(tool, rest) if tool else rest


def summarize_points(records, kw, max_points=2):
    """合併跨週重點文字：去除重複的專案名稱；連續且使用同一個工具的重點才合併、工具名稱只顯示一次，
    不同工具或無法辨識工具的內容不會被混在一起講。"""
    seen = set()
    parsed = []
    for r in records:
        t = strip_project_name(r["text"], kw)
        if not t or t in seen:
            continue
        seen.add(t)
        tool, rest = extract_tool_prefix(t)
        parsed.append((tool, rest))
        if len(parsed) >= max_points:
            break

    if not parsed:
        return "本月無相關紀錄"

    segments = []
    i = 0
    while i < len(parsed):
        tool, rest = parsed[i]
        group_rest = [rest] if rest else []
        j = i + 1
        while j < len(parsed) and parsed[j][0] == tool:
            if parsed[j][1]:
                group_rest.append(parsed[j][1])
            j += 1
        content = "；".join(group_rest)
        if tool:
            segments.append("{}：{}".format(tool, content) if content else tool)
        else:
            segments.append(content)
        i = j

    return "；".join(s for s in segments if s)


def clean_bullet(text):
    """清理三大成果句子：移除括號、省略號，修正標點殘留瑕疵，確保有句尾標點"""
    text = (text or "").strip()
    text = strip_parens(text)
    text = text.replace("…", "")
    text = re.sub(r"[：:]\s*[，、]", "：", text)  # 修正「：，」「：、」這類冒號後緊接多餘標點
    text = re.sub(r"([，、])\s*\1+", r"\1", text)  # 修正連續重複的逗號／頓號
    text = re.sub(r"^[：:，、\s]+", "", text)  # 開頭殘留的多餘標點
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in "。！？」":
        text += "。"
    return text


# ============================================================
# 彙整邏輯
# ============================================================
def dedupe_fuzzy(items, threshold=0.55):
    """依文字相似度去重合併：若兩筆內容相似度達到門檻，視為同一件事，只保留較完整（較長）的版本。
    threshold 越高代表要求越相似才會合併，避免誤把不相關的兩件事合併在一起。"""
    kept = []
    for it in items:
        merged = False
        for i, existing in enumerate(kept):
            ratio = difflib.SequenceMatcher(None, it["text"], existing["text"]).ratio()
            if ratio >= threshold:
                if len(it["text"]) > len(existing["text"]):
                    kept[i] = it  # 保留內容較完整的版本
                merged = True
                break
        if not merged:
            kept.append(it)
    return kept


# 週報裡常出現的人名／部門名稱（可自行增減）：用於「行政支援與其他事項」的人名合併與加註引號
KNOWN_NAMES = [
    "政偉", "忠翰", "書豪", "佳美", "冠翰", "鈺雯", "浩文", "陳熙", "欣妤", "雯瑛",
    "Beryl", "Eva", "Ida", "Krystal", "Yu",
]
KNOWN_DEPTS = ["副總", "資訊部", "財務", "總經理室", "營運部", "行銷部", "研發部", "客服部"]


def find_person_name(text):
    """在文字中找出第一個符合已知人名清單的名字，找不到回傳 None"""
    for name in KNOWN_NAMES:
        if name in text:
            return name
    return None


COMMON_NAME_TRAILING_WORDS = ["AI客服系統", "執行進度"]


def strip_name_prefix(text, name):
    """移除文字開頭的人名（含「實習生+姓名」寫法），以及緊接著的常見詞（如 AI客服系統、執行進度）"""
    text = re.sub(r"^(實習生\s*)?" + re.escape(name) + r"\s*", "", text)
    trailing_pattern = "|".join(re.escape(w) for w in COMMON_NAME_TRAILING_WORDS)
    text = re.sub(r"^(?:{})[：:，、\s]*".format(trailing_pattern), "", text)
    text = re.sub(r"^[：:，、\s]+", "", text)
    return text.strip()


def merge_by_person_name(items):
    """只要提到同一個人名，就合併成一句：人名只在開頭標示一次，
    每段內容開頭重複的人名／常見詞（如「AI客服系統」「實習生」）會先清除，避免重複顯示"""
    named_groups = OrderedDict()
    unnamed = []
    for it in items:
        name = find_person_name(it["text"])
        if name:
            named_groups.setdefault(name, []).append(it)
        else:
            unnamed.append(it)

    merged = []
    for name, group in named_groups.items():
        context_label = None
        for g in group:
            for w in COMMON_NAME_TRAILING_WORDS:
                if w in g["text"]:
                    context_label = w
                    break
            if context_label:
                break

        seen_pieces = set()
        pieces = []
        for g in group:
            stripped = strip_name_prefix(g["text"], name)
            if stripped and stripped not in seen_pieces:
                seen_pieces.add(stripped)
                pieces.append(stripped)

        prefix = "{}{}".format(name, context_label) if context_label else name
        combined_text = "{}：{}".format(prefix, "；".join(pieces)) if pieces else name
        merged.append({"week": group[-1]["week"], "text": combined_text})
    merged.extend(unnamed)
    return merged


def quote_names(text):
    """文字中提到的人名／部門名稱，加上「」標明"""
    for name in sorted(KNOWN_NAMES + KNOWN_DEPTS, key=len, reverse=True):
        quoted = "「{}」".format(name)
        if name in text and quoted not in text:
            text = text.replace(name, quoted)
    return text


def collect_other_items(weekly_records):
    """從『本週完成工作』表格中蒐集「其他」項目的內容，依「；」拆成個別事項，
    清理、依人名合併、去重（含模糊相似度合併）後回傳清單"""
    seen = set()
    items = []
    for end_date, filename, text in weekly_records:
        week_label = filename.replace("weekly_", "").replace(".md", "")
        work_rows = parse_pipe_table(section_after(text, "## 本週完成工作"))
        for row in work_rows:
            if row.get("項目") != "其他":
                continue
            content = row.get("完成內容", "")
            for piece in content.split("；"):
                cleaned = strip_parens(clean_snippet(piece))
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    items.append({"week": week_label, "text": cleaned})
    items = merge_by_person_name(items)
    return dedupe_fuzzy(items)


def collect_project_progress(weekly_records):
    """依專案關鍵字，從『本週完成工作』與『下週工作計畫』表格中蒐集每週提及的進度片段"""
    progress = OrderedDict((k, []) for k in PROJECT_KEYWORDS)

    for end_date, filename, text in weekly_records:
        week_label = filename.replace("weekly_", "").replace(".md", "")

        work_rows = parse_pipe_table(section_after(text, "## 本週完成工作"))
        for row in work_rows:
            content = row.get("完成內容", "")
            pct = row.get("進度", "")
            for kw in PROJECT_KEYWORDS:
                bare = kw.replace("ECOCO", "")
                if kw in content or bare in content:
                    progress[kw].append({"week": week_label, "text": clean_snippet(content), "pct": pct})

        next_rows = parse_pipe_table(section_after(text, "## 下週工作計畫"))
        for row in next_rows:
            content = row.get("預計工作", "")
            pct = row.get("目前進度", "")
            for kw in PROJECT_KEYWORDS:
                bare = kw.replace("ECOCO", "")
                if kw in content or bare in content:
                    progress[kw].append({"week": week_label, "text": clean_snippet(content), "pct": pct})

    return progress


CATEGORY_KEYWORDS = OrderedDict([
    ("新增", ["新增", "建置", "加入"]),
    ("修復", ["修復", "修正", "解決", "排除", "異常", "失敗", "待修正", "斷層", "錯誤", "無法"]),
    ("優化", ["優化", "調整", "改善"]),
])


def classify_action(text):
    """回傳 (分類, 觸發的關鍵字)：依文字中最早出現的關鍵字判斷分類，較貼近語句的實際重點"""
    best_cat, best_kw, best_idx = None, None, None
    for cat, kws in CATEGORY_KEYWORDS.items():
        for k in kws:
            idx = text.find(k)
            if idx != -1 and (best_idx is None or idx < best_idx):
                best_cat, best_kw, best_idx = cat, k, idx
    return best_cat, best_kw


def strip_matched_keyword(text, keyword):
    """已用分類標籤（如「新增:」）表示過的關鍵字，若出現在內容開頭附近就不重複顯示"""
    if not keyword:
        return text
    idx = text.find(keyword)
    if idx != -1 and idx <= 4:  # 只清除靠近開頭的重複，避免誤刪內文中間有意義的用字
        text = text[:idx] + text[idx + len(keyword):]
        text = re.sub(r"^[（(：:，、\s]+", "", text)
        text = re.sub(r"\s+", " ", text).strip()
    return text


def synthesize_narrative(records, kw):
    """將跨週重點依「新增／修復／優化」分類合併，格式如「修復：a、b；新增：c」，
    不重複填工具名稱，也不重複顯示分類關鍵字本身，不使用括號包裹"""
    seen = set()
    items = []
    for r in records:
        t = strip_project_name(r["text"], kw)
        _, rest = extract_tool_prefix(t)
        rest = (rest or t).strip()
        if rest and rest not in seen:
            seen.add(rest)
            items.append(rest)

    if len(items) < 2:
        return None

    grouped = OrderedDict()
    for it in items:
        cat, matched_kw = classify_action(it)
        cat = cat or "進度"
        cleaned = strip_matched_keyword(it, matched_kw)
        grouped.setdefault(cat, []).append(cleaned or it)

    parts = ["{}：{}".format(cat, "、".join(texts)) for cat, texts in grouped.items()]
    return "；".join(parts)


def parse_date_loose(s):
    """從不固定格式的日期文字中解析出日期，解析不出來回傳 None（例如「待確認」「2026/07/21~」等）"""
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s or "")
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


TASK_CONTENT_KEYWORDS = [
    "確認", "調整", "功能", "問題", "狀況", "系統", "優化", "建置", "流程", "申請",
    "追蹤", "檢查", "匯出", "狀態", "事宜", "延遲", "異常", "設定", "區間", "版位",
    "顯示", "資料", "退換貨", "外露", "更換", "紀錄", "傳送", "排程",
]


def looks_like_bare_name(text):
    """粗略判斷這段文字是否只是人名（沒有描述具體協助內容）。
    條件收得較嚴格，避免像「鈺雯粉專宣傳」這種本身就是任務描述的短句被誤判成人名：
    - 含常見任務類關鍵字 → 一律視為任務內容，不是人名
    - 含「/」「、」分隔多個姓名（如「忠翰/書豪」）→ 視為人名
    - 或整段文字很短（4字以內，如「佳美」「冠翰」）→ 視為人名
    """
    if len(text) > 10:
        return False
    if any(k in text for k in TASK_CONTENT_KEYWORDS):
        return False
    if not re.fullmatch(r"[\u4e00-\u9fff／/、]+", text):
        return False
    if "／" in text or "/" in text or "、" in text:
        return True
    return len(text) <= 4


def extract_name_from_dept(dept):
    """從「部門(姓名)」這種寫法中取出姓名；沒有括號則原樣回傳"""
    m = re.search(r"[（(]([^）)]+)[）)]", dept or "")
    return m.group(1) if m else (dept or "")


PLACEHOLDER_NO_CONTENT = "尚未於週報中記錄具體協助內容"


def resolve_item_and_collaborator(item, dept):
    """整理『項目』與『協作部門』：項目盡量顯示需協助的具體內容而非人名，協作部門盡量顯示人名。
    若項目本身只是人名、找不到任何任務描述，項目欄位會誠實標註尚未記錄具體內容，不臆測填寫。"""
    name_from_dept = extract_name_from_dept(dept)
    if looks_like_bare_name(item) and name_from_dept == dept:
        # 項目欄位其實只寫了人名，且協作部門也沒有可拆出的人名 → 把項目的人名搬到協作部門
        return PLACEHOLDER_NO_CONTENT, item

    # 「部門+姓名」黏在一起的寫法（例如項目欄寫「營運 忠翰/書豪」、部門欄寫「營運」）
    if dept and item.startswith(dept):
        remainder = item[len(dept):].strip()
        if remainder and looks_like_bare_name(remainder):
            return PLACEHOLDER_NO_CONTENT, remainder

    return item, name_from_dept


def merge_coordination_rows(rows):
    """先解析出每一列真正的『項目內容』與『協作人名』（不管人名原本寫在項目欄還是部門欄），
    再依解析後的結果合併——這樣同一個人即使各週欄位寫法不一致，也能正確合併成一筆。
    若能解析出多個預計完成日，顯示成「預計M/D~M/D完成」的起訖日格式"""
    resolved = []
    for r in rows:
        raw_item = strip_parens(clean_snippet(r.get("項目", "")))
        raw_dept = r.get("協作部門", "") or "－"
        item, collaborator = resolve_item_and_collaborator(raw_item, raw_dept)
        resolved.append({"item": item, "dept": collaborator, "raw": r})

    groups = OrderedDict()
    for entry in resolved:
        key = (entry["item"], entry["dept"])
        groups.setdefault(key, []).append(entry["raw"])

    merged = []
    for (item, dept), group in groups.items():
        dates = [d for d in (parse_date_loose(r.get("預計完成日", "")) for r in group) if d]
        if dates:
            dmin, dmax = min(dates), max(dates)
            if dmin == dmax:
                due_text = "預計{}/{}完成".format(dmin.month, dmin.day)
            else:
                due_text = "預計{}/{}~{}/{}完成".format(dmin.month, dmin.day, dmax.month, dmax.day)
        else:
            due_text = "預計完成日待確認"
        status = group[-1].get("進度", "") or "進行中"  # 取最新一週的進度狀態
        merged.append({"item": item, "dept": dept, "due_text": due_text, "status": status})
    return merged


def growth_text(records, kw=None):
    if not records:
        return "本月無相關進度紀錄"
    if kw is not None:
        narrative = synthesize_narrative(records, kw)
        if narrative:
            tool = common_tool(records, kw)
            return "{}：{}".format(tool, narrative) if tool else narrative
    first_pct = records[0]["pct"] or "進行中"
    last_pct = records[-1]["pct"] or "進行中"
    if first_pct == last_pct:
        return "持續推進中：{}".format(last_pct)
    return "由「{}」推進至「{}」".format(first_pct, last_pct)


VERSION_TAG_PATTERN = re.compile(r"第[一二三四五六七八九十1-9]版")


def split_by_version(records):
    """若內容中提到「第一版」「第二版」等版本字樣，拆成獨立子項目；否則回傳單一群組"""
    groups = OrderedDict()
    for r in records:
        m = VERSION_TAG_PATTERN.search(r["text"])
        tag = m.group(0) if m else None
        groups.setdefault(tag, []).append(r)

    if len(groups) == 1 and None in groups:
        return [(None, records)]

    result = []
    for tag, group_records in groups.items():
        if tag:
            cleaned = [dict(r, text=r["text"].replace(tag, "").strip()) for r in group_records]
        else:
            cleaned = group_records
        result.append((tag, cleaned))
    return result


def common_tool(records, kw):
    """判斷這組重點是否全部由同一個工具完成，若是則回傳工具名稱，否則回傳 None"""
    tools = set()
    for r in records:
        t = strip_project_name(r["text"], kw)
        tool, _ = extract_tool_prefix(t)
        tools.add(tool)
    if len(tools) == 1:
        return tools.pop()
    return None


def format_column_pair(records, kw):
    """組成『月初進度』『月底進度』欄位內容：只放內容本身，不加「月初：」「月底：」標籤，
    也不重複顯示工具名稱（工具名稱已顯示在『專案』欄位）。
    若本月只有一筆資料，月初欄位留空，內容放在月底欄位。"""
    def clean(text):
        t = strip_project_name(text, kw)
        _, rest = extract_tool_prefix(t)
        return rest

    if len(records) == 1:
        return "", clean(records[-1]["text"])

    return clean(records[0]["text"]), clean(records[-1]["text"])


def aggregate(weekly_records):
    customer_totals = OrderedDict([("已處理案件", 0.0), ("AI回覆案件", 0.0), ("追蹤案件", 0.0), ("補點案件", 0.0)])
    weekly_ai_rates = []
    ai_tool_hours = OrderedDict()
    ai_tool_notes = OrderedDict()
    total_saved_hours = 0.0
    all_bullets = []
    coordination_rows = []
    ai_tools_used = set()
    week_labels = []

    for end_date, filename, text in weekly_records:
        week_label = filename.replace("weekly_", "").replace(".md", "")
        week_labels.append(week_label)

        stats_rows = parse_pipe_table(section_after(text, "### 客服營運數據"))
        for row in stats_rows:
            key = row.get("指標", "")
            val = row.get("數據", "")
            if key in customer_totals:
                customer_totals[key] += extract_number(val)
            if key == "AI回覆率":
                weekly_ai_rates.append((week_label, extract_number(val)))

        ai_rows = parse_pipe_table(section_after(text, "### AI導入成效"))
        for row in ai_rows:
            tool = row.get("AI工具", "未標示")
            hours = extract_number(row.get("預估節省工時", ""))
            ai_tool_hours[tool] = ai_tool_hours.get(tool, 0.0) + hours
            ai_tool_notes.setdefault(tool, []).append(row.get("本週成果", ""))

        m = re.search(r"本週AI工具預估節省工時[：:]\s*約?([\d.]+)\s*小時", text)
        if m:
            total_saved_hours += float(m.group(1))

        highlight_block = section_after(text, "### 本週三大成果")
        for line in highlight_block.strip().split("\n"):
            line = line.strip()
            m2 = re.match(r"^\d+\.\s*(.+)$", line)
            if m2:
                all_bullets.append((week_label, m2.group(1).strip()))

        coord_rows = parse_pipe_table(section_after(text, "## 須協調與幫助"))
        for row in coord_rows:
            row["_week"] = week_label
            coordination_rows.append(row)

        work_rows = parse_pipe_table(section_after(text, "## 本週完成工作"))
        for row in work_rows:
            if row.get("項目") == "AI工具":
                content = row.get("完成內容", "")
                m3 = re.match(r"^([A-Za-z一-龥]+)\s*[：:]", content)
                if m3:
                    ai_tools_used.add(m3.group(1))

    ai_reply_rate = (customer_totals["AI回覆案件"] / customer_totals["已處理案件"] * 100) if customer_totals["已處理案件"] else 0.0

    return {
        "customer_totals": customer_totals,
        "ai_reply_rate": ai_reply_rate,
        "weekly_ai_rates": weekly_ai_rates,
        "ai_tool_hours": ai_tool_hours,
        "ai_tool_notes": ai_tool_notes,
        "total_saved_hours": total_saved_hours,
        "all_bullets": all_bullets,
        "coordination_rows": coordination_rows,
        "ai_tools_used": ai_tools_used,
        "week_labels": week_labels,
    }


SHIPPING_PATTERN = re.compile(
    r"彙整結果(.*?)總出貨數量\s*(\d+)\s*個(?:\s*\+\s*(\d+)\s*個)?"
)
SHIPPING_ORDER_COUNT_PATTERN = re.compile(r"(\d+)\s*筆")

# 新寫法：「訂單共X筆」（不拆品項明細，直接採用這個數字）
# 限定「商品包裝」附近才比對，避免誤抓瑕疵退換貨等其他情境的「訂單共X筆」
SIMPLE_ORDER_PATTERN = re.compile(r"商品包裝[^\n]{0,15}?訂單共\s*(\d+)\s*筆")


def aggregate_shipping_stats(weekly_records):
    """掃描全部週報，加總出貨相關數字，同時支援兩種寫法：
    1.「彙整結果X個：Y筆...總出貨數量Z個(+N個退貨補件)」（可能一次列多組X個:Y筆，訂單筆數需全部加總）
    2.「訂單共X筆」（不拆品項明細，直接採用該數字，同時計入訂單筆數與出貨數量）
    """
    total_orders = 0     # 訂單筆數加總（筆）
    total_shipped = 0    # 正常出貨數量加總（個）
    total_returns = 0    # 退貨／補件數量加總（個）
    found = False
    for _, _, text in weekly_records:
        matched_spans = []
        for m in SHIPPING_PATTERN.finditer(text):
            found = True
            matched_spans.append(m.span())
            detail = m.group(1)
            orders_this_match = sum(int(n) for n in SHIPPING_ORDER_COUNT_PATTERN.findall(detail))
            total_orders += orders_this_match
            total_shipped += int(m.group(2))
            if m.group(3):
                total_returns += int(m.group(3))

        for m in SIMPLE_ORDER_PATTERN.finditer(text):
            # 避免跟上面「彙整結果...」格式重疊比對到同一段文字
            if any(m.start() >= s and m.end() <= e for s, e in matched_spans):
                continue
            found = True
            n = int(m.group(1))
            total_orders += n
            total_shipped += n

    combined_total = total_shipped + total_returns
    return {
        "found": found,
        "orders": total_orders,
        "shipped": total_shipped,
        "returns": total_returns,
        "total": combined_total,
    }


def is_shipping_bullet(text):
    return bool(SHIPPING_PATTERN.search(text) or SIMPLE_ORDER_PATTERN.search(text))


def format_shipping_summary(stats):
    base = "ECOCO商城商品包裝出貨，本月累計彙整訂單 {} 筆，總出貨數量共 {} 個".format(
        stats["orders"], stats["total"]
    )
    if stats["returns"]:
        base += "，含正常出貨 {} 個、退貨／補件 {} 個".format(stats["shipped"], stats["returns"])
    return base + "。"


def mentioned_project(text):
    """判斷文字中提到哪個 PROJECT_KEYWORDS 專案，找不到回傳 None"""
    for kw in PROJECT_KEYWORDS:
        bare = kw.replace("ECOCO", "")
        if kw in text or bare in text:
            return kw
    return None


def pick_top_bullets(all_bullets, top_n=3):
    classified = [(classify_bullet(text), week_label, text) for week_label, text in all_bullets]

    picked = []
    picked_projects = set()  # 已選入的專案，避免同一個專案的舊資訊重複入選

    def try_pick(candidates):
        for c in candidates:
            proj = mentioned_project(c[2])
            if proj and proj in picked_projects:
                continue  # 同一個專案已經選過一筆，跳過這筆避免重複主題
            picked.append(c)
            if proj:
                picked_projects.add(proj)
            return True
        return False

    for category in PRIORITY_ORDER:
        candidates = [c for c in classified if c[0] == category]
        candidates.sort(key=lambda c: c[1], reverse=True)
        if candidates:
            try_pick(candidates)
        if len(picked) >= top_n:
            break

    if len(picked) < top_n:
        remaining = [c for c in classified if c not in picked]
        remaining.sort(key=lambda c: PRIORITY_ORDER.index(c[0]))
        for c in remaining:
            if len(picked) >= top_n:
                break
            proj = mentioned_project(c[2])
            if proj and proj in picked_projects:
                continue
            picked.append(c)
            if proj:
                picked_projects.add(proj)

    return picked[:top_n]


# ============================================================
# 樣板組裝
# ============================================================
def build_monthly_markdown(year, month, week_labels, agg, project_progress, next_week_rows, shipping_stats, other_items):
    ct = agg["customer_totals"]
    all_tools_used = agg["ai_tools_used"] | set(agg["ai_tool_hours"].keys())

    rate_trend = ""
    if len(agg["weekly_ai_rates"]) >= 2:
        first_rate = agg["weekly_ai_rates"][0][1]
        last_rate = agg["weekly_ai_rates"][-1][1]
        rate_trend = "AI自動回覆率由 {:.1f}% {} 至 {:.1f}%，".format(
            first_rate, "成長" if last_rate >= first_rate else "變化", last_rate
        )

    # ---------- 月度重點成果 ----------
    highlight_rows = []
    if agg["weekly_ai_rates"]:
        first_rate = agg["weekly_ai_rates"][0][1]
        last_rate = agg["weekly_ai_rates"][-1][1]
        highlight_rows.append("| AI客服自動回覆優化 | FB Meta Business AI 自動回覆率由 {:.1f}% 提升至 {:.1f}% | 進行中 | 月累計節省客服工時約 {:.1f} 小時 |".format(
            first_rate, last_rate, agg["total_saved_hours"]
        ))
    if shipping_stats["found"]:
        highlight_rows.append("| ECOCO商城商品包裝出貨 | 本月累計彙整訂單 {} 筆 | 進行中 | 支援商城訂單出貨作業 |".format(
            shipping_stats["orders"]
        ))
    for kw, display_name in PROJECT_KEYWORDS.items():
        records_all = project_progress.get(kw, [])
        if not records_all:
            continue
        for tag, records in split_by_version(records_all):
            name = display_name + tag if tag else display_name
            last = records[-1]
            category = PROJECT_CATEGORY.get(kw, classify_bullet(last["text"]))
            completion = "100%" if ("100%" in (last["pct"] or "") or "完成" in (last["pct"] or "")) else (last["pct"] or "進行中")
            _, result_text = format_column_pair(records, kw)  # 與「月底進度」保持一致，取最新內容
            highlight_rows.append("| {} | {} | {} | {} |".format(
                name, result_text, completion, VALUE_PHRASE_BY_CATEGORY.get(category, "提升作業效率")
            ))

    # ---------- AI導入效益 ----------
    ai_lines = []
    for tool, hours in agg["ai_tool_hours"].items():
        notes = strip_parens("；".join(n for n in agg["ai_tool_notes"].get(tool, []) if n))
        ai_lines.append("| {} | {} | 約 {:.1f} 小時 |".format(tool, notes or "－", hours))
    for tool in agg["ai_tools_used"]:
        if tool in agg["ai_tool_hours"]:
            continue
        ai_lines.append("| {} | 相關開發／優化工作，詳見月度重點成果 | 質化效益，未量化工時 |".format(tool))

    # ---------- 專案進度總覽 ----------
    project_lines = []
    for kw, display_name in PROJECT_KEYWORDS.items():
        records_all = project_progress.get(kw, [])
        if not records_all:
            continue
        for tag, records in split_by_version(records_all):
            name = display_name + tag if tag else display_name
            tool = common_tool(records, kw)
            if not tool and not tag and kw in PROJECT_FORCED_TOOL:
                tool = PROJECT_FORCED_TOOL[kw]
            label = "{}：{}".format(tool, name) if tool else name
            first_text, last_text = format_column_pair(records, kw)
            project_lines.append("| {} | {} | {} |".format(label, first_text, last_text))

    # ---------- 跨部門合作成果 / 風險與待協調事項 ----------
    status_map = {"達成": "已完成", "完成": "已完成", "追蹤中": "追蹤中", "進行中": "進行中"}
    cross_dept_lines = []
    risk_lines = []
    merged_coordination = merge_coordination_rows(agg["coordination_rows"])
    for m in merged_coordination:
        item, dept, due_text = m["item"], m["dept"], m["due_text"]
        status = status_map.get(m["status"], m["status"])
        if status == "已完成":
            # 跨部門合作成果只列真正已完成的項目，避免跟風險表重複列出進行中/追蹤中的事項
            cross_dept_lines.append("| {} | {} | {} |".format(item, dept, "已完成"))
        elif item != PLACEHOLDER_NO_CONTENT:
            # 只有真的有記錄具體協助內容才列進風險表；純佔位（沒有內容）的不顯示，但仍計入合計數
            risk_lines.append("| {} | {} | {} |".format(item, dept, due_text))

    # ---------- 行政支援與其他事項 ----------
    other_items_lines = ["- {}".format(quote_names(it["text"])) for it in other_items]

    # ---------- 本月三大貢獻 ----------
    top_bullets = pick_top_bullets(agg["all_bullets"], 3)
    contribution_lines = []
    for i, (category, week_label, text) in enumerate(top_bullets, 1):
        if is_shipping_bullet(text) and shipping_stats["found"]:
            final_text = format_shipping_summary(shipping_stats)
        else:
            final_text = clean_bullet(text)
        contribution_lines.append("{}. {}".format(i, final_text))

    # ---------- 下月工作規劃（取最後一週的下週工作計畫） ----------
    plan_lines = []
    for row in next_week_rows:
        goal = strip_parens(clean_snippet(row.get("預計工作", "")))
        due = row.get("預計完成日", "") or "待確認"
        plan_lines.append("| {} | {} | {} |".format(row.get("項目", "－"), goal, due))

    # ---------- 月度總結 ----------
    resolved_count = sum(1 for m in merged_coordination if status_map.get(m["status"], m["status"]) == "已完成")

    value_summary = (
        "本月客服案件量達 {total:.0f} 件，{trend}累計節省客服工時約 {hours:.1f} 小時，人力負擔持續降低。"
        "AI工具本月共使用 {tool_count} 種，持續推進系統優化與流程改善相關專案。"
        "跨部門合作事項共 {coord_count} 項，其中 {resolved_count} 項已完成，"
        "其餘 {unresolved_count} 項將持續追蹤協調。"
    ).format(
        total=ct["已處理案件"],
        trend=rate_trend,
        hours=agg["total_saved_hours"],
        tool_count=len(all_tools_used),
        coord_count=len(merged_coordination),
        resolved_count=resolved_count,
        unresolved_count=len(agg["coordination_rows"]) - resolved_count,
    )

    md = """# 【月報】{year}年{month:02d}月｜行銷客服營運分析助理

> ⚠️ **本月報由規則式程式自動彙整產出，未使用付費AI API，完全免費。**
> 數字類數據，案件數/工時/比率，為精準加總，「專案進度」「三大貢獻」等段落為關鍵字規則判斷結果，
> 建議送主管審閱前花 1-2 分鐘檢視並微調文字。資料來源週報：{week_list}

---

## 月度重點成果

| 項目 | 成果 | 完成進度 | 創造價值 |
| -- | -- | --- | ---- |
{highlight_table}

---

## 月度營運數據

### 客服統計

| 指標 | 數據 |
| -------- | -- |
| 已處理案件總數 | {total_cases:.0f} 件 |
| AI自動回覆總數 | {ai_cases:.0f} 件 |
| AI回覆率 | {ai_rate:.1f}% |
| 追蹤案件 | {tracked:.0f} 件 |
| 補點案件 | {refund:.0f} 件 |

---

### AI導入效益

| AI工具 | 導入成果 | 預估節省工時／月 |
| ---- | ---- | --------- |
{ai_table}

**本月節省總工時：約 {total_hours:.1f} 小時**
**AI處理總案件數：{ai_cases:.0f} 件**
**AI回覆率：{ai_rate:.1f}%**
**AI工具使用數量：{tool_count} 種**

---

## 專案進度總覽

| 專案 | 月初進度 | 月底進度 |
| -- | ---- | ---- |
{project_table}

---

## 跨部門合作成果

| 專案 | 協作部門 | 狀態 |
| -- | ---- | -- |
{cross_dept_table}

---

## 行政支援與其他事項

{other_items_list}

---

## 本月三大貢獻

{contributions}

---

## 下月工作規劃

| 項目 | 目標 | 預計完成日 |
| -- | -- | ----- |
{plan_table}

---

## 風險與待協調事項

| 項目 | 協作部門 | 預計完成日 |
| -- | ---- | ----- |
{risk_table}

---

## 月度總結

### 本月關鍵數據

| 指標 | 數據 |
| ------ | -- |
| 客服案件總數 | {total_cases:.0f} 件 |
| AI案件總數 | {ai_cases:.0f} 件 |
| AI占比 | {ai_rate:.1f}% |
| AI節省工時 | 約 {total_hours:.1f} 小時 |
| 完成專案數 | {resolved_count} 項，依須協調事項統計 |
| 跨部門專案數 | {coord_count} 項 |

---

### 本月價值總結

{value_summary}

---

*本月報依規則式程式自動彙整產出，免費、無API費用，產出時間：{gen_time}*
""".format(
        year=year,
        month=month,
        week_list="、".join(week_labels),
        highlight_table="\n".join(highlight_rows) if highlight_rows else "| 本月無可自動彙整的重點成果 | － | － | － |",
        total_cases=ct["已處理案件"],
        ai_cases=ct["AI回覆案件"],
        ai_rate=agg["ai_reply_rate"],
        tracked=ct["追蹤案件"],
        refund=ct["補點案件"],
        ai_table="\n".join(ai_lines) if ai_lines else "| 無資料 | － | 0 |",
        total_hours=agg["total_saved_hours"],
        tool_count=len(all_tools_used),
        project_table="\n".join(project_lines) if project_lines else "| 無符合關鍵字的專案紀錄 | － | － |",
        cross_dept_table="\n".join(cross_dept_lines) if cross_dept_lines else "| 本月無已完成之跨部門合作項目 | － | － |",
        other_items_list="\n".join(other_items_lines) if other_items_lines else "（本月「其他」欄位無額外事項）",
        contributions="\n".join(contribution_lines) if contribution_lines else "（本月無可分類的三大成果資料）",
        plan_table="\n".join(plan_lines) if plan_lines else "| 請參考本月最後一週週報之下週工作計畫 | － | 待確認 |",
        risk_table="\n".join(risk_lines) if risk_lines else "| 本月無待協調事項 | － | － |",
        resolved_count=resolved_count,
        coord_count=len(merged_coordination),
        value_summary=value_summary,
        gen_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    return md


# ============================================================
# 主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="忽略「是否為最後上班日」的判斷，直接執行")
    parser.add_argument("--month", type=str, default=None, help="指定月份 YYYY-MM，預設為今天所在月份")
    args = parser.parse_args()

    today = date.today()
    if args.month:
        year, month = map(int, args.month.split("-"))
    else:
        year, month = today.year, today.month

    gov_calendar = load_taiwan_calendar(today.year)

    if not args.force:
        last_workday = get_last_workday_of_month(today.year, today.month, gov_calendar)
        if last_workday != today:
            log("今天（{}）不是本月最後上班日（本月最後上班日為 {}），跳過執行。".format(
                today.isoformat(), last_workday.isoformat() if last_workday else "無法判斷"
            ))
            sys.exit(2)  # exit code 2 = 今天跳過（非最後上班日），非錯誤
        log("今天（{}）確認為本月最後上班日，開始產出月報。".format(today.isoformat()))
        year, month = today.year, today.month

    weekly_records = collect_weekly_reports_for_month(year, month)
    if not weekly_records:
        log("錯誤：在 {} 找不到 {}-{:02d} 的任何週報檔案。".format(REPORTS_DIR, year, month))
        sys.exit(1)

    week_files = [fn for _, fn, _ in weekly_records]
    log("找到 {} 份週報：{}".format(len(week_files), ", ".join(week_files)))

    agg = aggregate(weekly_records)
    project_progress = collect_project_progress(weekly_records)
    shipping_stats = aggregate_shipping_stats(weekly_records)
    other_items = collect_other_items(weekly_records)

    # 下月工作規劃：取本月最後一份週報的「下週工作計畫」表格
    last_text = weekly_records[-1][2]
    next_week_rows = parse_pipe_table(section_after(last_text, "## 下週工作計畫"))

    week_labels = [fn.replace("weekly_", "").replace(".md", "") for fn in week_files]
    monthly_content = build_monthly_markdown(year, month, week_labels, agg, project_progress, next_week_rows, shipping_stats, other_items)

    os.makedirs(MONTHLY_REPORTS_DIR, exist_ok=True)
    output_path = os.path.join(MONTHLY_REPORTS_DIR, "monthly_{}-M{:02d}.md".format(year, month))
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(monthly_content)

    log("月報已產出：{}".format(output_path))


if __name__ == "__main__":
    main()
