import os
import sys
import re
import time
import json
import random
from datetime import datetime
import pandas as pd
import requests
from bs4 import BeautifulSoup
from logger_util import (
    log_info, log_error, log_warning, log_txn, print_alert,
    save_scraper_state, load_scraper_state, reset_scraper_state,
    log_milestone, AuditedSession, AuditedCurlSession,
    safe_ssl_get, atomic_write_csv, print_structure_alert,
)

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
    finish_clock = datetime.fromtimestamp(datetime.now().timestamp() + eta_sec).strftime("%H:%M:%S")
    mins = int(eta_sec // 60)
    secs = int(eta_sec % 60)
    if mins >= 60:
        hrs = mins // 60
        m = mins % 60
        return f"เหลืออีก ~{hrs} ชม. {m} นาที ({finish_clock})"
    elif mins > 0:
        return f"เหลืออีก ~{mins} นาที ({finish_clock})"
    else:
        return f"เหลืออีก ~{secs} วินาที ({finish_clock})"

from timeout_handler import handle_timeout_retry, execute_with_retry
from time_window_util import wait_for_active_window, get_scraper_delay
import atexit
import signal
from clean_location_util import clean_row_location, clean_floor_val, extract_floor_from_text, reverse_geocode_location, init_gis

try:
    from clean_project_util import clean_project_name, extract_project_from_title
except ImportError:
    clean_project_name = lambda x, **kwargs: str(x).strip()
    extract_project_from_title = lambda x, **kwargs: ""

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

COMPANY_NAME = "ZmyHome"
MONTH_STR = datetime.now().strftime("%Y_%m")

_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR
OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"ZmyHome_NPA_New_{MONTH_STR}.csv")

BASE_URL = "https://zmyhome.com/buy"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "th,en-US;q=0.9,en;q=0.8",
    "Referer": "https://zmyhome.com/"
}

COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคา",
    "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ", "ยอดเข้าชม"
]

ITEMS_PER_PAGE = 35

# 77 จังหวัดทั่วไทยเรียงตาม ID 1..77 ของ ZmyHome
ZMYHOME_PROVINCES = {
    1: "กรุงเทพมหานคร", 2: "กระบี่", 3: "กาญจนบุรี", 4: "กาฬสินธุ์", 5: "กำแพงเพชร",
    6: "ขอนแก่น", 7: "จันทบุรี", 8: "ฉะเชิงเทรา", 9: "ชลบุรี", 10: "ชัยนาท",
    11: "ชัยภูมิ", 12: "ชุมพร", 13: "เชียงราย", 14: "เชียงใหม่", 15: "ตรัง",
    16: "ตราด", 17: "ตาก", 18: "นครนายก", 19: "นครปฐม", 20: "นครพนม",
    21: "นครราชสีมา", 22: "นครศรีธรรมราช", 23: "นครสวรรค์", 24: "นนทบุรี", 25: "นราธิวาส",
    26: "น่าน", 27: "บึงกาฬ", 28: "บุรีรัมย์", 29: "ปทุมธานี", 30: "ประจวบคีรีขันธ์",
    31: "ปราจีนบุรี", 32: "ปัตตานี", 33: "พระนครศรีอยุธยา", 34: "พังงา", 35: "พัทลุง",
    36: "พิจิตร", 37: "พิษณุโลก", 38: "เพชรบุรี", 39: "เพชรบูรณ์", 40: "แพร่",
    41: "พะเยา", 42: "ภูเก็ต", 43: "มหาสารคาม", 44: "มุกดาหาร", 45: "แม่ฮ่องสอน",
    46: "ยะลา", 47: "ยโสธร", 48: "ร้อยเอ็ด", 49: "ระนอง", 50: "ระยอง",
    51: "ราชบุรี", 52: "ลพบุรี", 53: "ลำปาง", 54: "ลำพูน", 55: "เลย",
    56: "ศรีสะเกษ", 57: "สกลนคร", 58: "สงขลา", 59: "สตูล", 60: "สมุทรปราการ",
    61: "สมุทรสงคราม", 62: "สมุทรสาคร", 63: "สระแก้ว", 64: "สระบุรี", 65: "สิงห์บุรี",
    66: "สุโขทัย", 67: "สุพรรณบุรี", 68: "สุราษฎร์ธานี", 69: "สุรินทร์", 70: "หนองคาย",
    71: "หนองบัวลำภู", 72: "อ่างทอง", 73: "อุดรธานี", 74: "อุทัยธานี", 75: "อุตรดิตถ์",
    76: "อุบลราชธานี", 77: "อำนาจเจริญ"
}

# หมวดหมู่ทรัพย์ของ ZmyHome
PROPERTY_TYPES = [
    ("condo", "ห้องชุดพักอาศัย"),
    ("house", "บ้านเดี่ยว"),
    ("townhome", "ทาวน์เฮ้าส์/ทาวน์โฮม"),
    ("land", "ที่ดิน"),
    ("homeoffice", "อาคารพาณิชย์"),
    ("npa", "ทรัพย์รอการขาย")
]

def clean_text(val):
    if val is None or pd.isna(val):
        return ""
    text = str(val).strip()
    return re.sub(r'\s+', ' ', text)

def format_wah_val(w):
    if isinstance(w, float) and w.is_integer():
        return str(int(w))
    elif isinstance(w, int):
        return str(int(w))
    elif isinstance(w, float):
        return f"{w:g}"
    return str(w)

