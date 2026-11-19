import os
import sys
import time
from time_window_util import get_scraper_delay, get_scraper_delay_range
import random
import re
from datetime import datetime
import pandas as pd
from bs4 import BeautifulSoup
import requests

from logger_util import (
    AuditedSession,
    log_txn,
    log_info,
    log_warning,
    log_error,
    log_milestone,
    log_success,
    save_scraper_state,
    load_scraper_state,
    reset_scraper_state,
    print_alert,
    safe_ssl_get,
    safe_ssl_post,
    read_csv_resume,
    atomic_write_csv,
)
from timeout_handler import wait_1hr_on_timeout, handle_timeout_retry, execute_with_retry
from clean_location_util import clean_row_location, forward_geocode_location, clean_price_val, extract_floor_from_text, clean_plaintiff_name
try:
    from clean_project_util import clean_project_name as clean_project_central
except ImportError:
    clean_project_central = None

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

COMPANY_NAME = "LED"
COMPANY_DISPLAY = "กรมบังคับคดี (LED)"
MONTH_STR = datetime.now().strftime("%Y_%m")

_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR
OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"LED_NPA_New_{MONTH_STR}.csv")

BASE_URL = "https://asset.led.go.th/newbidreg/"
SEARCH_ACTION_URL = "https://asset.led.go.th/newbidreg/default.asp"
MAX_WORKERS = 1
DEFAULT_DELAY_MIN = 15.0  # ปรับเป็น 15-16s ทุกตัว
DEFAULT_DELAY_MAX = 16.0

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept-Language': 'th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Origin': 'https://asset.led.go.th',
    'Referer': 'https://asset.led.go.th/newbidreg/'
}

COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคา",
    "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ", "เลขโฉนด", "โจทก์", "ศาล"
]

_SPINNER_CHARS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_spinner_frame = 0

def make_progress_bar(pct, length=20):
    global _spinner_frame
    _spinner_frame = (_spinner_frame + 1) % len(_SPINNER_CHARS)
    spin = _SPINNER_CHARS[_spinner_frame]
    pct = max(0, min(100, pct))
    filled = int(length * pct / 100)
    bar = '█' * filled + '░' * (length - filled)
    return f"[{bar}] {pct:3d}% {spin}"

