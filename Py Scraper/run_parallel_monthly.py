import subprocess
import sys
import os
import time
import threading
import collections
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

os.system('') # Enable ANSI escape codes in Windows Console

# Enable Virtual Terminal Processing & Clean Console Setup on Windows
if sys.platform == 'win32':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        h_out = kernel32.GetStdHandle(-11) # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(h_out, ctypes.byref(mode))
        mode.value |= 0x0004 # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        kernel32.SetConsoleMode(h_out, mode)
        kernel32.SetConsoleTitleW("All Asset NPA Intelligence — Monthly Pipeline Scraper")
    except Exception:
        pass

# ANSI Colors for Professional CLI
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_DIM = "\033[2m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_CYAN = "\033[96m"
COLOR_GRAY = "\033[90m"
COLOR_WHITE = "\033[97m"

SCRAPERS = [
    # 1. กรมบังคับคดี (LED)
    {"name": "LED", "script": "scrape_led_monthly.py", "est_time": "~3.5-4 ชม.", "est_sec": 13800, "delay": "15-16s", "est_pages": 78, "unit": "จว.", "est_items": 105004},
    {"name": "LandsMaps", "script": "enrich_led_landsmaps.py", "est_time": "~23-25 ชม.", "est_sec": 86400, "delay": "15-16s", "est_pages": 18500, "unit": "โฉนด", "est_items": 18500, "is_sub": True},
    {"name": "LED_Legal", "script": "scrape_led_legal.py", "est_time": "1-Thread", "est_sec": 4800, "delay": "15-16s", "est_pages": 134, "unit": "หน่วย", "est_items": 15000, "is_sub": True},
    
    # 2. บริษัทบริหารสินทรัพย์ (AMC)
    {"name": "SAM", "script": "scrape_sam_monthly.py", "est_time": "~1-1.5 ชม.", "est_sec": 4500, "delay": "15-16s", "est_pages": 246, "unit": "หน้า", "est_items": 4967},
    {"name": "BAM", "script": "scrape_bam_monthly.py", "est_time": "~3.5-4 ชม.", "est_sec": 14000, "delay": "15-16s", "est_pages": 745, "unit": "หน้า", "est_items": 17985},
    {"name": "Chayo555", "script": "scrape_chayo555_monthly.py", "est_time": "~1.2-1.5 ชม.", "est_sec": 5000, "delay": "15-16s", "est_pages": 312, "unit": "รายการ", "est_items": 320},
    
    # 3. สถาบันการเงิน / ธนาคาร (Financial Institutions)
    {"name": "GHB", "script": "scrape_ghb_monthly.py", "est_time": "~7-7.5 ชม.", "est_sec": 26000, "delay": "15-16s", "est_pages": 1564, "unit": "หน้า", "est_items": 31021},
    {"name": "KBANK", "script": "scrape_kbank_monthly.py", "est_time": "~3-3.5 ชม.", "est_sec": 12000, "delay": "15-16s", "est_pages": 739, "unit": "หน้า", "est_items": 14774},
    {"name": "KTB", "script": "scrape_ktb_monthly.py", "est_time": "~30-35 นาที", "est_sec": 2000, "delay": "15-16s", "est_pages": 116, "unit": "หน้า", "est_items": 2311},
    {"name": "SCB", "script": "scrape_scb_monthly.py", "est_time": "~50-55 นาที", "est_sec": 3300, "delay": "15-16s", "est_pages": 206, "unit": "หน้า", "est_items": 4106},
    {"name": "GSB", "script": "scrape_gsb_monthly.py", "est_time": "~1.5-2 ชม.", "est_sec": 6000, "delay": "15-16s", "est_pages": 4456, "unit": "รายการ", "est_items": 4456},
    
    # 4. เว็บไซต์อสังหาริมทรัพย์ (Portals & Websites)
    {"name": "DDproperty", "script": "scrape_ddproperty_monthly.py", "est_time": "~24-26 ชม.", "est_sec": 92000, "delay": "15-16s", "est_pages": 5715, "unit": "หน้า", "est_items": 107993},
    {"name": "Livinginsider", "script": "scrape_livinginsider_monthly.py", "est_time": "~13-14 ชม.", "est_sec": 50000, "delay": "15-16s", "est_pages": 2993, "unit": "หน้า", "est_items": 115887},
    {"name": "NaYoo", "script": "scrape_nayoo_monthly.py", "est_time": "~1.2-1.5 ชม.", "est_sec": 4800, "delay": "15-16s", "est_pages": 298, "unit": "หน้า", "est_items": 8136},
    {"name": "ZmyHome", "script": "scrape_zmyhome_monthly.py", "est_time": "~3-3.5 ชม.", "est_sec": 12000, "delay": "15-16s", "est_pages": 77, "unit": "จว.", "est_items": 35000},
    {"name": "Baania", "script": "scrape_baania_monthly.py", "est_time": "~2-2.5 ชม.", "est_sec": 8200, "delay": "15-16s", "est_pages": 500, "unit": "หน้า", "est_items": 9984}
]

company_state = {
    s["name"]: {
        "status": "WAITING", # WAITING, RUNNING, DONE, ERROR
        "pct": 0,
        "http": "",
        "cur_page": 0,
        "tot_page": s["est_pages"],
        "unit": s["unit"],
        "accum": 0,
        "tot_items": s.get("est_items", 0),
        "eta_str": "",
        "cd_end_time": 0.0,
        "cd_total_sec": 0,
        "cd_reason": ""
    }
    for s in SCRAPERS
}

status_dict = {
    s["name"]: f"[{s['name']:<14s}] [░░░░░░░░░░░░░░░░░░░░]   0% | [ WAIT ] รอคิวเริ่มทำงาน (ประมาณ {s['est_time']} | หน่วง {s['delay']})" 
    for s in SCRAPERS
}
company_health = {s["name"]: "[ WAIT ] รอคิวเริ่มทำงาน..." for s in SCRAPERS}
company_http_code = {s["name"]: "" for s in SCRAPERS}
company_issues = {s["name"]: "[ PASS ] ครบถ้วน 100%" for s in SCRAPERS}
recent_logs = collections.deque(maxlen=30)
scraper_time_summary = {}

lock = threading.Lock()
running = True

from logger_util import log_txn, log_start, log_finish, format_duration, load_scraper_state
import re

# Preload any existing checkpoint data from state JSON files
_preloaded_state_map = {}
try:
    from datetime import timedelta
    _now_dt = datetime.now()
    _m_now = _now_dt.strftime("%Y_%m")
    _m_prev = (_now_dt.replace(day=1) - timedelta(days=1)).strftime("%Y_%m")
    for _s in SCRAPERS:
        _s_name = _s["name"]
        _state_month = _m_prev if _s_name == "LED_Legal" else _m_now
        _st_json = load_scraper_state(_s_name, _state_month)
        if _st_json and isinstance(_st_json, dict):
            _preloaded_state_map[_s_name] = _st_json
            if _st_json.get("total_records"):
                company_state[_s_name]["accum"] = _st_json["total_records"]
except Exception:
    pass

ACTIVE_SCRAPER_NAMES = None

COMPANY_GROUP_ALIASES = {
    "amc": ["SAM", "BAM", "Chayo555"],
    "banks": ["GHB", "KBANK", "KTB", "SCB", "GSB"],
    "bank": ["GHB", "KBANK", "KTB", "SCB", "GSB"],
    "portals": ["DDproperty", "Livinginsider", "NaYoo", "ZmyHome", "Baania"],
    "portal": ["DDproperty", "Livinginsider", "NaYoo", "ZmyHome", "Baania"],
    "web": ["DDproperty", "Livinginsider", "NaYoo", "ZmyHome", "Baania"],
}

def get_active_scrapers():
    if ACTIVE_SCRAPER_NAMES is None:
        return list(SCRAPERS)
    return [s for s in SCRAPERS if s["name"] in ACTIVE_SCRAPER_NAMES]

def get_active_main_scrapers():
    return [s for s in get_active_scrapers() if not s.get("is_sub")]

def resolve_selected_main_scrapers(raw_expr):
    """
    Parse company selection expression (empty/all, numbers 1-14, ranges 4-8,
    company names case-insensitive, group aliases amc/banks/portals, or -exclusions).
    Returns ordered list of main scraper names from SCRAPERS (excluding is_sub).
    """
    main_list = [s["name"] for s in SCRAPERS if not s.get("is_sub")]
    name_lookup = {n.lower(): n for n in main_list}
    text = str(raw_expr or "").strip()
    if not text or text.lower() in {"all", "*"}:
        return list(main_list)

    tokens = [t.strip() for t in re.split(r'[,\s]+', text) if t.strip()]
    if not tokens:
        return list(main_list)

    def _expand_token(tok):
        tl = tok.lower()
        if tl in {"all", "*"}:
            return list(main_list)
        if tl in COMPANY_GROUP_ALIASES:
            return list(COMPANY_GROUP_ALIASES[tl])
        m_rng = re.match(r'^(\d+)\s*-\s*(\d+)$', tok)
        if m_rng:
            a, b = int(m_rng.group(1)), int(m_rng.group(2))
            if a < 1 or b > len(main_list) or a > b:
                raise ValueError(f"ช่วงลำดับไม่ถูกต้อง: '{tok}' (ต้องอยู่ระหว่าง 1-{len(main_list)})")
            return [main_list[i - 1] for i in range(a, b + 1)]
        if tok.isdigit():
            idx = int(tok)
            if 1 <= idx <= len(main_list):
                return [main_list[idx - 1]]
            raise ValueError(f"ไม่พบลำดับที่ {idx} (ต้องอยู่ระหว่าง 1-{len(main_list)})")
        if tl in name_lookup:
            return [name_lookup[tl]]
        raise ValueError(f"ไม่รู้จักชื่อหรือรหัสบริษัท: '{tok}'")

    has_positive = any(not (t.startswith("-") or t.startswith("!")) for t in tokens)
    selected = set() if has_positive else set(main_list)

    for tok in tokens:
        if tok.startswith("-") or tok.startswith("!"):
            sub_tok = tok[1:].strip()
            if not sub_tok:
                raise ValueError(f"รูปแบบการตัดออกไม่ถูกต้อง: '{tok}'")
            selected.difference_update(_expand_token(sub_tok))
        else:
            selected.update(_expand_token(tok))

    ordered = [n for n in main_list if n in selected]
    if not ordered:
        raise ValueError("ไม่มีบริษัทที่ถูกเลือกเหลืออยู่ กรุณาเลือกอย่างน้อย 1 บริษัท")
    return ordered

def prompt_select_companies():
    """Display numbered menu of the 14 main platforms and return selected main scraper names."""
    main_scrapers = [s for s in SCRAPERS if not s.get("is_sub")]
    print("\n" + "┌" + "─" * 82 + "┐")
    print(f"│  {COLOR_CYAN}{COLOR_BOLD}เลือกบริษัท / แพลตฟอร์มที่ต้องการรัน (14 ค่ายหลัก){COLOR_RESET}" + " " * 31 + "│")
    print("├" + "─" * 82 + "┤")
    for idx, s in enumerate(main_scrapers, 1):
        nm = s["name"]
        st = _preloaded_state_map.get(nm, {})
        accum = st.get("total_records", 0) or 0
        status = st.get("status", "")
        if status == "COMPLETED" and accum > 0:
            stat_txt = f"{COLOR_GREEN}[ครบ 100%: {accum:,}]{COLOR_RESET}"
        elif accum > 0:
            stat_txt = f"{COLOR_YELLOW}[ค้างเดิม: {accum:,}]{COLOR_RESET}"
        else:
            stat_txt = f"{COLOR_GRAY}[ยังไม่ดึง]{COLOR_RESET}"
        note = " (พ่วง LandsMaps + LED_Legal)" if nm == "LED" else ""
        row_str = f"  [{idx:02d}] {nm:<14s} ({s['est_time']:<11s}) {stat_txt}{note}"
        print(f"│{pad_display(row_str, 82, 'left')}│")
    print("├" + "─" * 82 + "┤")
    print(f"│{pad_display('  วิธีเลือก: กด Enter = รันครบทั้ง 14 ค่าย  │  พิมพ์เลข/ชื่อ เช่น 1,2,4 หรือ 4-8 หรือ SAM,BAM', 82, 'left')}│")
    print(f"│{pad_display('  กลุ่มลัด: amc (SAM,BAM,Chayo555) │ banks (GHB..GSB) │ portals (DD..Baania) │ all,-Livinginsider', 82, 'left')}│")
    print("└" + "─" * 82 + "┘")

    while True:
        try:
            raw = input("เลือกบริษัทที่ต้องการรัน [Enter = ทั้งหมด 14 ค่าย]: ").strip()
        except EOFError:
            return [s["name"] for s in main_scrapers]
        try:
            chosen = resolve_selected_main_scrapers(raw)
            print(f">> {COLOR_GREEN}เลือกแล้ว {len(chosen)}/{len(main_scrapers)} ค่าย:{COLOR_RESET} {', '.join(chosen)}")
            if "LED" in chosen:
                print(f"   {COLOR_CYAN}(พ่วง LandsMaps และ LED_Legal ต่อท้ายหลัง LED เสร็จตามปกติ){COLOR_RESET}")
            return chosen
        except ValueError as ve:
            print(f"{COLOR_RED}[!] {ve}{COLOR_RESET}")

def add_log(msg, comp_name="RUNNER", level="INFO"):
    now = datetime.now()
    full_timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    
    # Extract company name if present in brackets e.g. [BAM]
    c_name = comp_name
    clean_msg = msg
    if msg.startswith("[") and "]" in msg:
        extracted = msg[1:msg.find("]")].strip()
        if any(s["name"] == extracted for s in SCRAPERS):
            c_name = extracted
            clean_msg = msg[msg.find("]")+1:].strip()
            
    clean_level = level.upper().strip()
    display_msg = f"[{full_timestamp}] [{clean_level:<8s}] [{c_name:<14s}] {clean_msg}"
    recent_logs.appendleft(display_msg)

def calculate_overall_eta():
    max_rem_sec = 0
    all_done = True
    for s in get_active_main_scrapers():
        name = s["name"]
        st_data = company_state.get(name, {})
        sec = s.get("est_sec", 600)
        
        if st_data.get("status") in ("DONE", "PARTIAL") or st_data.get("pct", 0) >= 100:
            continue
        all_done = False
        
        cur_rem = 0
        if st_data.get("status") == "RUNNING":
            eta_s = st_data.get("eta_str", "")
            m_h = re.search(r'(\d+)\s*ชม', eta_s)
            m_m = re.search(r'(\d+)\s*น', eta_s)
            m_s = re.search(r'(\d+)\s*ว', eta_s)
            if m_h or m_m or m_s:
                h_v = int(m_h.group(1)) if m_h else 0
                m_v = int(m_m.group(1)) if m_m else 0
                s_v = int(m_s.group(1)) if m_s else 0
                cur_rem = h_v * 3600 + m_v * 60 + s_v
            else:
                pct = st_data.get("pct", 0)
                rem_pct = max(0, 100 - pct)
                cur_rem = int(sec * (rem_pct / 100.0))
            # Include countdown sleep time if actively paused
            cd_end = st_data.get("cd_end_time", 0.0)
            rem_cd = int(cd_end - time.time()) if cd_end > time.time() else 0
            if rem_cd > 0:
                cur_rem += rem_cd
        else:
            cur_rem = sec
            
        if cur_rem > max_rem_sec:
            max_rem_sec = cur_rem
            
    if all_done or max_rem_sec <= 0:
        return "เสร็จสมบูรณ์ 100% ครบทุกบริษัท [SUCCESS]"
        
    hrs = max_rem_sec // 3600
    mins = (max_rem_sec % 3600) // 60
    finish_ts = datetime.now().timestamp() + max_rem_sec
    finish_clock = datetime.fromtimestamp(finish_ts).strftime("%H:%M")
    
    if hrs > 0:
        return f"~{hrs} ชม. {mins:02d} นาที (~{finish_clock} น.)"
    else:
        return f"~{mins} นาที (~{finish_clock} น.)"

SPINNER_FRAMES = ["-", "\\", "|", "/"]
spinner_idx = 0
current_active_company = None

import unicodedata

ANSI_REGEX = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')

def strip_ansi(s):
    return ANSI_REGEX.sub('', s)

def get_char_width(ch):
    if ch in '\ufe0f\ufe0e' or unicodedata.combining(ch) or unicodedata.category(ch) in ('Mn', 'Me', 'Cf'):
        return 0
    cp = ord(ch)
    # Explicit Thai nonspacing marks check (vowels above/below & tone marks: 0x0E31, 0x0E34..0x0E3A, 0x0E47..0x0E4E)
    if cp == 0x0E31 or (0x0E34 <= cp <= 0x0E3A) or (0x0E47 <= cp <= 0x0E4E):
        return 0
    ew = unicodedata.east_asian_width(ch)
    if ew in ('F', 'W'):
        return 2
    # Emojis and full-width symbols
    if (0x1F300 <= cp <= 0x1FAFF) or (0x2600 <= cp <= 0x27BF) or cp in (0x231B, 0x23F3, 0x23F1, 0x25B6, 0x25CF, 0x25CB):
        return 2
    return 1

def str_display_width(s):
    clean = strip_ansi(s)
    return sum(get_char_width(ch) for ch in clean)

def pad_display(s, target_width, align='left'):
    cur = str_display_width(s)
    spaces = max(0, target_width - cur)
    if align == 'right':
        return ' ' * spaces + s
    elif align == 'center':
        left = spaces // 2
        right = spaces - left
        return ' ' * left + s + ' ' * right
    return s + ' ' * spaces

def truncate_display(s, max_width):
    clean = strip_ansi(s)
    if str_display_width(clean) <= max_width:
        return s
    res = []
    w = 0
    for ch in clean:
        cw = get_char_width(ch)
        if w + cw + 3 > max_width:
            break
        res.append(ch)
        w += cw
    return "".join(res) + "..."

# Precision Box Constants (Exact 135 Characters Width)
TARGET_W = 135
INNER_W = TARGET_W - 2 # 133

TOP_CARD_TOP = "┌" + "─" * INNER_W + "┐"
TOP_CARD_BOT = "└" + "─" * INNER_W + "┘"

BOX_TOP = "┌────┬─────────────────┬────────────────────────┬───────┬──────────┬──────────────────────┬────────────────────┬──────────────────────┐"
BOX_HDR = "│ No │ Platform / AMC  │      Progress Bar      │   %   │ HTTP Code│  Live Items / Pages  │       Status       │      Est. / ETA      │"
BOX_MID = "├────┼─────────────────┼────────────────────────┼───────┼──────────┼──────────────────────┼────────────────────┼──────────────────────┤"
BOX_BOT = "└────┴─────────────────┴────────────────────────┴───────┴──────────┴──────────────────────┴────────────────────┴──────────────────────┘"

LOG_CARD_TOP = "┌" + "─" * INNER_W + "┐"
LOG_CARD_HDR = f"│{pad_display('  RECENT PIPELINE ACTIVITY LOGS (LAST 10 EVENTS)', INNER_W, 'left')}│"
LOG_CARD_MID = "├" + "─" * INNER_W + "┤"
LOG_CARD_BOT = "└" + "─" * INNER_W + "┘"

def format_compact_eta(s):
    if not s:
        return ""
    s = s.strip()
    if s.startswith("~~"):
        s = "~" + s[2:].strip()

    # Static estimates or simple statuses (e.g. ~3.5-4 ชม., พัก 01:45, เสร็จสิ้น, 2.5 นาที)
    if "เหลือ" not in s and "(" not in s:
        return s
    
    # 1. Extract clock if present e.g. "(10:15:10 น.)" -> "10:15"
    m_clock = re.search(r'\((\d{1,2}:\d{2})(?::\d{2})?\s*น?\.\)', s)
    clock = m_clock.group(1) if m_clock else ""
    
    # Remove the clock parenthesis from body
    body = re.sub(r'\(.*?\)', '', s).strip()

    # 2. Hours & Mins: e.g. "เหลือ ~3ชม.10น."
    m_hrs = re.search(r'(\d+)\s*ชม\.?(?:\s*(\d+)\s*น\.?)?', body)
    if m_hrs and ("เหลือ" in body or "ชม" in body):
        h = m_hrs.group(1)
        m = m_hrs.group(2)
        if m:
            return f"~{h}ชม.{m}น."
        elif clock:
            return f"~{h}ชม. ({clock})"
        else:
            return f"~{h} ชม."

    # 3. Mins & Secs: e.g. "เหลืออีก ~7น. 46ว."
    m_mins = re.search(r'(\d+)\s*น\.?(?:\s*(\d+)\s*ว\.?)?', body)
    if m_mins:
        m = m_mins.group(1)
        s_val = m_mins.group(2)
        if s_val:
            return f"~{m}น.{s_val}ว."
        elif clock:
            return f"~{m}น. ({clock})"
        else:
            return f"~{m} นาที"

    # 4. Secs only: e.g. "เหลืออีก ~45ว."
    m_sec = re.search(r'(\d+)\s*ว\.', body)
    if m_sec:
        s_val = m_sec.group(1)
        if clock:
            return f"~{s_val}ว. ({clock})"
        else:
            return f"~{s_val} วิ"

    return s

def render_dashboard_row(idx, s, data, spinner_char, is_active):
    name = s["name"]
    state = data["status"]
    pct = 100 if state == "DONE" else max(0, min(100, data["pct"]))
    tot_p = data["tot_page"] or s.get("est_pages", 100)
    cur_p = data["cur_page"]
    unit = data.get("unit", "หน้า")
    accum = data["accum"]
    h_code = data["http"] or company_http_code.get(name, "") or ("200 OK" if state == "DONE" else "")
    if h_code.startswith("HTTP "):
        h_code = h_code[5:].strip()
    
    cd_end = data.get("cd_end_time", 0.0)
    rem_cd = int(cd_end - time.time()) if cd_end > time.time() else 0
    is_counting_down = (rem_cd > 0)
    tot_it = data.get("est_items", 0) or data.get("tot_items", 0)

    is_sub = s.get("is_sub", False)

    # 1. Column No (Width 2)
    if is_sub:
        col_no = pad_display("", 2, 'center')
    else:
        col_no = pad_display(f"{idx:02d}" if isinstance(idx, int) else str(idx), 2, 'center')

    # 2. Column Name (Width 15)
    display_name = f" └ {name}" if is_sub else name
    col_name = pad_display(display_name, 15, 'left')

    # 3. Column Progress Bar & Percentage (Bar Width 20 -> Box Width 22)
    filled = int(20 * pct / 100)
    bar_chars = "█" * filled + "░" * (20 - filled)
    
    # 4. Column HTTP (Width 8)
    if "403" in h_code or "WAF" in h_code:
        http_colored = f"{COLOR_YELLOW}403 WAF{COLOR_RESET}"
    elif h_code.startswith("200") or h_code == "200 OK":
        http_colored = f"{COLOR_GREEN}200 OK{COLOR_RESET}"
    elif "ERR" in h_code or h_code.startswith("5") or h_code.startswith("4"):
        http_colored = f"{COLOR_RED}{h_code[:8]}{COLOR_RESET}"
    elif h_code:
        http_colored = f"{COLOR_CYAN}{h_code[:8]}{COLOR_RESET}"
    elif state == "DONE":
        http_colored = f"{COLOR_GREEN}200 OK{COLOR_RESET}"
    elif state == "WAITING":
        http_colored = f"{COLOR_GRAY}Pending{COLOR_RESET}"
    else:
        http_colored = f"{COLOR_GRAY}-{COLOR_RESET}"
    col_http = pad_display(http_colored, 8, 'center')

    # 5. Column Items / Pages (Width 16)
    if name == "LED":
        if state == "DONE":
            items_text = f"{accum:,d} (77 จว.)"
        elif state == "RUNNING" or is_active:
            items_text = f"{cur_p}/77 จว."
        else:
            items_text = "77 จังหวัด"
    elif name == "LandsMaps":
        if state == "DONE":
            items_text = f"{accum:,d} โฉนด"
        elif state == "RUNNING" or is_active:
            if tot_p > 0:
                items_text = f"{cur_p:,d}/{tot_p:,d}"
            elif accum > 0:
                items_text = f"{accum:,d} โฉนด"
            else:
                items_text = "1-Thread ⚙"
        else:
            items_text = "รอ LED เสร็จ"
    else:
        if state == "DONE":
            items_text = f"{accum:,d} รายการ"
        elif state == "RUNNING" or is_active:
            if accum > 0 and tot_it > 0:
                items_text = f"{accum:,d}/{tot_it:,d}"
            elif accum > 0:
                items_text = f"{accum:,d} รายการ"
            else:
                items_text = f"{cur_p:,d}/{tot_p:,d} {unit}"
        else:
            if tot_it > 0:
                items_text = f"เป้า {tot_it:,d}"
            else:
                items_text = f"~{tot_p:,d} {unit}"
    col_items = truncate_display(items_text, 20)
    col_items = pad_display(col_items, 20, 'right')

    # 6. Column Status & Est Time (Status 14, Time 16)
    if state == "DONE":
        bar_colored = f"{COLOR_GREEN}[{bar_chars}]{COLOR_RESET}"
        col_pct = pad_display(f"{COLOR_GREEN}100%{COLOR_RESET}", 5, 'right')
        status_colored = f"{COLOR_GREEN}{COLOR_BOLD}[PASS] DONE{COLOR_RESET}"
        dur_done = scraper_time_summary.get(name, {}).get("duration", "")
        time_text = dur_done if dur_done else s.get("est_time", "เสร็จสิ้น")
    elif ("403" in h_code or "WAF" in h_code) and (data.get("is_warn") or is_counting_down):
        bar_colored = f"{COLOR_YELLOW}[{bar_chars}]{COLOR_RESET}"
        col_pct = pad_display(f"{COLOR_YELLOW}{pct:3d}%{COLOR_RESET}", 5, 'right')
        status_colored = f"{COLOR_YELLOW}{COLOR_BOLD}[WARN] 403 WAF{COLOR_RESET}"
        if is_counting_down:
            if rem_cd >= 60:
                m_val = rem_cd // 60
                s_val = rem_cd % 60
                cd_s = f"{m_val:02d}:{s_val:02d}"
            else:
                cd_s = f"{rem_cd:02d}s"
            time_text = f"พัก {cd_s}"
        else:
            time_text = "พักรอปลดแบน"
    elif is_counting_down:
        bar_colored = f"{COLOR_YELLOW}[{bar_chars}]{COLOR_RESET}"
        col_pct = pad_display(f"{COLOR_YELLOW}{pct:3d}%{COLOR_RESET}", 5, 'right')
        cd_reason = data.get("cd_reason", "")
        if rem_cd >= 3600:
            h_val = rem_cd // 3600
            m_val = (rem_cd % 3600) // 60
            cd_s = f"{h_val}ชม.{m_val}น."
        elif rem_cd >= 60:
            m_val = rem_cd // 60
            s_val = rem_cd % 60
            cd_s = f"{m_val:02d}:{s_val:02d}"
        else:
            cd_s = f"{rem_cd:02d}s"
        status_colored = f"{COLOR_YELLOW}{COLOR_BOLD}[PAUSE] {cd_s}{COLOR_RESET}"
        time_text = f"พัก {cd_s}"
    elif state == "RUNNING" or is_active:
        bar_colored = f"{COLOR_CYAN}[{bar_chars}]{COLOR_RESET}"
        col_pct = pad_display(f"{COLOR_CYAN}{pct:3d}%{COLOR_RESET}", 5, 'right')
        if name == "LandsMaps":
            status_colored = f"{COLOR_CYAN}{COLOR_BOLD}[RUN] 1Thread{COLOR_RESET}{COLOR_WHITE}{spinner_char}{COLOR_RESET}"
        else:
            status_colored = f"{COLOR_CYAN}{COLOR_BOLD}[RUN] RUNNING{COLOR_RESET}{COLOR_WHITE}{spinner_char}{COLOR_RESET}"
        eta_val = data.get("eta_str", "")
        time_text = eta_val if eta_val else f"~{s['est_time']}"
    elif state == "PARTIAL":
        bar_colored = f"{COLOR_YELLOW}[{bar_chars}]{COLOR_RESET}"
        col_pct = pad_display(f"{COLOR_YELLOW}{pct:3d}%{COLOR_RESET}", 5, 'right')
        status_colored = f"{COLOR_YELLOW}{COLOR_BOLD}[WARN] PARTIAL{COLOR_RESET}"
        dur_done = scraper_time_summary.get(name, {}).get("duration", "")
        time_text = dur_done if dur_done else "ไม่ครบบางส่วน"
    elif state == "ERROR":
        bar_colored = f"{COLOR_RED}[{bar_chars}]{COLOR_RESET}"
        col_pct = pad_display(f"{COLOR_RED}  0%{COLOR_RESET}", 5, 'right')
        status_colored = f"{COLOR_RED}{COLOR_BOLD}[FAIL] ERROR{COLOR_RESET}"
        time_text = "ล้มเหลว"
    else: # WAITING
        bar_colored = f"{COLOR_GRAY}[{bar_chars}]{COLOR_RESET}"
        col_pct = pad_display(f"{COLOR_GRAY}  0%{COLOR_RESET}", 5, 'right')
        if is_sub:
            status_colored = f"{COLOR_GRAY}[WAIT] รอ LED{COLOR_RESET}"
            time_text = "รอเริ่มหลัง LED"
        else:
            status_colored = f"{COLOR_GRAY}[WAIT] QUEUED{COLOR_RESET}"
            time_text = f"~{s['est_time']}"

    col_bar = pad_display(bar_colored, 22, 'center')
    col_stat = pad_display(status_colored, 18, 'left')
    time_text = format_compact_eta(time_text)
    time_text = truncate_display(time_text, 20)
    col_time = pad_display(time_text, 20, 'center')

    return f"│ {col_no} │ {col_name} │ {col_bar} │ {col_pct} │ {col_http} │ {col_items} │ {col_stat} │ {col_time} │"

def draw_fixed_dashboard():
    global spinner_idx
    with lock:
        spinner_idx = (spinner_idx + 1) % len(SPINNER_FRAMES)
        spinner_char = SPINNER_FRAMES[spinner_idx]
        overall_eta_str = calculate_overall_eta()
        
        # 1. Top Card Information (filter out is_sub so selected platform stats remain accurate)
        active_scrapers = get_active_scrapers()
        main_scrapers = [s for s in active_scrapers if not s.get("is_sub")]
        total_main = len(main_scrapers)
        running_names = [s["name"] for s in main_scrapers if company_state[s["name"]]["status"] == "RUNNING"]
        done_count = sum(1 for s in main_scrapers if company_state[s["name"]]["status"] in ("DONE", "PARTIAL"))
        err_count = sum(1 for s in main_scrapers if company_state[s["name"]]["status"] == "ERROR")
        running_count = len(running_names)
        tot_scraped = sum(company_state[s["name"]]["accum"] for s in main_scrapers)
        
        # Countdown status in header if any scraper is in countdown
        active_cd_header = ""
        pausing = [s["name"] for s in active_scrapers if company_state[s["name"]].get("cd_end_time", 0.0) > time.time()]
        if pausing:
            active_cd_header = f"  │  {COLOR_YELLOW}[PAUSE: {', '.join(pausing)}]{COLOR_RESET}"

        # Time Window Status & Delay Info
        try:
            from time_window_util import is_within_active_window, format_window_str, is_window_disabled, get_scraper_delay_range
            d_min, d_max = get_scraper_delay_range()
            delay_str = f"{int(d_min)}-{int(d_max)}s/req" if d_min != d_max else f"{int(d_min)}s/req"
            delay_tag = f" {COLOR_YELLOW}[Delay: {delay_str}]{COLOR_RESET}"
            if is_window_disabled():
                win_tag = f" {COLOR_CYAN}[NOW-MODE 24/7]{COLOR_RESET}"
            elif is_within_active_window():
                win_tag = f" {COLOR_GREEN}[ACTIVE {format_window_str()}]{COLOR_RESET}"
            else:
                win_tag = f" {COLOR_YELLOW}[PAUSED {format_window_str()}]{COLOR_RESET}"
        except Exception:
            win_tag = ""
            delay_tag = f" {COLOR_YELLOW}[Delay: 15-16s/req]{COLOR_RESET}"

        title_line = f"  {COLOR_CYAN}{COLOR_BOLD}ALL ASSET NPA DATA INTELLIGENCE — PARALLEL PIPELINE ({total_main} PLATFORMS){COLOR_RESET}{win_tag}{delay_tag}"
        lm_running = (company_state.get("LandsMaps", {}).get("status") == "RUNNING" or company_state.get("LED_Legal", {}).get("status") == "RUNNING")
        lm_tag = f"  │  {COLOR_CYAN}[LandsMaps 1-Thread Active]{COLOR_RESET}" if lm_running else ""
        if running_count > 0 or lm_running:
            sub_title = f"  Status: {COLOR_CYAN}{COLOR_BOLD}Running {running_count}/{total_main} Parallel{COLOR_RESET}{lm_tag}  │  Done: {COLOR_GREEN}{done_count}/{total_main}{COLOR_RESET}  │  ETA: {overall_eta_str}  │  Scraped: {tot_scraped:,d} items{active_cd_header}"
        else:
            sub_title = f"  Status: {COLOR_GREEN}{COLOR_BOLD}All {total_main} Platforms Finished{COLOR_RESET}  │  Scraped Total: {tot_scraped:,d} items  │  Done: {done_count}/{total_main} (Fail: {err_count})"

        # Build complete frame in memory buffer
        buf = ["\033[?25l\033[H"]
        
        # Top Card
        buf.append(f"\033[K{TOP_CARD_TOP}\n")
        buf.append(f"\033[K│{pad_display(title_line, INNER_W, 'left')}│\n")
        buf.append(f"\033[K│{pad_display(sub_title, INNER_W, 'left')}│\n")
        buf.append(f"\033[K{TOP_CARD_BOT}\n")
        
        # Main Table
        buf.append(f"\033[K{BOX_TOP}\n")
        buf.append(f"\033[K{BOX_HDR}\n")
        buf.append(f"\033[K{BOX_MID}\n")
        display_idx = 1
        for s in active_scrapers:
            name = s["name"]
            st_data = company_state[name]
            is_active = (st_data["status"] == "RUNNING")
            if s.get("is_sub"):
                row_no = ""
            else:
                row_no = display_idx
                display_idx += 1
            line_str = render_dashboard_row(row_no, s, st_data, spinner_char, is_active)
            buf.append(f"\033[K{line_str}\n")
        buf.append(f"\033[K{BOX_BOT}\n")
        
        # Logs Card (10 lines)
        buf.append(f"\033[K{LOG_CARD_TOP}\n")
        buf.append(f"\033[K{LOG_CARD_HDR}\n")
        buf.append(f"\033[K{LOG_CARD_MID}\n")
        logs_list = list(recent_logs)
        for i in range(10):
            if i < len(logs_list):
                log_txt = truncate_display(logs_list[i], INNER_W - 2)
                buf.append(f"\033[K│ {pad_display(log_txt, INNER_W - 2, 'left')} │\n")
            else:
                buf.append(f"\033[K│ {pad_display('-', INNER_W - 2, 'left')} │\n")
        buf.append(f"\033[K{LOG_CARD_BOT}\n")
        buf.append(f"\033[K  {COLOR_GRAY}Tip: กด Ctrl+C เพื่อหยุดอย่างปลอดภัย  │  บันทึก Log ละเอียดที่: scraping.log{COLOR_RESET}\n")
        
        # Single atomic write to stdout
        sys.stdout.write("".join(buf))
        sys.stdout.flush()

def ui_refresh_loop():
    while running:
        draw_fixed_dashboard()
        time.sleep(0.25) # 4 FPS smooth, flicker-free rendering

def stream_process_output(process, name):
    st_data = company_state[name]
    for raw_line in iter(process.stdout.readline, ''):
        line = raw_line.strip()
        if not line:
            continue
            
        # Ignore divider lines like ====================
        if set(line) <= {"=", "-", "*", "#"}:
            continue
            
        # 0. Real-time Countdown signal detection e.g. [COUNTDOWN:3600]
        m_cd = re.search(r'\[COUNTDOWN:\s*(\d+)\s*\]', line)
        if m_cd:
            cd_sec = int(m_cd.group(1))
            with lock:
                if cd_sec > 0:
                    st_data["cd_end_time"] = time.time() + cd_sec
                    st_data["cd_total_sec"] = cd_sec
                    if "นอกช่วงเวลา" in line or "TIME WINDOW" in line:
                        st_data["cd_reason"] = "พักนอกเวลา"
                        st_data["http"] = "พักนอกเวลา"
                        company_http_code[name] = "พักนอกเวลา"
                        reason_label = "พักนอกเวลาทำงาน"
                    else:
                        st_data["cd_reason"] = "HTTP Error/Timeout"
                        st_data["http"] = "HTTP ERR"
                        company_http_code[name] = "HTTP ERR"
                        reason_label = "HTTP Error/Timeout"
                    if cd_sec >= 3600:
                        h_v = cd_sec // 3600
                        m_v = (cd_sec % 3600) // 60
                        desc_str = f"{h_v} ชม. {m_v} นาที"
                    elif cd_sec >= 60:
                        m_v = cd_sec // 60
                        s_v = cd_sec % 60
                        desc_str = f"{m_v} นาที {s_v} วินาที" if s_v else f"{m_v} นาที"
                    else:
                        desc_str = f"{cd_sec} วินาที"
                    add_log(f"[PAUSE] {reason_label}: พักรอนับถอยหลัง {desc_str}", comp_name=name, level="COUNTDOWN")
                else:
                    st_data["cd_end_time"] = 0.0
                    st_data["cd_total_sec"] = 0
                    st_data["cd_reason"] = ""
                    add_log("[RESUME] ครบกำหนดพักรอนับถอยหลังแล้ว -> กำลังเริ่มทำงานต่อ", comp_name=name, level="RESUME")
        # 0.1 WAF / 403 Circuit Breaker Detection -> Flag as WARN
        if ("403" in line or "WAF" in line or "CLOUDFRONT" in line) and ("กำลังรอปลดแบน" in line or "Rate Limit" in line or "HTTP 403" in line or "พักส่ง Request" in line):
            with lock:
                st_data["is_warn"] = True
                st_data["http"] = "403 WAF"
                company_http_code[name] = "403 WAF"
                m_m = re.search(r'กำลังรอปลดแบน.*?เหลือเวลา\s*~?(\d+):(\d+)\s*นาที', line)
                if not m_m:
                    m_m = re.search(r'เหลือเวลา\s*~?(\d+):(\d+)\s*นาที', line)
                if m_m:
                    rem_s = int(m_m.group(1)) * 60 + int(m_m.group(2))
                    st_data["cd_end_time"] = time.time() + rem_s
                    st_data["cd_total_sec"] = rem_s
                elif "60 นาที" in line or "1 ชม" in line:
                    if st_data.get("cd_end_time", 0.0) <= time.time():
                        st_data["cd_end_time"] = time.time() + 3600
                        st_data["cd_total_sec"] = 3600
        elif "ปลดบล็อกสำเร็จ" in line or "UNBLOCKED" in line or "กลับเข้าสู่กระบวนการสแครป" in line:
            with lock:
                st_data["is_warn"] = False
                st_data["http"] = "200 OK"
                company_http_code[name] = "200 OK"
                st_data["cd_end_time"] = 0.0

        # 1. HTTP Request Activity - capture for live dashboard display (recent logs)
        if "[HTTP-REQ ]" in line or "-> GET" in line or "-> POST" in line or "➔ GET" in line or "➔ POST" in line:
            clean_msg = line.replace("[HTTP-REQ ]", "").strip()
            if clean_msg.startswith("[") and "]" in clean_msg:
                clean_msg = clean_msg[clean_msg.find("]")+1:].strip()
                
            m_code = re.search(r'<-\s*(\d{3})', clean_msg)
            if m_code:
                h_code = f"HTTP {m_code.group(1)}"
            elif "ERR" in clean_msg or "ERROR" in clean_msg:
                h_code = "HTTP ERR"
            else:
                h_code = "HTTP 200"
                
            with lock:
                st_data["http"] = h_code
                company_http_code[name] = h_code
                if h_code.startswith("HTTP 2"):
                    # Success -> clear countdown and reset warning flag
                    st_data["is_warn"] = False
                    st_data["cd_end_time"] = 0.0
                elif h_code == "HTTP ERR" or h_code.startswith("HTTP 5"):
                    # If error occurs and no active countdown is set, start a temporary countdown (5s)
                    if st_data.get("cd_end_time", 0.0) <= time.time():
                        st_data["cd_end_time"] = time.time() + 5.0
                        st_data["cd_total_sec"] = 5
                        st_data["cd_reason"] = "HTTP Error"
                add_log(clean_msg, comp_name=name, level="HTTP-REQ")
            continue
                
        # 2. Health check update (update dashboard state only)
        elif "สถานะลิงก์" in line:
            clean_msg = line.replace(f"[{name}]", "").strip()
            m_http = re.search(r'HTTP\s*(\d+)', line)
            h_code = f"HTTP {m_http.group(1)}" if m_http else "HTTP 200"
            company_http_code[name] = h_code
            with lock:
                st_data["http"] = h_code
                company_health[name] = clean_msg
        
        # 3. Completion status & Error tracking
        elif "รายการ" in line and "ข้าม/ดึงไม่ได้" in line:
            clean_msg = line.replace(f"[{name}]", "").strip()
            with lock:
                company_issues[name] = clean_msg

        elif "ดึงข้อมูลได้ครบถ้วน" in line:
            clean_msg = line.replace(f"[{name}]", "").strip()
            with lock:
                company_issues[name] = "[PASS] ดึงข้อมูลได้ครบถ้วน 100% (ไม่มีรายการล้มเหลว)"

        elif "สแครปเสร็จสมบูรณ์" in line or "สิ้นสุดการสแครป" in line or "ครบถ้วน 100%" in line or "Completed!" in line or ("เสร็จสมบูรณ์" in line and ("🎉" in line or "✅" in line or "[SUCCESS]" in line or "บันทึก" in line)):
            clean_msg = line.replace(f"[{name}]", "").replace("✅", "").replace("🎉", "").strip()
            with lock:
                st_data["status"] = "DONE"
                st_data["pct"] = 100
                st_data["eta_str"] = ""
                m_pages = re.search(r'\(\s*([\d,]+)\s*/\s*([\d,]+)\s*(หน้า|รายการ|จว\.|หมวด|โฉนด[^\)]*)', line)
                if m_pages:
                    st_data["cur_page"] = int(m_pages.group(1).replace(",", ""))
                    st_data["tot_page"] = int(m_pages.group(2).replace(",", ""))
                    st_data["unit"] = m_pages.group(3).strip()
                elif st_data["cur_page"] == 0:
                    st_data["cur_page"] = st_data["tot_page"]
                    
                m_accum = re.search(r'(?:สะสม|พบพิกัด(?:จริง)?):\s*([\d,]+)(?:\s*/\s*([\d,]+))?\s*(?:รายการ|โฉนด|แปลง)?', line)
                if m_accum:
                    st_data["accum"] = int(m_accum.group(1).replace(",", ""))
                    if m_accum.group(2):
                        st_data["tot_items"] = int(m_accum.group(2).replace(",", ""))
                elif st_data["accum"] == 0:
                    m_cnt = re.search(r'([0-9,]+)\s*(?:รายการ|โฉนด|แปลง)', clean_msg)
                    if m_cnt:
                        st_data["accum"] = int(m_cnt.group(1).replace(",", ""))
                
        # 4. Real-time Progress Updates
        elif re.search(r'\[[█░]+\]\s*\d+%', line) or ("หน้า" in line and "สะสม:" in line) or ("รายการ" in line and "สะสม:" in line) or ("จว." in line and "สะสม:" in line) or ("โฉนด" in line):
            with lock:
                if st_data["status"] == "DONE":
                    continue
                st_data["status"] = "RUNNING"
                m_pct = re.search(r'(\d+)%', line)
                if m_pct:
                    st_data["pct"] = int(m_pct.group(1))
                m_pages = re.search(r'\(\s*([\d,]+)\s*/\s*([\d,]+)\s*(หน้า|รายการ|จว\.|หมวด|โฉนด[^\)]*)', line)
                if m_pages:
                    st_data["cur_page"] = int(m_pages.group(1).replace(",", ""))
                    st_data["tot_page"] = int(m_pages.group(2).replace(",", ""))
                    st_data["unit"] = m_pages.group(3).strip()
                m_accum = re.search(r'(?:สะสม|พบพิกัด(?:จริง)?):\s*([\d,]+)(?:\s*/\s*([\d,]+))?\s*(?:รายการ|โฉนด|แปลง)?', line)
                if m_accum:
                    st_data["accum"] = int(m_accum.group(1).replace(",", ""))
                    if m_accum.group(2):
                        st_data["tot_items"] = int(m_accum.group(2).replace(",", ""))
                m_eta = re.search(r'(เหลือ(?:อีก)?\s*~?[^\n\|]+)', line)
                if m_eta:
                    st_data["eta_str"] = m_eta.group(1).strip()
                    
        # 4.1 LandsMaps & General Activity Detail Lines (routed to recent logs)
        elif "➔" in line or "[SESSION ROT]" in line or "[SAVED]" in line or "🔄" in line:
            clean_msg = line
            if clean_msg.startswith("[") and "]" in clean_msg:
                clean_msg = clean_msg[clean_msg.find("]")+1:].strip()
            level = "TOKEN" if "[SESSION ROT]" in line or "Token" in line else ("SAVE" if "[SAVED]" in line else "INFO")
            with lock:
                add_log(clean_msg, comp_name=name, level=level)

        # 5. Structure Alert Detection
        elif "STRUCTURE ALERT" in line or "STRUCT_ERR" in line:
            clean_msg = line.replace(f"[{name}]", "").strip()
            with lock:
                st_data["status"] = "ERROR"
                company_issues[name] = "[WARN] โครงสร้างเว็บเปลี่ยน (Web Structure Changed)"
                add_log(f"[CRITICAL] โครงสร้างเว็บเปลี่ยน: {clean_msg}", comp_name=name, level="CRITICAL")

        # 6. Important Milestones (update counters only, no log spam)
        elif "Milestone" in line or "ALERT" in line or "Smart Resume" in line or "Fast-Forward" in line:
            with lock:
                m_res = re.search(r'พบแล้ว\s*([\d,]+)\s*รายการ', line)
                if m_res and st_data["accum"] == 0:
                    st_data["accum"] = int(m_res.group(1).replace(",", ""))

def parse_cli_company_selection():
    """Return selected main company list from CLI flags (--all, --companies, --only, --select), or None if interactive needed."""
    args = sys.argv[1:]
    if "--all" in args:
        return [s["name"] for s in SCRAPERS if not s.get("is_sub")]
    for i, a in enumerate(args):
        al = a.lower()
        for prefix in ("--companies=", "--only=", "--select="):
            if al.startswith(prefix):
                return resolve_selected_main_scrapers(a.split("=", 1)[1])
        if al in ("--companies", "--only", "--select") and i + 1 < len(args):
            return resolve_selected_main_scrapers(args[i + 1])
    return None

def main(selected_names=None):
    global running, current_active_company, ACTIVE_SCRAPER_NAMES
    if getattr(sys, 'frozen', False):
        exe_d = Path(sys.executable).parent.resolve()
        project_root = exe_d.parent if exe_d.name.lower() in ["py scraper", "tools", "dist", "build"] else exe_d
        base_dir = project_root / "Py Scraper" if (project_root / "Py Scraper").exists() else project_root
    else:
        file_d = Path(__file__).parent.resolve()
        project_root = file_d.parent if file_d.name.lower() in ["py scraper", "tools", "dist", "build"] else file_d
        base_dir = file_d
    python_exe = sys.executable

    if selected_names is None and "--check-only" not in sys.argv:
        try:
            cli_sel = parse_cli_company_selection()
        except ValueError as ve:
            print(f"{COLOR_RED}[ERROR] {ve}{COLOR_RESET}")
            sys.exit(1)
        if cli_sel is not None:
            selected_names = cli_sel
        elif sys.stdin and sys.stdin.isatty():
            selected_names = prompt_select_companies()
        else:
            selected_names = [s["name"] for s in SCRAPERS if not s.get("is_sub")]

    if selected_names is not None:
        active_set = set(selected_names)
        if "LED" in active_set:
            active_set.update(["LandsMaps", "LED_Legal"])
        ACTIVE_SCRAPER_NAMES = active_set
    else:
        ACTIVE_SCRAPER_NAMES = None

    active_scrapers = get_active_scrapers()
    active_main_scrapers = get_active_main_scrapers()
    
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["RUN_PARALLEL_MANAGED"] = "1"
    if os.environ.get("SCRAPER_TIME_WINDOW"):
        env["SCRAPER_TIME_WINDOW"] = os.environ["SCRAPER_TIME_WINDOW"]
    if os.environ.get("SCRAPER_IGNORE_WINDOW") == "1":
        env["SCRAPER_IGNORE_WINDOW"] = "1"

    # Phase 0.0: Check Time Window Restriction (18:00 - 06:00 น.)
    try:
        from time_window_util import (
            is_within_active_window,
            format_window_str,
            get_next_window_open_datetime,
            get_seconds_until_window_opens,
            is_window_disabled
        )
        if not is_window_disabled() and not is_within_active_window():
            win_str = format_window_str()
            target_dt = get_next_window_open_datetime()
            target_clock = target_dt.strftime("%H:%M:%S น.")
            
            border = f"{COLOR_CYAN}{'═' * 78}{COLOR_RESET}"
            tag_win = f"{COLOR_YELLOW}{COLOR_BOLD}[TIME WINDOW]{COLOR_RESET}"
            tag_status = f"{COLOR_CYAN}{COLOR_BOLD}[STATUS]{COLOR_RESET}"
            tag_override = f"{COLOR_GREEN}{COLOR_BOLD}[OVERRIDE]{COLOR_RESET}"
            
            print("\n" + border)
            print(f"  {tag_win}  Allowed schedule : {COLOR_WHITE}{COLOR_BOLD}{win_str}{COLOR_RESET}")
            print(f"  {tag_status}       Current time     : {COLOR_WHITE}{datetime.now().strftime('%H:%M:%S น.')}{COLOR_RESET}  │  Auto-resume: {COLOR_YELLOW}{COLOR_BOLD}{target_clock}{COLOR_RESET}")
            print(f"  {tag_override}     Action           : Press {COLOR_GREEN}{COLOR_BOLD}[N]{COLOR_RESET} or {COLOR_GREEN}{COLOR_BOLD}[Enter]{COLOR_RESET} to run in {COLOR_CYAN}{COLOR_BOLD}NOW MODE{COLOR_RESET} immediately")
            print(border + "\n")
            
            try:
                import msvcrt
                has_msvcrt = True
            except ImportError:
                has_msvcrt = False

            now_triggered = False
            while not is_within_active_window() and not is_window_disabled():
                rem_sec = get_seconds_until_window_opens()
                if rem_sec <= 0:
                    break
                h_v = rem_sec // 3600
                m_v = (rem_sec % 3600) // 60
                s_v = rem_sec % 60
                cd_tag = f"{COLOR_YELLOW}{COLOR_BOLD}[PAUSED]{COLOR_RESET}"
                time_display = f"{COLOR_WHITE}{COLOR_BOLD}{h_v:02d}h {m_v:02d}m {s_v:02d}s{COLOR_RESET}"
                action_hint = f"Press {COLOR_GREEN}{COLOR_BOLD}[N]{COLOR_RESET} to {COLOR_CYAN}{COLOR_BOLD}RUN NOW{COLOR_RESET}"
                sys.stdout.write(f"\r  {cd_tag} Auto-start in: {time_display}  │  {action_hint}   ")
                sys.stdout.flush()

                if has_msvcrt:
                    for _ in range(10): # 10 x 0.1s = 1.0s
                        if msvcrt.kbhit():
                            ch = msvcrt.getwch().lower()
                            if ch in ['n', '2', 'y', ' ', '\r', '\n']:
                                os.environ["SCRAPER_IGNORE_WINDOW"] = "1"
                                env["SCRAPER_IGNORE_WINDOW"] = "1"
                                now_triggered = True
                                break
                        time.sleep(0.1)
                    if now_triggered:
                        print(f"\n\n>> {COLOR_GREEN}{COLOR_BOLD}[RUN-NOW]{COLOR_RESET} {COLOR_WHITE}Override accepted: Starting pipeline execution immediately...{COLOR_RESET}\n")
                        break
                else:
                    time.sleep(1)
            if not now_triggered and not is_window_disabled():
                print(f"\n\n>> {COLOR_GREEN}{COLOR_BOLD}[ACTIVE]{COLOR_RESET} {COLOR_WHITE}Scheduled window reached: Initializing pipeline...{COLOR_RESET}\n")
    except Exception as e:
        print(f"[WARN] ตรวจสอบช่วงเวลาผิดพลาด: {e}")
    
    # Phase 0: Pre-flight Health & Structure Checks for selected platforms
    try:
        from preflight_check import run_all_preflight_checks
        passed, preflight_results = run_all_preflight_checks(
            parallel=True,
            timeout=35,
            render_table=True,
            selected_names=[s["name"] for s in active_main_scrapers]
        )
        # Pre-populate company_http_code and tot_items from live preflight results
        for name, r in preflight_results.items():
            if name in company_http_code and r.get("status_code", 0) > 0:
                company_http_code[name] = f"{r['status_code']} OK" if r.get("ok") else f"HTTP {r['status_code']}"
            if name in company_state and r.get("items", 0) > 0:
                company_state[name]["tot_items"] = r["items"]
                
        if "--check-only" in sys.argv:
            print("[INFO] เสร็จสิ้นการตรวจสอบสถานะระบบ (โหมด --check-only)")
            sys.exit(0 if passed else 1)
            
        if passed:
            print(f">> ทุกแพลตฟอร์มที่เลือกพร้อมทำงาน 100% -> เริ่มต้นการสแครปในอีก 3 วินาที...")
            time.sleep(3)
        else:
            failed_comps = [n for n, r in preflight_results.items() if not r.get("ok")]
            print(f"[WARN] พบ {len(failed_comps)} แพลตฟอร์มที่การเชื่อมต่อมีปัญหา: {', '.join(failed_comps)}")
            print(">> กำลังเริ่มต้นการสแครปตัวที่พร้อมทำงานในอีก 5 วินาที...")
            time.sleep(5)
    except Exception as e:
        print(f"[WARN] ไม่สามารถรัน Pre-flight check: {e}")

    # Clear screen once at startup
    os.system('cls' if os.name == 'nt' else 'clear')
    
    batch_start_time = time.time()
    batch_start_clock = datetime.now().strftime("%H:%M:%S")
    system_start_msg = f"เวลาเริ่ม: {batch_start_clock} (เริ่มต้นระบบ Scraper Monthly แบบคู่ขนานพร้อมกัน {len(active_main_scrapers)} แพลตฟอร์ม)"
    with lock:
        add_log(system_start_msg, comp_name="SYSTEM", level="START")
    log_start("SYSTEM", system_start_msg, start_clock=batch_start_clock)
    
    ui_thread = threading.Thread(target=ui_refresh_loop)
    ui_thread.daemon = True
    ui_thread.start()
    
    is_frozen = getattr(sys, 'frozen', False)
    global scraper_time_summary
    scraper_time_summary.clear()
    
    active_subprocesses = []
    proc_lock = threading.Lock()
    landsmaps_threads = []
    landsmaps_lock = threading.Lock()

    main_scrapers = active_main_scrapers

    def run_worker(idx, scraper):
        name = scraper["name"]
        script_file = (base_dir / scraper["script"]).resolve()
        is_sub = scraper.get("is_sub", False)
        
        scraper_start_t = time.time()
        start_clock = datetime.now().strftime("%H:%M:%S")
        start_msg = f"เวลาเริ่ม: {start_clock} ({name} โหมด 1-Thread Safe Mode)" if is_sub else f"เวลาเริ่ม: {start_clock} ({name} ตัวที่ {idx}/{len(main_scrapers)})"
        with lock:
            company_state[name]["status"] = "RUNNING"
            company_health[name] = "[CONNECT] กำลังเชื่อมต่อและตรวจสอบข้อมูล..."
            add_log(start_msg, comp_name=name, level="START")
        log_start(name, start_msg, start_clock=start_clock)
        
        _has_now = (env.get("SCRAPER_IGNORE_WINDOW") == "1") or ("--now" in sys.argv)
        _has_fresh = ("--fresh" in sys.argv or "--force-restart" in sys.argv) and (name not in ("LandsMaps", "LandsMaps-Merge"))
        if is_frozen:
            cmd = [sys.executable, "--worker", name]
            if _has_now:
                cmd.append("--now")
            if _has_fresh:
                cmd.append("--fresh")
        else:
            if not script_file.exists():
                with lock:
                    company_state[name]["status"] = "ERROR"
                    company_health[name] = "[FAIL] ไม่พบไฟล์สคริปต์"
                    company_issues[name] = "[FAIL] ไม่พบไฟล์สคริปต์"
                    err_msg = f"เวลาเริ่ม: {start_clock} | เวลาเสร็จ: {start_clock} | [FAIL] ไม่พบไฟล์สคริปต์"
                    add_log(err_msg, comp_name=name, level="ERROR")
                log_finish(name, is_error=True, start_clock=start_clock, message=err_msg)
                with lock:
                    scraper_time_summary[name] = {
                        "idx": idx,
                        "start": start_clock,
                        "finish": start_clock,
                        "duration": "0 วินาที",
                        "duration_sec": 0,
                        "records": 0,
                        "status": "[FAIL] ไม่พบไฟล์สคริปต์"
                    }
                return
            cmd = [python_exe, "-u", str(script_file)]
            if name == "LED":
                cmd.append("--skip-coords")
            elif name == "LandsMaps":
                cmd.extend(["--limit", "0", "--workers", "1", "--no-merge"])
            if _has_now:
                cmd.append("--now")
            if _has_fresh:
                cmd.append("--fresh")

        try:
            work_cwd = project_root
            p = subprocess.Popen(
                cmd,
                cwd=work_cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env
            )
            with proc_lock:
                active_subprocesses.append(p)
                
            stream_process_output(p, name)
            p.wait()
            
            with proc_lock:
                if p in active_subprocesses:
                    active_subprocesses.remove(p)
                    
            elapsed_sec = time.time() - scraper_start_t
            finish_clock = datetime.now().strftime("%H:%M:%S")
            dur_str = format_duration(elapsed_sec)
            accum = company_state[name]["accum"]
            is_success = (p.returncode == 0)
            is_partial = (p.returncode == 2)
            is_usable = is_success or is_partial
            
            with lock:
                stat_label = "[PASS] 100%" if is_success else ("[WARN] PARTIAL (Code 2)" if is_partial else f"[FAIL] ล้มเหลว (Exit Code {p.returncode})")
                scraper_time_summary[name] = {
                    "idx": idx,
                    "start": start_clock,
                    "finish": finish_clock,
                    "duration": dur_str,
                    "duration_sec": elapsed_sec,
                    "records": accum,
                    "status": stat_label
                }
                
                if is_success:
                    company_state[name]["status"] = "DONE"
                    company_state[name]["pct"] = 100
                    if company_state[name]["cur_page"] == 0:
                        company_state[name]["cur_page"] = company_state[name]["tot_page"]
                    finish_msg = f"เวลาเริ่ม: {start_clock} | เวลาเสร็จ: {finish_clock} | เวลารวมที่ใช้: {dur_str} | ข้อมูล: {accum:,} รายการ"
                    add_log(finish_msg, comp_name=name, level="FINISH")
                elif is_partial:
                    company_state[name]["status"] = "PARTIAL"
                    company_issues[name] = "[WARN] ดึงได้บางส่วนยังไม่ครบ 100% (Exit Code 2)"
                    finish_msg = f"เวลาเริ่ม: {start_clock} | เวลาเสร็จ: {finish_clock} | เวลารวมที่ใช้: {dur_str} | ข้อมูลบางส่วน: {accum:,} รายการ (Code 2)"
                    add_log(finish_msg, comp_name=name, level="WARN")
                else:
                    company_state[name]["status"] = "ERROR"
                    if not company_issues.get(name):
                        company_issues[name] = f"[FAIL] สแครปล้มเหลว (Exit Code {p.returncode})"
                    err_msg = f"เวลาเริ่ม: {start_clock} | เวลาเสร็จ: {finish_clock} | เวลารวมที่ใช้: {dur_str} | [FAIL] สแครปล้มเหลว (Exit Code {p.returncode})"
                    add_log(err_msg, comp_name=name, level="ERROR")
                    
            if is_usable:
                log_finish(name, duration_sec=elapsed_sec, records=accum, start_clock=start_clock, message=finish_msg)
                if name == "LED":
                    def _run_led_downstream_pipeline():
                        lg_scraper = next((s for s in SCRAPERS if s["name"] == "LED_Legal"), None)
                        lm_scraper = next((s for s in SCRAPERS if s["name"] == "LandsMaps"), None)

                        # 1. Run LED_Legal BEFORE LandsMaps so LED_Legal_merge and cache never race
                        if lg_scraper:
                            with lock:
                                add_log("[SEQ 1/3] LED เสร็จสิ้น -> เริ่มรัน LED_Legal ก่อน LandsMaps...", comp_name="SYSTEM", level="TRIGGER")
                            run_worker("↳", lg_scraper)
                            try:
                                import scrape_led_legal
                                if os.path.exists(scrape_led_legal.REPORT_CSV):
                                    scrape_led_legal.build_led_legal_merge(
                                        report_csv_path=scrape_led_legal.REPORT_CSV,
                                        merge_csv_path=scrape_led_legal.MERGE_CSV,
                                    )
                            except Exception as e:
                                with lock:
                                    add_log(f"[WARN] อัปเดต LED_Legal_merge ไม่สำเร็จ: {e}", comp_name="SYSTEM", level="WARN")

                        # 2. Run LandsMaps (enrich_led_landsmaps) sequentially
                        if lm_scraper:
                            with lock:
                                add_log("[SEQ 2/3] LED_Legal เสร็จสิ้น -> เริ่มรัน LandsMaps (1-Thread Safe Mode)...", comp_name="SYSTEM", level="TRIGGER")
                            run_worker("↳", lm_scraper)

                            # 3. Run enrich_led_merge_landsmaps sequentially after LandsMaps
                            if company_state.get("LandsMaps", {}).get("status") in ("DONE", "PARTIAL"):
                                with lock:
                                    add_log("[SEQ 3/3] LandsMaps เสร็จสิ้น -> กำลังผสานพิกัดจริงลง LED_Legal_merge...", comp_name="SYSTEM", level="TRIGGER")
                                if is_frozen:
                                    m_cmd = [sys.executable, "--worker", "LandsMaps-Merge"]
                                else:
                                    m_cmd = [python_exe, "-u", str((base_dir / "enrich_led_merge_landsmaps.py").resolve()), "--no-merge"]
                                if env.get("SCRAPER_IGNORE_WINDOW") == "1" or "--now" in sys.argv:
                                    m_cmd.append("--now")
                                try:
                                    m_res = subprocess.run(
                                        m_cmd,
                                        cwd=work_cwd,
                                        env=env,
                                        capture_output=True,
                                        text=True,
                                        encoding="utf-8",
                                        errors="replace",
                                        check=False,
                                    )
                                    if m_res.returncode in (0, 2):
                                        with lock:
                                            add_log("[SYNC] อัปเดตพิกัดจริง LandsMaps เข้าสู่ LED_Legal_merge เรียบร้อยแล้ว", comp_name="SYSTEM", level="SAVE")
                                    else:
                                        with lock:
                                            add_log(f"[WARN] LandsMaps-Merge จบด้วย code {m_res.returncode}", comp_name="SYSTEM", level="WARN")
                                except Exception as e:
                                    with lock:
                                        add_log(f"[WARN] ผสานพิกัด LandsMaps-Merge ไม่สำเร็จ: {e}", comp_name="SYSTEM", level="WARN")

                    seq_th = threading.Thread(target=_run_led_downstream_pipeline, name="Worker-LED-Downstream")
                    seq_th.daemon = True
                    with landsmaps_lock:
                        landsmaps_threads.append(seq_th)
                    seq_th.start()
            else:
                log_finish(name, duration_sec=elapsed_sec, is_error=True, start_clock=start_clock, message=err_msg)
        except Exception as e:
            elapsed_sec = time.time() - scraper_start_t
            finish_clock = datetime.now().strftime("%H:%M:%S")
            dur_str = format_duration(elapsed_sec)
            with lock:
                scraper_time_summary[name] = {
                    "idx": idx,
                    "start": start_clock,
                    "finish": finish_clock,
                    "duration": dur_str,
                    "duration_sec": elapsed_sec,
                    "records": 0,
                    "status": f"[FAIL] Error: {e}"
                }
                company_state[name]["status"] = "ERROR"
                company_health[name] = f"[FAIL] สั่งรันไม่ได้: {e}"
                company_issues[name] = f"[FAIL] Error: {e}"
                err_msg = f"เวลาเริ่ม: {start_clock} | เวลาเสร็จ: {finish_clock} | เวลารวมที่ใช้: {dur_str} | [FAIL] สั่งรันไม่ได้: {e}"
                add_log(err_msg, comp_name=name, level="ERROR")
            log_finish(name, duration_sec=elapsed_sec, is_error=True, start_clock=start_clock, message=err_msg)

    # Launch all 14 main scrapers simultaneously in parallel
    worker_threads = []
    for idx, scraper in enumerate(main_scrapers, 1):
        th = threading.Thread(target=run_worker, args=(idx, scraper), name=f"Worker-{scraper['name']}")
        th.daemon = True
        worker_threads.append(th)
        th.start()
        time.sleep(0.15)  # 150ms stagger to prevent initial CPU / socket storm

    # Wait for all workers and LandsMaps to finish
    try:
        for th in worker_threads:
            th.join()
        joined_subs = set()
        while True:
            with landsmaps_lock:
                pending_subs = [th for th in landsmaps_threads if th not in joined_subs]
            if not pending_subs:
                break
            for th in pending_subs:
                th.join()
                joined_subs.add(th)
    except KeyboardInterrupt:
        with lock:
            add_log("[INTERRUPT] ผู้ใช้กด Ctrl+C เพื่อหยุดกระบวนการ -> กำลังบันทึกข้อมูลและรวบรวมไฟล์...", comp_name="SYSTEM", level="STOP")
        with proc_lock:
            for p in list(active_subprocesses):
                try:
                    p.terminate()
                except Exception:
                    pass
            for p in list(active_subprocesses):
                try:
                    p.wait(timeout=3)
                except Exception:
                    try:
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
                    except Exception:
                        pass
        time.sleep(0.5)
            
    current_active_company = None
    running = False
    time.sleep(0.4)
    
    total_elapsed = time.time() - batch_start_time
    batch_finish_clock = datetime.now().strftime("%H:%M:%S")
    total_dur_str = format_duration(total_elapsed)
    total_records = sum(company_state[s["name"]]["accum"] for s in active_main_scrapers)
    
    all_done_msg = f"เวลาเริ่มทั้งหมด: {batch_start_clock} | เวลาเสร็จทั้งหมด: {batch_finish_clock} | เวลารวมทั้งหมด: {total_dur_str} | ข้อมูลรวม: {total_records:,} รายการ (ครบทั้ง {len(active_scrapers)} ตัว)"
    with lock:
        add_log(all_done_msg, comp_name="SYSTEM", level="FINISH")
    log_finish("SYSTEM", duration_sec=total_elapsed, records=total_records, start_clock=batch_start_clock, message=all_done_msg)
    
    draw_fixed_dashboard()
    
    # Restore cursor for normal terminal use
    sys.stdout.write("\033[?25h\n")
    sys.stdout.flush()

    SUM_INNER_W = 133
    SUM_CARD_TOP = "┌" + "─" * SUM_INNER_W + "┐"
    SUM_CARD_BOT = "└" + "─" * SUM_INNER_W + "┘"
    
    SUM_BOX_TOP = "┌────┬──────────────────────┬────────────┬────────────┬────────────────────┬──────────────────────────┬───────────────────────────────┐"
    SUM_BOX_HDR = "│ No │   Platform / Bank    │ Start Time │ Finish Time│      Duration      │     Records Scraped      │            Status             │"
    SUM_BOX_MID = "├────┼──────────────────────┼────────────┼────────────┼────────────────────┼──────────────────────────┼───────────────────────────────┤"
    SUM_BOX_BOT = "└────┴──────────────────────┴────────────┴────────────┴────────────────────┴──────────────────────────┴───────────────────────────────┘"

    try:
        from time_window_util import get_scraper_delay_range
        d_min, d_max = get_scraper_delay_range()
        sum_delay_str = f"{int(d_min)}-{int(d_max)}s/req" if d_min != d_max else f"{int(d_min)}s/req"
    except Exception:
        sum_delay_str = "15-16s/req"

    print("\n" + SUM_CARD_TOP, flush=True)
    sum_title = f"  {COLOR_GREEN}{COLOR_BOLD}[SUCCESS] ALL ASSET NPA PIPELINE COMPLETED — สแครปและรวมไฟล์ครบทั้ง {len(active_main_scrapers)} แพลตฟอร์ม{COLOR_RESET}"
    sum_meta = f"  เริ่ม: {batch_start_clock} น.  │  เสร็จ: {batch_finish_clock} น.  │  เวลารวม: {total_dur_str}  │  หน่วงเวลา: {sum_delay_str}  │  ข้อมูลสุทธิรวม: {total_records:,d} รายการ"
    print(f"│{pad_display(sum_title, SUM_INNER_W, 'left')}│", flush=True)
    print(f"│{pad_display(sum_meta, SUM_INNER_W, 'left')}│", flush=True)
    print(SUM_CARD_BOT, flush=True)
    
    print("\n" + SUM_BOX_TOP, flush=True)
    print(SUM_BOX_HDR, flush=True)
    print(SUM_BOX_MID, flush=True)
    display_sum_idx = 1
    for s in active_scrapers:
        n = s["name"]
        item = scraper_time_summary.get(n, {})
        is_sub = s.get("is_sub", False)
        if is_sub:
            s_idx = pad_display("", 2, 'center')
            s_name = pad_display(f" └ {n}", 20, 'left')
        else:
            s_idx = pad_display(f"{display_sum_idx:02d}", 2, 'center')
            s_name = pad_display(n, 20, 'left')
            display_sum_idx += 1
        s_recs = pad_display(f"{item.get('records', 0):,d} รายการ", 24, 'right')
        s_start = pad_display(str(item.get("start", "-")), 10, 'center')
        s_finish = pad_display(str(item.get("finish", "-")), 10, 'center')
        s_dur = pad_display(str(item.get("duration", "-")), 18, 'center')
        raw_stat = str(item.get("status", company_issues.get(n, "[PASS] 100%")))
        if "ครบถ้วน" in raw_stat or "PASS" in raw_stat or "100%" in raw_stat:
            stat_colored = f"{COLOR_GREEN}[PASS] 100%{COLOR_RESET}"
        elif "WARN" in raw_stat or "PARTIAL" in raw_stat or "ไม่ครบ" in raw_stat:
            stat_colored = f"{COLOR_YELLOW}[WARN] {truncate_display(raw_stat, 22)}{COLOR_RESET}"
        else:
            stat_colored = f"{COLOR_RED}[FAIL] {truncate_display(raw_stat, 22)}{COLOR_RESET}"
        s_stat = pad_display(stat_colored, 29, 'left')
        
        print(f"│ {s_idx} │ {s_name} │ {s_start} │ {s_finish} │ {s_dur} │ {s_recs} │ {s_stat} │", flush=True)
    print(SUM_BOX_BOT, flush=True)
    
    try:
        try:
            import scrape_led_legal
            if os.path.exists(scrape_led_legal.REPORT_CSV):
                scrape_led_legal.build_led_legal_merge(
                    report_csv_path=scrape_led_legal.REPORT_CSV,
                    merge_csv_path=scrape_led_legal.MERGE_CSV,
                )
        except Exception:
            pass
        import merge_csv_monthly
        merge_csv_monthly.merge_monthly_csv()
        print("\n[SUCCESS] รวมไฟล์และอัปเดต all_assets.parquet เรียบร้อย พร้อมใช้งานบน Dashboard!", flush=True)
    except Exception as e:
        print(f"[ERROR] เกิดข้อผิดพลาดในการรวมไฟล์: {e}", flush=True)

    print("\n" + "=" * 80, flush=True)
    print("[COMPLETE] ทุกขั้นตอนเสร็จสมบูรณ์ 100% แล้ว สามารถตรวจสอบผลลัพธ์และปิดหน้าต่างนี้ได้", flush=True)
    print("=" * 80, flush=True)
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\n>> กดปุ่ม Enter เพื่อปิดหน้าต่างนี้...")
    except Exception:
        pass


def find_python():
    """Find the best Python executable to run external tools/scripts."""
    if not getattr(sys, 'frozen', False):
        return sys.executable
    import shutil
    base = Path(sys.executable).parent
    for cand in [
        base / ".venv" / "Scripts" / "python.exe",
        base.parent / ".venv" / "Scripts" / "python.exe",
    ]:
        if cand.exists():
            return str(cand)
    for name in ["python", "py", "python3"]:
        p = shutil.which(name)
        if p:
            return p
    return "python"


def run_led_workflow():
    """Run LED scraping + LandsMaps real coordinates enrichment + master merge."""
    print("\n" + "=" * 75)
    print(f" {COLOR_CYAN}{COLOR_BOLD}[LED PIPELINE] เริ่มต้นกระบวนการรันเฉพาะ กรมบังคับคดี (LED) + LandsMaps{COLOR_RESET}")
    print("=" * 75 + "\n")
    
    try:
        import scrape_led_monthly
        scrape_led_monthly.main()
    except Exception as e:
        print(f"[ERROR] เกิดข้อผิดพลาดในกระบวนการ LED: {e}")
        return

    print("\n" + "=" * 75)
    print(f"{COLOR_GREEN}[SUCCESS] ดำเนินการเฉพาะ กรมบังคับคดี (LED) และ LandsMaps เสร็จสมบูรณ์ 100%!{COLOR_RESET}")
    print("=" * 75)
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\n>> กดปุ่ม Enter เพื่อปิดหน้าต่างนี้...")
    except Exception:
        pass


def run_landsmaps_only_workflow():
    """Run only LandsMaps real coordinates enrichment on existing CSV (works in script and frozen EXE)."""
    print("\n" + "=" * 75)
    print(f" {COLOR_CYAN}{COLOR_BOLD}[LANDSMAPS ENRICHMENT] รันเฉพาะดึงพิกัดจริงจากโฉนดที่ดิน (ใช้ไฟล์ CSV เดิม){COLOR_RESET}")
    print("=" * 75 + "\n")

    is_frozen = getattr(sys, 'frozen', False)
    root_dir = Path(sys.executable).parent if is_frozen else Path(__file__).parent.parent
    enrich_script = (Path(__file__).parent / "enrich_led_landsmaps.py") if (Path(__file__).parent / "enrich_led_landsmaps.py").exists() else (root_dir / "Py Scraper" / "enrich_led_landsmaps.py")
    merge_script = (Path(__file__).parent / "enrich_led_merge_landsmaps.py") if (Path(__file__).parent / "enrich_led_merge_landsmaps.py").exists() else (root_dir / "Py Scraper" / "enrich_led_merge_landsmaps.py")

    if not is_frozen and not enrich_script.exists():
        print(f"[ERROR] ไม่พบสคริปต์ดึงพิกัดที่: {enrich_script}")
        return

    try:
        bg_choice = input("ต้องการรันเบื้องหลัง (ซ่อนหน้าต่างเบราว์เซอร์ ไม่กวนหน้าจอ) หรือไม่? [Y/n] (กด Enter = ใช่): ").strip().lower()
    except Exception:
        bg_choice = ""
    headless = (bg_choice != "n")

    try:
        prov = input("ระบุจังหวัด (เช่น ปทุมธานี หรือกด Enter เพื่อดึงทุกจังหวัด): ").strip()
    except Exception:
        prov = ""

    try:
        lim = input("ระบุจำนวนโฉนด (เช่น 50, 100 หรือกด Enter เพื่อดึงทั้งหมด): ").strip()
    except Exception:
        lim = ""
    lim_val = int(lim) if lim.isdigit() else 0

    print(f"\n[INFO] เริ่มต้นค้นหาพิกัดจริง... [โหมด: {'รันเบื้องหลัง (Headless)' if headless else 'เปิดหน้าต่าง Chrome'}]")
    print("[NOTE] ข้อมูลจะถูกบันทึกลงไฟล์ CSV และแคชอัตโนมัติ (สามารถกด Ctrl+C เพื่อหยุดเมื่อไหร่ก็ได้)\n")
    if is_frozen:
        try:
            tools_d = str(Path(__file__).parent)
            if tools_d not in sys.path:
                sys.path.insert(0, tools_d)
            import enrich_led_landsmaps
            import enrich_led_merge_landsmaps
            enrich_led_landsmaps.run_enrichment(
                province_filter=prov or None,
                limit=lim_val,
                headless=headless,
                workers=1,
                auto_merge=False,
            )
            enrich_led_merge_landsmaps.run_merge_enrichment(
                province_filter=prov or None,
                limit=lim_val,
                auto_merge=True,
            )
        except Exception as e:
            print(f"[WARNING] เกิดข้อผิดพลาดในการรัน LandsMaps: {e}")
    else:
        py_exe = find_python()
        common_args = []
        if prov:
            common_args += ["--province", prov]
        if lim and lim.isdigit():
            common_args += ["--limit", lim]
        if os.environ.get("SCRAPER_IGNORE_WINDOW") == "1" or "--now" in sys.argv:
            common_args.append("--now")

        cmd = [py_exe, str(enrich_script), "--no-merge"]
        if headless:
            cmd += ["--headless"]
        cmd += common_args
        try:
            subprocess.run(cmd, check=False)
            if merge_script.exists():
                subprocess.run([py_exe, str(merge_script)] + common_args, check=False)
        except Exception as e:
            print(f"[WARNING] เกิดข้อผิดพลาดในการรัน LandsMaps: {e}")

    print("\n" + "=" * 75)
    print(f"{COLOR_GREEN}[SUCCESS] การดึงพิกัดจริง LandsMaps เสร็จสมบูรณ์!{COLOR_RESET}")
    print("=" * 75)
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\n>> กดปุ่ม Enter เพื่อปิดหน้าต่างนี้...")
    except Exception:
        pass


if __name__ == "__main__":
    # 0. Parse Time-Window Arguments
    for i, a in enumerate(sys.argv):
        if a.lower() in ["--now", "-now", "now", "--ignore-window", "--force-now", "--no-window"]:
            os.environ["SCRAPER_IGNORE_WINDOW"] = "1"
        elif a.lower().startswith("--window="):
            os.environ["SCRAPER_TIME_WINDOW"] = a.split("=")[1]
        elif a.lower() == "--window" and i + 1 < len(sys.argv):
            os.environ["SCRAPER_TIME_WINDOW"] = sys.argv[i + 1]

    if len(sys.argv) > 2 and sys.argv[1] == "--worker":
        worker = sys.argv[2]
        _worker_rc = 0
        if worker == "LED":
            import scrape_led_monthly; _worker_rc = scrape_led_monthly.main()
        elif worker == "SAM":
            import scrape_sam_monthly; _worker_rc = scrape_sam_monthly.main()
        elif worker == "BAM":
            import scrape_bam_monthly; _worker_rc = scrape_bam_monthly.main()
        elif worker == "Chayo555":
            import scrape_chayo555_monthly; _worker_rc = scrape_chayo555_monthly.main()
        elif worker == "GHB":
            import scrape_ghb_monthly; _worker_rc = scrape_ghb_monthly.main()
        elif worker == "KBANK":
            import scrape_kbank_monthly; _worker_rc = scrape_kbank_monthly.main()
        elif worker == "KTB":
            import scrape_ktb_monthly; _worker_rc = scrape_ktb_monthly.main()
        elif worker == "SCB":
            import scrape_scb_monthly; _worker_rc = scrape_scb_monthly.main()
        elif worker == "GSB":
            import scrape_gsb_monthly; _worker_rc = scrape_gsb_monthly.main()
        elif worker == "DDproperty":
            import scrape_ddproperty_monthly; _worker_rc = scrape_ddproperty_monthly.main()
        elif worker == "Livinginsider":
            import scrape_livinginsider_monthly; _worker_rc = scrape_livinginsider_monthly.main()
        elif worker == "NaYoo":
            import scrape_nayoo_monthly; _worker_rc = scrape_nayoo_monthly.scrape_nayoo()
        elif worker == "ZmyHome":
            import scrape_zmyhome_monthly; _worker_rc = scrape_zmyhome_monthly.main()
        elif worker == "Baania":
            import scrape_baania_monthly; _worker_rc = scrape_baania_monthly.main()
        elif worker == "LED_Legal":
            import scrape_led_legal; _worker_rc = scrape_led_legal.main()
        elif worker == "LandsMaps":
            try:
                tools_d = str(Path(__file__).parent)
                if tools_d not in sys.path:
                    sys.path.insert(0, tools_d)
                import enrich_led_landsmaps
                enrich_led_landsmaps.run_enrichment(limit=0, workers=1, auto_merge=False)
            except Exception as e:
                print(f"[ERROR] ไม่สามารถรัน LandsMaps ได้: {e}")
                _worker_rc = 1
        elif worker == "LandsMaps-Merge":
            try:
                tools_d = str(Path(__file__).parent)
                if tools_d not in sys.path:
                    sys.path.insert(0, tools_d)
                import enrich_led_merge_landsmaps
                enrich_led_merge_landsmaps.run_merge_enrichment(limit=0, auto_merge=False)
            except Exception as e:
                print(f"[ERROR] ไม่สามารถรัน LandsMaps-Merge ได้: {e}")
                _worker_rc = 1
        sys.exit(_worker_rc if isinstance(_worker_rc, int) and not isinstance(_worker_rc, bool) else 0)
    elif "--check-only" in sys.argv:
        from preflight_check import run_all_preflight_checks
        try:
            cli_sel = parse_cli_company_selection()
        except ValueError as ve:
            print(f"{COLOR_RED}[ERROR] {ve}{COLOR_RESET}")
            sys.exit(1)
        passed, _ = run_all_preflight_checks(parallel=True, timeout=12, render_table=True, selected_names=cli_sel)
        sys.exit(0 if passed else 1)
    elif "--landsmaps" in sys.argv or "--enrich" in sys.argv or "--coords-only" in sys.argv:
        run_landsmaps_only_workflow()
    elif "--led-legal" in sys.argv or "--legal-only" in sys.argv:
        import scrape_led_legal; scrape_led_legal.main()
        sys.exit(0)
    elif "--led" in sys.argv or "--only-led" in sys.argv or "--led-only" in sys.argv:
        run_led_workflow()
    elif "--living" in sys.argv or "--livinginsider" in sys.argv or "--retry-living" in sys.argv:
        import scrape_livinginsider_monthly
        scrape_livinginsider_monthly.main()
        sys.exit(0)
    elif "--menu" in sys.argv or "--interactive" in sys.argv or "--choose" in sys.argv:
        # โหมดเลือกเมนูเอง (หากเปิดด้วย --menu หรือ --interactive)
        print("\n" + "┌" + "─" * 70 + "┐")
        print(f"│  {COLOR_CYAN}{COLOR_BOLD}ALL ASSET NPA INTELLIGENCE — PIPELINE SCRAPER{COLOR_RESET}" + " " * 24 + "│")
        print("├" + "─" * 70 + "┤")
        print(f"│  {COLOR_WHITE}[1] รันตามช่วงเวลา 18:00 - 06:00 น. (เลือกบริษัท หรือทั้ง 14 ค่าย - แนะนำ){COLOR_RESET}" + " " * 2 + "│")
        print(f"│  {COLOR_CYAN}[2] รันทันที (โหมดรัน NOW - ตลอด 24 ชม. ไม่จำกัดช่วงเวลา){COLOR_RESET}" + " " * 15 + "│")
        print(f"│  {COLOR_GREEN}[3] รันเฉพาะ กรมบังคับคดี (LED) สแครปเว็บ + ดึงพิกัดจริง LandsMaps{COLOR_RESET}" + " " * 7 + "│")
        print(f"│  {COLOR_YELLOW}[4] รันเฉพาะ ดึงพิกัดจริง LandsMaps (สำหรับไฟล์ CSV เดิม / รันเบื้องหลัง){COLOR_RESET}" + " " * 3 + "│")
        print("└" + "─" * 70 + "┘")
        
        try:
            choice = input("เลือกโหมด [1/2/3/4] (กด Enter = รันตามช่วงเวลา 18:00 - 06:00 น.): ").strip()
        except Exception:
            choice = ""

        if choice in ["2", "n", "N", "now", "NOW"]:
            os.environ["SCRAPER_IGNORE_WINDOW"] = "1"
            main()
        elif choice == "3":
            run_led_workflow()
        elif choice == "4":
            run_landsmaps_only_workflow()
        else:
            main()
    else:
        # เริ่มต้นทำงานทันที (หากอยู่นอกเวลา 18:00 - 06:00 ระบบจะพักรอตามเวลาปกติอัตโนมัติ)
        main()


