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
    safe_ssl_get,
    get_nayoo_api_key,
    read_csv_resume,
    atomic_write_csv,
    print_alert,
)
from timeout_handler import wait_1hr_on_timeout, handle_timeout_retry, execute_with_retry

# -*- coding: utf-8 -*-
"""
NaYoo (น่าอยู่) Monthly Scraper
Scrapes all Secondhand properties (~10,711) and Project listings (~3,528) from https://api.nayoo.co
Adheres strictly to the 21 standard dashboard columns, GIS STRtree reverse geocoding, coordinates extraction, and monthly export structure.
"""

import os
import re
import sys
import time
from time_window_util import get_scraper_delay, get_scraper_delay_range
import json
import logging
import datetime
import random
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
from clean_location_util import clean_floor_val, extract_floor_from_text, reverse_geocode_location as central_reverse_geocode
try:
    from clean_project_util import clean_project_name, extract_project_from_title
except ImportError:
    clean_project_name = lambda x, **kwargs: str(x).strip()
    extract_project_from_title = lambda x, **kwargs: ""

# Set stdout encoding to UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

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

_SPINNER_CHARS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_spinner_frame = 0

def make_progress_bar(pct, length=20):
    global _spinner_frame
    _spinner_frame = (_spinner_frame + 1) % len(_SPINNER_CHARS)
    spin = _SPINNER_CHARS[_spinner_frame]
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
    if rate <= 0:
        return "กำลังคำนวณ..."
    eta_sec = remaining_units / rate
    finish_clock = datetime.datetime.fromtimestamp(datetime.datetime.now().timestamp() + eta_sec).strftime("%H:%M:%S")
    mins = int(eta_sec // 60)
    secs = int(eta_sec % 60)
    if mins >= 60:
        hrs = mins // 60
        mins = mins % 60
        return f"เหลืออีก ~{hrs}ชม. {mins}น. ({finish_clock} น.)"
    elif mins > 0:
        return f"เหลืออีก ~{mins}น. {secs}ว. ({finish_clock} น.)"
    else:
        return f"เหลืออีก ~{secs}ว. ({finish_clock} น.)"

# Constants
COMPANY_NAME = "NaYoo"
API_BASE = "https://api.nayoo.co"
API_KEY = os.environ.get("NAYOO_API_KEY", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://nayoo.co",
    "Referer": "https://nayoo.co/",
    "apikey": API_KEY,
}

def _ensure_nayoo_headers(session=None, force_refresh=False):
    global API_KEY
    if force_refresh or not API_KEY:
        API_KEY = get_nayoo_api_key(session=session, timeout=15)
        HEADERS["apikey"] = API_KEY
    return HEADERS

# Output directories
MONTH_STR = datetime.datetime.now().strftime("%Y_%m")
_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR
OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"{COMPANY_NAME}_NPA_New_{MONTH_STR}.csv")

TODAY_STR = datetime.datetime.now().strftime("%Y-%m-%d")

# Standard 24 Columns
COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์",
    "ประเภทการขาย", "ราคา", "ตำบล", "อำเภอ", "จังหวัด",
    "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ", "เลขโฉนด", "ยอดเข้าชม"
]


# Thailand Province Slug Mapping
PROVINCE_SLUG_MAP = {
    'rayong': 'ระยอง',
    'chonburi': 'ชลบุรี',
    'khonkaen': 'ขอนแก่น',
    'udon': 'อุดรธานี',
    'huahin': 'ประจวบคีรีขันธ์',
    'buriram': 'บุรีรัมย์',
    'phitsanulok': 'พิษณุโลก',
    'ubon': 'อุบลราชธานี',
    'chiangrai': 'เชียงราย',
    'surin': 'สุรินทร์',
    'bangkok': 'กรุงเทพมหานคร'
}

