from logger_util import (
    AuditedSession,
    AuditedCurlSession,
    log_txn,
    log_info,
    log_warning,
    log_error,
    log_milestone,
    log_success,
    save_scraper_state,
    load_scraper_state,
    reset_scraper_state,
    get_state_file_path,
    safe_ssl_get,
    read_csv_resume,
    atomic_write_csv,
    print_structure_alert,
)
from timeout_handler import wait_1hr_on_timeout, handle_timeout_retry, execute_with_retry
from clean_location_util import clean_row_location, init_gis, clean_floor_val, extract_floor_from_text
try:
    from clean_project_util import clean_project_name, extract_project_from_title
except ImportError:
    clean_project_name = lambda x, **kwargs: str(x).strip()
    extract_project_from_title = lambda x, **kwargs: ""
import requests
import json
import re
import os
import sys
import time
from time_window_util import get_scraper_delay, get_scraper_delay_range
import random
import urllib.parse
from datetime import datetime, timedelta
import concurrent.futures
import threading
import pandas as pd
from bs4 import BeautifulSoup

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

COMPANY_NAME = "DDproperty"
MONTH_STR = datetime.now().strftime("%Y_%m")

_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR
OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"DDproperty_NPA_New_{MONTH_STR}.csv")

CATEGORIES = [
    {
        "type": "รวมประกาศขาย",
        "url": "https://www.ddproperty.com/รวมประกาศขาย"
    }
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Ch-Ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="8"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0"
}

COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคา",
    "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ"
]

PROVINCES = [
    "กรุงเทพมหานคร", "กรุงเทพ", "กระบี่", "กาญจนบุรี", "กาฬสินธุ์", "กำแพงเพชร", "ขอนแก่น", "จันทบุรี",
    "ฉะเชิงเทรา", "ชลบุรี", "ชัยนาท", "ชัยภูมิ", "ชุมพร", "เชียงราย", "เชียงใหม่", "ตรัง", "ตราด",
    "ตาก", "นครนายก", "นครปฐม", "นครพนม", "นครราชสีมา", "นครศรีธรรมราช", "นครสวรรค์", "นนทบุรี",
    "นราธิวาส", "น่าน", "บึงกาฬ", "บุรีรัมย์", "ปทุมธานี", "ประจวบคีรีขันธ์", "ปราจีนบุรี", "ปัตตานี",
    "พระนครศรีอยุธยา", "อยุธยา", "พะเยา", "พังงา", "พัทลุง", "พิจิตร", "พิษณุโลก", "เพชรบุรี",
    "เพชรบูรณ์", "แพร่", "ภูเก็ต", "มหาสารคาม", "มุกดาหาร", "แม่ฮ่องสอน", "ยโสธร", "ยะลา", "ร้อยเอ็ด",
    "ระนอง", "ระยอง", "ราชบุรี", "ลพบุรี", "ลำปาง", "ลำพูน", "เลย", "ศรีสะเกษ", "สกลนคร", "สงขลา",
    "สตูล", "สมุทรปราการ", "สมุทรสงคราม", "สมุทรสาคร", "สระแก้ว", "สระบุรี", "สิงห์บุรี", "สุโขทัย",
    "สุพรรณบุรี", "สุราษฎร์ธานี", "สุรินทร์", "หนองคาย", "หนองบัวลำภู", "อ่างทอง", "อำนาจเจริญ",
    "อุดรธานี", "อุตรดิตถ์", "อุทัยธานี", "อุบลราชธานี", "หัวหิน", "พัทยา"
]

DISTRICTS = [
    "ราชเทวี", "วัฒนา", "บางซื่อ", "คลองเตย", "ห้วยขวาง", "จตุจักร", "บางนา", "ประเวศ", "ลาดกระบัง",
    "สวนหลวง", "ธนบุรี", "คลองสาน", "บางกะปิ", "มีนบุรี", "สายไหม", "ทวีวัฒนา", "บางแค", "ภาษีเจริญ",
    "ศรีราชา", "บางละมุง", "เมือง", "ปากเกร็ด", "คลองหลวง", "ธัญบุรี", "ลำลูกกา", "เมืองนนทบุรี",
    "บางบัวทอง", "บางใหญ่", "เมืองปทุมธานี", "บางพลี", "บางเสาธง", "พระประแดง", "สัตหีบ", "บ้านฉาง",
    "เมืองเชียงใหม่", "หางดง", "สารภี", "สันทราย", "กะทู้", "ถลาง", "เมืองภูเก็ต", "หัวหิน", "ชะอำ"
]

DD_KNOWN_COORDINATES = {
    "11733560": (13.9541418, 100.7003629),
    "500083373": (13.63913407277473, 100.61555266137695),
    "500153112": (13.7386978, 100.5915899),
    "500409382": (13.621590678047562, 100.48659962526416),
    "500139374": (13.7920875, 100.3902656),
    "11382798": (13.7354198, 100.5830695),
    "11333503": (13.7306456, 100.6330301),
    "500093020": (13.6522024, 100.786181),
    "60175059": (13.9594997, 100.4902451),
    "500126028": (13.910099935642506, 100.36210348682101),
    "60171813": (13.688030863519169, 100.65088160315851),
    "60174382": (13.835101, 100.611473),
    "60174406": (13.835101, 100.611473),
    "11417214": (13.95550137489205, 100.48829008014545),
    "60023691": (12.9506943, 102.2776838),
    "60101239": (13.634516, 100.449468),
    "60047459": (13.761920825986545, 100.66233149956285),
    "60047457": (13.761920825986545, 100.66233149956285),
    "500054190": (7.844992289157446, 98.3567283693274),
    "500309892": (13.656155746887865, 100.6218962),
    "11783246": (13.934847200044183, 100.7431434795949),
}

ITEMS_PER_PAGE = 20

def print_alert(msg: str, level: str = "ERROR"):
    border = "=" * 75
    if level == "CRITICAL":
        icon = "🚨 [CRITICAL ALERT]"
    elif level == "WARNING":
        icon = "⚠️ [WARNING ALERT]"
    else:
        icon = "❌ [ERROR ALERT]"
    print(f"\n{border}\n{icon} ({COMPANY_NAME}): {msg}\n{border}\n", flush=True)

def make_progress_bar(pct, length=20):
    filled = int(length * pct / 100)
    bar = '█' * filled + '░' * (length - filled)
    return f"[{bar}] {pct:3d}%"

