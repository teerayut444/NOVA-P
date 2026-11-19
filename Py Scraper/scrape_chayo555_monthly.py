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
    read_csv_resume,
    atomic_write_csv,
)
from timeout_handler import wait_1hr_on_timeout, handle_timeout_retry, execute_with_retry
from time_window_util import get_scraper_delay

# -*- coding: utf-8 -*-
"""
Chayo555 NPA Monthly Scraper
Scrapes all NPA properties from https://asset.chayo555.com
Adheres strictly to the 16 standard dashboard columns, GIS reverse geocoding, and monthly export structure.
"""

import os
import re
import sys
import time
import json
import logging
import datetime
import random
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
from bs4 import BeautifulSoup

from clean_location_util import clean_floor_val, extract_floor_from_text
try:
    from clean_project_util import clean_project_name
except ImportError:
    clean_project_name = lambda x, **kwargs: str(x).strip()

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
COMPANY_NAME = "Chayo555"
BASE_URL = "https://asset.chayo555.com"
SEARCH_URL = f"{BASE_URL}/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "th,en-US;q=0.9,en;q=0.8",
    "Referer": "https://asset.chayo555.com/",
}

# Output directories
MONTH_STR = datetime.datetime.now().strftime("%Y_%m")
_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR
OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"{COMPANY_NAME}_NPA_New_{MONTH_STR}.csv")

# Standard 22 Columns
COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคา",
    "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ"
]

# Thailand Provinces for fallback normalization
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
        from shapely.geometry import shape, Point
        from shapely.strtree import STRtree
        
        candidates = []
        if getattr(sys, '_MEIPASS', None):
            candidates.append(os.path.join(sys._MEIPASS, "subdistricts.geojson"))
            candidates.append(os.path.join(sys._MEIPASS, "data", "subdistricts.geojson"))
        candidates.append(os.path.join(_BASE_DIR, "subdistricts.geojson"))
        candidates.append(os.path.join(_BASE_DIR, "data", "subdistricts.geojson"))
        candidates.append(os.path.join(os.path.dirname(_BASE_DIR), "subdistricts.geojson"))
        candidates.append(os.path.join(os.path.dirname(_BASE_DIR), "data", "subdistricts.geojson"))
        
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

def reverse_geocode_location(session, lat, lng):
    if not lat or not lng:
        return "", "", ""
    try:
        lat_f = float(lat)
        lng_f = float(lng)
        if not (5.0 < lat_f < 21.0 and 97.0 < lng_f < 106.0):
            return "", "", ""
        _init_gis()
        if _GIS_TREE is not None and _GIS_PROPS is not None:
            from shapely.geometry import Point
            pt = Point(lng_f, lat_f)
            res = _GIS_TREE.query(pt, predicate='intersects')
            if len(res) > 0:
                g_idx = res[0]
                return _GIS_PROPS[g_idx]
            else:
                nearest = _GIS_TREE.query_nearest(pt)
                if len(nearest) > 0:
                    import numpy as np
                    g_idx = nearest[0] if not isinstance(nearest[0], (list, tuple, np.ndarray)) else nearest[1][0]
                    return _GIS_PROPS[g_idx]
    except Exception:
        pass

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
    if any(w in combined for w in ["โรงแรม", "รีสอร์ท", "อพาร์ทเม้นท์", "อพาร์ตเมนต์"]):
        return "โรงแรม/รีสอร์ท"
    return "บ้านเดี่ยว" if raw_type else "อื่นๆ"