def format_eta(elapsed_sec, completed_units, total_units, start_unit=1):
    completed_in_session = max(1, completed_units - start_unit + 1)
    remaining_units = max(0, total_units - completed_units)
    if remaining_units <= 0:
        return "ใกล้เสร็จสมบูรณ์"
    if completed_in_session <= 0 or elapsed_sec <= 0:
        return "กำลังคำนวณ..."
    rate = completed_in_session / elapsed_sec
    eta_seconds = remaining_units / rate
    finish_timestamp = time.time() + eta_seconds
    finish_clock = datetime.fromtimestamp(finish_timestamp).strftime('%H:%M:%S')
    
    if eta_seconds < 60:
        return f"เหลืออีก ~{int(eta_seconds)}ว. ({finish_clock} น.)"
    elif eta_seconds < 3600:
        mins = int(eta_seconds // 60)
        secs = int(eta_seconds % 60)
        return f"เหลืออีก ~{mins}น. {secs}ว. ({finish_clock} น.)"
    else:
        hours = int(eta_seconds // 3600)
        mins = int((eta_seconds % 3600) // 60)
        return f"เหลืออีก ~{hours}ชม. {mins}น. ({finish_clock} น.)"

def clean_text(val):
    if val is None:
        return ""
    s = str(val).strip()
    if s in ["None", "null", "-", ""]:
        return ""
    return re.sub(r'\s+', ' ', s)

def clean_project_name(land_desc, land_type="", remark=""):
    """
    คัดกรองและสกัดชื่อโครงการ/หมู่บ้าน/คอนโดจริงจากข้อมูลกรมบังคับคดี (LED)
    1. หากมีคำว่า หมู่บ้าน, โครงการ, อาคารชุด อยู่ใน landdesc หรือ remark ให้สกัดชื่อออกมา
    2. หากเป็นเพียงข้อความทางกฎหมายทั่วไป (เช่น ตามสำเนาโฉนด, น.ส. 3, ตราจอง, ที่ดินเปล่า) ให้ส่งคืนค่าว่าง ""
    """
    combined = f"{clean_text(land_desc)} {clean_text(remark)}".strip()
    if not combined:
        return ""

    # ลองค้นหาคำว่า หมู่บ้าน, โครงการ, อาคารชุด
    m_proj = re.search(r'(?:ใน|ติด)?(?:โครงการหมู่บ้าน|หมู่บ้านโครงการ|ในโครงการ|โครงการ|หมู่บ้าน|อาคารชุด)\s*([ก-๙a-zA-Z0-9\s\-_()]+)', combined)
    if m_proj:
        cand = m_proj.group(1).strip()
        cand = re.sub(r'[\s\-_/]+(?:เลขที่|แปลงที่|โฉนดเลขที่|ตึก|อาคาร|ชั้น|ตำบล|อำเภอ|จังหวัด).*$', '', cand)
        if clean_project_central:
            res = clean_project_central(cand, company="LED")
            if res:
                return res

    s = clean_text(land_desc)
    generic_patterns = [
        r'^(?:ตาม)?(?:สำเนา)?\s*โฉนด(?:เลขที่)?',
        r'^(?:ตาม)?(?:สำเนา)?\s*น\.?ส\.?\s*[34]\s*[ก-ฮ]?',
        r'^(?:ตาม)?(?:สำเนา)?\s*ตราจอง(?:เลขที่)?',
        r'^(?:ตาม)?(?:สำเนา)?\s*กรรมสิทธิ์ห้องชุด',
        r'^(?:ตาม)?(?:สำเนา)?\s*หนังสือกรรมสิทธิ์',
        r'^(?:ตาม)?(?:สำเนา)?\s*เอกสารสิทธิ์',
        r'^(?:ที่ดินว่างเปล่า|ที่ดินเปล่า|สิ่งปลูกสร้าง|ห้องชุด|บ้านพักอาศัย|ตึกแถว|อาคารพาณิชย์|ทาวน์เฮ้าส์|บ้านเดี่ยว)$',
        r'^(?:ไม่มี|ไม่ปรากฏ|-|\.|\/)$'
    ]
    for pat in generic_patterns:
        if re.search(pat, s):
            return ""
    if re.match(r'^[\d\s,\/\-\.]+$', s):
        return ""
    if clean_project_central:
        return clean_project_central(s, company="LED")
    return s

def extract_deed_no(data):
    """
    สกัดเลขโฉนด หรือ เลขตามสำเนาโฉนดเลขที่ จากข้อมูลกรมบังคับคดี (LED)
    1. ตรวจสอบฟิลด์ input 'deedno' โดยตรง
    2. หากไม่มี ให้ค้นหาด้วย Regex จาก landdesc, remark, remark1, landtype
    """
    # 1. จาก deedno โดยตรง
    val = clean_text(data.get('deedno') or '')
    if val:
        val = re.sub(r'^(?:ตามสำเนาโฉนด(?:ที่ดิน)?(?:เลขที่)?|โฉนด(?:ที่ดิน)?(?:เลขที่)?)\s*[:\s]*', '', val).strip()
        if val:
            return val
            
    # 2. ค้นหาจาก landdesc, remark, remark1, landtype
    combined = f"{clean_text(data.get('landtype') or '')} {clean_text(data.get('landdesc') or '')} {clean_text(data.get('remark') or '')} {clean_text(data.get('remark1') or '')}"
    patterns = [
        r'(?:ตามสำเนาโฉนด(?:ที่ดิน)?เลขที่|ตามสำเนาโฉนด|โฉนดที่ดินเลขที่|โฉนดเลขที่|โฉนดที่)\s*[:\s]*([0-9\s,\/\-]+)',
        r'(?:น\.?ส\.?\s*[34]\s*[ก-ฮ]?\s*(?:เลขที่)?)\s*[:\s]*([0-9\s,\/\-]+)',
        r'(?:ตราจอง(?:เลขที่)?)\s*[:\s]*([0-9\s,\/\-]+)'
    ]
    for pat in patterns:
        m = re.search(pat, combined)
        if m:
            clean_val = clean_text(m.group(1)).strip(' ,/-')
            if clean_val and any(c.isdigit() for c in clean_val):
                return clean_val
    return ""

def extract_area_fields(asset_type, rai, quaterrai, wa, remark, land_desc):
    """
    แยกวิเคราะห์ เนื้อที่ (ตร.ว.) และ พื้นที่ใช้สอย (ตร.ม.) ให้ถูกต้องตามประเภททรัพย์:
    1. ห้องชุด/คอนโด: เนื้อที่ (ตร.ว.) จะเว้นว่าง และดึงขนาดห้องจากฟิลด์ wa เป็น พื้นที่ใช้สอย (ตร.ม.) เป็นหลัก
       (ในระบบ LED คอลัมน์ "ตร.วา/ตร.ม." ของห้องชุดคือขนาดพื้นที่ ตร.ม. ของห้องชุดโดยตรง)
       หากไม่มีใน wa ค่อยค้นหาจาก remark/land_desc โดยตัด 'ระเบียง' ออกเสมอ ไม่ให้ดึงเนื้อที่ระเบียงมาแทนขนาดห้อง
    2. บ้าน/ที่ดิน/อาคาร: บันทึกขนาดที่ดินเป็น r-g-w (ตร.ว.) และดึงพื้นที่ใช้สอย (ตร.ม.) จาก remark/land_desc หากมีระบุ
    3. ป้องกันและตัดข้อมูลวันเดือนปี (เช่น 03/02/1987, 03-02-2530) ออกจากช่องเนื้อที่โดยเด็ดขาด
    """
    asset_type = clean_text(asset_type)
    remark = clean_text(remark)
    land_desc = clean_text(land_desc)
    combined = f"{remark} {land_desc}".strip()
    
    is_condo = any(k in asset_type for k in ['ห้องชุด', 'คอนโด', 'อาคารชุด'])
    
    if is_condo:
        land_area = ""
        usable_area = ""
        
        # 1. สำหรับห้องชุด/คอนโด: ในระบบ LED ช่อง wa (ตร.วา/ตร.ม.) คือพื้นที่ห้องชุด (ตร.ม.) ทางการจากหนังสือกรรมสิทธิ์ห้องชุด
        wa_clean = str(wa or '').replace(',', '').strip()
        if wa_clean and wa_clean not in ["-", "0", "0.0", "None", "nan", "null"] and '/' not in wa_clean:
            try:
                wa_f = float(wa_clean)
                if 0 < wa_f < 1900:  # ป้องกันกรณีตัวเลขเป็นปี พ.ศ./ค.ศ.
                    usable_area = wa_f
            except (ValueError, TypeError):
                pass
                
        # 2. กรณีไม่มีใน wa หรือ wa เป็น 0 ให้ค้นหาจากข้อความ โดยต้องตัด 'เนื้อที่ระเบียง' ออกเสมอ
        if not usable_area:
            # ตัดส่วนเนื้อที่ระเบียงออกเพื่อไม่ให้เผลอดึงขนาดระเบียงมาเป็นขนาดห้องชุด
            text_cleaned = re.sub(r'(?:เนื้อที่|พื้นที่)?\s*ระเบียง\s*[\d,]+(?:\.\d+)?\s*(?:ตร\.?ม\.?|ตารางเมตร|sq\.?m)?', '', combined, flags=re.IGNORECASE)
            m = re.search(r'(?:เนื้อที่|พื้นที่)\s*(?:ห้องชุด|ห้อง|ใช้สอย)?(?:\s*ประมาณ)?\s*([\d,]+(?:\.\d+)?)\s*(?:ตร\.?ม\.?|ตารางเมตร|sq\.?m)', text_cleaned, re.IGNORECASE)
            if not m:
                m = re.search(r'(?:ขนาดห้องชุด|ขนาดห้อง)\s*(?:ประมาณ)?\s*([\d,]+(?:\.\d+)?)\s*(?:ตร\.?ม\.?|ตารางเมตร|sq\.?m)', text_cleaned, re.IGNORECASE)
            if m:
                try:
                    val = float(m.group(1).replace(',', ''))
                    if 0 < val < 1900:
                        usable_area = val
                except (ValueError, TypeError):
                    pass
                    
        return land_area, usable_area
        
    else:
        # บ้าน / ทาวน์เฮ้าส์ / อาคารพาณิชย์ / ที่ดินเปล่า
        usable_area = ""
        # ตัดส่วนเนื้อที่ระเบียงออกเสมอ
        text_cleaned = re.sub(r'(?:เนื้อที่|พื้นที่)?\s*ระเบียง\s*[\d,]+(?:\.\d+)?\s*(?:ตร\.?ม\.?|ตารางเมตร|sq\.?m)?', '', combined, flags=re.IGNORECASE)
        m = re.search(r'(?:พื้นที่ใช้สอย|เนื้อที่ใช้สอย|พื้นที่อาคาร|พื้นที่สิ่งปลูกสร้าง|เนื้อที่อาคาร)(?:\s*ประมาณ)?\s*([\d,]+(?:\.\d+)?)\s*(?:ตร\.?ม\.?|ตารางเมตร|sq\.?m)', text_cleaned, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1).replace(',', ''))
                if 0 < val < 100000:
                    usable_area = val
            except (ValueError, TypeError):
                pass
                
        try:
            r_str = clean_text(rai) or "0"
            g_str = clean_text(quaterrai) or "0"
            w_str = clean_text(wa) or "0"
            
            # ตรวจจับและตัดกรณีเป็นวันเดือนปี (มีเครื่องหมาย / หรือปี ค.ศ./พ.ศ. >= 1900)
            for part in [r_str, g_str, w_str]:
                if '/' in part or re.search(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', part):
                    return "", usable_area
                    
            r_f, g_f, w_f = float(r_str), float(g_str), float(w_str)
            if r_f >= 1900 or g_f >= 1900 or w_f >= 1900:
                return "", usable_area
                
            if g_f >= 4:
                r_f += int(g_f // 4)
                g_f = g_f % 4
                
            if (r_f * 400 + g_f * 100 + w_f) > 0:
                land_area = f"{int(r_f)}-{int(g_f)}-{w_f:g}"
            else:
                land_area = ""
        except Exception:
            land_area = ""
            
        return land_area, usable_area

def format_publish_date(ischeck_date):
    """
    แปลงวันที่ลงประกาศขึ้นเว็บ เช่น '25690604' -> '2026-06-04' (มาตรฐาน ISO YYYY-MM-DD ค.ศ.)
    """
    s = clean_text(ischeck_date)
    if len(s) == 8 and s.isdigit():
        year = int(s[:4])
        if year > 2400: # แปลง พ.ศ. -> ค.ศ.
            year -= 543
        return f"{year:04d}-{s[4:6]}-{s[6:]}"
    return s

def clean_price(val):
    return clean_price_val(val)

_PROVINCE_ALIAS_MAP = {
    "อุตรดิต": "อุตรดิตถ์",
}


def _normalize_led_province(name: str) -> str:
    s = clean_text(name)
    return _PROVINCE_ALIAS_MAP.get(s, s)


def load_existing_csv(filename):
    tmp_orphan = filename + ".tmp"
    if os.path.exists(tmp_orphan):
        try:
            os.remove(tmp_orphan)
        except OSError:
            pass

    if "--fresh" in sys.argv or "--force-restart" in sys.argv:
        print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นดึงข้อมูลใหม่ทั้งหมด (โหมด --fresh)", flush=True)
        reset_scraper_state(COMPANY_NAME, MONTH_STR)
        return [], set()

    raw_records, _ = read_csv_resume(filename, COLUMNS, id_col="ID", company_name=COMPANY_NAME)
    if not raw_records:
        return [], set()

    records = []
    seen_ids = set()
    for r in raw_records:
        iid = str(r.get('ID') or r.get('รหัสทรัพย์') or '').strip()
        # กรองเฉพาะ auc_asset_gen ที่แท้จริง (ไม่เอาเลขคดีแดงที่มี /)
        if iid and iid not in ["nan", "None", ""] and "/" not in iid and iid not in seen_ids:
            # กรองช่องเนื้อที่ไม่ให้มี / หรือวันเดือนปี
            area_val = str(r.get("เนื้อที่ (ตร.ว.)") or "").strip()
            if "/" in area_val or re.search(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', area_val):
                r["เนื้อที่ (ตร.ว.)"] = ""
            records.append(r)
            seen_ids.add(iid)
    return records, seen_ids


def save_to_csv(records, filename):
    return atomic_write_csv(records, filename, COLUMNS, company_name=COMPANY_NAME)


def get_initial_session_and_provinces(session):
    """
    ดึงค่า oseckey และรายชื่อจังหวัดจากหน้าหลัก
    """
    for attempt in range(5):
        try:
            r = safe_ssl_get(session, BASE_URL, timeout=100, ssl_fallback_on_gov=True)
            if r.status_code == 200:
                soup = BeautifulSoup(r.content.decode('utf-8', errors='ignore'), 'html.parser')
                oseckey_inp = soup.find('input', {'name': 'oseckey'})
                oseckey = oseckey_inp.get('value', '') if oseckey_inp else ''

                prov_select = soup.find('select', {'id': 'provinces'}) or soup.find('select', {'name': 'province'})
                provinces = []
                seen_provs = set()
                if prov_select:
                    for opt in prov_select.find_all('option'):
                        txt = _normalize_led_province(opt.get_text(strip=True))
                        if txt and "--" not in txt and txt not in seen_provs:
                            seen_provs.add(txt)
                            provinces.append(txt)
                return True, r.status_code, oseckey, provinces
        except Exception:
            time.sleep(2 + attempt)
    return False, 0, '', []

def parse_items_from_html(html_content, scrape_time):
    """
    สกัดข้อมูลรายการทรัพย์จากฟอร์ม web1, web2, ... ในหน้า HTML พร้อมทำ Geocoding พิกัด GIS และจัดรูปแบบข้อมูลให้ตรงมาตรฐาน
    """
    if isinstance(html_content, bytes):
        html_content = html_content.decode('utf-8', errors='ignore')
    soup = BeautifulSoup(html_content, 'html.parser')
    forms = soup.find_all('form')
    records = []
    
    for f in forms:
        fname = f.get('name') or ''
        # Match only genuine item forms web1, web2, ...
        if not re.match(r'^web\d+$', fname):
            continue
        data = {inp.get('name'): inp.get('value', '') for inp in f.find_all('input') if inp.get('name')}
        if not data:
            continue
            
        auc_id = clean_text(data.get('auc_asset_gen') or '')
        if not auc_id:
            continue

        # กรองทรัพย์ที่ประมูลขายได้แล้วออก (issale == '1' ในนัดใดก็ตาม หรือ issale หลักเป็น '1')
        sub_sales = [str(data.get(f'issale{i}', '')).strip() for i in range(1, 10)]
        main_sale = str(data.get('issale', '')).strip()
        if any(s == '1' for s in sub_sales) or (main_sale == '1'):
            continue
            
        suit_no = clean_text(data.get('law_suit_no') or '')
        suit_year = clean_text(data.get('law_suit_year') or '')
        bid_num = clean_text(data.get('str_bid_num') or '')
        lawsuit_full = f"{suit_no}/{suit_year}".strip('/')
        
        item_id = auc_id
        prop_code = lawsuit_full if lawsuit_full else auc_id
        
        asset_type = clean_text(data.get('assettypedesc') or '')
        sale_type = clean_text(data.get('saletypename') or '')
        
        # ค้นหาราคาประเมินที่ไม่เป็น 0
        price = None
        for p_key in [f'assetprice{i}' for i in range(1, 10)]:
            p_val = clean_price(data.get(p_key))
            if p_val and p_val > 0:
                price = p_val
                break
                
        tumbol_raw = data.get('deedtumbol') or data.get('tumbol') or ''
        ampur_raw = data.get('deedampur') or data.get('ampur') or ''
        city_raw = data.get('deedcity') or data.get('city') or ''
        
        tumbol, ampur, city = clean_row_location(tumbol_raw, ampur_raw, city_raw)
        if lawsuit_full and city:
            prop_code = f"{lawsuit_full}_{city}"
        lat, lng = forward_geocode_location(tumbol, ampur, city)
        
        land_desc = clean_text(data.get('landdesc') or '')
        remark = clean_text(data.get('remark') or data.get('remark1') or '')
        proj_name = clean_project_name(land_desc, data.get('landtype'), remark=remark)
        
        land_area, usable_area = extract_area_fields(asset_type, data.get('rai'), data.get('quaterrai'), data.get('wa'), remark, land_desc)
        
        pub_date = format_publish_date(data.get('ischeck_date'))
        
        deed_no = extract_deed_no(data)
        deed_suffix = f" (โฉนดเลขที่ {deed_no})" if deed_no else ""
        title_desc = f"ทรัพย์ขายทอดตลาด กรมบังคับคดี {lawsuit_full} {asset_type} {ampur} {city}{deed_suffix}".strip()

        # ดึงชื่อโจทก์ (person1) โดยกรองชื่อจริงคนออก (เช่น นาย, นาง, นางสาว ให้เว้นว่างไว้ ตามนโยบาย PDPA)
        plaintiff_raw = re.sub(r'[\r\n\t]+', ' ', str(data.get('person1') or '')).strip()
        plaintiff = clean_plaintiff_name(plaintiff_raw)

        # ดึงชื่อศาล (law_court_name)
        court_raw = clean_text(data.get('law_court_name') or '')
        if court_raw in ["None", "null", "-"]:
            court_raw = ""

        if lawsuit_full and '/' in lawsuit_full:
            import urllib.parse
            parts = lawsuit_full.split('/')
            link = f"app/static/led_bridge.html?suit_no={urllib.parse.quote(parts[0].strip())}&suit_year={urllib.parse.quote(parts[1].strip())}"
            if plaintiff:
                plaintiff_search = re.sub(r'\s*\(.*$', '', plaintiff).strip()
                if plaintiff_search:
                    link += f"&person1={urllib.parse.quote(plaintiff_search)}"
            if court_raw:
                link += f"&court={urllib.parse.quote(court_raw)}"
        else:
            link = "https://asset.led.go.th/newbidreg/asset_search_law_suit.asp"
        
        rec = {
            "บริษัท": COMPANY_NAME,
            "ID": item_id,
            "รหัสทรัพย์": prop_code,
            "ชื่อโครงการ": proj_name,
            "ประเภททรัพย์": asset_type,
            "ประเภทการขาย": sale_type,
            "ราคา": price,
            "ตำบล": tumbol,
            "อำเภอ": ampur,
            "จังหวัด": city,
            "ละติจูด": lat,
            "ลองจิจูด": lng,
            "ชื่อประกาศ": title_desc,
            "ลิงก์": link,
            "เนื้อที่ (ตร.ว.)": land_area,
            "พื้นที่ใช้สอย (ตร.ม.)": usable_area,
            "วันที่ดึงข้อมูล": scrape_time,
            "ห้องนอน": "",
            "ห้องน้ำ": "",
            "ที่จอดรถ": "",
            "ชั้น": extract_floor_from_text(remark, land_desc, title_desc, asset_type=asset_type) or "",
            "วันประกาศ": pub_date,
            "เลขโฉนด": deed_no,
            "โจทก์": plaintiff,
            "ศาล": court_raw
        }
        records.append(rec)
        
    return records

PROVINCES_77 = [
    "กรุงเทพมหานคร", "กระบี่", "กาญจนบุรี", "กาฬสินธุ์", "กำแพงเพชร", "ขอนแก่น", "จันทบุรี", "ฉะเชิงเทรา",
    "ชลบุรี", "ชัยนาท", "ชัยภูมิ", "ชุมพร", "เชียงราย", "เชียงใหม่", "ตรัง", "ตราด", "ตาก", "นครนายก",
    "นครปฐม", "นครพนม", "นครราชสีมา", "นครศรีธรรมราช", "นครสวรรค์", "นนทบุรี", "นราธิวาส", "น่าน",
    "บึงกาฬ", "บุรีรัมย์", "ปทุมธานี", "ประจวบคีรีขันธ์", "ปราจีนบุรี", "ปัตตานี", "พระนครศรีอยุธยา",
    "พะเยา", "พังงา", "พัทลุง", "พิจิตร", "พิษณุโลก", "เพชรบุรี", "เพชรบูรณ์", "แพร่", "ภูเก็ต",
    "มหาสารคาม", "มุกดาหาร", "แม่ฮ่องสอน", "ยโสธร", "ยะลา", "ร้อยเอ็ด", "ระนอง", "ระยอง", "ราชบุรี",
    "ลพบุรี", "ลำปาง", "ลำพูน", "เลย", "ศรีสะเกษ", "สกลนคร", "สงขลา", "สตูล", "สมุทรปราการ",
    "สมุทรสงคราม", "สมุทรสาคร", "สระแก้ว", "สระบุรี", "สิงห์บุรี", "สุโขทัย", "สุพรรณบุรี", "สุราษฎร์ธานี",
    "สุรินทร์", "หนองคาย", "หนองบัวลำภู", "อ่างทอง", "อำนาจเจริญ", "อุดรธานี", "อุตรดิตถ์", "อุทัยธานี",
    "อุบลราชธานี"
]

def find_python():
    """Find Python executable to run external tools/scripts when frozen or in environment."""
    if not getattr(sys, 'frozen', False):
        return sys.executable
    import shutil
    from pathlib import Path
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

def extract_total_pages(html_content):
    if isinstance(html_content, bytes):
        html_content = html_content.decode('utf-8', errors='ignore')
    # 1. Check form webFormTopLast1 or dwebFormBottomLast1
    m_last = re.search(r'name=[\"\'](?:webFormTopLast1|dwebFormBottomLast1)[\"\'][^>]*>.*?<input[^>]*name=[\"\']page[\"\'][^>]*value=[\"\'](\d+)[\"\']', html_content, re.DOTALL | re.I)
    if m_last:
        return int(m_last.group(1))
    
    # 2. Check all Page inputs
    page_vals = [int(v) for v in re.findall(r'name=[\"\']page[\"\'][^>]*value=[\"\'](\d+)[\"\']', html_content, re.I)]
    if page_vals:
        return max(page_vals)
        
    # 3. Check web1..web30 items count
    forms_count = len(re.findall(r'<form\s+[^>]*name=[\"\']web\d+[\"\']', html_content, re.I))
    if forms_count > 0:
        return 1
    return 0

def main():
    print(f"==================================================", flush=True)
    print(f"🚀 เริ่มต้นการ Scrape [{COMPANY_NAME}] ({COMPANY_DISPLAY}) (Monthly Mode)", flush=True)
    print(f"📁 บันทึกข้อมูลลงไฟล์: {OUTPUT_CSV}", flush=True)
    print(f"==================================================", flush=True)
    
    session = AuditedSession(company_name=COMPANY_NAME)
    session.headers.update(HEADERS)

    from logger_util import print_structure_alert
    is_ok, code, oseckey, provinces = get_initial_session_and_provinces(session)
    if not is_ok:
        print_alert("❌ ไม่สามารถเชื่อมต่อระบบกรมบังคับคดี (LED) ได้", level="CRITICAL")
        sys.exit(1)

    if not oseckey:
        print_structure_alert(COMPANY_NAME, "ไม่พบค่าความปลอดภัย 'oseckey' ในหน้าเริ่มต้นของ LED (Form Signature เปลี่ยนแปลง)")
        sys.exit(1)

    # โหลด/รีเซ็ตข้อมูลหลังจากตรวจสอบการเชื่อมต่อสำเร็จแล้วเท่านั้น (--fresh ปลอดภัยหากเว็บล่ม)
    all_records, seen_ids = load_existing_csv(OUTPUT_CSV)

    if not provinces or len(provinces) < 70:
        provinces = list(PROVINCES_77)

    status_msg = f"🌐 สถานะลิงก์: ปกติ (HTTP {code}) | ครอบคลุม {len(provinces)} จังหวัดทั่วประเทศ"
    print(f"[{COMPANY_NAME}] {status_msg}", flush=True)

    total_provs = len(provinces)
    saved_state = load_scraper_state(COMPANY_NAME, MONTH_STR)
    saved_done_provs = {_normalize_led_province(p) for p in saved_state.get("completed_provinces", []) if _normalize_led_province(p)}
    partial_province = _normalize_led_province(saved_state.get("partial_province") or "")
    try:
        partial_page = int(saved_state.get("partial_page") or 0)
    except (TypeError, ValueError):
        partial_page = 0
    partial_completed_pages = {
        int(p) for p in (saved_state.get("partial_completed_pages") or [])
        if str(p).isdigit()
    }

    # Smart Resume: ยึดเฉพาะจังหวัดที่ดึงจบครบทุกหน้าจาก JSON state (ไม่ใช้ csv_provinces ป้องกันการข้ามจังหวัดที่ยังดึงไม่เสร็จ)
    done_provinces = {p for p in saved_done_provs if p in provinces}

    missing_provinces = [p for p in provinces if p not in done_provinces]
    
    if len(missing_provinces) == 0 and (len(all_records) >= 30000 or (saved_state.get("status") == "COMPLETED" and len(all_records) > 0)):
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลใน CSV ครบถ้วน 100% ทุกจังหวัดแล้ว ({total_provs:3d}/{total_provs:3d} จว.) | สะสม: {len(all_records):,d} รายการ -> สแครปเสร็จสมบูรณ์ทันที!", flush=True)
        save_to_csv(all_records, OUTPUT_CSV)
        save_scraper_state(COMPANY_NAME, total_provs, total_provs, len(all_records), status="COMPLETED", month_str=MONTH_STR, extra={"completed_provinces": list(provinces), "partial_province": "", "partial_page": 0})
        log_success(COMPANY_NAME, f"✅ ข้อมูลใน CSV ครบถ้วน 100% ทุกจังหวัดแล้ว ({len(all_records):,} รายการ)")
        return

    start_time = time.time()
    new_added = 0
    saved_milestones = set()
    failed_units = []
    
    if done_provinces:
        pct_start = int((len(done_provinces) / total_provs) * 100)
        print(f"[{COMPANY_NAME}] 🔄 Smart Resume: มีข้อมูลเดิมแล้ว {len(done_provinces)}/{total_provs} จังหวัด (สะสม {len(all_records):,} รายการ) -> จะดึงต่อเฉพาะจังหวัดที่เหลือ ({len(missing_provinces)} จว.): {', '.join(missing_provinces)}", flush=True)
        for target_pct in range(5, pct_start + 1, 5):
            saved_milestones.add(target_pct)
        saved_milestones.add("initial_page")
    elif partial_province and partial_page > 0:
        print(f"[{COMPANY_NAME}] 🔄 Smart Resume: พบรอยต่อค้างอยู่ที่จังหวัด {partial_province} หน้า {partial_page} (สะสม {len(all_records):,} รายการ)", flush=True)
    
    log_milestone(COMPANY_NAME, f"🚀 เริ่มต้นการ Scrape รายเดือน {total_provs} จังหวัด (เป้าหมาย: {OUTPUT_CSV})")
    
    current_prov_name = ""
    current_prov_page = 0
    current_prov_done_pages = set()
    try:
        for p_idx, prov in enumerate(provinces, 1):
            if prov in done_provinces:
                pct = int((p_idx / total_provs) * 100)
                pbar = make_progress_bar(pct, length=20)
                prog_line = f"[{COMPANY_NAME:<13s}] {pbar} | ({p_idx:3d}/{total_provs:3d} จว.) | สะสม: {len(all_records):7,d} รายการ | ⏩ ข้าม {prov} (มีข้อมูลเดิมแล้ว)"
                print(prog_line, flush=True)
                continue

            current_prov_name = prov
            current_prov_page = 0
            prov_all_pages_ok = True
            if prov == partial_province and partial_completed_pages:
                prov_done_pages = set(partial_completed_pages)
            elif prov == partial_province and partial_page > 0:
                prov_done_pages = set(range(1, partial_page + 1))
            else:
                prov_done_pages = set()
            current_prov_done_pages = prov_done_pages

            # 1. First page search for this province
            payload_p1 = {
                'page': '1',
                'mode': 'asset',
                'province': prov,
                'search': 'ok',
                'oseckey': oseckey,
                'seckey': oseckey
            }

            def _fetch_p1():
                resp = safe_ssl_post(session, SEARCH_ACTION_URL, data=payload_p1, timeout=100, ssl_fallback_on_gov=True)
                if resp.status_code != 200:
                    resp.raise_for_status()
                return resp

            try:
                r1 = execute_with_retry(_fetch_p1, company_name=COMPANY_NAME, context_msg=f"จังหวัด {prov} (หน้า 1)", max_retries=4, max_cooldown_cycles=1)
            except Exception:
                r1 = None

            if r1 is None or r1.status_code != 200:
                failed_units.append(f"{prov} (หน้า 1)")
                prov_all_pages_ok = False
                continue

            html_p1 = r1.content.decode('utf-8', errors='ignore')
            total_pages = extract_total_pages(html_p1)
            scrape_time = datetime.now().strftime("%Y-%m-%d")
            items_p1 = parse_items_from_html(html_p1, scrape_time)

            for item in items_p1:
                iid = str(item.get("ID", "")).strip()
                if iid and iid not in seen_ids:
                    seen_ids.add(iid)
                    all_records.append(item)
                    new_added += 1

            prov_done_pages.add(1)
            current_prov_page = 1
            if prov == partial_province and len(prov_done_pages) > 1 and total_pages > 1:
                resumed_cnt = len([p for p in prov_done_pages if 2 <= p <= total_pages])
                if resumed_cnt > 0:
                    print(f"[{COMPANY_NAME}] ⏩ Smart Resume จังหวัด {prov}: ข้าม {resumed_cnt} หน้าเดิมที่สำเร็จแล้ว -> ดึงหน้าที่เหลือถึง {total_pages}", flush=True)

            # 2. Iterate remaining pages for this province (retrying any previously failed pages too)
            for page in range(2, total_pages + 1):
                if page in prov_done_pages:
                    current_prov_page = page
                    continue

                time.sleep(get_scraper_delay()) # หน่วงเวลาอย่างน้อย 15 วินาทีต่อหน้า

                payload_page = {
                    'page': str(page),
                    'mode': 'asset',
                    'province': prov,
                    'search': 'ok',
                    'oseckey': oseckey,
                    'seckey': oseckey
                }

                def _fetch_page():
                    resp = safe_ssl_post(session, SEARCH_ACTION_URL, data=payload_page, timeout=100, ssl_fallback_on_gov=True)
                    if resp.status_code != 200:
                        resp.raise_for_status()
                    return resp

                try:
                    rp = execute_with_retry(_fetch_page, company_name=COMPANY_NAME, context_msg=f"จังหวัด {prov} (หน้า {page})", max_retries=4, max_cooldown_cycles=1)
                except Exception:
                    rp = None

                if rp is None or rp.status_code != 200:
                    failed_units.append(f"{prov} (หน้า {page})")
                    prov_all_pages_ok = False
                    continue

                html_page = rp.content.decode('utf-8', errors='ignore')
                scrape_time = datetime.now().strftime("%Y-%m-%d")
                items = parse_items_from_html(html_page, scrape_time)
                for item in items:
                    iid = str(item.get("ID", "")).strip()
                    if iid and iid not in seen_ids:
                        seen_ids.add(iid)
                        all_records.append(item)
                        new_added += 1

                prov_done_pages.add(page)
                current_prov_page = page
                if page % 5 == 0 or page == total_pages:
                    save_to_csv(all_records, OUTPUT_CSV)
                    safe_partial_page = max((p for p in prov_done_pages if p == 1 or p - 1 in prov_done_pages), default=0)
                    save_scraper_state(
                        COMPANY_NAME, len(done_provinces), total_provs, len(all_records),
                        status="RUNNING", month_str=MONTH_STR,
                        extra={
                            "completed_provinces": list(done_provinces),
                            "current_province": prov,
                            "partial_province": prov,
                            "partial_page": safe_partial_page,
                            "partial_completed_pages": sorted(prov_done_pages),
                        }
                    )

            # Mark province as completely scraped only if all pages succeeded
            if prov_all_pages_ok and len(prov_done_pages) >= max(1, total_pages):
                done_provinces.add(prov)
                partial_province = ""
                partial_page = 0
                partial_completed_pages = set()
                current_prov_page = 0
                current_prov_done_pages = set()

            # Report progress per province
            pct = int((p_idx / total_provs) * 100)
            pbar = make_progress_bar(pct, length=20)
            elapsed = time.time() - start_time
            eta_str = format_eta(elapsed, p_idx, total_provs, 1)

            prog_line = f"[{COMPANY_NAME:<13s}] {pbar} | ({p_idx:3d}/{total_provs:3d} จว.) | สะสม: {len(all_records):7,d} รายการ | {eta_str}"
            print(prog_line, flush=True)

            # Save after each province
            save_to_csv(all_records, OUTPUT_CSV)
            save_scraper_state(
                COMPANY_NAME, len(done_provinces), total_provs, len(all_records),
                status="RUNNING", month_str=MONTH_STR,
                extra={
                    "completed_provinces": list(done_provinces),
                    "current_province": prov,
                    "partial_province": "" if prov in done_provinces else prov,
                    "partial_page": 0 if prov in done_provinces else current_prov_page,
                    "partial_completed_pages": [] if prov in done_provinces else sorted(prov_done_pages),
                }
            )

            if "initial_page" not in saved_milestones and len(all_records) > 0:
                saved_milestones.add("initial_page")
                print(f"\n💾 [{COMPANY_NAME}] ครบจังหวัดแรก -> บันทึกไฟล์เริ่มต้นลง {OUTPUT_CSV}...", flush=True)
                log_milestone(COMPANY_NAME, f"💾 บันทึกเริ่มต้น (ครบจังหวัดแรก) {len(all_records):,} รายการลง " + os.path.basename(OUTPUT_CSV))

            for target_pct in range(5, 105, 5):
                if pct >= target_pct and target_pct not in saved_milestones:
                    saved_milestones.add(target_pct)
                    print(f"\n💾 [{COMPANY_NAME}] ครบ Milestone {target_pct}% -> บันทึกสำรองลง {OUTPUT_CSV}...", flush=True)
                    log_milestone(COMPANY_NAME, f"💾 บันทึก Milestone สำรอง {target_pct}% ({len(all_records):,} รายการ) ลง " + os.path.basename(OUTPUT_CSV))

            # Polite pause between provinces (หน่วงเวลาอย่างน้อย 15 วินาที)
            time.sleep(get_scraper_delay())
    except (KeyboardInterrupt, SystemExit):
        print(f"\n⚠️ [{COMPANY_NAME}] ได้รับสัญญาณหยุดทำงาน -> กำลังบันทึกข้อมูลสะสม ({len(all_records):,} รายการ) ลง {OUTPUT_CSV}...", flush=True)
        save_to_csv(all_records, OUTPUT_CSV)
        save_scraper_state(
            COMPANY_NAME, len(done_provinces), total_provs, len(all_records),
            status="PAUSED", month_str=MONTH_STR,
            extra={
                "completed_provinces": list(done_provinces),
                "current_province": current_prov_name,
                "partial_province": current_prov_name if current_prov_name not in done_provinces else "",
                "partial_page": current_prov_page if current_prov_name not in done_provinces else 0,
                "partial_completed_pages": sorted(current_prov_done_pages) if current_prov_name not in done_provinces else [],
            }
        )
        raise

    # Save final CSV
    save_to_csv(all_records, OUTPUT_CSV)
    elapsed = time.time() - start_time
    if failed_units:
        final_status = "FAILED" if len(all_records) == 0 else "PARTIAL"
        save_scraper_state(
            COMPANY_NAME, len(done_provinces), total_provs, len(all_records),
            status=final_status, month_str=MONTH_STR,
            extra={"completed_provinces": list(done_provinces), "failed_units": failed_units[:100]}
        )
        print(f"\n==================================================", flush=True)
        print(f"⚠️ [{COMPANY_NAME}] สแครปเสร็จแบบมีรายการล้มเหลว ({final_status}) | สำเร็จ {len(done_provinces)}/{total_provs} จว. | สะสม: {len(all_records):,d} รายการ", flush=True)
        print(f"⚠️ รายการที่ข้าม/ดึงไม่ได้ ({len(failed_units)} รายการ): {sorted(failed_units)[:30]}", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที | 💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        log_warning(COMPANY_NAME, f"⚠️ สแครปเสร็จแบบ {final_status}: สำเร็จ {len(done_provinces)}/{total_provs} จว. (ล้มเหลว {len(failed_units)} หน่วย)")
        sys.exit(1 if len(all_records) == 0 else 2)
    else:
        save_scraper_state(COMPANY_NAME, total_provs, total_provs, len(all_records), status="COMPLETED", month_str=MONTH_STR, extra={"completed_provinces": list(provinces), "partial_province": "", "partial_page": 0, "partial_completed_pages": []})
        print(f"\n==================================================", flush=True)
        print(f"✅ [{COMPANY_NAME}] สแครปเสร็จสมบูรณ์! | ({total_provs:3d}/{total_provs:3d} จว.) | สะสม: {len(all_records):,d} รายการ", flush=True)
        print(f"📊 ได้ข้อมูลทั้งหมด: {len(all_records):,} รายการ (เพิ่มใหม่ในรอบนี้: {new_added:,} รายการ)", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที", flush=True)
        print(f"💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        print(f"✅ ดึงข้อมูลได้ครบถ้วนสำเร็จ 100% (ไม่มีรายการล้มเหลว)", flush=True)
        log_success(COMPANY_NAME, f"✅ สแครปเสร็จสมบูรณ์! ได้ข้อมูลทั้งหมดสะสม {len(all_records):,} รายการลง {os.path.basename(OUTPUT_CSV)}")

    # Phase 2: LandsMaps Real Coordinates Enrichment (อัตโนมัติ 100%)
    enable_coords = any(arg in sys.argv for arg in ["--enable-coords", "--with-landsmaps"])
    if not enable_coords:
        print("\n💡 [Info] ขั้นตอนการดึงพิกัดจริง LandsMaps ถูกปิดไว้เป็นค่าเริ่มต้น (พิกัดจะใช้ Centroid GIS 99.9% อัตโนมัติ)", flush=True)
    else:
        print("\n" + "=" * 65, flush=True)
        print("🗺️ [Phase 2/2] เริ่มต้นค้นหาพิกัดจริงจากโฉนดที่ดิน LandsMaps อัตโนมัติ...", flush=True)
        print("   - Single-Tab Playwright ทำงานต่อเนื่องบนเบราว์เซอร์เดียว", flush=True)
        print("   - บันทึกพิกัดจริงลงในไฟล์ CSV และ Parquet Cache อัตโนมัติ", flush=True)
        print("   - ซิงค์เข้า Dashboard (all_assets.parquet) ทันทีเมื่อเสร็จ", flush=True)
        print("   - สามารถกด Ctrl+C เพื่อหยุดเมื่อใดก็ได้ (ข้อมูลที่ดึงไปแล้วปลอดภัย 100%)", flush=True)
        print("=" * 65, flush=True)

        limit = 0
        province_filter = None
        headless = False
        for i, arg in enumerate(sys.argv):
            if arg == "--limit" and i + 1 < len(sys.argv):
                try:
                    limit = int(sys.argv[i+1])
                except Exception:
                    pass
            elif arg == "--province" and i + 1 < len(sys.argv):
                province_filter = sys.argv[i+1]
            elif arg == "--headless":
                headless = True

        try:
            tools_dir = os.path.join(_ROOT_DIR, "Py Scraper")
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)
            from enrich_led_landsmaps import run_enrichment
            run_enrichment(
                input_file=OUTPUT_CSV,
                province_filter=province_filter,
                limit=limit,
                headless=headless,
                auto_merge=True
            )
        except Exception as e:
            print(f"⚠️ เกิดข้อผิดพลาดในการดึงพิกัด LandsMaps: {e}", flush=True)


if __name__ == "__main__":
    main()