def format_eta(elapsed_sec, completed_units, total_units, start_unit=1):
    if completed_units <= 0 or total_units <= 0 or elapsed_sec <= 0:
        return "กำลังคำนวณ..."
    completed_in_session = max(1, completed_units - start_unit + 1)
    rate = completed_in_session / elapsed_sec
    remaining_units = max(0, total_units - completed_units)
    if rate <= 0:
        return "กำลังคำนวณ..."
    eta_sec = remaining_units / rate
    finish_clock = datetime.fromtimestamp(datetime.now().timestamp() + eta_sec).strftime("%H:%M:%S")
    mins = int(eta_sec // 60)
    secs = int(eta_sec % 60)
    if mins > 60:
        hrs = mins // 60
        mins = mins % 60
        return f"เหลืออีก ~{hrs}ชม. {mins}น. ({finish_clock} น.)"
    elif mins > 0:
        return f"เหลืออีก ~{mins}น. {secs}ว. ({finish_clock} น.)"
    else:
        return f"เหลืออีก ~{secs}ว. ({finish_clock} น.)"

def parse_rai_ngan_wah_robust(s):
    if s is None or pd.isna(s):
        return None, None, None
    s = str(s).strip()
    if not s or s.lower() in ["nan", "none", "null", "$undefined", "-", "0", "0.0"]:
        return None, None, None
    m_dash = re.match(r'^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$', s)
    if m_dash:
        return float(m_dash.group(1)), float(m_dash.group(2)), float(m_dash.group(3))
    has_thai_units = any(u in s for u in ['ไร่', 'งาน', 'วา', 'ตร.ว', 'ตารางวา', 'ตร.ว.'])
    if has_thai_units:
        m_r = re.search(r'([\d\.,]+)\s*ไร่', s)
        m_g = re.search(r'([\d\.,]+)\s*งาน', s)
        m_w = re.search(r'([\d\.,]+)\s*(?:ตร\.?ว\.?|ตารางวา|วา)', s)
        r = float(m_r.group(1).replace(',', '')) if m_r else 0.0
        g = float(m_g.group(1).replace(',', '')) if m_g else 0.0
        w = float(m_w.group(1).replace(',', '')) if m_w else 0.0
        if r > 0 or g > 0 or w > 0:
            return r, g, w
    clean_num = re.sub(r'[^\d\.]', '', s)
    if clean_num:
        try:
            total_wah = float(clean_num)
            if total_wah > 0:
                r = int(total_wah // 400)
                rem = total_wah - (r * 400)
                g = int(rem // 100)
                w = rem - (g * 100)
                return r, g, round(w, 4)
        except ValueError:
            pass
    return None, None, None

def format_wah_val(w):
    if isinstance(w, float) and w.is_integer():
        return str(int(w))
    elif isinstance(w, int):
        return str(int(w))
    elif isinstance(w, float):
        return f"{w:g}"
    return str(w)

def convert_to_rai_ngan_wah(val):
    r, g, w = parse_rai_ngan_wah_robust(val)
    if r is None:
        return ""
    if w >= 100:
        g += int(w // 100)
        w = w % 100
    if g >= 4:
        r += int(g // 4)
        g = g % 4
    if r == 0 and g == 0 and w == 0:
        return ""
    return f"{int(r)}-{int(g)}-{format_wah_val(w)}"

def clean_text(val):
    if not val:
        return ""
    return re.sub(r"\s+", " ", str(val)).strip()

THAI_MONTHS = {
    'ม.ค.': 1, 'มกราคม': 1, 'ก.พ.': 2, 'กุมภาพันธ์': 2,
    'มี.ค.': 3, 'มีนาคม': 3, 'เม.ย.': 4, 'เมษายน': 4,
    'พ.ค.': 5, 'พฤษภาคม': 5, 'มิ.ย.': 6, 'มิถุนายน': 6,
    'ก.ค.': 7, 'กรกฎาคม': 7, 'ส.ค.': 8, 'สิงหาคม': 8,
    'ก.ย.': 9, 'กันยายน': 9, 'ต.ค.': 10, 'ตุลาคม': 10,
    'พ.ย.': 11, 'พฤศจิกายน': 11, 'ธ.ค.': 12, 'ธันวาคม': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
}

def format_to_thai_date(day, month, year):
    try:
        d = int(day)
        m = int(month)
        y = int(year)
        if y < 2400:
            y += 543
        return f"{d:02d}/{m:02d}/{y}"
    except Exception:
        return ""

def parse_ddproperty_post_date(raw_date=None, text_content=""):
    """
    สกัดเฉพาะ 'วันประกาศ' (โพสต์เมื่อ / ลงประกาศเมื่อ / ประกาศเมื่อ) ของ DDproperty
    และแปลงให้อยู่ในฟอร์แมต DD/MM/YYYY (พ.ศ.)
    ตัด completionYear, builtYear และคำว่า 'สร้างเสร็จ' ออกทั้งหมด
    """
    now_dt = datetime.now()

    # 1. ตรวจสอบ raw_date จาก JSON-LD / NextData (listingDate, createdDate, postDate, datePosted, createdAt)
    if raw_date is not None and str(raw_date).strip():
        # ถ้าเป็น timestamp ตัวเลข (ms หรือ s)
        if isinstance(raw_date, (int, float)) or (isinstance(raw_date, str) and raw_date.strip().isdigit()):
            try:
                ts = float(raw_date)
                if ts > 1e11:
                    ts = ts / 1000.0
                if 1e9 <= ts <= 2e9:
                    dt = datetime.fromtimestamp(ts)
                    return format_to_thai_date(dt.day, dt.month, dt.year)
            except Exception:
                pass

        raw_str = str(raw_date).strip()
        # ตัดกรณีที่เป็นปี 4 หลักอย่างเดียว หรือค่าทศนิยมปี เช่น "2024", "2026.0" (ซึ่งมักเป็น completionYear ที่หลุดมา)
        if not re.match(r'^\d{4}(?:\.\d+)?$', raw_str):
            # ตรวจสอบ ISO format: 2026-09-08 หรือ 2026-09-08T...
            m_iso = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', raw_str)
            if m_iso:
                return format_to_thai_date(m_iso.group(3), m_iso.group(2), m_iso.group(1))

            m_slash = re.search(r'(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})', raw_str)
            if m_slash:
                return format_to_thai_date(m_slash.group(1), m_slash.group(2), m_slash.group(3))

    # 2. ค้นหาจาก text_content (card text หรือ full text) โดยเน้นเฉพาะคำว่า ประกาศเมื่อ / ลงประกาศเมื่อ / โพสต์เมื่อ
    if text_content:
        m_kw = re.search(r'(?:ลงประกาศเมื่อ|ประกาศเมื่อ|โพสต์เมื่อ|posted on|listed on|date posted)', text_content, re.I)
        if m_kw:
            snippet = text_content[m_kw.start():m_kw.start() + 250]

            # 2.1 วันที่แบบไทย เช่น "8 ก.ย. 2569" หรือ "8 กันยายน 2026"
            m_th = re.search(r'(\d{1,2})\s+([ก-๙\w\.]+)\s+(\d{4})', snippet)
            if m_th:
                d = m_th.group(1)
                month_name = m_th.group(2).strip().lower()
                y = m_th.group(3)
                m_num = next((v for k, v in THAI_MONTHS.items() if k in month_name), None)
                if m_num:
                    return format_to_thai_date(d, m_num, y)

            # 2.2 วันที่แบบตัวเลข DD/MM/YYYY หรือ DD-MM-YYYY
            m_num_date = re.search(r'(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})', snippet)
            if m_num_date:
                return format_to_thai_date(m_num_date.group(1), m_num_date.group(2), m_num_date.group(3))

            # 2.3 วันที่แบบสัมพัทธ์ (Relative dates) เช่น "3 วันก่อน", "1 สัปดาห์ก่อน", "2 เดือนก่อน"
            m_rel_d = re.search(r'(\d+)\s*(?:day|วัน)(?:ที่)?(?:ก่อน|ที่แล้ว)?', snippet, re.I)
            m_rel_w = re.search(r'(\d+)\s*(?:week|สัปดาห์)(?:ที่)?(?:ก่อน|ที่แล้ว)?', snippet, re.I)
            m_rel_m = re.search(r'(\d+)\s*(?:month|เดือน)(?:ที่)?(?:ก่อน|ที่แล้ว)?', snippet, re.I)
            if m_rel_d:
                dt = now_dt - timedelta(days=int(m_rel_d.group(1)))
                return format_to_thai_date(dt.day, dt.month, dt.year)
            elif m_rel_w:
                dt = now_dt - timedelta(weeks=int(m_rel_w.group(1)))
                return format_to_thai_date(dt.day, dt.month, dt.year)
            elif m_rel_m:
                dt = now_dt - timedelta(days=int(m_rel_m.group(1)) * 30)
                return format_to_thai_date(dt.day, dt.month, dt.year)
            elif any(w in snippet for w in ['เมื่อวาน', 'yesterday']):
                dt = now_dt - timedelta(days=1)
                return format_to_thai_date(dt.day, dt.month, dt.year)
            elif any(w in snippet for w in ['วันนี้', 'today']):
                return format_to_thai_date(now_dt.day, now_dt.month, now_dt.year)

    return ""

def parse_dd_location(title, link, text):
    combined = f"{title} {link} {text}"
    prov, dist, subdist = "", "", ""
    for p in PROVINCES:
        if p in combined:
            if p == "ตราด" and any(k in combined for k in ["บางนา-ตราด", "บางนา - ตราด", "บางนาตราด", "บางนา"]):
                continue
            prov = "กรุงเทพมหานคร" if p == "กรุงเทพ" or p == "กรุงเทพมหานคร" else p
            if prov == "พัทยา": prov = "ชลบุรี"; dist = "บางละมุง"
            elif prov == "หัวหิน": prov = "ประจวบคีรีขันธ์"; dist = "หัวหิน"
            break
    if not dist:
        for d in DISTRICTS:
            if d in combined:
                dist = d
                break
    if dist == "กันทรลักษ์":
        prov = "ศรีสะเกษ"
    elif dist == "บางนา" and (not prov or prov == "ตราด"):
        prov = "กรุงเทพมหานคร"
                
    # Filter out text lines that contain room/land specs before matching comma-separated address
    clean_text_lines = []
    for line in str(text).split('\n'):
        if any(w in line for w in ["ห้องนอน", "ห้องน้ำ", "ไร่", "งาน", "ตร.ว.", "ตารางวา", "ตร.ม.", "ตารางเมตร", "ชั้น"]):
            continue
        clean_text_lines.append(line)
    filtered_text = " ".join(clean_text_lines)

    m_loc = re.search(r'([ก-๙\s]+)\s*,\s*([ก-๙\s]+)\s*,\s*([ก-๙\s]+)', filtered_text)
    if m_loc:
        s_cand = m_loc.group(1).strip()
        d_cand = m_loc.group(2).strip()
        p_cand = m_loc.group(3).strip()
        junk_kws = ["นายหน้า", "แนะนำ", "ขาย", "เช่า", "ห้องนอน", "ห้องน้ำ", "ไร่", "ซอย", "ถนน", "โครงการ", "มิวนีค"]
        if not subdist and len(s_cand) < 25 and not any(x in s_cand for x in junk_kws):
            subdist = s_cand
        if not dist and len(d_cand) < 20 and not any(x in d_cand for x in junk_kws): dist = d_cand
        if not prov and len(p_cand) < 20 and not any(x in p_cand for x in junk_kws): prov = p_cand
    return subdist, dist, prov

def parse_ddproperty_price(price_raw, text_hint=''):
    if price_raw is None:
        return None
        
    # 1. If dict from JSON
    if isinstance(price_raw, dict):
        val = price_raw.get('value')
        if isinstance(val, (int, float)) and val > 0:
            return float(val)
            
        min_p = price_raw.get('min') or price_raw.get('minPrice') or price_raw.get('from')
        if isinstance(min_p, (int, float)) and min_p > 0:
            return float(min_p)
            
        p_str = str(price_raw.get('pretty') or price_raw.get('localeStringValue') or price_raw.get('text') or '')
    elif isinstance(price_raw, (int, float)):
        return float(price_raw)
    else:
        p_str = str(price_raw)
        
    if not p_str or p_str.lower() in ['nan', 'none', 'null', '-']:
        return None
        
    # Check ฿ patterns if text contains ฿
    m_b = re.findall(r'฿\s*([\d\.,]+)', p_str)
    if m_b:
        first_clean = m_b[0].replace(',', '').strip()
        try:
            val_f = float(first_clean)
            if val_f >= 500:
                return val_f
        except Exception:
            pass

    # Split range if present (e.g. ฿18,900,000 - ฿21,900,000 or 18.9M - 21.9M)
    parts = re.split(r'\s*(?:[-–—~]|ถึง|\bto\b)\s*', p_str, flags=re.I)
    candidate_strs = [p for p in parts if p.strip()]
    
    for p_part in candidate_strs:
        # Check Million shorthand: 18.9M, 18.9 ล้าน
        m_mil = re.search(r'([\d\.]+)\s*(?:M|ล้าน|m)', p_part)
        if m_mil:
            try:
                val_m = float(m_mil.group(1)) * 1_000_000
                if val_m >= 500:
                    return val_m
            except Exception:
                pass
                
        p_clean = re.sub(r'[^\d\.]', '', p_part)
        if len(p_clean) > 8 and len(p_clean) % 2 == 0 and p_clean[:len(p_clean)//2] == p_clean[len(p_clean)//2:]:
            p_clean = p_clean[:len(p_clean)//2]
            
        try:
            val_f = float(p_clean)
            if val_f >= 500:
                # If number still looks like two 6-8 digit numbers concatenated (e.g. 1890000021900000)
                if val_f > 1e11:
                    digits = re.sub(r'[^\d]', '', p_clean.split('.')[0])
                    if len(digits) in [14, 15, 16]:
                        half = len(digits) // 2
                        first_p = float(digits[:half])
                        if 10_000 <= first_p <= 1e9:
                            return first_p
                    elif len(digits) == 14:
                        return float(digits[:7])
                    elif len(digits) == 13:
                        return float(digits[:6])
                return val_f
        except Exception:
            pass
            
    return None

def load_existing_csv(filename, session=None):
    if "--fresh" in sys.argv or "--force-restart" in sys.argv:
        print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นดึงข้อมูลใหม่ทั้งหมดจากหน้าแรก (โหมด --fresh)", flush=True)
        reset_scraper_state(COMPANY_NAME, MONTH_STR)
        return [], set()
    return read_csv_resume(filename, COLUMNS, id_col="ID", company_name=COMPANY_NAME)

def _http_get_ddproperty(session, url, timeout=100, headers=None):
    try:
        r = safe_ssl_get(session, url, timeout=timeout, headers=headers, ssl_fallback_on_gov=False)
        return r.status_code, r.text
    except Exception:
        return 0, ""

def get_category_total_pages(session, base_url) -> tuple[int, int]:
    raw_path = "/รวมประกาศขาย"
    url = "https://www.ddproperty.com" + urllib.parse.quote(raw_path)
    def _probe():
        status, html_text = _http_get_ddproperty(session, url, timeout=100)
        if status != 200 or not html_text:
            raise TimeoutError(f"DDproperty HTTP {status}")
        return status, html_text

    try:
        status, html_text = execute_with_retry(_probe, company_name=COMPANY_NAME, context_msg="DDproperty Health Probe", max_retries=3, max_cooldown_cycles=1)
        soup = BeautifulSoup(html_text, 'html.parser')
        script = soup.find("script", id="__NEXT_DATA__")
        script_content = (script.string or script.text) if script else ""
        if script_content:
            js = json.loads(script_content)
            page_data = js.get("props", {}).get("pageProps", {}).get("pageData", {})
            data_dict = page_data.get("data", {})
            pagination = data_dict.get("paginationData", {})
            tp = pagination.get("totalPages")
            if tp and int(tp) > 0:
                return status, int(tp)
        print_structure_alert(COMPANY_NAME, "ไม่พบค่า totalPages ใน __NEXT_DATA__ ของ DDproperty (โครงสร้างเว็บอาจเปลี่ยนแปลง)")
        return status, 0
    except Exception:
        return 0, 0

def fetch_ddproperty_page(session, base_url, target_type, page_num, cooldown_cycles=0):
    if page_num == 1:
        raw_path = "/รวมประกาศขาย"
    else:
        raw_path = f"/รวมประกาศขาย/{page_num}"
    url = "https://www.ddproperty.com" + urllib.parse.quote(raw_path)

    def _fetch_parse_once():
        if True:
            time.sleep(get_scraper_delay()) # หน่วงเวลาอย่างน้อย 15 วินาที
            status, html_text = _http_get_ddproperty(session, url, timeout=100)
            if status != 200 or not html_text:
                raise TimeoutError(f"หน้า {page_num} (HTTP {status})")
                
            soup = BeautifulSoup(html_text, 'html.parser')
            records = []
            now_str = datetime.now().strftime("%Y-%m-%d")
            
            # 1. Try __NEXT_DATA__ JSON first
            script = soup.find("script", id="__NEXT_DATA__")
            script_content = (script.string or script.text) if script else ""
            if script_content:
                js = json.loads(script_content)
                page_data = js.get("props", {}).get("pageProps", {}).get("pageData", {})
                listings = page_data.get("data", {}).get("listingsData", [])
                for listing in listings:
                    ld = listing.get("listingData", {}) or listing
                    prop = ld.get("property", {}) or {}
                    lid = str(ld.get("id") or listing.get("id") or "")
                    if not lid: continue
                    
                    title = clean_text(ld.get("localizedTitle") or ld.get("title") or ld.get("name") or ld.get("heading") or listing.get("title") or listing.get("name") or "")
                    code = clean_text(ld.get("code") or ld.get("listingCode") or ld.get("propertyCode") or "")
                    if not code:
                        code = lid
                    
                    prop_type = prop.get("subTypeText") or ld.get("localizedPropertyType") or ld.get("propertyTypeLabel") or ld.get("typeText") or target_type
                    prop_type = re.sub(r'^ขาย', '', str(prop_type)).strip() or "บ้านเดี่ยว"
                    
                    link = ld.get("url") or ""
                    if link and not link.startswith('http'): link = 'https://www.ddproperty.com' + link
                    
                    # Title fallback from HTML link tag matching lid if localizedTitle missing
                    card_match = soup.find('a', href=re.compile(rf'-{lid}(?:#|$|\?)')) or soup.find('a', href=re.compile(rf'/{lid}(?:#|$|\?)'))
                    card_parent = card_match.find_parent(class_=re.compile(r'listing-card|hui-card', re.I)) if card_match else None
                    if card_match and not link:
                        link = card_match.get('href', '')
                        if link and not link.startswith('http'): link = 'https://www.ddproperty.com' + link
                    
                    if not title and card_match:
                        if not title or len(title) < 3 or any(x in title.upper() for x in ["จำกัด", "นายหน้า", "CO., LTD"]):
                            parts = link.split('/property/')[-1].split('/project/')[-1].split('#')[0].split('?')[0].split('-ขาย-')[0]
                            title = urllib.parse.unquote(parts).replace('-', ' ').strip().title()
                    if title.startswith("Project/"):
                        title = title.replace("Project/", "").strip()
                    if not link:
                        link = f"https://www.ddproperty.com/property/{lid}"
                        
                    price_raw = ld.get("price") or listing.get("price")
                    price = parse_ddproperty_price(price_raw, text_hint=title)
                    if not price and card_match:
                        price = parse_ddproperty_price(card_parent.get_text() if card_parent else "")
                        
                    # 1. Structured location from additionalData / segment / shortAddress / fullAddress
                    add_data = ld.get("additionalData", {}) or {}
                    seg_data = listing.get("segment", {}).get("parameters", {}).get("metaData", {}).get("listingData", {}) or {}

                    subdist = clean_text(add_data.get("areaText") or seg_data.get("areaName") or "")
                    dist = clean_text(add_data.get("districtText") or seg_data.get("districtName") or "")
                    prov = clean_text(add_data.get("regionText") or seg_data.get("regionName") or "")

                    if not prov or not dist or not subdist:
                        short_addr = clean_text(ld.get("shortAddress") or ld.get("fullAddress") or "")
                        if short_addr and "," in short_addr:
                            parts = [p.strip() for p in short_addr.split(",") if p.strip()]
                            if len(parts) >= 3:
                                if not subdist: subdist = parts[-3]
                                if not dist: dist = parts[-2]
                                if not prov: prov = parts[-1]
                            elif len(parts) == 2:
                                if not dist: dist = parts[-2]
                                if not prov: prov = parts[-1]
                            elif len(parts) == 1 and not prov:
                                prov = parts[0]

                    if not prov or not dist or not subdist:
                        addr = ld.get("address", {}) or ld.get("localizedAddress", {}) or listing.get("address", {}) or listing.get("localizedAddress", {})
                        if isinstance(addr, str) and "," in addr:
                            parts = [x.strip() for x in addr.split(",") if x.strip()]
                            if len(parts) >= 3 and not subdist: subdist, dist, prov = parts[0], parts[1], parts[2]
                            elif len(parts) == 2 and not dist: dist, prov = parts[0], parts[1]
                            elif len(parts) == 1 and not prov: prov = parts[0]
                        elif isinstance(addr, dict):
                            if not prov: prov = clean_text(addr.get("province") or addr.get("region") or addr.get("state") or "")
                            if not dist: dist = clean_text(addr.get("district") or addr.get("city") or "")
                            if not subdist: subdist = clean_text(addr.get("subdistrict") or addr.get("area") or "")
                            
                    card_text = card_parent.get_text() if card_parent else str(listing)
                    
                    s_fb, d_fb, p_fb = parse_dd_location(title, link, card_text)
                    if not prov: prov = p_fb
                    if not dist: dist = d_fb
                    if not subdist: subdist = s_fb

                    coords = ld.get("coordinates", {}) or ld.get("location", {}) or ld.get("geo", {}) or listing.get("coordinates", {}) or listing.get("location", {}) or {}
                    lat, lng = None, None
                    if isinstance(coords, dict):
                        lat = coords.get("lat") or coords.get("latitude")
                        lng = coords.get("lng") or coords.get("longitude") or coords.get("lon")
                        
                    if not lat and card_parent:
                        m_map = re.search(r'(?:center|query|markers|staticmap|location|ll|q|destination)[^"\']*=([0-9\.\-]+)[,%2C]+([0-9\.\-]+)', str(card_parent), re.I)
                        if m_map:
                            try:
                                v1, v2 = float(m_map.group(1)), float(m_map.group(2))
                                if 5.0 <= v1 <= 21.0 and 97.0 <= v2 <= 106.0:
                                    lat, lng = v1, v2
                            except Exception: pass

                    area_raw = ld.get("area") or ld.get("usableArea") or listing.get("area")
                    area_str = ""
                    if isinstance(area_raw, dict):
                        area_str = clean_text(area_raw.get("localeStringValue") or area_raw.get("value") or "")
                    elif area_raw:
                        area_str = clean_text(area_raw)
                        
                    land_area = ""
                    usable_area = ""
                    
                    # 1. Check direct land area fields from listing JSON (unitDetails / dimensions / landAreaText)
                    land_raw = ld.get("landAreaText") or ld.get("landArea")
                    if not land_raw and isinstance(listing.get("unitDetails"), dict):
                        dims = listing["unitDetails"].get("dimensions", {}).get("land", {}).get("size", [])
                        for dim in dims:
                            if isinstance(dim, dict) and any(w in str(dim.get("formatted")) for w in ["วา", "ตร.ว.", "ไร่", "งาน"]):
                                land_raw = dim.get("formatted")
                                break
                    if land_raw and any(w in str(land_raw) for w in ["วา", "ตร.ว.", "ไร่", "งาน", "ตารางวา"]):
                        land_area = str(land_raw).strip()

                    # 2. Check floor area (usable area)
                    floor_raw = ld.get("floorAreaText") or ld.get("floorArea") or ld.get("usableAreaText")
                    if floor_raw:
                        m_f = re.search(r'([\d\.,]+)', str(floor_raw))
                        if m_f: usable_area = m_f.group(1).replace(',', '').strip()

                    # 3. Fallback parse from area_str or listing card_text for ไร่/งาน/วา/ตร.ว./ตารางวา
                    if not land_area:
                        full_search_text = area_str + " " + card_text
                        m_land_full = re.search(r'((?:\d+\s*ไร่\s*)?(?:\d+\s*งาน\s*)?[\d\.,]+\s*(?:ตร\.ว\.|ตร\.วา|ตารางวา|วา))', full_search_text, re.I)
                        if m_land_full:
                            land_area = m_land_full.group(1).strip()

                    if not usable_area and area_str:
                        if re.search(r'ตร\.ม\.|ตารางเมตร', area_str):
                            m_num = re.search(r'([\d\.,]+)', area_str)
                            if m_num: usable_area = m_num.group(1).replace(',', '').strip()
                        
                    # วันประกาศ: ดึงเฉพาะวันลงประกาศจริง (โพสต์เมื่อ / ลงประกาศเมื่อ / ประกาศเมื่อ) แปลงเป็น DD/MM/YYYY (พ.ศ.)
                    # ตัด completionYear, builtYear และคำว่า 'สร้างเสร็จ' ออกทั้งหมด
                    raw_post_val = ld.get("listingDate") or ld.get("createdDate") or ld.get("postDate") or ld.get("datePosted") or ld.get("createdAt") or ""
                    post_date = parse_ddproperty_post_date(raw_date=raw_post_val, text_content=card_text)
                    
                    floor_val = clean_floor_val(ld.get("floor") or ld.get("floorLevel") or ld.get("floors") or ld.get("totalFloors") or listing.get("floor") or listing.get("floorLevel"))
                    if not floor_val:
                        floor_val = extract_floor_from_text(title, card_text, asset_type=prop_type)
                    
                    records.append({
                        "บริษัท": COMPANY_NAME,
                        "ID": lid,
                        "รหัสทรัพย์": code,
                        "ชื่อโครงการ": extract_project_from_title(title, tambon=subdist, amphoe=dist, province=prov, company=COMPANY_NAME) if extract_project_from_title else "",
                        "ประเภททรัพย์": prop_type,
                        "ประเภทการขาย": "ขาย",
                        "ราคา": price,
                        "ตำบล": subdist,
                        "อำเภอ": dist,
                        "จังหวัด": prov,
                        "ละติจูด": lat,
                        "ลองจิจูด": lng,
                        "ชื่อประกาศ": title,
                        "ลิงก์": link,
                        "เนื้อที่ (ตร.ว.)": convert_to_rai_ngan_wah(land_area),
                        "พื้นที่ใช้สอย (ตร.ม.)": usable_area,
                        "วันที่ดึงข้อมูล": now_str,
                        "ห้องนอน": ld.get("bedrooms"),
                        "ห้องน้ำ": ld.get("bathrooms"),
                        "ที่จอดรถ": None,
                        "ชั้น": floor_val or "",
                        "วันประกาศ": post_date
                    })
                    
            # 2. Fallback to HTML cards if records empty
            if not records:
                cards = soup.find_all(class_=re.compile(r'listing-card|property-card|hui-card', re.I))
                top_cards = []
                for c in cards:
                    classes = [str(k) for k in (c.get('class') or [])]
                    if 'hui-card' in classes and any('listing-card' in k for k in classes):
                        top_cards.append(c)
                        
                for card in top_cards:
                    card_html = str(card)
                    text = re.sub(r'\s+', ' ', card.get_text()).strip()
                    
                    a_tag = card.find('a', href=re.compile(r'/property/|/project/')) or card.find('a', href=True)
                    link = a_tag['href'] if a_tag else ""
                    if link and not link.startswith('http'): link = 'https://www.ddproperty.com' + link
                    m_id = re.search(r'-(\d+)(?:#|$|\?)', link) or re.search(r'/(\d+)(?:#|$|\?)', link)
                    lid = m_id.group(1) if m_id else ""
                    if not lid: continue
                    
                    title = ""
                    if a_tag and a_tag.get('title'): title = clean_text(a_tag['title'])
                    if not title and a_tag: title = clean_text(a_tag.get_text())
                    if not title or len(title) < 3 or any(x in title.upper() for x in ["จำกัด", "นายหน้า", "CO., LTD"]):
                        parts = link.split('/property/')[-1].split('/project/')[-1].split('#')[0].split('?')[0].split('-ขาย-')[0]
                        title = urllib.parse.unquote(parts).replace('-', ' ').strip().title()
                    title = re.sub(r'^(?:บริษัท|นายหน้า).*?จำกัด\s*', '', title, flags=re.I).strip() or title
                    
                    price = parse_ddproperty_price(text, text_hint=title)
                        
                    subdist, dist, prov = parse_dd_location(title, link, text)
                    
                    lat, lng = None, None
                    m_map = re.search(r'(?:center|query|markers|staticmap)[^"\']*=([\d\.-]+)%2C([\d\.-]+)', card_html, re.I) or re.search(r'(?:center|query|markers|staticmap)[^"\']*=([\d\.-]+),([\d\.-]+)', card_html, re.I)
                    if m_map:
                        try:
                            lat = float(m_map.group(1))
                            lng = float(m_map.group(2))
                        except Exception:
                            pass
                            
                    # วันประกาศ fallback จากข้อความการ์ด HTML (ตัด 'สร้างเสร็จ' ออกเด็ดขาด)
                    post_date = parse_ddproperty_post_date(raw_date=None, text_content=text)
                        
                    bed, bath = None, None
                    m_bed = re.search(r'(\d+)\s*ห้องนอน', text)
                    if m_bed: bed = int(m_bed.group(1))
                    m_bath = re.search(r'(\d+)\s*ห้องน้ำ', text)
                    if m_bath: bath = int(m_bath.group(1))
                    
                    land_area = ""
                    usable_area = ""
                    m_land = re.search(r'([\d\.,]+)\s*(?:ตร\.ว\.|ตารางวา)', text, re.I)
                    if m_land:
                        land_area = m_land.group(1).replace(',', '').strip()
                    m_u = re.search(r'([\d\.,]+)\s*(?:ตร\.ม\.|ตารางเมตร)', text, re.I)
                    if m_u:
                        usable_area = m_u.group(1).replace(',', '').strip()
                    
                    floor_val = extract_floor_from_text(title, text, card_html, asset_type=target_type)

                    records.append({
                        "บริษัท": COMPANY_NAME,
                        "ID": lid,
                        "รหัสทรัพย์": lid,
                        "ชื่อโครงการ": extract_project_from_title(title, tambon=subdist, amphoe=dist, province=prov, company=COMPANY_NAME) if extract_project_from_title else "",
                        "ประเภททรัพย์": target_type,
                        "ประเภทการขาย": "ขาย",
                        "ราคา": price,
                        "ตำบล": subdist,
                        "อำเภอ": dist,
                        "จังหวัด": prov,
                        "ละติจูด": lat,
                        "ลองจิจูด": lng,
                        "ชื่อประกาศ": title,
                        "ลิงก์": link,
                        "เนื้อที่ (ตร.ว.)": convert_to_rai_ngan_wah(land_area),
                        "พื้นที่ใช้สอย (ตร.ม.)": usable_area,
                        "วันที่ดึงข้อมูล": now_str,
                        "ห้องนอน": bed,
                        "ห้องน้ำ": bath,
                        "ที่จอดรถ": None,
                        "ชั้น": floor_val or "",
                        "วันประกาศ": post_date
                    })
            if records:
                records = enrich_ddproperty_coords(records, session)
            return records

    try:
        return execute_with_retry(_fetch_parse_once, company_name=COMPANY_NAME, context_msg=f"หน้า {page_num} ({target_type})", max_retries=5, max_cooldown_cycles=2)
    except Exception as e:
        print_alert(f"เกิดข้อผิดพลาดในการดึงข้อมูลหน้า {page_num} ({target_type}): {e}", level="WARNING")
        log_warning(COMPANY_NAME, f"ข้ามหน้า {page_num} ({target_type}) เนื่องจากพักรอและลองซ้ำไม่สำเร็จ")
        return None

REFERER_LISTING_URL = "https://www.ddproperty.com" + urllib.parse.quote("/รวมประกาศขาย")

def fetch_ddproperty_detail_coords(session, target, referer_url=None, prop_type=""):
    """
    Fetches real GPS coordinates and floor directly from the DDproperty detail page.
    Searches __NEXT_DATA__ for:
    - listingLocationData.data.center (lat/lng)
    - descriptionBlockData.description (เกี่ยวกับคุณสมบัตินี้) -> extracts unit floor (e.g. 'ห้องอยู่ชั้นที่ : 25', 'ชั้น 23')
    - detailsData.metatable.items (รายละเอียดอสังหาฯ)
    """
    try:
        t = str(target or "").strip()
        if not t:
            return None, None, None
        if t.startswith("http"):
            url = t
        elif t.startswith("/"):
            url = "https://www.ddproperty.com" + t
        else:
            url = f"https://www.ddproperty.com/property/{t}"
            
        hdrs = dict(HEADERS)
        hdrs["Referer"] = referer_url or REFERER_LISTING_URL
        
        for attempt in range(2):
            time.sleep(get_scraper_delay())  # พักอย่างน้อย 15 วินาทีต่อรายการ (Safe pacing ป้องกัน WAF / Rate limit บล็อก)
            status, html_text = _http_get_ddproperty(session, url, timeout=100, headers=hdrs)
            if status == 200 and html_text:
                lat, lng, floor = None, None, None
                
                # 1. Parse __NEXT_DATA__ JSON
                soup = BeautifulSoup(html_text, 'html.parser')
                script = soup.find('script', id='__NEXT_DATA__')
                if script and script.string:
                    try:
                        js = json.loads(script.string)
                        pdata = js.get('props', {}).get('pageProps', {}).get('pageData', {}).get('data', {})
                        
                        # Priority A for coords: listingLocationData.data.center
                        center = pdata.get('listingLocationData', {}).get('data', {}).get('center', {})
                        if center and 'lat' in center and 'lng' in center:
                            v1, v2 = float(center['lat']), float(center['lng'])
                            if 5.0 <= v1 <= 21.0 and 97.0 <= v2 <= 106.0:
                                lat, lng = v1, v2
                                
                        items = pdata.get('detailsData', {}).get('metatable', {}).get('items', [])
                        
                        # Priority 1 for floor: Dedicated floor icon from detailsData / metatable (layers-2-o)
                        for it in items:
                            icon = str(it.get('icon', ''))
                            val = str(it.get('value', '')).strip()
                            if 'layer' in icon or 'stair' in icon:
                                f = clean_floor_val(val) or extract_floor_from_text(val, asset_type=prop_type)
                                if f:
                                    floor = f
                                    break

                        # Priority 2: Extract floor from descriptionBlockData: 'เกี่ยวกับคุณสมบัตินี้'
                        if not floor:
                            desc_raw = pdata.get('descriptionBlockData', {}).get('description', '')
                            if desc_raw:
                                clean_desc = BeautifulSoup(desc_raw, 'html.parser').get_text(' ')
                                floor = extract_floor_from_text(clean_desc, asset_type=prop_type)
                            
                        # Priority 3: Fallback floor from other detailsData / metatable items (STRICTLY EXCLUDE area/measurement items)
                        if not floor:
                            for it in items:
                                icon = str(it.get('icon', ''))
                                val = str(it.get('value', '')).strip()
                                # ข้ามไอคอนและข้อความที่เป็นพื้นที่/การวัด/ราคาต่อตารางเมตรอย่างเด็ดขาด
                                if icon in ['ruler-o', 'auto-size-o', 'asterisk-o']:
                                    continue
                                if 'พื้นที่' in val or any(u in val for u in ['ตร.ม.', 'ตารางเมตร', 'sqm', 'sq.m.', 'ตร.ว.', 'ตารางวา']):
                                    continue
                                if 'ชั้น' in val:
                                    f = extract_floor_from_text(val, asset_type=prop_type)
                                    if f:
                                        floor = f
                                        break
                    except Exception:
                        pass
                
                # Regex fallbacks if coords still not found
                if not lat:
                    m = re.search(r'"center"\s*:\s*\{"lat"\s*:\s*([\d\.-]+)\s*,\s*"lng"\s*:\s*([\d\.-]+)\}', html_text)
                    if m:
                        v1, v2 = float(m.group(1)), float(m.group(2))
                        if 5.0 <= v1 <= 21.0 and 97.0 <= v2 <= 106.0:
                            lat, lng = v1, v2
                if not lat:
                    m2 = re.search(r'"point"\s*:\s*\{"lat"\s*:\s*([\d\.-]+)\s*,\s*"lon"\s*:\s*([\d\.-]+)\}', html_text)
                    if m2:
                        v1, v2 = float(m2.group(1)), float(m2.group(2))
                        if 5.0 <= v1 <= 21.0 and 97.0 <= v2 <= 106.0:
                            lat, lng = v1, v2
                if not lat:
                    m3 = re.search(r'"geo"\s*:\s*\{[^}]*"latitude"\s*:\s*([\d\.-]+)\s*,\s*"longitude"\s*:\s*([\d\.-]+)', html_text)
                    if m3:
                        v1, v2 = float(m3.group(1)), float(m3.group(2))
                        if 5.0 <= v1 <= 21.0 and 97.0 <= v2 <= 106.0:
                            lat, lng = v1, v2

                # Fallback floor from full page text if still not found (clean area text first)
                if not floor:
                    clean_soup_text = re.sub(r'พื้นที่(?:ชั้น|ใช้สอย)?\s*[:\s]*[\d\.,]+\s*(?:ตร\.?ม|ตรม|ตารางเมตร|sqm)?', ' ', soup.text, flags=re.I)
                    floor = extract_floor_from_text(clean_soup_text, asset_type=prop_type)

                return lat, lng, floor
            elif status in (429, 503) and attempt == 0:
                time.sleep(get_scraper_delay())
                continue
            else:
                break
    except Exception:
        pass
    return None, None, None

def is_empty_coord(val):
    if val is None: return True
    v_str = str(val).strip().lower()
    return v_str == "" or v_str == "nan" or v_str == "none" or v_str == "0"

def enrich_ddproperty_coords(records, session=None, max_workers=1):
    """
    Coordinate and Floor Resolution Pipeline:
    Priority 1: Real GPS Coordinates & Floor from Detail Page (fetch_ddproperty_detail_coords)
    Priority 2: Known Coordinates cache (DD_KNOWN_COORDINATES)
    Priority 3: Offline GIS Centroid Imputation (clean_row_location)
    """
    need_detail_fetch = []
    for r in records:
        # ทำความสะอาดค่าชั้นเดิมด้วย clean_floor_val ป้องกันค่าพื้นที่หลุดเข้ามา
        cleaned_fl = clean_floor_val(r.get("ชั้น"), usable_area=r.get("พื้นที่ใช้สอย (ตร.ม.)"))
        r["ชั้น"] = cleaned_fl or ""
        
        needs_coords = is_empty_coord(r.get("ละติจูด")) or is_empty_coord(r.get("ลองจิจูด"))
        is_condo = any(k in str(r.get("ประเภททรัพย์", "")) for k in ["คอนโด", "ห้องชุด", "อาคารชุด", "condo", "apartment"])
        needs_floor = is_condo and not r.get("ชั้น")
        if needs_coords or needs_floor:
            need_detail_fetch.append(r)

    if session and need_detail_fetch:
        def _fetch_gps(row):
            link = row.get("ลิงก์") or row.get("ID")
            ptype = row.get("ประเภททรัพย์", "")
            lat, lng, floor = fetch_ddproperty_detail_coords(session, link, referer_url=REFERER_LISTING_URL, prop_type=ptype)
            if lat and lng and (is_empty_coord(row.get("ละติจูด")) or is_empty_coord(row.get("ลองจิจูด"))):
                row["ละติจูด"] = lat
                row["ลองจิจูด"] = lng
            if floor and not row.get("ชั้น"):
                row["ชั้น"] = floor

        for row in need_detail_fetch:
            _fetch_gps(row)

    # Priority 2: Fallback to Known Coordinates cache for any still missing
    for r in records:
        if is_empty_coord(r.get("ละติจูด")) or is_empty_coord(r.get("ลองจิจูด")):
            lid = str(r.get("ID") or "").strip()
            if lid in DD_KNOWN_COORDINATES:
                lat_k, lng_k = DD_KNOWN_COORDINATES[lid]
                r["ละติจูด"] = lat_k
                r["ลองจิจูด"] = lng_k

    # Priority 3: Fallback to GIS Centroid Imputation for any remaining empty coordinates
    for r in records:
        clean_row_location(r)
        
    return records

def save_to_csv(records, filename, session=None):
    return atomic_write_csv(records, filename, COLUMNS, company_name=COMPANY_NAME)

STATE_FILE = get_state_file_path(COMPANY_NAME, MONTH_STR)

def load_state():
    return load_scraper_state(COMPANY_NAME, MONTH_STR).get("completed_pages", 0)

def save_state(completed_pages, total_pages=0, total_records=0, status="RUNNING", extra=None):
    save_scraper_state(COMPANY_NAME, completed_pages, total_pages=total_pages, total_records=total_records, status=status, month_str=MONTH_STR, extra=extra)

def main():
    print(f"==================================================", flush=True)
    print(f"🚀 เริ่มต้นการ Scrape [{COMPANY_NAME}] (Monthly Mode)", flush=True)
    print(f"📁 บันทึกข้อมูลลงไฟล์: {OUTPUT_CSV}", flush=True)
    print(f"==================================================", flush=True)

    init_gis()
    session = AuditedCurlSession(company_name=COMPANY_NAME, impersonate="chrome120")
    session.headers.update(HEADERS)

    saved_milestones = set()
    failed_pages = []
    start_time = time.time()

    total_task_pages = 0
    cat_tasks = []
    last_code = 0

    for cat in CATEGORIES:
        code, tp = get_category_total_pages(session, cat["url"])
        if code > 0:
            last_code = code
        if code == 200 and tp > 0:
            total_task_pages += tp
            cat_tasks.append((cat["type"], cat["url"], tp))

    if last_code != 200 or total_task_pages <= 0:
        print_alert(f"ไม่สามารถเข้าถึง DDproperty ได้ (HTTP Status: {last_code} | Pages: {total_task_pages})", level="CRITICAL")
        sys.exit(1)

    status_msg = f"🌐 สถานะลิงก์: ปกติ (HTTP {last_code}) | ทั้งหมด {len(cat_tasks)} หมวด ({total_task_pages:,} หน้า) | {ITEMS_PER_PAGE} รายการ/หน้า (พบทั้งหมด ~{total_task_pages*ITEMS_PER_PAGE:,} รายการ)"
    print(f"[{COMPANY_NAME}] {status_msg}", flush=True)

    all_records, seen_ids = load_existing_csv(OUTPUT_CSV, session=session)
    saved_state = load_scraper_state(COMPANY_NAME, MONTH_STR)
    prev_failed_pages = [int(p) for p in (saved_state.get("failed_pages") or []) if str(p).isdigit()]

    estimated_total = total_task_pages * ITEMS_PER_PAGE
    if not prev_failed_pages and estimated_total > 0 and len(all_records) > 0 and (len(all_records) >= estimated_total or saved_state.get("status") == "COMPLETED"):
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลใน CSV ครบถ้วน 100% แล้ว ({total_task_pages:5,d}/{total_task_pages:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{estimated_total:,d} รายการ -> สแครปเสร็จสมบูรณ์ทันที!", flush=True)
        save_to_csv(all_records, OUTPUT_CSV, session=session)
        save_state(total_task_pages, total_task_pages, len(all_records), status="COMPLETED")
        log_success(COMPANY_NAME, f"✅ ข้อมูลใน CSV ครบถ้วน 100% อยู่แล้ว ({len(all_records):,} รายการ)")
        return

    completed_pages = min(total_task_pages - 1, len(all_records) // ITEMS_PER_PAGE) if total_task_pages > 0 else 0
    saved_page = int(saved_state.get("completed_pages", 0) or 0)
    start_page = max(completed_pages, saved_page)
    start_page = min(total_task_pages - 1, start_page) if total_task_pages > 0 else 0
    processed_pages = start_page
    new_added = 0

    if start_page > 0:
        pct_start = int((start_page / total_task_pages) * 100) if total_task_pages > 0 else 0
        print(f"[{COMPANY_NAME}] ⏩ Smart Fast-Forward: ข้ามหน้าที่เคยดึงแล้ว 1..{start_page:,} หน้า ({pct_start}%) -> กระโดดไปต่อหน้าที่ {start_page + 1:,} ทันที!", flush=True)

    global_offset = 0
    for ctype, curl, total_p in cat_tasks:
        cat_start = max(0, start_page - global_offset)
        pages_order = sorted(set([p for p in prev_failed_pages if 1 <= p <= cat_start] + list(range(cat_start + 1, total_p + 1))))
        global_offset += total_p
        for p in pages_order:
            if not failed_pages and estimated_total > 0 and len(all_records) >= estimated_total:
                print(f"\n[{COMPANY_NAME}] 🎉 สะสมข้อมูลครบถ้วนทั้งหมดแล้ว ({len(all_records):,}/{estimated_total:,} รายการ) -> สิ้นสุดการสแครป!", flush=True)
                break
            items = fetch_ddproperty_page(session, curl, ctype, p)
            if items is None:
                failed_pages.append(p)
                print(f"\n[{COMPANY_NAME}] ⚠️ ข้ามหมวด {ctype} หน้า {p} เนื่องจากดึงข้อมูลไม่สำเร็จ", flush=True)
                continue

            page_added = 0
            for item in items:
                iid = str(item["ID"]).strip()
                if iid and iid in seen_ids:
                    continue
                if iid:
                    seen_ids.add(iid)
                all_records.append(item)
                page_added += 1
                new_added += 1

            if not failed_pages:
                processed_pages = max(processed_pages, p)
            if page_added > 0:
                save_to_csv(all_records, OUTPUT_CSV, session=session)

            pct = int((processed_pages / total_task_pages) * 100) if total_task_pages > 0 else 0
            elapsed_sec = time.time() - start_time
            eta_msg = format_eta(elapsed_sec, processed_pages, total_task_pages, start_unit=start_page + 1)
            pbar = make_progress_bar(pct)

            print(f"[{COMPANY_NAME:<13s}] {pbar} | ({processed_pages:5,d}/{total_task_pages:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{estimated_total:,d} รายการ | {eta_msg}", flush=True)

            if len(all_records) >= 10 and "initial_10" not in saved_milestones:
                saved_milestones.add("initial_10")
                save_state(processed_pages, total_task_pages, len(all_records), extra={"failed_pages": failed_pages})
                log_milestone(COMPANY_NAME, f"💾 บันทึก 10 รายการแรก ({len(all_records):,} รายการ)")

            if total_task_pages > 0:
                for target_pct in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]:
                    if pct >= target_pct and target_pct not in saved_milestones:
                        saved_milestones.add(target_pct)
                        save_state(processed_pages, total_task_pages, len(all_records), extra={"failed_pages": failed_pages})
                        log_milestone(COMPANY_NAME, f"💾 บันทึกข้อมูล Milestone {target_pct}% ({len(all_records):,} รายการ)")

            time.sleep(get_scraper_delay()) # หน่วงเวลาอย่างน้อย 15 วินาทีต่อหน้า

    print("", flush=True)
    save_to_csv(all_records, OUTPUT_CSV, session=session)
    elapsed = time.time() - start_time
    if failed_pages:
        final_status = "FAILED" if len(all_records) == 0 else "PARTIAL"
        save_state(processed_pages, total_task_pages, len(all_records), status=final_status, extra={"failed_pages": failed_pages})
        print(f"\n==================================================", flush=True)
        print(f"⚠️ [{COMPANY_NAME}] สแครปเสร็จแบบมีหน้าล้มเหลว ({final_status}) | ({processed_pages:5,d}/{total_task_pages:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{estimated_total:,d} รายการ", flush=True)
        print(f"⚠️ รายการหน้าที่ข้าม/ดึงไม่ได้ ({len(failed_pages)} หน้า): {failed_pages}", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที | 💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        log_warning(COMPANY_NAME, f"สแครปเสร็จแบบ {final_status} แต่มี {len(failed_pages)} หน้าที่ดึงไม่ได้")
        sys.exit(1 if len(all_records) == 0 else 2)
    else:
        save_state(processed_pages, total_task_pages, len(all_records), status="COMPLETED", extra={"failed_pages": []})
        print(f"\n==================================================", flush=True)
        print(f"✅ [{COMPANY_NAME}] สแครปเสร็จสมบูรณ์! | ({processed_pages:5,d}/{total_task_pages:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{estimated_total:,d} รายการ", flush=True)
        print(f"📊 ได้ข้อมูลทั้งหมด: {len(all_records):,} รายการ (เพิ่มใหม่ในรอบนี้: {new_added:,} รายการ)", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที", flush=True)
        print(f"💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        print(f"✅ ดึงข้อมูลได้ครบถ้วนสำเร็จทุกหน้า (ไม่มีหน้าล้มเหลว)", flush=True)
        log_success(COMPANY_NAME, f"✅ สแครปเสร็จสมบูรณ์ครบถ้วน 100% ได้ข้อมูล {len(all_records):,} รายการ")
        print(f"==================================================", flush=True)

if __name__ == "__main__":
    main()