def parse_chayo_areas(full_text, spec_land="", spec_usable="", prop_type=""):
    land_area = ""
    usable_area = ""

    # 1. Prefer spec_land / spec_usable directly from sidebar if present
    if spec_land and str(spec_land).strip() not in ["", "nan", "None"]:
        clean_l = str(spec_land).strip()
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

    if not land_area:
        m_dash = re.search(r'(?:ขนาดที่ดิน|เนื้อที่)\s*[:\s]*([0-9]{1,3})\s*-\s*([0-3])\s*-\s*([0-9]{1,2}(?:\.[0-9]+)?)\s*(?:ไร่)?', full_text)
        m_txt_land = re.search(r'(?:ขนาดที่ดิน|เนื้อที่)\s*[:\s]*((?:\d+\s*ไร่\s*)?(?:\d+\s*งาน\s*)?[\d\.,]+\s*(?:ตร\.วา|ตารางวา|ตร\.ว\.|วา))', full_text)
        if m_dash:
            land_area = f"{m_dash.group(1)} ไร่ {m_dash.group(2)} งาน {m_dash.group(3)} ตร.ว."
        elif m_txt_land:
            land_area = m_txt_land.group(1).strip()
            land_area = re.sub(r'(?<=\d|\s)(?:ตร\.วา|ตารางวา|วา)\b', 'ตร.ว.', land_area)

    # 2. Usable Area
    if spec_usable and str(spec_usable).strip() not in ["", "nan", "None"]:
        m_u = re.search(r'([\d\.,]+)', str(spec_usable))
        if m_u:
            usable_area = m_u.group(1).replace(',', '').strip()

    if not usable_area:
        m_txt_usable = re.search(r'พื้นที่ใช้สอย\s*[:\s]*([\d\.,]+)\s*(?:ตร\.ม\.|ตารางเมตร|sqm)?', full_text)
        if m_txt_usable:
            usable_area = m_txt_usable.group(1).replace(',', '').strip()

    # Apply property type constraints
    if prop_type == "คอนโด":
        land_area = ""
    if prop_type in ("ที่ดิน", "ที่ดินเปล่า"):
        if not any(w in full_text for w in ["ตึก", "อาคาร", "โรงงาน", "โกดัง", "บ้าน", "รีสอร์ท"]):
            usable_area = ""

    if land_area:
        land_area = re.sub(r'\s*วา$', ' ตร.ว.', land_area)
        land_area = re.sub(r'\s*ตารางวา$', ' ตร.ว.', land_area)
        land_area = re.sub(r'\s*ตร\.วา$', ' ตร.ว.', land_area)
        if re.match(r'^\d+(?:\.\d+)?$', land_area):
            land_area = f"{land_area} ตร.ว."

    return land_area, usable_area