PROVINCES = [
    "กรุงเทพมหานคร", "กรุงเทพ", "กระบี่", "กาญจนบุรี", "กาฬสินธุ์", "กำแพงเพชร", "ขอนแก่น",
    "จันทบุรี", "ฉะเชิงเทรา", "ชลบุรี", "ชัยนาท", "ชัยภูมิ", "ชุมพร", "เชียงราย", "เชียงใหม่",
    "ตรัง", "ตราด", "ตาก", "นครนายก", "นครปฐม", "นครพนม", "นครราชสีมา", "นครศรีธรรมราช",
    "นครสวรรค์", "นนทบุรี", "นราธิวาส", "น่าน", "บึงกาฬ", "บุรีรัมย์", "ปทุมธานี", "ประจวบคีรีขันธ์",
    "ปราจีนบุรี", "ปัตตานี", "พระนครศรีอยุธยา", "พะเยา", "พังงา", "พัทลุง", "พิจิตร", "พิษณุโลก",
    "เพชรบุรี", "เพชรบูรณ์", "แพร่", "ภูเก็ต", "มหาสารคาม", "มุกดาหาร", "แม่ฮ่องสอน", "ยโสธร",
    "ยะลา", "ร้อยเอ็ด", "ระนอง", "ระยอง", "ราชบุรี", "ลพบุรี", "ลำปาง", "ลำพูน", "เลย", "ศรีสะเกษ",
    "สกลนคร", "สงขลา", "สตูล", "สมุทรปราการ", "สมุทรสงคราม", "สมุทรสาคร", "สระแก้ว", "สระบุรี",
    "สิงห์บุรี", "สุโขทัย", "สุพรรณบุรี", "สุราษฎร์ธานี", "สุรินทร์", "หนองคาย", "หนองบัวลำภู",
    "อ่างทอง", "อำนาจเจริญ", "อุดรธานี", "อุตรดิตถ์", "อุทัยธานี", "อุบลราชธานี"
]

# GIS Boundary Engine Cache
_GIS_TREE = None
_GIS_PROPS = None

SPECIAL_TAM_CLEAN = {
    'เทศบาลนครสมุทรปร': 'ปากน้ำ',
    'เทศบาลบางปู': 'บางปูใหม่',
    'เทศบาลบางเมือง': 'บางเมือง',
    'เทศบาลเมืองพระปร': 'ตลาด',
    'เทศบาลสำโรงใต้': 'สำโรงใต้',
    'เขตการปกคองพิเศษ': 'เมืองพัทยา',
    'ท่าเรือ (เทศบาลเมื': 'ท่าเรือ',
    'เทศบาลเมืองทุ่งส': 'ปากแพรก'
}