def convert_to_rai_ngan_wah(val):
    if not val or pd.isna(val):
        return ""
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ["nan", "none", "null", "-", "0", "0.0"]:
        return ""
    # Strip superscript 2 / ² after unit keywords (e.g. "68.4 วา 2" -> "68.4 วา")
    val_str = re.sub(r'(วา|ตร\.?ว\.?|ตร\.?วา|ตารางวา)\s*(?:2|²)\b', r'\1', val_str)
    m = re.match(r'^(\d+)\s*-\s*(\d+)\s*-\s*([\d\.]+)$', val_str)
    if m:
        r_v, n_v, w_v = int(m.group(1)), int(m.group(2)), round(float(m.group(3)), 4)
        if r_v == 0 and n_v == 0 and w_v <= 0:
            return ""
        return f"{r_v}-{n_v}-{format_wah_val(w_v)}"
    if any(u in val_str for u in ['ไร่', 'งาน', 'วา', 'ตร.ว', 'ตารางวา']):
        m_r = re.search(r'([\d\.,]+)\s*ไร่', val_str)
        m_g = re.search(r'([\d\.,]+)\s*งาน', val_str)
        m_w = re.search(r'([\d\.,]+)\s*(?:ตร\.?ว\.?|ตร\.?วา|ตารางวา|วา)', val_str)
        r = float(m_r.group(1).replace(',', '')) if m_r else 0.0
        g = float(m_g.group(1).replace(',', '')) if m_g else 0.0
        w = float(m_w.group(1).replace(',', '')) if m_w else 0.0
        total_sq_wah = (r * 400.0) + (g * 100.0) + w
        if total_sq_wah > 0:
            rai = int(total_sq_wah // 400)
            rem = total_sq_wah - (rai * 400)
            ngan = int(rem // 100)
            wah = round(rem - (ngan * 100), 4)
            return f"{rai}-{ngan}-{format_wah_val(wah)}"
    try:
        m_num = re.search(r'([\d\.,]+)', val_str)
        total_sq_wah = float(m_num.group(1).replace(',', '')) if m_num else 0.0
        if total_sq_wah > 0:
            rai = int(total_sq_wah // 400)
            rem = total_sq_wah - (rai * 400)
            ngan = int(rem // 100)
            wah = round(rem - (ngan * 100), 4)
            return f"{rai}-{ngan}-{format_wah_val(wah)}"
    except Exception:
        pass
    return ""

def parse_sqm(val):
    if not val or pd.isna(val):
        return ""
    try:
        val_clean = str(val).strip()
        if not val_clean or val_clean.lower() in ["nan", "none", "null", "-", "0", "0.0"]:
            return ""
        # Strip superscript 2 / ² after unit keywords (e.g. "30.43 ม 2" -> "30.43 ม")
        val_clean = re.sub(r'(ม\.?|ตร\.?ม\.?|ตารางเมตร|sqm)\s*(?:2|²)\b', r'\1', val_clean, flags=re.I)
        val_clean = val_clean.replace(',', '')
        m = re.search(r'([\d\.]+)', val_clean)
        if m:
            v = float(m.group(1))
            if v > 0:
                return int(v) if v.is_integer() else round(v, 2)
    except Exception:
        pass
    return ""

def _is_condo_type(p_type: str) -> bool:
    s = str(p_type or "")
    return "ห้องชุด" in s or "คอนโด" in s

def _is_land_type(p_type: str) -> bool:
    s = str(p_type or "").strip()
    return s in ("ที่ดิน", "ที่ดินเปล่า", "ที่ดินเกษตรกรรม", "ที่ดินว่างเปล่า") or ("ที่ดิน" in s and "สิ่งปลูกสร้าง" not in s)

def enforce_area_rules_by_type(item: dict):
    """บังคับกฎแยกเก็บ เนื้อที่ (ตร.ว.) และ พื้นที่ใช้สอย (ตร.ม.) ตามประเภททรัพย์อย่างเคร่งครัด"""
    p_type = str(item.get("ประเภททรัพย์", ""))
    if _is_condo_type(p_type):
        item["เนื้อที่ (ตร.ว.)"] = ""
        if item.get("พื้นที่ใช้สอย (ตร.ม.)"):
            item["พื้นที่ใช้สอย (ตร.ม.)"] = parse_sqm(item["พื้นที่ใช้สอย (ตร.ม.)"])
    elif _is_land_type(p_type):
        item["พื้นที่ใช้สอย (ตร.ม.)"] = ""
        item["ห้องนอน"] = None
        item["ห้องน้ำ"] = None
        item["ที่จอดรถ"] = None
        item["ชั้น"] = ""
        if item.get("เนื้อที่ (ตร.ว.)"):
            item["เนื้อที่ (ตร.ว.)"] = convert_to_rai_ngan_wah(item["เนื้อที่ (ตร.ว.)"])
    else:
        if item.get("เนื้อที่ (ตร.ว.)"):
            item["เนื้อที่ (ตร.ว.)"] = convert_to_rai_ngan_wah(item["เนื้อที่ (ตร.ว.)"])
        if item.get("พื้นที่ใช้สอย (ตร.ม.)"):
            item["พื้นที่ใช้สอย (ตร.ม.)"] = parse_sqm(item["พื้นที่ใช้สอย (ตร.ม.)"])
    return item

def is_sam_property(seller_name="", title="", proj_name="", html_text=""):
    seller_upper = str(seller_name).upper()
    if any(k in seller_upper for k in ["SAM", "SUKHUMVIT ASSET", "สุขุมวิท", "บสส."]):
        return True
    combo = f"{title} {proj_name}".upper()
    if re.search(r'\bSAM\b', combo) or "บสส." in combo or "สุขุมวิท แอสเซท" in combo:
        return True
    if html_text:
        if re.search(r"""seller["':\s]+[^}]*?(?:SAM|SUKHUMVIT ASSET|บสส\.|สุขุมวิท)""", html_text, re.I):
            return True
        if re.search(r'(?:เจ้าของทรัพย์|ผู้ดูแลทรัพย์|ลงประกาศโดย)\s*[:\-]?\s*(?:บสส\.|SAM|บริษัทบริหารสินทรัพย์สุขุมวิท)', html_text, re.I):
            return True
    return False

def load_existing_csv(filename):
    if "--fresh" in sys.argv or "--force-restart" in sys.argv:
        print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นดึงข้อมูลใหม่ทั้งหมดจากจังหวัดแรก (โหมด --fresh)", flush=True)
        reset_scraper_state(COMPANY_NAME, MONTH_STR)
        return [], set()
    seen_ids = set()
    records = []
    if os.path.exists(filename):
        try:
            df = pd.read_csv(filename, encoding="utf-8-sig", dtype=str).fillna("")
            records = df.to_dict("records")
            healed_count = 0
            for r in records:
                enforce_area_rules_by_type(r)
                iid = str(r.get("ID", "")).strip()
                if iid and iid not in ("nan", "None", "null"):
                    seen_ids.add(iid)
                if not r.get("ตำบล") or not r.get("อำเภอ") or not r.get("จังหวัด"):
                    lat = r.get("ละติจูด")
                    lng = r.get("ลองจิจูด")
                    if lat and lng and not pd.isna(lat) and not pd.isna(lng):
                        try:
                            sd_gis, d_gis, p_gis = reverse_geocode_location(float(lat), float(lng))
                            if p_gis:
                                r["ตำบล"] = sd_gis
                                r["อำเภอ"] = d_gis
                                r["จังหวัด"] = p_gis
                                clean_row_location(r)
                                healed_count += 1
                        except Exception:
                            pass
            if healed_count > 0:
                print(f"[{COMPANY_NAME}] 🗺️ ซ่อมแซมและเติมที่อยู่จากพิกัด GIS สำเร็จ: {healed_count:,} รายการ", flush=True)
            print(f"[{COMPANY_NAME}] 🔄 Smart Resume: โหลดข้อมูลเดิมจาก {filename} พบแล้ว {len(records):,} รายการ", flush=True)
        except Exception as e:
            print_alert(f"ไม่สามารถอ่านไฟล์สะสมเดิม {filename}: {e}", level="WARNING")
    return records, seen_ids

def check_link_health(session):
    """
    ตรวจสอบความพร้อมของระบบและโครงสร้างการค้นหา (77 จังหวัด)
    """
    url = "https://zmyhome.com/buy/condo/province/1?page=1&sortFilter=ads&per-page=35"
    def _probe():
        r = safe_ssl_get(session, url, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code != 200:
            r.raise_for_status()
        return r

    try:
        r = execute_with_retry(_probe, company_name=COMPANY_NAME, context_msg="ZmyHome Health Probe", max_retries=4, max_cooldown_cycles=1)
        status_code = r.status_code
        soup = BeautifulSoup(r.text, 'html.parser')
        cards = soup.find_all("article", class_="card-property__item--article")
        if not cards:
            cards = soup.find_all("article")

        if not cards:
            print_structure_alert(COMPANY_NAME, "ไม่พบ Element การ์ดรายการ 'article' บนหน้าเว็บ ZmyHome (โครงสร้าง HTML เปลี่ยนแปลง)")
            return False, status_code, 0, 0

        sample_valid = 0
        for c in cards[:5]:
            it = parse_zmyhome_card(c)
            if it and it.get("ID"):
                sample_valid += 1

        if sample_valid == 0:
            print_structure_alert(COMPANY_NAME, "ไม่สามารถสกัด ID รายการทรัพย์จากการ์ด ZmyHome ได้")
            return False, status_code, 0, 0

        return True, status_code, 35000, 77
    except Exception:
        print_alert("ไม่สามารถเชื่อมต่อเว็บ ZmyHome ได้ (Timeout / Connection Error)", level="CRITICAL")
        return False, 0, 0, 0

def fetch_zmyhome_detail(session, item):
    link = item.get("ลิงก์")
    if not link:
        return item

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}
    for attempt in range(2):
        try:
            time.sleep(get_scraper_delay())
            r = safe_ssl_get(session, link, headers=headers, timeout=100, ssl_fallback_on_gov=False)
            if r.status_code == 200:
                html = r.text
                soup = BeautifulSoup(html, 'html.parser')

                # 1. Lat/Lng from Google Maps link / static map
                map_link = soup.find('a', href=re.compile(r'google.*map|maps\.google|maps\.app\.goo\.gl', re.I))
                if map_link:
                    href = map_link.get('href', '')
                    m_ll = (
                        re.search(r'[?&](?:query|q)=([\d\.-]+),([\d\.-]+)', href) or
                        re.search(r'@([\d\.-]+),([\d\.-]+)', href) or
                        re.search(r'center=([\d\.-]+),([\d\.-]+)', href) or
                        re.search(r'll=([\d\.-]+),([\d\.-]+)', href)
                    )
                    if m_ll:
                        try:
                            lat_v, lng_v = float(m_ll.group(1)), float(m_ll.group(2))
                            if 5.0 <= lat_v <= 21.0 and 97.0 <= lng_v <= 106.0:
                                item["ละติจูด"] = lat_v
                                item["ลองจิจูด"] = lng_v
                        except Exception:
                            pass
                            
                if not item.get("ละติจูด"):
                    m_map = (
                        re.search(r'[?&](?:query|q)=([\d\.-]+),([\d\.-]+)', html) or
                        re.search(r'center=([\d\.-]+),([\d\.-]+)', html) or
                        re.search(r'@([\d\.-]+),([\d\.-]+)', html)
                    )
                    if m_map:
                        try:
                            lat_v, lng_v = float(m_map.group(1)), float(m_map.group(2))
                            if 5.0 <= lat_v <= 21.0 and 97.0 <= lng_v <= 106.0:
                                item["ละติจูด"] = lat_v
                                item["ลองจิจูด"] = lng_v
                        except Exception:
                            pass

                # 2. Location from GIS Boundaries
                if item.get("ละติจูด") and item.get("ลองจิจูด"):
                    sd_gis, d_gis, p_gis = reverse_geocode_location(item["ละติจูด"], item["ลองจิจูด"])
                    if p_gis:
                        item["ตำบล"] = sd_gis
                        item["อำเภอ"] = d_gis
                        item["จังหวัด"] = p_gis

                # 3. Project name & Seller & JSON-LD fields & View Count (extract before decomposing noise)
                seller_name = ""
                for m_jsonld in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
                    try:
                        j_data = json.loads(m_jsonld.group(1))
                        j_list = j_data if isinstance(j_data, list) else [j_data]
                        for j_obj in j_list:
                            if not isinstance(j_obj, dict):
                                continue
                            if j_obj.get("@type") == "Offer":
                                s_obj = j_obj.get("seller", {})
                                seller_name = s_obj.get("name", "") if isinstance(s_obj, dict) else str(s_obj)
                            if not item.get("วันประกาศ") and j_obj.get("datePosted"):
                                dp = str(j_obj.get("datePosted"))[:10]
                                if dp:
                                    item["วันประกาศ"] = dp
                            f_size = j_obj.get("floorSize")
                            if isinstance(f_size, dict) and f_size.get("value") and not item.get("พื้นที่ใช้สอย (ตร.ม.)") and not _is_land_type(item.get("ประเภททรัพย์", "")):
                                item["พื้นที่ใช้สอย (ตร.ม.)"] = parse_sqm(f_size.get("value"))
                    except Exception:
                        pass

                og = soup.find('meta', property='og:title')
                if og and clean_text(og.get('content', '')):
                    item["ชื่อประกาศ"] = clean_text(og.get('content', ''))

                proj_name = ""
                proj_section = soup.find(class_=re.compile(r'info-project', re.I))
                if proj_section:
                    first_item = proj_section.find('li', class_=re.compile(r'info-project__item', re.I))
                    if first_item:
                        p_txt = first_item.get_text().strip()
                        if p_txt and p_txt != item.get("ชื่อประกาศ", ""):
                            proj_name = p_txt

                if proj_name:
                    item["ชื่อโครงการ"] = clean_project_name(proj_name, tambon=item.get("ตำบล", ""), amphoe=item.get("อำเภอ", ""), province=item.get("จังหวัด", ""), company=COMPANY_NAME) if clean_project_name else proj_name
                elif item.get("ชื่อประกาศ") and extract_project_from_title and not item.get("ชื่อโครงการ"):
                    item["ชื่อโครงการ"] = extract_project_from_title(item.get("ชื่อประกาศ", ""), tambon=item.get("ตำบล", ""), amphoe=item.get("อำเภอ", ""), province=item.get("จังหวัด", ""), company=COMPANY_NAME)

                # Filter out SAM properties (mark _is_sam so caller skips adding it!)
                if is_sam_property(seller_name=seller_name, title=item.get("ชื่อประกาศ", ""), proj_name=proj_name, html_text=html):
                    item["_is_sam"] = True
                    return None

                eye_icon = soup.find(class_=re.compile(r'bi-eye', re.I))
                if eye_icon:
                    p_eye = eye_icon.parent
                    cand_span = p_eye.find_next_sibling(['span', 'div']) if p_eye else None
                    if cand_span:
                        txt = clean_text(cand_span.text).replace(',', '')
                        if txt.isdigit():
                            item["ยอดเข้าชม"] = int(txt)

                # 4. Structured extraction from <ul class="info-room__list"> (Ground Truth for property specs)
                p_type_str = str(item.get("ประเภททรัพย์", ""))
                room_ul = soup.find('ul', class_=re.compile(r'info-room__list', re.I)) or soup.find(class_=re.compile(r'info-room', re.I))
                if room_ul:
                    for li in room_ul.find_all('li'):
                        li_txt = clean_text(li.get_text(" ", strip=True))
                        if not li_txt:
                            continue
                        if any(k in li_txt for k in ("ขนาดที่ดิน", "เนื้อที่ดิน", "เนื้อที่")) and not _is_condo_type(p_type_str):
                            v_land = convert_to_rai_ngan_wah(li_txt)
                            if v_land:
                                item["เนื้อที่ (ตร.ว.)"] = v_land
                        elif any(k in li_txt for k in ("พื้นที่ใช้สอย", "พื้นที่บ้าน", "พื้นที่อาคาร", "ขนาดห้อง")) and not _is_land_type(p_type_str):
                            v_sqm = parse_sqm(li_txt)
                            if v_sqm:
                                item["พื้นที่ใช้สอย (ตร.ม.)"] = v_sqm
                        elif "ห้องนอน" in li_txt:
                            m_b = re.search(r'(\d{1,2})\s*ห้องนอน', li_txt)
                            if m_b:
                                item["ห้องนอน"] = int(m_b.group(1))
                        elif "ห้องน้ำ" in li_txt:
                            m_ba = re.search(r'(\d{1,2})\s*ห้องน้ำ', li_txt)
                            if m_ba:
                                item["ห้องน้ำ"] = int(m_ba.group(1))
                        elif "จอดรถ" in li_txt:
                            m_pk = re.search(r'(\d{1,2})\s*(?:ที่จอดรถ|จอดรถ|คัน)', li_txt)
                            if m_pk:
                                item["ที่จอดรถ"] = int(m_pk.group(1))
                        elif "ชั้น" in li_txt and "จำนวนชั้น" not in li_txt:
                            fl_v = extract_floor_from_text(li_txt, asset_type=p_type_str)
                            if fl_v:
                                item["ชั้น"] = fl_v

                # 5. Decompose project info (`พื้นที่โครงการ`), comparison tables (`announce-project`), and similar cards (`card-property`)
                for bad_tag in soup.find_all(['section', 'div', 'article', 'ul', 'table', 'small'], class_=re.compile(r'info-project|announce-project|carousel|card-property|recommend|nearby|similar|relate|footer|banner|currency-per-unit', re.I)):
                    bad_tag.decompose()
                for s_tag in soup.find_all(['script', 'style', 'footer']):
                    s_tag.decompose()

                main_text = soup.get_text(" ", strip=True)
                # Strip price-per-unit patterns like "83,725 ฿/ตร.ม." or "71,053 ฿/วา 2"
                main_text = re.sub(r'[\d\.,]+\s*(?:฿|บาท)\s*/\s*(?:ตร\.?[วม]\.?|ตาราง(?:วา|เมตร)|วา|ม\.?)(?:\s*2|²)?', ' ', main_text)

                # Text fallback for ตำบล / อำเภอ when map coordinates are absent
                if not item.get("ตำบล"):
                    m_sd = re.search(r'(?:ตำบล|ต\.|แขวง)\s*([^\s,\|<"\'\(\)\/\d\-\:\.]+)', main_text)
                    if m_sd and len(m_sd.group(1).strip()) > 1:
                        item["ตำบล"] = m_sd.group(1).strip()
                if not item.get("อำเภอ"):
                    m_d = re.search(r'(?:อำเภอ|อ\.|เขต)\s*([^\s,\|<"\'\(\)\/\d\-\:\.]+)', main_text)
                    if m_d and len(m_d.group(1).strip()) > 1:
                        item["อำเภอ"] = m_d.group(1).strip()

                # Clean & standardize location
                clean_row_location(item)

                # แยกประเภท อาคารพาณิชย์ และ โฮมออฟฟิศ จากเนื้อหาประกาศเชิงลึก
                if item.get("ประเภททรัพย์") in ("อาคารพาณิชย์", "โฮมออฟฟิศ", "อาคารพาณิชย์/โฮมออฟฟิศ"):
                    full_chk = f"{item.get('ชื่อประกาศ', '')} {item.get('ชื่อโครงการ', '')} {main_text}".lower()
                    if any(k in full_chk for k in ["โฮมออฟฟิศ", "โฮมออฟฟิต", "home office", "homeoffice"]):
                        item["ประเภททรัพย์"] = "โฮมออฟฟิศ"
                    else:
                        item["ประเภททรัพย์"] = "อาคารพาณิชย์"

                # Additional Specs fallback from clean main_text
                if not item.get("ห้องนอน"):
                    m_bed = re.search(r'([0-9]{1,2})\s*ห้องนอน', main_text)
                    if m_bed: item["ห้องนอน"] = int(m_bed.group(1))
                if not item.get("ห้องน้ำ"):
                    m_bath = re.search(r'([0-9]{1,2})\s*ห้องน้ำ', main_text)
                    if m_bath: item["ห้องน้ำ"] = int(m_bath.group(1))
                if not item.get("ที่จอดรถ"):
                    m_park = re.search(r'([0-9]{1,2})\s*(?:ที่จอดรถ|จอดรถ)', main_text)
                    if m_park: item["ที่จอดรถ"] = int(m_park.group(1))

                # Fallback Land Area (เนื้อที่ (ตร.ว.)) and Usable Area (พื้นที่ใช้สอย (ตร.ม.)) from clean description
                if not item.get("เนื้อที่ (ตร.ว.)") and not _is_condo_type(p_type_str):
                    m_land = (
                        re.search(r'(?:ขนาดที่ดิน|เนื้อที่(?:ดิน)?|พื้นที่ทั้งหมด)\s*[:\s]*((?:\d+\s*ไร่\s*)?(?:\d+\s*งาน\s*)?[\d\.,]+\s*(?:ตร\.?ว\.?|ตร\.?วา|ตารางวา|วา))', main_text) or
                        re.search(r'((?:\d+\s*ไร่\s*)(?:\d+\s*งาน\s*)?(?:[\d\.,]+\s*(?:ตร\.?ว\.?|ตร\.?วา|ตารางวา|วา))?)', main_text) or
                        re.search(r'([\d\.,]+\s*(?:ตร\.?ว\.?|ตร\.?วา|ตารางวา))', main_text)
                    )
                    if m_land:
                        item["เนื้อที่ (ตร.ว.)"] = convert_to_rai_ngan_wah(m_land.group(1))

                if not item.get("พื้นที่ใช้สอย (ตร.ม.)") and not _is_land_type(p_type_str):
                    m_sqm = (
                        re.search(r'(?:พื้นที่ใช้สอย|พื้นที่บ้าน|พื้นที่อาคาร|ขนาดห้อง|พื้นที่)\s*[:\s]*([\d\.,]+)\s*(?:ตร\.?ม\.?|ตารางเมตร|sqm)', main_text, re.I) or
                        re.search(r'([\d\.,]+)\s*(?:ตร\.?ม\.?|ตารางเมตร)', main_text)
                    )
                    if m_sqm:
                        item["พื้นที่ใช้สอย (ตร.ม.)"] = parse_sqm(m_sqm.group(1))

                # Extract วันประกาศ (datePosted / ลงประกาศเมื่อ / อัปเดตเมื่อ)
                if not item.get("วันประกาศ"):
                    m_dp = re.search(r'["\'](?:datePosted|datePublished|created_at|updated_at)["\']\s*:\s*["\'](\d{4}-\d{2}-\d{2})', html)
                    if m_dp:
                        item["วันประกาศ"] = m_dp.group(1)
                    else:
                        m_th_dt = re.search(r'(?:ลงประกาศเมื่อ|อัปเดตเมื่อ|แก้ไขล่าสุด|วันที่ลงประกาศ)\s*[:\s]*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}-\d{2}-\d{2})', main_text)
                        if m_th_dt:
                            item["วันประกาศ"] = m_th_dt.group(1).strip()

                if not item.get("ชั้น"):
                    floor_val = extract_floor_from_text(main_text, item.get("ชื่อประกาศ", ""), proj_name, asset_type=p_type_str)
                    if floor_val:
                        item["ชั้น"] = floor_val

                enforce_area_rules_by_type(item)
                break
        except Exception:
            time.sleep(1.0)
    return enforce_area_rules_by_type(item)

def parse_zmyhome_card(card, default_type="", default_province=""):
    try:
        fig_a = card.find("figure").find("a") if card.find("figure") else card.find('a', href=True)
        link = fig_a['href'].strip() if fig_a and fig_a.has_attr('href') else ""
        if link and not link.startswith("http"):
            link = "https://zmyhome.com" + link
            
        m_id = re.search(r'/([A-Za-z0-9]+)(?:\?|$)', link)
        item_id = m_id.group(1) if m_id else ""
        if not item_id or item_id.lower() in ["buy", "property"]:
            item_id = link.split("/")[-1].split("?")[0].strip()
            
        if not item_id:
            return None
            
        title_tag = card.find("div", class_="card-property__ad-text-small-highlight")
        title = ""
        if title_tag:
            h3 = title_tag.find("h3")
            title = clean_text(h3.text) if h3 else ""
        if not title:
            title_tag = card.find(class_=lambda c: c and ("title" in c.lower() or "heading" in c.lower()))
            title = clean_text(title_tag.text) if title_tag else clean_text(card.text[:50])
            
        title = re.sub(r'^(?:ขาย\s*)+', 'ขาย ', title).strip()
        title = re.sub(r'^(?:เช่า\s*)+', 'เช่า ', title).strip()
        
        if is_sam_property(title=title):
            return None
        
        price_tag = card.find("span", class_="currency th")
        if not price_tag:
            price_tag = card.find(class_=lambda c: c and "price" in c.lower())
        price_str = clean_text(price_tag.text) if price_tag else ""
        price = None
        if price_str:
            is_million = bool(re.search(r'(?:ล้าน|ลบ\.?|mb)', price_str, re.I)) and not bool(re.search(r'/(?:เดือน|month|mo|m)', price_str, re.I))
            price_clean = re.sub(r"[^\d\.]", "", price_str.replace(",", ""))
            if price_clean:
                try:
                    p_val = float(price_clean)
                    if is_million and p_val < 500:
                        p_val = p_val * 1000000.0
                    if p_val >= 500.0:
                        price = p_val
                except ValueError:
                    price = None
        now_str = datetime.now().strftime("%Y-%m-%d")
        
        p_type = default_type if default_type else ("ห้องชุดพักอาศัย" if item_id.startswith("V") else "บ้านเดี่ยว")
        # แยกประเภทระหว่าง อาคารพาณิชย์ และ โฮมออฟฟิศ
        if default_type in ("อาคารพาณิชย์", "โฮมออฟฟิศ", "อาคารพาณิชย์/โฮมออฟฟิศ"):
            chk_title = f"{title}".lower()
            if any(k in chk_title for k in ["โฮมออฟฟิศ", "โฮมออฟฟิต", "home office", "homeoffice"]):
                p_type = "โฮมออฟฟิศ"
            else:
                p_type = "อาคารพาณิชย์"
        card_text = card.get_text(" ", strip=True)
        card_text_clean = re.sub(r'[\d\.,]+\s*(?:฿|บาท)\s*/\s*(?:ตร\.?[วม]\.?|ตาราง(?:วา|เมตร)|วา|ม\.?)(?:\s*2|²)?', ' ', card_text)

        # Extract card-level specs from structured spans first
        bed, bath, floor_val, land_area, usable_area, post_date, proj_name = None, None, "", "", "", "", ""
        size_unit_tag = card.find("span", class_="size-unit")
        if size_unit_tag:
            su_txt = clean_text(size_unit_tag.get_text(" ", strip=True))
            if _is_condo_type(p_type):
                if any(u in su_txt for u in ("ม", "ตร.ม", "sqm")):
                    usable_area = parse_sqm(su_txt)
            elif _is_land_type(p_type):
                if any(u in su_txt for u in ("วา", "ไร่", "งาน", "ตร.ว")):
                    land_area = convert_to_rai_ngan_wah(su_txt)
            else:
                if any(u in su_txt for u in ("วา", "ไร่", "งาน", "ตร.ว")):
                    land_area = convert_to_rai_ngan_wah(su_txt)
                elif any(u in su_txt for u in ("ม", "ตร.ม", "sqm")):
                    usable_area = parse_sqm(su_txt)

        bed_tag = card.find("span", class_=re.compile(r'bed'))
        if bed_tag:
            m_b = re.search(r'(\d{1,2})', bed_tag.get_text())
            if m_b and int(m_b.group(1)) > 0:
                bed = int(m_b.group(1))
        if bed is None:
            m_bed = re.search(r'(\d{1,2})\s*ห้องนอน', card_text_clean)
            if m_bed and int(m_bed.group(1)) > 0:
                bed = int(m_bed.group(1))

        bath_tag = card.find("span", class_=re.compile(r'bath'))
        if bath_tag:
            m_ba = re.search(r'(\d{1,2})', bath_tag.get_text())
            if m_ba and int(m_ba.group(1)) > 0:
                bath = int(m_ba.group(1))
        if bath is None:
            m_bath = re.search(r'(\d{1,2})\s*ห้องน้ำ', card_text_clean)
            if m_bath and int(m_bath.group(1)) > 0:
                bath = int(m_bath.group(1))

        floor_tag = card.find("span", class_=re.compile(r'floor'))
        if floor_tag and clean_text(floor_tag.get_text()):
            floor_val = extract_floor_from_text(clean_text(floor_tag.get_text()), title, asset_type=p_type) or ""
        if not floor_val:
            floor_val = extract_floor_from_text(card_text_clean, title, asset_type=p_type) or ""

        name_li = card.find("li", class_="name")
        if name_li:
            a_proj = name_li.find("a")
            raw_proj = clean_text(a_proj.get_text() if a_proj else name_li.get_text())
            if raw_proj and raw_proj != "-":
                proj_name = clean_project_name(raw_proj, province=default_province, company=COMPANY_NAME) if clean_project_name else raw_proj

        # Text fallback for land_area and usable_area from card description
        if not land_area and not _is_condo_type(p_type):
            m_land = (
                re.search(r'(?:ขนาดที่ดิน|เนื้อที่(?:ดิน)?|พื้นที่ทั้งหมด)\s*[:\s]*((?:\d+\s*ไร่\s*)?(?:\d+\s*งาน\s*)?[\d\.,]+\s*(?:ตร\.?ว\.?|ตร\.?วา|ตารางวา|วา))', card_text_clean) or
                re.search(r'((?:\d+\s*ไร่\s*)?(?:\d+\s*งาน\s*)?[\d\.,]+\s*(?:ตร\.?ว\.?|ตร\.?วา|ตารางวา))', card_text_clean)
            )
            if m_land:
                land_area = convert_to_rai_ngan_wah(m_land.group(1))

        if not usable_area and not _is_land_type(p_type):
            m_sqm = (
                re.search(r'(?:พื้นที่ใช้สอย|พื้นที่บ้าน|พื้นที่อาคาร|ขนาดห้อง|พื้นที่)\s*[:\s]*([\d\.,]+)\s*(?:ตร\.?ม\.?|ตารางเมตร|sqm)', card_text_clean, re.I) or
                re.search(r'([\d\.,]+)\s*(?:ตร\.?ม\.?|ตารางเมตร)', card_text_clean)
            )
            if m_sqm:
                usable_area = parse_sqm(m_sqm.group(1))

        m_dt = re.search(r'(?:ลงประกาศเมื่อ|อัปเดตเมื่อ)\s*[:\s]*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}-\d{2}-\d{2})', card_text_clean)
        if m_dt:
            post_date = m_dt.group(1).strip()

        subdist, dist = "", ""
        m_sd = re.search(r'(?:ตำบล|ต\.|แขวง)\s*([^\s,\|<"\'\(\)\/\d\-\:\.]+)', card_text_clean)
        if m_sd and len(m_sd.group(1).strip()) > 1:
            subdist = m_sd.group(1).strip()
        m_d = re.search(r'(?:อำเภอ|อ\.|เขต)\s*([^\s,\|<"\'\(\)\/\d\-\:\.]+)', card_text_clean)
        if m_d and len(m_d.group(1).strip()) > 1:
            dist = m_d.group(1).strip()
        
        item_dict = {
            "บริษัท": COMPANY_NAME,
            "ID": item_id,
            "รหัสทรัพย์": item_id,
            "ชื่อโครงการ": proj_name,
            "ประเภททรัพย์": p_type,
            "ประเภทการขาย": "ขาย",
            "ราคา": price,
            "ตำบล": subdist,
            "อำเภอ": dist,
            "จังหวัด": default_province,
            "ละติจูด": None,
            "ลองจิจูด": None,
            "ชื่อประกาศ": title,
            "ลิงก์": link,
            "เนื้อที่ (ตร.ว.)": land_area,
            "พื้นที่ใช้สอย (ตร.ม.)": usable_area,
            "วันที่ดึงข้อมูล": now_str,
            "ห้องนอน": bed,
            "ห้องน้ำ": bath,
            "ที่จอดรถ": None,
            "ชั้น": floor_val,
            "วันประกาศ": post_date,
            "ยอดเข้าชม": None
        }
        return enforce_area_rules_by_type(item_dict)
    except Exception:
        return None

_global_all_records = []
_global_output_csv = OUTPUT_CSV
_clean_exit = False
_LAST_DISCOVERED_MAX_PAGE = 1

def _emergency_save():
    global _global_all_records, _global_output_csv, _clean_exit
    if _global_all_records and not _clean_exit:
        try:
            save_to_csv(_global_all_records, _global_output_csv)
            print(f"\n💾 [{COMPANY_NAME}] บันทึกข้อมูลฉุกเฉิน {len(_global_all_records):,} รายการลง {os.path.basename(_global_output_csv)} สำเร็จ", flush=True)
        except Exception:
            pass

atexit.register(_emergency_save)

def _extract_max_page(soup, html_text=""):
    pages = [1]
    pag_ul = soup.find(class_=lambda c: c and "pagination" in c.lower()) if soup else None
    if pag_ul:
        for a in pag_ul.find_all('a', href=True):
            m = re.search(r'page=(\d+)', a['href'])
            if m:
                pages.append(int(m.group(1)))
    if html_text:
        m_tot = re.search(r'(?:พบ|ทั้งหมด|จำนวน)\s*([\d,]+)\s*(?:รายการ|ประกาศ)', html_text)
        if m_tot:
            try:
                tot_n = int(m_tot.group(1).replace(',', ''))
                if 0 < tot_n < 100000:
                    pages.append((tot_n + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
            except Exception:
                pass
        m_jtot = re.search(r'"numberOfItems"\s*:\s*(\d+)', html_text)
        if m_jtot:
            try:
                tot_j = int(m_jtot.group(1))
                if 0 < tot_j < 100000:
                    pages.append((tot_j + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
            except Exception:
                pass
    return min(1000, max(pages))

def fetch_zmyhome_page(session, p_type, prov_id, page_num, default_type="", default_province="", seen_ids=None, meta=None):
    global _LAST_DISCOVERED_MAX_PAGE
    url = f"https://zmyhome.com/buy/{p_type}/province/{prov_id}?page={page_num}&sortFilter=ads&per-page=35"

    def _fetch():
        r = safe_ssl_get(session, url, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code == 404:
            return None, True
        if r.status_code != 200:
            r.raise_for_status()
        return r, False

    try:
        r, is_404 = execute_with_retry(_fetch, company_name=COMPANY_NAME, context_msg=f"{p_type} จว.{prov_id} หน้า {page_num}", max_retries=3, max_cooldown_cycles=1)
        if is_404:
            if meta is not None:
                meta["raw_count"] = 0
            return []

        soup = BeautifulSoup(r.text, 'html.parser')
        _LAST_DISCOVERED_MAX_PAGE = _extract_max_page(soup, r.text)
        cards = soup.find_all("article", class_="card-property__item--article")
        if not cards:
            cards = soup.find_all("article")

        raw_records = []
        for card in cards:
            item = parse_zmyhome_card(card, default_type=default_type, default_province=default_province)
            if item and item.get("ID"):
                raw_records.append(item)

        if meta is not None:
            meta["raw_count"] = len(raw_records)
            meta["raw_ids"] = [str(it.get("ID", "")).strip() for it in raw_records if it.get("ID")]

        records = []
        if raw_records:
            for it in raw_records:
                iid = str(it.get("ID", "")).strip()
                if seen_ids and iid in seen_ids:
                    continue
                try:
                    det = fetch_zmyhome_detail(session, it)
                    if it.get("_is_sam"):
                        continue
                    if det:
                        records.append(det)
                    else:
                        records.append(it)
                except Exception:
                    if not it.get("_is_sam"):
                        records.append(it)
        return records
    except Exception:
        if meta is not None:
            meta["raw_count"] = -1
        return None

def save_to_csv(records, filename):
    return atomic_write_csv(records, filename, COLUMNS, company_name=COMPANY_NAME)

def main():
    global _global_all_records, _global_output_csv, _clean_exit
    print(f"==================================================", flush=True)
    print(f"🚀 เริ่มต้นการ Scrape [{COMPANY_NAME}] (โหมด 77 จังหวัดทั่วประเทศ)", flush=True)
    print(f"📁 บันทึกข้อมูลลงไฟล์: {OUTPUT_CSV}", flush=True)
    print(f"==================================================", flush=True)

    session = AuditedCurlSession(company_name=COMPANY_NAME, impersonate="chrome120")
    session.headers.update(HEADERS)

    init_gis()

    is_ok, code, total_est, total_provinces = check_link_health(session)
    if is_ok:
        status_msg = f"🌐 สถานะลิงก์: ปกติ (HTTP {code}) | ({total_provinces:2d}/77 จังหวัด) | ประมาณการ ~{total_est:,} รายการ"
        print(f"[{COMPANY_NAME}] {status_msg}", flush=True)
    else:
        print_alert("ไม่สามารถเข้าถึงเว็บ ZmyHome ได้", level="CRITICAL")
        _clean_exit = True
        sys.exit(1)

    all_records, seen_ids = load_existing_csv(OUTPUT_CSV)
    _global_all_records = all_records
    _global_output_csv = OUTPUT_CSV

    # สร้างไฟล์ CSV ทันทีตั้งแต่เริ่ม เพื่อให้มีไฟล์จริงบนโฟลเดอร์ 100%
    if not os.path.exists(OUTPUT_CSV) or os.path.getsize(OUTPUT_CSV) == 0:
        save_to_csv([], OUTPUT_CSV)
        print(f"[{COMPANY_NAME}] 📄 สร้างไฟล์ CSV เริ่มต้นแล้วที่ {OUTPUT_CSV}", flush=True)
    elif all_records:
        save_to_csv(all_records, OUTPUT_CSV)

    saved_state = load_scraper_state(COMPANY_NAME, MONTH_STR)
    saved_prov = int(saved_state.get("completed_pages", 0) or 0)
    prev_failed_tasks = saved_state.get("failed_tasks") or []
    if not prev_failed_tasks and saved_prov >= 77 and saved_state.get("status") == "COMPLETED" and len(all_records) > 0:
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลใน CSV ครบถ้วน 100% แล้ว (77/77 จังหวัด) | สะสม: {len(all_records):>6,d}/{len(all_records):,d} รายการ -> สแครปเสร็จสมบูรณ์ทันที!", flush=True)
        _clean_exit = True
        return
    start_prov = saved_prov + 1 if (0 < saved_prov < 77) else 1

    if start_prov > 1:
        pct_start = int((saved_prov / 77) * 100)
        print(f"[{COMPANY_NAME}] ⏩ Fast-Forward Resume: ข้าม {saved_prov} จังหวัดแรกที่เคยดึงแล้ว ({pct_start}%) -> เริ่มสแครปจังหวัดที่ {start_prov} ({ZMYHOME_PROVINCES.get(start_prov, '')}) ทันที", flush=True)

    is_test_mode = "--test" in sys.argv
    if is_test_mode:
        print(f"[{COMPANY_NAME}] 🧪 เปิดใช้งานโหมดทดสอบรวดเร็ว (--test): ดึง 1 หน้าแล้วบันทึกลง CSV ทันที", flush=True)

    start_time = time.time()
    new_added = 0
    saved_milestones = set()
    failed_tasks = []
    total_provs = 77
    pct = int(((start_prov - 1) * 100) / total_provs)

    try:
        for prov_id in range(start_prov, 78):
            wait_for_active_window(COMPANY_NAME)
            prov_name = ZMYHOME_PROVINCES.get(prov_id, f"จังหวัด_{prov_id}")
            prov_start_items = len(all_records)
            prov_ok = True

            for p_type, type_th in PROPERTY_TYPES:
                base_url = f"https://zmyhome.com/buy/{p_type}/province/{prov_id}?page=1&sortFilter=ads&per-page=35"
                try:
                    def _fetch_z_p1():
                        resp = safe_ssl_get(session, base_url, timeout=100, ssl_fallback_on_gov=False)
                        if resp.status_code == 404:
                            return None
                        if resp.status_code != 200:
                            resp.raise_for_status()
                        return resp

                    r = execute_with_retry(_fetch_z_p1, company_name=COMPANY_NAME, context_msg=f"{p_type} จว.{prov_id} หน้า 1", max_retries=3, max_cooldown_cycles=1)
                    if r is None:
                        continue
                    soup = BeautifulSoup(r.text, 'html.parser')
                    cards = soup.find_all("article", class_="card-property__item--article")
                    if not cards:
                        cards = soup.find_all("article")

                    if not cards:
                        # ไม่มีประกาศในหมวดนี้ของจังหวัดนี้ ข้ามทันที
                        continue

                    max_page = _extract_max_page(soup, r.text)
                    prev_raw_ids = set()

                    # วนลูปทุกหน้า (รองรับการขยาย max_page อัตโนมัติหากจังหวัดใหญ่มีมากกว่าที่แสดงในหน้าแรก)
                    page = 1
                    while page <= max_page:
                        page_added = 0
                        if page == 1:
                            p1_ids = set()
                            for c in cards:
                                it = parse_zmyhome_card(c, default_type=type_th, default_province=prov_name)
                                if it and it.get("ID"):
                                    iid = str(it["ID"]).strip()
                                    p1_ids.add(iid)
                                    if iid not in seen_ids:
                                        det = fetch_zmyhome_detail(session, it)
                                        if it.get("_is_sam"):
                                            seen_ids.add(iid)
                                            continue
                                        seen_ids.add(iid)
                                        item_to_add = det if det else it
                                        all_records.append(item_to_add)
                                        new_added += 1
                                        page_added += 1
                                        if len(all_records) % 5 == 0:
                                            save_to_csv(all_records, OUTPUT_CSV)

                                if is_test_mode and len(all_records) >= 5:
                                    break
                            prev_raw_ids = p1_ids
                        else:
                            page_meta = {}
                            items = fetch_zmyhome_page(session, p_type, prov_id, page, default_type=type_th, default_province=prov_name, seen_ids=seen_ids, meta=page_meta)
                            if _LAST_DISCOVERED_MAX_PAGE > max_page:
                                max_page = min(1000, _LAST_DISCOVERED_MAX_PAGE)
                            if items is None:
                                failed_tasks.append(f"{prov_name}-{p_type}-p{page}")
                                prov_ok = False
                                page += 1
                                time.sleep(get_scraper_delay())
                                continue
                            raw_cnt = page_meta.get("raw_count", len(items))
                            cur_raw_ids = set(page_meta.get("raw_ids") or [])
                            if raw_cnt == 0 or (prev_raw_ids and cur_raw_ids and cur_raw_ids.issubset(prev_raw_ids)):
                                break
                            prev_raw_ids = cur_raw_ids
                            for it in items:
                                if it.get("_is_sam"):
                                    continue
                                iid = str(it.get("ID", "")).strip()
                                if iid and iid not in seen_ids:
                                    seen_ids.add(iid)
                                    all_records.append(it)
                                    new_added += 1
                                    page_added += 1
                                    if len(all_records) % 5 == 0:
                                        save_to_csv(all_records, OUTPUT_CSV)

                        # 💾 บันทึก CSV ทันทีในทุกๆ หน้าที่ดึงเสร็จ! (บันทึก prov_id - 1 เป็น completed_pages จนกว่าจะครบทุกหมวดในจังหวัดนี้)
                        if page_added > 0:
                            save_to_csv(all_records, OUTPUT_CSV)
                            save_scraper_state(
                                COMPANY_NAME,
                                max(0, prov_id - 1),
                                77,
                                len(all_records),
                                status="RUNNING",
                                month_str=MONTH_STR,
                                extra={"current_prov": prov_id, "current_type": p_type, "current_page": page}
                            )

                        pct = int((prov_id / 77) * 100)
                        pbar = make_progress_bar(pct)
                        print(f"[{COMPANY_NAME:<13s}] {pbar} | ({prov_id:2d}/77 จังหวัด) ({prov_name}) | {type_th} หน้า {page}/{max_page} | +{page_added:2d} รายการ | สะสม: {len(all_records):>6,d} รายการ | 💾 บันทึก CSV แล้ว", flush=True)

                        if is_test_mode and len(all_records) >= 5:
                            break

                        page += 1
                        time.sleep(get_scraper_delay())

                    if is_test_mode and len(all_records) >= 5:
                        break
                except Exception as e:
                    log_warning(COMPANY_NAME, f"ขัดข้องชั่วคราวใน {p_type} จว.{prov_id}: {e}")
                    failed_tasks.append(f"{prov_name}-{p_type}")
                    prov_ok = False

            prov_items_added = len(all_records) - prov_start_items
            if prov_items_added > 0:
                save_to_csv(all_records, OUTPUT_CSV)

            pct = int((prov_id / 77) * 100)
            if prov_ok:
                save_scraper_state(COMPANY_NAME, prov_id, 77, len(all_records), status="RUNNING", month_str=MONTH_STR)
            else:
                save_scraper_state(COMPANY_NAME, max(0, prov_id - 1), 77, len(all_records), status="RUNNING", month_str=MONTH_STR, extra={"failed_tasks": failed_tasks[-100:]})

            for target_pct in range(5, 105, 5):
                if pct >= target_pct and target_pct not in saved_milestones:
                    saved_milestones.add(target_pct)
                    log_milestone(COMPANY_NAME, f"💾 บันทึก Milestone สำรอง {target_pct}% ({len(all_records):,} รายการ) ลง {os.path.basename(OUTPUT_CSV)}")

            if is_test_mode and len(all_records) >= 5:
                break

            time.sleep(1.0) # หน่วงเวลาสั้นๆ ระหว่างจังหวัด

    except (KeyboardInterrupt, SystemExit):
        print(f"\n⚠️ [{COMPANY_NAME}] ผู้ใช้หยุดการทำงานชั่วคราว -> กำลังบันทึกข้อมูลสะสมทั้งหมด ({len(all_records):,} รายการ) ลง {OUTPUT_CSV} ทันที...", flush=True)
        save_to_csv(all_records, OUTPUT_CSV)
        _clean_exit = True
        save_scraper_state(COMPANY_NAME, max(0, (prov_id - 1) if 'prov_id' in locals() else 0), 77, len(all_records), status="STOPPED", month_str=MONTH_STR)
        raise
    except Exception as e:
        print_alert(f"เกิดข้อผิดพลาด: {e}", level="CRITICAL")
        save_to_csv(all_records, OUTPUT_CSV)
        _clean_exit = True
        save_scraper_state(
            COMPANY_NAME,
            max(0, (prov_id - 1) if 'prov_id' in locals() else 0),
            77,
            len(all_records),
            status="FAILED",
            month_str=MONTH_STR,
            extra={"failed_tasks": failed_tasks[-100:], "error": str(e)}
        )
        sys.exit(1)

    save_to_csv(all_records, OUTPUT_CSV)
    _clean_exit = True
    elapsed = time.time() - start_time
    if failed_tasks and not is_test_mode:
        final_status = "FAILED" if len(all_records) == 0 else "PARTIAL"
        save_scraper_state(COMPANY_NAME, 77, 77, len(all_records), status=final_status, month_str=MONTH_STR, extra={"failed_tasks": failed_tasks[-100:]})
        print(f"\n==================================================", flush=True)
        print(f"⚠️ [{COMPANY_NAME}] สแครปเสร็จแบบมีรายการล้มเหลว ({final_status}) | สะสม: {len(all_records):,d} รายการ | ล้มเหลว {len(failed_tasks)} จุด", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที | ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        print(f"==================================================", flush=True)
        log_warning(COMPANY_NAME, f"⚠️ สแครปเสร็จแบบ {final_status}: ล้มเหลว {len(failed_tasks)} จุด")
        sys.exit(1 if len(all_records) == 0 else 2)

    save_scraper_state(COMPANY_NAME, 77, 77, len(all_records), status="COMPLETED" if not is_test_mode else "RUNNING", month_str=MONTH_STR, extra={"failed_tasks": []})
    print(f"\n==================================================", flush=True)
    if is_test_mode:
        print(f"✅ [{COMPANY_NAME}] ทดสอบรวดเร็วสำเร็จ! บันทึกข้อมูลลง CSV เรียบร้อย | สะสม: {len(all_records):,d} รายการ", flush=True)
    else:
        print(f"✅ [{COMPANY_NAME}] สแครปครบถ้วน 100% (77/77 จังหวัด) เสร็จสมบูรณ์! | สะสม: {len(all_records):,d} รายการ", flush=True)
    print(f"📊 ได้ข้อมูลทั้งหมด: {len(all_records):,} รายการ (เพิ่มใหม่รอบนี้: {new_added:,} รายการ)", flush=True)
    print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที | ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
    print(f"==================================================", flush=True)

if __name__ == "__main__":
    main()