def fetch_chayo_detail(session, item_url, preview_data):
    try:
        def _get_detail():
            time.sleep(get_scraper_delay()) # หน่วงเวลาอย่างน้อย 15 วินาที
            r = safe_ssl_get(session, item_url, headers=HEADERS, timeout=100, ssl_fallback_on_gov=False)
            if r.status_code != 200:
                r.raise_for_status()
            return r

        r = execute_with_retry(_get_detail, company_name=COMPANY_NAME, context_msg=f"รายละเอียด {item_url.split('/')[-1]}", max_retries=3, max_cooldown_cycles=1)

        soup = BeautifulSoup(r.text, 'html.parser')
        full_text = soup.get_text()

        title = ""
        h_title = soup.find(['h1', 'h2', 'h3', 'h4'], class_=re.compile(r'title|name', re.I))
        if h_title:
            title = h_title.get_text().strip()
        if not title:
            t_tag = soup.find('title')
            if t_tag:
                title = t_tag.get_text().split('-')[0].strip()
        if not title:
            title = preview_data.get("ชื่อโครงการ", "")

        code = preview_data.get("รหัสทรัพย์", "")
        if not code or any(ord(c) >= 0x0E00 and ord(c) <= 0x0E7F for c in code):
            # 1. Search for inner_label span with รหัสทรัพย์
            for span in soup.find_all('span', class_=re.compile(r'inner_label', re.I)):
                if 'รหัสทรัพย์' in span.get_text():
                    parent = span.parent
                    if parent:
                        raw = parent.get_text().replace(span.get_text(), '').strip()
                        clean = re.sub(r'[\u0E00-\u0E7F\s]', '', raw).strip()
                        if clean:
                            code = clean
                            break
            # 2. Regex fallback in HTML / full_text
            if not code or any(ord(c) >= 0x0E00 and ord(c) <= 0x0E7F for c in code):
                m_code = re.search(r'รหัสทรัพย์(?:สิน)?\s*(?:</span>)?\s*[\u0E00-\u0E7F\s]*([A-Za-z0-9\-\/_]+)', r.text) or re.search(r'รหัสทรัพย์(?:สิน)?\s*[:\s]*[\u0E00-\u0E7F\s]*([A-Za-z0-9\-\/_]+)', full_text)
                if m_code:
                    code = m_code.group(1).strip()

        price = preview_data.get("ราคา", None)
        if price is not None:
            try:
                if float(price) < 500.0: price = None
            except Exception:
                price = None
        m_price = re.search(r'ราคา(?:ขาย)?\s*[:\s]*฿?([\d,]+)', full_text)
        if m_price:
            p_val = m_price.group(1).replace(',', '').strip()
            if p_val.isdigit() and int(p_val) >= 500:
                price = float(p_val)

        spec_land = ""
        spec_subdist = ""
        spec_dist = ""
        spec_prov = ""

        for span in soup.find_all('span'):
            txt = span.get_text().strip()
            parent_txt = span.parent.get_text().strip() if span.parent else ""
            if 'เนื้อที่' in txt:
                spec_land = parent_txt.replace(txt, '').strip()
            elif 'แขวง/ตำบล' in txt or 'ตำบล' in txt:
                spec_subdist = parent_txt.replace(txt, '').strip()
            elif 'เขต/อำเภอ' in txt or 'อำเภอ' in txt:
                spec_dist = parent_txt.replace(txt, '').strip()
            elif 'จังหวัด' in txt:
                spec_prov = parent_txt.replace(txt, '').strip()

        if not spec_prov or not spec_dist:
            m_addr = re.search(r'ที่ตั้งทรัพย์\s*[:\s]*(.*?)(?=✨|ขนาด|พื้นที่|$)', full_text, re.DOTALL)
            if m_addr:
                addr_text = m_addr.group(1).strip().replace('\n', ' ')
                m_sd = re.search(r'(?:ตำบล|แขวง)\s*([^\s,]+)', addr_text)
                if m_sd: spec_subdist = m_sd.group(1).strip()
                m_d = re.search(r'(?:อำเภอ|เขต)\s*([^\s,]+)', addr_text)
                if m_d: spec_dist = m_d.group(1).strip()
                m_p = re.search(r'(?:จังหวัด|จ\.)\s*([^\s,]+)', addr_text)
                if m_p: spec_prov = m_p.group(1).strip()

        if not spec_prov:
            for p in PROVINCES:
                if p in title or p in item_url:
                    spec_prov = "กรุงเทพมหานคร" if p == "กรุงเทพ" else p
                    break

        if spec_prov == "กรุงเทพ":
            spec_prov = "กรุงเทพมหานคร"

        lat, lng = None, None
        m_map = (
            re.search(r'(?:query|daddr|q|center|loc|ll|markers)=([0-9\.\-]+)[,%2C]+([0-9\.\-]+)', r.text)
            or re.search(r'(?:maps\.google\.com|google\.com/maps)[^"\']*(?:q|center|ll)=([0-9\.\-]+)[,%2C]+([0-9\.\-]+)', r.text)
            or re.search(r'latitude["\']?\s*[:=]\s*["\']?([0-9\.\-]+)["\']?.*?[,]?\s*longitude["\']?\s*[:=]\s*["\']?([0-9\.\-]+)["\']?', r.text, re.I)
            or re.search(r'(?:lat|latitude)[=:\s]+(["\']?[\d\.-]+["\']?).*?(?:lng|longitude|lon)[=:\s]+(["\']?[\d\.-]+)["\']?', r.text, re.I)
        )
        if m_map:
            try:
                v1 = float(re.sub(r'["\']', '', m_map.group(1)))
                v2 = float(re.sub(r'["\']', '', m_map.group(2)))
                if 5.0 <= v1 <= 21.0 and 97.0 <= v2 <= 106.0:
                    lat, lng = v1, v2
            except Exception:
                pass

        if lat and lng:
            sd_geo, d_geo, p_geo = reverse_geocode_location(session, lat, lng)
            if sd_geo: spec_subdist = sd_geo
            if d_geo: spec_dist = d_geo
            if p_geo: spec_prov = p_geo

        bed = None
        m_bed = re.search(r'(\d+)\s*ห้องนอน', full_text)
        if m_bed:
            try: bed = int(m_bed.group(1))
            except Exception: pass

        bath = None
        m_bath = re.search(r'(\d+)\s*ห้องน้ำ', full_text)
        if m_bath:
            try: bath = int(m_bath.group(1))
            except Exception: pass

        parking = None
        m_park = re.search(r'(\d+)\s*(?:ที่)?จอดรถ', full_text)
        if m_park:
            try: parking = int(m_park.group(1))
            except Exception: pass

        pull_date = datetime.datetime.now().strftime("%Y-%m-%d")
        post_date = ""
        m_date = re.search(r'(?:ประกาศเมื่อ|วันที่ลงประกาศ|สร้างเมื่อ)\s*[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})', full_text)
        if m_date:
            post_date = m_date.group(1).strip()

        prop_type = normalize_prop_type(preview_data.get("ประเภททรัพย์", ""), title)
        land_area, usable_area = parse_chayo_areas(full_text, spec_land=spec_land, prop_type=prop_type)
        floor = extract_floor_from_text(full_text, title, asset_type=prop_type)

        return {
            "บริษัท": COMPANY_NAME,
            "ID": code or item_url.split('/')[-1],
            "รหัสทรัพย์": code or item_url.split('/')[-1],
            "ชื่อโครงการ": clean_project_name(title, tambon=spec_subdist, amphoe=spec_dist, province=spec_prov, company=COMPANY_NAME) if clean_project_name else "",
            "ประเภททรัพย์": prop_type,
            "ประเภทการขาย": "ขาย",
            "ราคา": price,
            "ตำบล": spec_subdist,
            "อำเภอ": spec_dist,
            "จังหวัด": spec_prov,
            "ละติจูด": lat,
            "ลองจิจูด": lng,
            "ชื่อประกาศ": title,
            "ลิงก์": item_url,
            "เนื้อที่ (ตร.ว.)": convert_to_rai_ngan_wah(land_area),
            "พื้นที่ใช้สอย (ตร.ม.)": usable_area,
            "วันที่ดึงข้อมูล": pull_date,
            "ห้องนอน": bed,
            "ห้องน้ำ": bath,
            "ที่จอดรถ": parking,
            "ชั้น": floor or "",
            "วันประกาศ": post_date
        }
    except Exception as e:
        logger.warning(f"Error fetching detail {item_url}: {e}")
        return None