def _init_gis():
    global _GIS_TREE, _GIS_PROPS
    if _GIS_TREE is not None:
        return
    try:
        from shapely.geometry import shape
        from shapely.strtree import STRtree
        
        candidates = []
        if getattr(sys, '_MEIPASS', None):
            candidates.append(os.path.join(sys._MEIPASS, "subdistricts.geojson"))
        candidates.append(os.path.join(_BASE_DIR, "subdistricts.geojson"))
        candidates.append(os.path.join(os.path.dirname(_BASE_DIR), "subdistricts.geojson"))
        
        geojson_path = next((p for p in candidates if os.path.exists(p)), None)
        
        if geojson_path:
            with open(geojson_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            geoms = []
            props = []
            for feat in data.get("features", []):
                geom = shape(feat["geometry"])
                geoms.append(geom)
                p = feat.get("properties", {})
                tam = p.get("tam_th", "").strip()
                amp = p.get("amp_th", "").strip()
                pro = p.get("pro_th", "").strip()
                if tam in SPECIAL_TAM_CLEAN:
                    tam = SPECIAL_TAM_CLEAN[tam]
                if "กรุงเทพ" in pro:
                    pro = "กรุงเทพมหานคร"
                props.append((tam, amp, pro))
            _GIS_PROPS = props
            _GIS_TREE = STRtree(geoms)
            logger.info(f"Loaded {len(_GIS_PROPS):,} GIS subdistrict boundaries & built STRtree.")
    except Exception as e:
        logger.warning(f"Failed to load subdistricts.geojson: {e}")

def reverse_geocode_location(lat, lng):
    if not lat or not lng:
        return "", "", ""
    res = central_reverse_geocode(lat, lng)
    if res and any(res):
        return res
    return "", "", ""

def normalize_prop_type(raw_type, title=""):
    combined = f"{raw_type} {title}".lower()
    if any(w in combined for w in ["คอนโด", "ห้องชุด", "อาคารชุด"]):
        return "คอนโด"
    if any(w in combined for w in ["ทาวน์เฮ้าส์", "ทาวน์โฮม", "ทาวน์เฮาส์", "ทฮ"]):
        return "ทาวน์เฮ้าส์"
    if any(w in combined for w in ["บ้านแฝด", "บ้านเดี่ยว/แฝด"]):
        return "บ้านแฝด"
    if any(w in combined for w in ["บ้านเดี่ยว", "บ้านพร้อมที่ดิน", "บ้านพักอาศัย", "บ้าน"]):
        return "บ้านเดี่ยว"
    if any(w in combined for w in ["โฮมออฟฟิศ", "โฮมออฟฟิต", "home office", "homeoffice"]):
        return "โฮมออฟฟิศ"
    if any(w in combined for w in ["อาคารพาณิชย์", "ตึกแถว", "อาคาร"]):
        return "อาคารพาณิชย์"
    if any(w in combined for w in ["โรงงาน", "โกดัง", "คลังสินค้า"]):
        return "โรงงาน/โกดัง"
    if any(w in combined for w in ["ที่ดิน", "สวน", "ไร่", "นา", "เกษตรกรรม"]):
        return "ที่ดินเปล่า"
    if any(w in combined for w in ["โรงแรม", "รีสอร์ท", "อพาร์ทเม้นท์", "อพาร์ตเมนต์", "หอพัก"]):
        return "โรงแรม/รีสอร์ท"
    return "บ้านเดี่ยว" if raw_type else "อื่นๆ"

def parse_nayoo_areas(raw_land, raw_usable, title="", prop_type=""):
    combined = f"{raw_land} {raw_usable} {title}"
    land_area = ""
    usable_area = ""

    # 1. Parse Land Area
    if raw_land and str(raw_land).strip() not in ["", "nan", "None", "0"]:
        clean_l = str(raw_land).strip()
        m_dash = re.search(r'(?<!\d)([0-9]{1,3})\s*-\s*([0-3])\s*-\s*([0-9]{1,2}(?:\.[0-9]+)?)\s*(?:ไร่)?', clean_l)
        m_sqw = re.search(r'([\d\.,]+)\s*(?:ตร\.วา|ตารางวา|ตร\.ว\.|วา)', clean_l)
        if m_dash:
            land_area = f"{m_dash.group(1)} ไร่ {m_dash.group(2)} งาน {m_dash.group(3)} ตร.ว."
        elif m_sqw:
            land_area = f"{m_sqw.group(1).replace(',', '')} ตร.ว."
        elif re.match(r'^\d+(?:\.\d+)?$', clean_l):
            land_area = f"{clean_l} ตร.ว."
        else:
            land_area = clean_l

    if not land_area and title:
        m_dash = re.search(r'(?:ขนาดที่ดิน|เนื้อที่)?\s*([0-9]{1,3})\s*-\s*([0-3])\s*-\s*([0-9]{1,2}(?:\.[0-9]+)?)\s*(?:ไร่)?', title)
        m_txt_land = re.search(r'((?:\d+\s*ไร่\s*)?(?:\d+\s*งาน\s*)?[\d\.,]+\s*(?:ตร\.วา|ตารางวา|ตร\.ว\.|วา))', title)
        if m_dash and any(w in title for w in ["ไร่", "เนื้อที่", "ที่ดิน"]):
            land_area = f"{m_dash.group(1)} ไร่ {m_dash.group(2)} งาน {m_dash.group(3)} ตร.ว."
        elif m_txt_land:
            land_area = m_txt_land.group(1).strip()
            land_area = re.sub(r'(?<=\d|\s)(?:ตร\.วา|ตารางวา|วา)\b', 'ตร.ว.', land_area)

    # 2. Parse Usable Area (Filter out dummy 1.0 placeholder)
    if raw_usable and str(raw_usable).strip() not in ["", "nan", "None", "0"]:
        try:
            u_val = float(str(raw_usable).replace(',', '').strip())
            if u_val > 1.0:
                usable_area = f"{u_val:g}"
        except Exception:
            pass

    if not usable_area and title:
        m_txt_usable = re.search(r'([\d\.,]+)\s*(?:ตร\.ม\.|ตารางเมตร|sqm)\b', title, re.I)
        if m_txt_usable:
            try:
                u_val = float(m_txt_usable.group(1).replace(',', '').strip())
                if u_val > 1.0:
                    usable_area = f"{u_val:g}"
            except Exception:
                pass

    # Apply property type constraints
    if prop_type == "คอนโด":
        land_area = ""
    if prop_type in ("ที่ดิน", "ที่ดินเปล่า"):
        if not any(w in combined for w in ["ตึก", "อาคาร", "โรงงาน", "โกดัง", "บ้าน", "รีสอร์ท"]):
            usable_area = ""

    if land_area:
        land_area = re.sub(r'\s*วา$', ' ตร.ว.', land_area)
        land_area = re.sub(r'\s*ตารางวา$', ' ตร.ว.', land_area)
        land_area = re.sub(r'\s*ตร\.วา$', ' ตร.ว.', land_area)
        if re.match(r'^\d+(?:\.\d+)?$', land_area):
            land_area = f"{land_area} ตร.ว."

    return land_area, usable_area

def fetch_nayoo_page(session, endpoint, page, per_page=36, cooldown_cycles=0):
    url = f"{API_BASE}{endpoint}"
    params = {"page": page, "per_page": per_page}
    refreshed_key = False

    def _fetch():
        nonlocal refreshed_key
        hdrs = _ensure_nayoo_headers(session=session)
        r = safe_ssl_get(session, url, headers=hdrs, params=params, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 401 and not refreshed_key:
            refreshed_key = True
            hdrs = _ensure_nayoo_headers(session=session, force_refresh=True)
            r = safe_ssl_get(session, url, headers=hdrs, params=params, timeout=100, ssl_fallback_on_gov=False)
            if r.status_code == 200:
                return r.json()
        if r.status_code == 401:
            logger.error("NaYoo API 401 Unauthorized - Check API Key!")
            raise ValueError("NaYoo API 401 Unauthorized")
        r.raise_for_status()
        return None

    try:
        return execute_with_retry(_fetch, company_name=COMPANY_NAME, context_msg=f"NaYoo {endpoint} p{page}", max_retries=4, max_cooldown_cycles=2)
    except ValueError:
        return None
    except Exception:
        logger.warning(f"ข้าม NaYoo {endpoint} หน้า {page} เนื่องจากพักรอและลองซ้ำไม่สำเร็จ")
        return None

def fetch_and_process_item(session, item):
    pid = str(item.get("id") or item.get("uuid") or "").strip()
    if not pid or pid == "None":
        return None

    # Project candidate & Title
    raw_p_name = item.get("project_name")
    proj_cand = ""
    if isinstance(raw_p_name, dict):
        proj_cand = str(raw_p_name.get("th") or raw_p_name.get("en") or "").strip()
    elif isinstance(raw_p_name, str):
        proj_cand = raw_p_name.strip()

    title = item.get("title") or ""
    if isinstance(title, dict):
        title = str(title.get("th") or title.get("en") or "").strip()
    if not title and proj_cand:
        title = proj_cand
    if not title:
        title = item.get("slug", "").replace("-", " ")
    if not title:
        return None

    # Property Type
    raw_type = ""
    p_info = item.get("project_info", {})
    if isinstance(p_info, dict):
        p_types = p_info.get("property_type", [])
        if isinstance(p_types, list) and p_types:
            first_pt = p_types[0]
            if isinstance(first_pt, dict):
                raw_type = first_pt.get("name", {}).get("th", "") or first_pt.get("slug", "")
    if not raw_type and item.get("property_type"):
        pt_val = item.get("property_type")
        if isinstance(pt_val, dict):
            raw_type = pt_val.get("name", {}).get("th") or pt_val.get("slug", "")
        elif isinstance(pt_val, str):
            raw_type = pt_val
    prop_type = normalize_prop_type(raw_type, title)

    # Price & Sale Type
    pricing = item.get("pricing", {}) or {}
    price = None
    sale_type = "ขาย"

    if isinstance(pricing, dict):
        p_val = pricing.get("sale_price") or pricing.get("start_price") or pricing.get("starting_price") or pricing.get("promotion_price")
        if p_val and str(p_val).replace('.', '').isdigit():
            try:
                p_num = float(p_val)
                if p_num > 0: price = p_num
            except Exception: pass
        if not price and pricing.get("rent_price"):
            # Filter pure rental listings per requirement
            return None

    if not price and item.get("price"):
        try:
            p_num = float(item.get("price"))
            if p_num > 0: price = p_num
        except Exception: pass

    # Functions (Bed, Bath, Area)
    funcs = item.get("functions", {}) or {}
    bed = funcs.get("bedrooms") if isinstance(funcs, dict) else None
    bath = funcs.get("bathrooms") if isinstance(funcs, dict) else None
    parking = funcs.get("parking") if isinstance(funcs, dict) else None
    raw_land = funcs.get("land_area") if isinstance(funcs, dict) else ""
    raw_usable = funcs.get("usable_area") if isinstance(funcs, dict) else ""

    # Fetch Detailed endpoint for Coordinates and Precise Location
    detail_data = None
    lat, lng = None, None
    subdist, dist, prov = "", "", ""
    post_date = ""

    try:
        time.sleep(max(0.4, min(1.5, get_scraper_delay() / 10.0)))
        hdrs = _ensure_nayoo_headers(session=session)
        r_det = safe_ssl_get(session, f"{API_BASE}/api/listing/post/{pid}", headers=hdrs, timeout=100, ssl_fallback_on_gov=False)
        if r_det.status_code == 200:
            detail_data = r_det.json().get("data", {})
    except Exception:
        pass

    if detail_data:
        loc = detail_data.get("location", {})
        coords = loc.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                c0 = float(coords[0])
                c1 = float(coords[1])
                if c0 != 0 or c1 != 0:
                    lat, lng = c0, c1
            except Exception:
                pass

        if lat and lng:
            sd_geo, d_geo, p_geo = reverse_geocode_location(lat, lng)
            if sd_geo: subdist = sd_geo
            if d_geo: dist = d_geo
            if p_geo: prov = p_geo

        if not prov or not dist:
            p_dict = loc.get("province", {})
            if isinstance(p_dict, dict): prov = p_dict.get("name", {}).get("th", "")
            d_dict = loc.get("district", {})
            if isinstance(d_dict, dict): dist = d_dict.get("name", {}).get("th", "")
            sd_dict = loc.get("sub_district", {})
            if isinstance(sd_dict, dict): subdist = sd_dict.get("name", {}).get("th", "")

        spec = detail_data.get("spec", {})
        if isinstance(spec, dict):
            if spec.get("parking") is not None:
                parking = spec.get("parking")
            if spec.get("bedroom") is not None:
                bed = spec.get("bedroom")
            if spec.get("bathroom") is not None:
                bath = spec.get("bathroom")
            if spec.get("usable_area") and float(spec.get("usable_area") or 0) > 1.0:
                raw_usable = spec.get("usable_area")

        # Price fallback from detail_data
        det_pricing = detail_data.get("pricing", {}) or {}
        if isinstance(det_pricing, dict):
            det_val = det_pricing.get("sale_price") or det_pricing.get("start_price") or det_pricing.get("starting_price") or det_pricing.get("promotion_price")
            if det_val and str(det_val).replace('.', '').isdigit():
                try:
                    d_num = float(det_val)
                    if d_num > 0 and (not price or price == 0):
                        price = d_num
                except Exception: pass
            if (not price or price == 0) and det_pricing.get("rent_price"):
                try:
                    r_num = float(det_pricing.get("rent_price"))
                    if r_num > 0:
                        price = r_num
                        sale_type = "ให้เช่า"
                except Exception: pass

        if (not price or price == 0) and detail_data.get("price"):
            try:
                d_num = float(detail_data.get("price"))
                if d_num > 0: price = d_num
            except Exception: pass

        det_types = detail_data.get("listing_types") or item.get("listing_types") or []
        if isinstance(det_types, list) and "rent" in det_types and "sale" not in det_types:
            sale_type = "ให้เช่า"

        pub_dt = detail_data.get("published_at") or detail_data.get("created_at") or detail_data.get("updated_at")
        if pub_dt:
            post_date = str(pub_dt)[:10]

    # Smart price sanity check (filter out seller input typos like phone numbers or billion errors)
    desc_obj = (detail_data.get("description") if detail_data else None) or item.get("description") or {}
    desc_text = desc_obj.get("th", "") if isinstance(desc_obj, dict) else str(desc_obj or "")
    combined_text = f"{title} {desc_text}"
    if price and price > 1_000_000_000:
        m_lakh = re.findall(r'(?:ราคา|ขาย|เพียง)?\s*[:\s]*(\d+(?:\.\d+)?)\s*(?:ล้านบาท|ล้าน|ลบ\b)', combined_text)
        if m_lakh:
            try:
                candidate = float(m_lakh[0]) * 1_000_000
                if 100_000 <= candidate <= 500_000_000:
                    price = candidate
            except Exception:
                pass

    if price is not None and price < 500.0:
        price = None

    # Fallback for location if detail was not reachable
    if not prov:
        p_obj = item.get("province", {})
        p_slug = p_obj.get("slug", "") if isinstance(p_obj, dict) else str(p_obj)
        prov = PROVINCE_SLUG_MAP.get(str(p_slug).lower(), "")

    if not post_date:
        dt_str = item.get("created_at") or item.get("updated_at") or ""
        if dt_str:
            post_date = str(dt_str)[:10]

    # Clean location strings
    if dist:
        dist = dist.replace("อำเภอ", "").replace("เขต", "").strip()
    if subdist:
        subdist = subdist.replace("ตำบล", "").replace("แขวง", "").strip()
    if prov == "กรุงเทพ":
        prov = "กรุงเทพมหานคร"

    land_area, usable_area = parse_nayoo_areas(raw_land, raw_usable, title=title, prop_type=prop_type)

    p_obj = item.get("province", {})
    p_slug = p_obj.get("slug", "") if isinstance(p_obj, dict) else str(p_obj)
    item_slug = item.get("slug", "")
    if item_slug:
        link = f"https://nayoo.co/property-for-sale/properties/{p_slug or 'thailand'}/{item_slug}"
    else:
        link = f"https://nayoo.co/posts/{pid}"

    floor_val = None
    if isinstance(detail_data, dict):
        spec = detail_data.get("spec", {})
        if isinstance(spec, dict):
            floor_val = clean_floor_val(spec.get("floor") or spec.get("floors") or spec.get("total_floor") or spec.get("number_of_floors") or spec.get("storey"))
    if not floor_val:
        floor_val = extract_floor_from_text(combined_text, title, asset_type=prop_type)

    pull_date = TODAY_STR

    raw_views = item.get("views")
    if raw_views is None and isinstance(detail_data, dict):
        raw_views = detail_data.get("views")
    try:
        views_count = int(raw_views) if raw_views is not None and str(raw_views).isdigit() else None
    except Exception:
        views_count = None

    return {
        "บริษัท": COMPANY_NAME,
        "ID": pid,
        "รหัสทรัพย์": pid,
                # Clean project name using centralized cleaning engine
        "ชื่อโครงการ": (clean_project_name(proj_cand, tambon=subdist, amphoe=dist, province=prov, company=COMPANY_NAME) if proj_cand else (extract_project_from_title(title, tambon=subdist, amphoe=dist, province=prov, company=COMPANY_NAME) if extract_project_from_title else "")) if clean_project_name else "",
        "ประเภททรัพย์": prop_type,
        "ประเภทการขาย": sale_type,
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
        "วันที่ดึงข้อมูล": pull_date,
        "ห้องนอน": bed,
        "ห้องน้ำ": bath,
        "ที่จอดรถ": parking,
        "ชั้น": floor_val or "",
        "วันประกาศ": post_date,
        "เลขโฉนด": "",
        "ยอดเข้าชม": views_count
    }

def save_to_csv(records, filename):
    return atomic_write_csv(records, filename, COLUMNS, company_name=COMPANY_NAME)

def load_existing_csv(filename):
    if "--fresh" in sys.argv or "--force-restart" in sys.argv:
        print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นดึงข้อมูลใหม่ทั้งหมดจากหน้า 1 (โหมด --fresh)", flush=True)
        reset_scraper_state(COMPANY_NAME, MONTH_STR)
        return [], set()
    return read_csv_resume(filename, COLUMNS, id_col="ID", company_name=COMPANY_NAME)

def scrape_nayoo(progress_callback=None):
    logger.info("=" * 65)
    logger.info("🚀 Starting NaYoo (น่าอยู่) Monthly Scraper")
    logger.info("=" * 65)

    start_time = time.time()
    failed_units = []
    saved_milestones = set()

    _init_gis()

    session = AuditedSession(company_name=COMPANY_NAME)
    adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    _ensure_nayoo_headers(session=session)

    endpoints = [
        ("/api/listing/search/secondhands", "Secondhands (อสังหามือสอง)")
    ]

    endpoint_configs = []
    total_all_pages = 0
    total_all_items = 0

    # Probe page 1 FIRST before --fresh resets existing data
    for ep, ep_label in endpoints:
        res1 = fetch_nayoo_page(session, ep, page=1, per_page=36)
        if not res1 or not res1.get("success"):
            from logger_util import print_structure_alert
            print_structure_alert(COMPANY_NAME, f"ไม่สามารถเรียก API Endpoint '{ep}' หรือ API Key/Header หมดอายุ (โครงสร้าง NaYoo API เปลี่ยนแปลง)")
            logger.warning(f"Failed to fetch initial page for {ep_label}")
            failed_units.append(f"หมวด {ep_label} หน้า 1")
            continue

        pag = res1.get("data", {}).get("pagination", {})
        total_items = int(pag.get("total_items") or pag.get("total") or 0)
        items_per_page = int(pag.get("items_per_page") or 36)
        total_pages = (total_items + items_per_page - 1) // items_per_page if total_items > 0 else 0

        total_all_pages += total_pages
        total_all_items += total_items
        endpoint_configs.append({
            "ep": ep,
            "ep_label": ep_label,
            "total_pages": total_pages,
            "res1": res1
        })

    if not endpoint_configs or total_all_pages <= 0:
        print_alert("ไม่สามารถเชื่อมต่อ NaYoo API หรือไม่พบข้อมูลหน้าแรก (ยกเลิกก่อนเขียนทับไฟล์เดิม)", level="CRITICAL")
        sys.exit(1)

    print(f"[{COMPANY_NAME}] 🌐 สถานะลิงก์: ปกติ (HTTP 200) | ทั้งหมด {total_all_pages:,} หน้า | (พบทั้งหมด {total_all_items:,} รายการ)", flush=True)

    all_records, seen_ids = load_existing_csv(OUTPUT_CSV)
    saved_state = load_scraper_state(COMPANY_NAME, MONTH_STR)
    prev_failed_pages = [int(p) for p in (saved_state.get("failed_pages") or []) if str(p).isdigit()]

    # 1. Fast-Forward check: only when COMPLETED cleanly with no failed pages
    if not prev_failed_pages and total_all_items > 0 and (saved_state.get("status") == "COMPLETED" or len(all_records) >= total_all_items):
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลใน CSV ครบถ้วน 100% แล้ว ({total_all_pages:5,d}/{total_all_pages:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{total_all_items:,d} รายการ -> สแครปเสร็จสมบูรณ์ทันที!", flush=True)
        save_to_csv(all_records, OUTPUT_CSV)
        save_scraper_state(COMPANY_NAME, total_all_pages, total_all_pages, len(all_records), status="COMPLETED", month_str=MONTH_STR)
        log_success(COMPANY_NAME, f"✅ ข้อมูลใน CSV ครบถ้วน 100% อยู่แล้ว ({len(all_records):,} รายการ)")
        return pd.DataFrame(all_records)

    # 2. Smart Resume: Calculate completed pages from state (NaYoo has ~30 genuine properties + 6 insert ads per page)
    saved_page = int(saved_state.get("completed_pages", 0) or 0)
    calc_pages = min(total_all_pages - 1, len(all_records) // 30) if total_all_pages > 0 else 0
    completed_pages = max(saved_page, calc_pages)
    completed_pages = min(total_all_pages - 1, completed_pages) if total_all_pages > 0 else 0
    pages_scanned = completed_pages
    start_page = completed_pages + 1

    if completed_pages > 0:
        pct_start = int(pages_scanned * 100 / total_all_pages) if total_all_pages > 0 else 0
        for target_pct in range(5, pct_start + 1, 5):
            saved_milestones.add(target_pct)
        saved_milestones.add("initial_page")
        print(f"[{COMPANY_NAME}] ⏩ Smart Fast-Forward: ข้ามหน้าที่เคยดึงแล้ว 1..{completed_pages:,} หน้า ({pct_start}%) -> กระโดดไปต่อหน้าที่ {start_page:,} ทันที!", flush=True)
        p_bar = make_progress_bar(pct_start, length=20)
        print(f"[{COMPANY_NAME:<13s}] {p_bar} | ({pages_scanned:5,d}/{total_all_pages:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{total_all_items:,d} รายการ", flush=True)

    failed_page_nums = []

    # 3. Fetch remaining pages sequentially
    for cfg in endpoint_configs:
        ep = cfg["ep"]
        ep_label = cfg["ep_label"]
        tot_p = cfg["total_pages"]
        res1 = cfg["res1"]

        # If starting from page 1
        if start_page == 1:
            posts1 = res1.get("data", {}).get("posts", []) or []
            for p in posts1:
                pid = str(p.get("id") or p.get("uuid") or "").strip()
                if pid and pid not in seen_ids:
                    rec = fetch_and_process_item(session, p)
                    if rec:
                        seen_ids.add(pid)
                        all_records.append(rec)

            pages_scanned += 1
            pct = int(pages_scanned * 100 / total_all_pages)
            p_bar = make_progress_bar(pct, length=20)
            elapsed_cur = time.time() - start_time
            eta_str = format_eta(elapsed_cur, pages_scanned, total_all_pages, 1)
            print(f"[{COMPANY_NAME:<13s}] {p_bar} | ({pages_scanned:5,d}/{total_all_pages:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{total_all_items:,d} รายการ | {eta_str}", flush=True)

            if "initial_page" not in saved_milestones and len(all_records) > 0:
                saved_milestones.add("initial_page")
                print(f"\n💾 [{COMPANY_NAME}] รายการแรก -> บันทึกไฟล์เริ่มต้นลง {os.path.basename(OUTPUT_CSV)}...", flush=True)
                log_milestone(COMPANY_NAME, f"💾 บันทึกเริ่มต้น (รายการแรก) {len(all_records):,} รายการลง " + os.path.basename(OUTPUT_CSV))
                save_to_csv(all_records, OUTPUT_CSV)
                save_scraper_state(COMPANY_NAME, pages_scanned, total_all_pages, len(all_records), status="RUNNING", month_str=MONTH_STR)

        loop_start = max(2, start_page)
        pages_to_run = sorted(set([p for p in prev_failed_pages if 2 <= p < loop_start] + list(range(loop_start, tot_p + 1))))
        # Fetch remaining pages sequentially with polite delay
        for p_num in pages_to_run:
            try:
                p_res = fetch_nayoo_page(session, ep, p_num, 36)
                if p_res and p_res.get("success"):
                    p_posts = p_res.get("data", {}).get("posts", []) or []
                    for item in p_posts:
                        pid = str(item.get("id") or item.get("uuid") or "").strip()
                        if pid and pid not in seen_ids:
                            rec = fetch_and_process_item(session, item)
                            if rec:
                                seen_ids.add(pid)
                                all_records.append(rec)
                    if not failed_page_nums:
                        pages_scanned = max(pages_scanned, p_num)
                else:
                    failed_units.append(f"หมวด {ep_label} หน้า {p_num}")
                    failed_page_nums.append(p_num)
            except Exception as e:
                logger.warning(f"Error on {ep_label} page {p_num}: {e}")
                failed_units.append(f"หมวด {ep_label} หน้า {p_num}")
                failed_page_nums.append(p_num)

            pct = int(pages_scanned * 100 / total_all_pages)
            p_bar = make_progress_bar(pct, length=20)
            elapsed_cur = time.time() - start_time
            eta_str = format_eta(elapsed_cur, pages_scanned, total_all_pages, start_unit=start_page)
            print(f"[{COMPANY_NAME:<13s}] {p_bar} | ({pages_scanned:5,d}/{total_all_pages:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{total_all_items:,d} รายการ | {eta_str}", flush=True)

            # Checkpoint every 5 pages and at milestones
            if p_num % 5 == 0:
                save_to_csv(all_records, OUTPUT_CSV)
                save_scraper_state(COMPANY_NAME, pages_scanned, total_all_pages, len(all_records), status="RUNNING", month_str=MONTH_STR, extra={"failed_pages": failed_page_nums})

            for target_pct in range(5, 105, 5):
                if pct >= target_pct and target_pct not in saved_milestones:
                    saved_milestones.add(target_pct)
                    save_scraper_state(COMPANY_NAME, pages_scanned, total_all_pages, len(all_records), status="RUNNING", month_str=MONTH_STR, extra={"failed_pages": failed_page_nums})
                    print(f"\n💾 [{COMPANY_NAME}] ครบ Milestone {target_pct}% ({pages_scanned}/{total_all_pages} หน้า) -> บันทึกสำรองลง {os.path.basename(OUTPUT_CSV)}...", flush=True)
                    log_milestone(COMPANY_NAME, f"💾 บันทึก Milestone สำรอง {target_pct}% ({len(all_records):,} รายการ) ลง " + os.path.basename(OUTPUT_CSV))
                    save_to_csv(all_records, OUTPUT_CSV)

            if progress_callback:
                progress_callback(pct, f"Scraped {pages_scanned}/{total_all_pages} pages ({len(all_records):,} items)")

            time.sleep(get_scraper_delay()) # หน่วงเวลาอย่างน้อย 15 วินาทีต่อหน้า

    # Convert to DataFrame & Final Deduplicate
    df = pd.DataFrame(all_records)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[COLUMNS]

    df.dropna(subset=["ID"], inplace=True)
    df.drop_duplicates(subset=["ID"], inplace=True)
    save_to_csv(df.to_dict('records'), OUTPUT_CSV)

    elapsed = time.time() - start_time
    if failed_units or failed_page_nums:
        final_status = "FAILED" if len(df) == 0 else "PARTIAL"
        save_scraper_state(COMPANY_NAME, pages_scanned, total_all_pages, len(df), status=final_status, month_str=MONTH_STR, extra={"failed_pages": failed_page_nums})
        print(f"\n==================================================", flush=True)
        print(f"⚠️ [{COMPANY_NAME}] สแครปเสร็จแบบมีรายการล้มเหลว ({final_status}) | ({pages_scanned:5,d}/{total_all_pages:5,d} หน้า) | สะสม: {len(df):>6,d}/{total_all_items:,d} รายการ", flush=True)
        print(f"⚠️ รายการที่ข้าม/ดึงไม่ได้ ({len(failed_units)} รายการ): {sorted(failed_units)[:30]}", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที | 💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        log_warning(COMPANY_NAME, f"⚠️ สแครปเสร็จแบบ {final_status}: ดึงไม่ได้ {len(failed_units)} รายการ")
        sys.exit(1 if len(df) == 0 else 2)
    else:
        save_scraper_state(COMPANY_NAME, total_all_pages, total_all_pages, len(df), status="COMPLETED", month_str=MONTH_STR, extra={"failed_pages": []})
        print(f"\n==================================================", flush=True)
        print(f"✅ [{COMPANY_NAME}] สแครปเสร็จสมบูรณ์! | ({total_all_pages:5,d}/{total_all_pages:5,d} หน้า) | สะสม: {len(df):>6,d}/{total_all_items:,d} รายการ", flush=True)
        print(f"📊 ได้ข้อมูลทั้งหมด: {len(df):,} รายการ", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที", flush=True)
        print(f"💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        print(f"✅ ดึงข้อมูลได้ครบถ้วนสำเร็จ 100% (ไม่มีรายการล้มเหลว)", flush=True)
        print(f"==================================================", flush=True)
        log_success(COMPANY_NAME, f"✅ สแครปเสร็จสมบูรณ์! ได้ข้อมูลทั้งหมดสะสม {len(df):,} รายการลง {os.path.basename(OUTPUT_CSV)}")

    return df

main = scrape_nayoo

if __name__ == "__main__":
    main()