def save_to_csv(records, filename):
    return atomic_write_csv(records, filename, COLUMNS, company_name=COMPANY_NAME)

def load_existing_csv(filename):
    if "--fresh" in sys.argv or "--force-restart" in sys.argv:
        print(f"[{COMPANY_NAME}] ⚠️ พบคำสั่ง --fresh หรือ --force-restart: รีเซ็ตข้อมูลใหม่ทั้งหมด", flush=True)
        reset_scraper_state(COMPANY_NAME, MONTH_STR)
        return [], set()
    return read_csv_resume(filename, COLUMNS, id_col="ID", company_name=COMPANY_NAME)

def scrape_chayo555(progress_callback=None):
    logger.info("=" * 65)
    logger.info("🚀 Starting Chayo555 NPA Monthly Scraper")
    logger.info("=" * 65)

    session = AuditedSession(company_name=COMPANY_NAME)

    # 1. Link Health Probe (ตรวจสอบการเชื่อมต่อก่อน --fresh เพื่อไม่ให้ลบไฟล์เดิมหากเว็บล่ม)
    test_url = f"{SEARCH_URL}?term_condition=1&q=&category=&start_price=0&end_price=100000&geography=&province=&district=&sys_lang_id=1"
    def _probe_chayo():
        r = safe_ssl_get(session, test_url, headers=HEADERS, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code != 200:
            r.raise_for_status()
        return r

    try:
        r_probe = execute_with_retry(_probe_chayo, company_name=COMPANY_NAME, context_msg="Chayo555 Health Probe", max_retries=3, max_cooldown_cycles=1)
        code = r_probe.status_code
    except Exception:
        code = 0

    if code != 200:
        print_alert(f"ไม่สามารถเชื่อมต่อเว็บ Chayo555 ได้ (HTTP {code})", level="CRITICAL", company_name=COMPANY_NAME)
        sys.exit(1)

    print(f"[{COMPANY_NAME}] 🌐 สถานะลิงก์: ปกติ (HTTP {code}) | ตรวจพบระบบออนไลน์พร้อมใช้งาน", flush=True)
    records, seen_ids = load_existing_csv(OUTPUT_CSV)

    # 2. Check saved scraper state before scanning
    saved_state = load_scraper_state(COMPANY_NAME, MONTH_STR)
    saved_total = int(saved_state.get("total_pages") or 0)
    if saved_state.get("status") == "COMPLETED" and saved_total > 0 and len(records) >= saved_total:
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลใน CSV ครบถ้วน 100% แล้ว ({len(records):5,d}/{saved_total:5,d} รายการ) | สะสม: {len(records):,d} รายการ -> สแครปเสร็จสมบูรณ์ทันที!", flush=True)
        save_to_csv(records, OUTPUT_CSV)
        log_success(COMPANY_NAME, f"✅ ข้อมูลใน CSV ครบถ้วน 100% อยู่แล้ว ({len(records):,} รายการ)")
        return pd.DataFrame(records)

    discovered_items = {}
    categories = ['', '1', '2', '3', '4', '5', '6', '18', '33', '34']
    widgets = ['2', '3', '4', '5', '6', '11', '12']

    total_tasks = len(categories) + len(widgets)
    completed_tasks = 0
    scan_failed = False

    def _scan_paginated(base_query_builder, label_prefix, param_val):
        nonlocal scan_failed
        prev_hrefs = set()
        page_num = 1
        while page_num <= 500:
            url = base_query_builder(param_val, page_num)

            def _fetch_scan():
                r = safe_ssl_get(session, url, headers=HEADERS, timeout=100, ssl_fallback_on_gov=False)
                if r.status_code != 200:
                    r.raise_for_status()
                return r

            try:
                r = execute_with_retry(_fetch_scan, company_name=COMPANY_NAME, context_msg=f"{label_prefix} {param_val} หน้า {page_num}", max_retries=3, max_cooldown_cycles=1)
            except Exception as e:
                logger.warning(f"Error checking {label_prefix} {param_val} page {page_num}: {e}")
                scan_failed = True
                break

            soup = BeautifulSoup(r.text, 'html.parser')
            page_hrefs = set()
            for a in soup.find_all('a', href=True):
                href = a['href']
                txt = a.get_text().strip()
                if 'รหัสทรัพย์สิน' in txt and href.startswith('http'):
                    page_hrefs.add(href)
                    if href not in discovered_items:
                        m_code = re.search(r'รหัสทรัพย์สิน\s*([A-Za-z0-9\-\/_]+)', txt)
                        m_price = re.search(r'ราคาขาย\s*฿?([\d,]+)', txt)
                        price_val = None
                        if m_price:
                            try: price_val = float(m_price.group(1).replace(',', ''))
                            except Exception: pass
                        discovered_items[href] = {
                            "url": href,
                            "รหัสทรัพย์": m_code.group(1) if m_code else "",
                            "ราคา": price_val,
                            "ประเภททรัพย์": "",
                            "ชื่อโครงการ": clean_project_name(href.split('/')[-1].replace('-', ' '), company=COMPANY_NAME) if clean_project_name else ""
                        }

            time.sleep(get_scraper_delay()) # หน่วงเวลาอย่างน้อย 15 วินาที
            if not page_hrefs or (prev_hrefs and page_hrefs.issubset(prev_hrefs)):
                break
            prev_hrefs = page_hrefs
            page_num += 1

    logger.info("📡 Scanning Chayo555 category & widget listings...")
    for cat_id in categories:
        _scan_paginated(
            lambda cid, p: f"{SEARCH_URL}?term_condition=1&q=&category={cid}&start_price=0&end_price=100000&geography=&province=&district=&sys_lang_id=1" + (f"&page={p}" if p > 1 else ""),
            "category", cat_id
        )
        completed_tasks += 1
        if progress_callback:
            progress_callback(int((completed_tasks / total_tasks) * 30), f"Scanning listings ({len(discovered_items)} found)")

    for w_id in widgets:
        _scan_paginated(
            lambda wid, p: f"{SEARCH_URL}?term_condition=1&q=&category=&start_price=0&end_price=100000&geography=&province=&district=&widgets={wid}&sys_lang_id=1" + (f"&page={p}" if p > 1 else ""),
            "widget", w_id
        )
        completed_tasks += 1
        if progress_callback:
            progress_callback(int((completed_tasks / total_tasks) * 30), f"Scanning listings ({len(discovered_items)} found)")

    total_discovered = len(discovered_items)
    if total_discovered == 0:
        from logger_util import print_structure_alert
        print_structure_alert(COMPANY_NAME, "ไม่พบรายการทรัพย์จากการสแกน Category/Widget URL บน Chayo555 (โครงสร้างเว็บเปลี่ยนแปลง)")
        sys.exit(1)
    logger.info(f"🎯 Total unique Chayo555 listings discovered: {total_discovered:,}")
    print(f"[{COMPANY_NAME}] 🌐 สถานะลิงก์: ปกติ | พบทั้งหมด {total_discovered:,} รายการ", flush=True)

    if total_discovered > 0 and len(records) >= total_discovered:
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลใน CSV ครบถ้วน 100% แล้ว ({total_discovered:5,d}/{total_discovered:5,d} รายการ) | สะสม: {len(records):>6,d}/{total_discovered:,d} รายการ -> สแครปเสร็จสมบูรณ์ทันที!", flush=True)
        save_to_csv(records, OUTPUT_CSV)
        save_scraper_state(
            company_name=COMPANY_NAME,
            month_str=MONTH_STR,
            completed_pages=total_discovered,
            total_pages=total_discovered,
            total_records=len(records),
            status="COMPLETED"
        )
        return pd.DataFrame(records)

    start_time = time.time()
    failed_units = []
    saved_milestones = set()
    
    items_to_fetch = []
    for url, data in discovered_items.items():
        code = str(data.get("รหัสทรัพย์") or url.split('/')[-1]).strip()
        if code in seen_ids or url in seen_ids:
            continue
        items_to_fetch.append((url, data))
        
    logger.info(f"⚡ Fetching {len(items_to_fetch)} property detail pages politely (1 worker / single thread)...")
    
    done_count = total_discovered - len(items_to_fetch)
    if done_count > 0 and len(items_to_fetch) > 0:
        pct_start = int((done_count / total_discovered) * 100) if total_discovered > 0 else 0
        print(f"[{COMPANY_NAME}] ⏩ Smart Fast-Forward: ข้าม {done_count:,} รายการเดิม ({pct_start}%) -> ดึงเฉพาะรายการใหม่ {len(items_to_fetch):,} รายการต่อทันที", flush=True)
        
    if items_to_fetch:
        for url, data in items_to_fetch:
            code = str(data.get("รหัสทรัพย์") or url.split('/')[-1]).strip()
            try:
                res = fetch_chayo_detail(session, url, data)
                if res:
                    iid = str(res.get("ID") or res.get("รหัสทรัพย์") or code).strip()
                    seen_ids.add(iid)
                    records.append(res)
                else:
                    failed_units.append(url.split('/')[-1])
            except Exception as e:
                logger.warning(f"Error fetching {url}: {e}")
                failed_units.append(url.split('/')[-1])
                
            done_count += 1
            pct = 30 + int((done_count / max(1, total_discovered)) * 70)
            p_bar = make_progress_bar(pct, length=20)
            elapsed_cur = time.time() - start_time
            eta_str = format_eta(elapsed_cur, done_count - (total_discovered - len(items_to_fetch)), len(items_to_fetch), 1)
            print(f"[{COMPANY_NAME:<13s}] {p_bar} | ({done_count:5,d}/{total_discovered:5,d} รายการ) | สะสม: {len(records):>6,d}/{total_discovered:,d} รายการ | {eta_str}", flush=True)

            if "initial_page" not in saved_milestones and len(records) > 0:
                saved_milestones.add("initial_page")
                print(f"\n💾 [{COMPANY_NAME}] รายการแรก -> บันทึกไฟล์เริ่มต้นลง {OUTPUT_CSV}...", flush=True)
                log_milestone(COMPANY_NAME, f"💾 บันทึกเริ่มต้น (รายการแรก) {len(records):,} รายการลง " + os.path.basename(OUTPUT_CSV))
                save_to_csv(records, OUTPUT_CSV)

            for target_pct in range(5, 105, 5):
                if pct >= target_pct and target_pct not in saved_milestones:
                    saved_milestones.add(target_pct)
                    print(f"\n💾 [{COMPANY_NAME}] ครบ Milestone {target_pct}% -> บันทึกสำรองลง {OUTPUT_CSV}...", flush=True)
                    log_milestone(COMPANY_NAME, f"💾 บันทึก Milestone สำรอง {target_pct}% ({len(records):,} รายการ) ลง " + os.path.basename(OUTPUT_CSV))
                    save_to_csv(records, OUTPUT_CSV)

            if done_count % 10 == 0 or done_count == total_discovered:
                save_to_csv(records, OUTPUT_CSV)
                save_scraper_state(
                    company_name=COMPANY_NAME,
                    month_str=MONTH_STR,
                    completed_pages=done_count,
                    total_pages=total_discovered,
                    total_records=len(records),
                    status="RUNNING"
                )
                
            if progress_callback:
                progress_callback(pct, f"Scraped {done_count}/{total_discovered} items")

    df = pd.DataFrame(records)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[COLUMNS]

    if "ID" in df.columns and not df.empty:
        non_empty_id = df["ID"].astype(str).str.strip().ne("") & df["ID"].notna()
        df = pd.concat([
            df[non_empty_id].drop_duplicates(subset=["ID"], keep="first"),
            df[~non_empty_id].drop_duplicates(subset=["รหัสทรัพย์", "ชื่อโครงการ"], keep="first")
        ], ignore_index=True)
    save_to_csv(df.to_dict('records'), OUTPUT_CSV)
    elapsed = time.time() - start_time
    if failed_units or scan_failed:
        final_status = "FAILED" if len(df) == 0 else "PARTIAL"
        save_scraper_state(
            company_name=COMPANY_NAME,
            month_str=MONTH_STR,
            completed_pages=done_count - len(failed_units),
            total_pages=total_discovered,
            total_records=len(df),
            status=final_status
        )
        print(f"\n==================================================", flush=True)
        print(f"⚠️ [{COMPANY_NAME}] สแครปเสร็จแบบมีรายการล้มเหลว ({final_status}) | สะสม: {len(df):>6,d}/{total_discovered:,d} รายการ", flush=True)
        if failed_units:
            print(f"⚠️ รายการที่ข้าม/ดึงไม่ได้ ({len(failed_units)} รายการ): {sorted(failed_units)[:30]}", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที | 💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        log_warning(COMPANY_NAME, f"⚠️ สแครปเสร็จแบบ {final_status}: ดึงไม่ได้ {len(failed_units)} รายการ")
        sys.exit(1 if len(df) == 0 else 2)
    else:
        save_scraper_state(
            company_name=COMPANY_NAME,
            month_str=MONTH_STR,
            completed_pages=total_discovered,
            total_pages=total_discovered,
            total_records=len(df),
            status="COMPLETED"
        )
        print(f"\n==================================================", flush=True)
        print(f"✅ [{COMPANY_NAME}] สแครปเสร็จสมบูรณ์! | ({done_count:4d}/{total_discovered:4d} รายการ) | สะสม: {len(df):>6,d}/{total_discovered:,d} รายการ", flush=True)
        print(f"📊 ได้ข้อมูลทั้งหมด: {len(df):,} รายการ", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที", flush=True)
        print(f"💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        print(f"✅ ดึงข้อมูลได้ครบถ้วนสำเร็จ 100% (ไม่มีรายการล้มเหลว)", flush=True)
        print(f"==================================================", flush=True)
        log_success(COMPANY_NAME, f"✅ สแครปเสร็จสมบูรณ์! ได้ข้อมูลทั้งหมดสะสม {len(df):,} รายการลง {os.path.basename(OUTPUT_CSV)}")

    return df

main = scrape_chayo555

if __name__ == "__main__":
    main()
