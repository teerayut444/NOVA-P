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
    safe_ssl_get,
    atomic_write_csv,
    print_alert,
    print_structure_alert,
)
from timeout_handler import wait_1hr_on_timeout, handle_timeout_retry, execute_with_retry
from clean_location_util import clean_floor_val, extract_floor_from_text, clean_row_location, init_gis
try:
    from clean_project_util import clean_project_name, extract_project_from_title
except ImportError:
    clean_project_name = lambda x, **kwargs: str(x).strip()
    extract_project_from_title = lambda x, **kwargs: ""
from curl_cffi import requests
import json
import re
import os
import sys
import time
from time_window_util import get_scraper_delay, get_scraper_delay_range
import random
from datetime import datetime
import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

COMPANY_NAME = "Baania"
MONTH_STR = datetime.now().strftime("%Y_%m")

_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR
OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"Baania_NPA_New_{MONTH_STR}.csv")

BASE_URL = "https://www.baania.com/s/%E0%B8%97%E0%B8%B1%E0%B9%89%E0%B8%87%E0%B8%AB%E0%B8%A1%E0%B8%94/listing?sellState=on-sale,sale-rent&sort.created=desc"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept-Language': 'th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Connection': 'keep-alive'
}

COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคา",
    "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ"
]

ITEMS_PER_PAGE = 48
MAX_PAGES_CAP = 208  # Elasticsearch max_result_window = 10,000 / 48 = 208 pages

def print_alert(msg: str, level: str = "ERROR"):
    border = "=" * 75
    if level == "CRITICAL":
        icon = "🚨 [CRITICAL ALERT]"
    elif level == "WARNING":
        icon = "⚠️ [WARNING ALERT]"
    else:
        icon = "❌ [ERROR ALERT]"
    print(f"\n{border}\n{icon} ({COMPANY_NAME}): {msg}\n{border}\n", flush=True)

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
        mins = mins % 60
        return f"เหลืออีก ~{hrs}ชม. {mins}น. ({finish_clock} น.)"
    elif mins > 0:
        return f"เหลืออีก ~{mins}น. {secs}ว. ({finish_clock} น.)"
    else:
        return f"เหลืออีก ~{secs}ว. ({finish_clock} น.)"

def clean_text(val):
    if val is None:
        return ""
    s = str(val)
    return re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', s).strip()

def is_date_pattern(s):
    if not s:
        return False
    s_str = str(s).strip()
    if re.search(r'\b(19\d\d|20\d\d|25\d\d)[-/]\d{1,2}[-/]\d{1,2}\b', s_str):
        return True
    if ('T' in s_str and ':' in s_str) or s_str.endswith('Z'):
        return True
    if re.search(r'\b(ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)', s_str):
        return True
    return False

def parse_rai_ngan_wah_robust(s):
    if s is None or pd.isna(s):
        return None, None, None
    s = str(s).strip()
    if not s or s.lower() in ["nan", "none", "null", "$undefined", "-", "0", "0.0"]:
        return None, None, None
    if is_date_pattern(s):
        return None, None, None
    m_dash = re.match(r'^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$', s)
    if m_dash:
        r, g, w = float(m_dash.group(1)), float(m_dash.group(2)), float(m_dash.group(3))
        # If rai or wah is a year like 2026, it is a date mistakenly passed as dash
        if r > 10000 or (r > 2000 and g <= 12 and w <= 31):
            return None, None, None
        return r, g, w
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
            if total_wah > 0 and total_wah < 500000: # prevent phone numbers or years from being treated as wah
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
    if is_date_pattern(val):
        return ""
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

def parse_land_area(area_total):
    if not isinstance(area_total, dict):
        if isinstance(area_total, str) and not is_date_pattern(area_total):
            return area_total
        return ""
    rai = area_total.get("rai")
    ngan = area_total.get("ngan")
    wa = area_total.get("wa")
    
    def clean_num(v):
        if v is None: return None
        if isinstance(v, (int, float)): return v if v > 0 else None
        s = str(v).strip()
        if is_date_pattern(s): return None
        try:
            val_f = float(re.sub(r'[^\d\.]', '', s))
            return val_f if val_f > 0 else None
        except Exception:
            return None

    r_v = clean_num(rai)
    g_v = clean_num(ngan)
    w_v = clean_num(wa)

    parts = []
    if r_v: parts.append(f"{r_v} ไร่")
    if g_v: parts.append(f"{g_v} งาน")
    if w_v: parts.append(f"{w_v} ตร.ว.")
    return " ".join(parts)

def parse_sell_state(vd):
    st = str(vd.get("sell_state", "")).lower()
    lt = str(vd.get("listing_type", "")).lower()
    if "sale-rent" in st or "sale-rent" in lt: return "ขาย/เช่า"
    if "rent" in lt or "rent" in st: return "เช่า"
    if "on-sale" in st or "for-sale" in lt or "sale" in st: return "ขาย"
    return vd.get("sell_state") or vd.get("listing_type") or ""

def parse_property_type(vd):
    pt_list = vd.get("property_type", [])
    if isinstance(pt_list, list):
        names = []
        for pt in pt_list:
            if isinstance(pt, dict) and pt.get("th"): names.append(pt.get("th"))
            elif isinstance(pt, str): names.append(pt)
        return ", ".join(names)
    return ""

def extract_addr_part(part):
    if not part:
        return ""
    if isinstance(part, str):
        return part.strip()
    if isinstance(part, dict):
        title = part.get("title")
        if isinstance(title, dict):
            val = title.get("th") or title.get("en")
            if val:
                return str(val).strip()
        elif isinstance(title, str) and title:
            return title.strip()
        if "th" in part and part.get("th"):
            return str(part.get("th")).strip()
        if "name" in part and part.get("name"):
            return str(part.get("name")).strip()
        if "name_th" in part and part.get("name_th"):
            return str(part.get("name_th")).strip()
        if "en" in part and part.get("en"):
            return str(part.get("en")).strip()
    return str(part).strip()

def extract_price(vd, flt):
    for p in [vd.get("price_start"), vd.get("price")]:
        if p is not None:
            try:
                p_f = float(p)
                if p_f >= 1000.0:
                    return p_f
            except Exception:
                pass
    if isinstance(flt, dict):
        p_list = flt.get("price")
        if isinstance(p_list, list) and len(p_list) > 0:
            p = p_list[0]
            if p is not None:
                try:
                    p_f = float(p)
                    if p_f >= 1000.0:
                        return p_f
                except Exception:
                    pass
    return None

def extract_publish_date(vd, flt, src):
    date_val = vd.get("created_at") or vd.get("published_at") or vd.get("updated_at")
    if not date_val and isinstance(flt, dict):
        date_val = flt.get("created") or flt.get("updated")
    if not date_val and isinstance(src, dict):
        date_val = src.get("created") or src.get("updated")
    return clean_text(date_val or "")

def load_existing_csv(filename):
    records = []
    seen_ids = set()
    if "--fresh" in sys.argv or "--force-restart" in sys.argv:
        print(f"[{COMPANY_NAME}] ⚠️ พบคำสั่ง --fresh หรือ --force-restart: รีเซ็ตข้อมูลใหม่ทั้งหมด", flush=True)
        reset_scraper_state(COMPANY_NAME, MONTH_STR)
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass
        return records, seen_ids

    if os.path.exists(filename):
        try:
            df = pd.read_csv(filename, encoding="utf-8-sig", dtype=str).fillna("")
            for col in COLUMNS:
                if col not in df.columns:
                    df[col] = ""
            raw_records = df[COLUMNS].to_dict(orient="records")
            valid_records = []
            for r in raw_records:
                iid = str(r.get("ID") or "").strip()
                if not iid or iid in ("nan", "NaN", "None", "null"):
                    continue
                p = r.get("ราคา")
                prov = str(r.get("จังหวัด") or "").strip()
                has_price = p is not None and str(p).strip() not in ["", "nan", "NaN", "None"]
                has_prov = prov not in ["", "nan", "NaN", "None"]
                
                # Clean area field from date artifacts
                area_val = r.get("เนื้อที่ (ตร.ว.)")
                if is_date_pattern(area_val):
                    r["เนื้อที่ (ตร.ว.)"] = ""
                    
                # Ensure รหัสทรัพย์ falls back to ID if missing
                code_val = str(r.get("รหัสทรัพย์") or "").strip()
                if not code_val or code_val.lower() in ["none", "null", "nan", "-", ""]:
                    r["รหัสทรัพย์"] = iid
                    
                if iid and (has_price or has_prov):
                    valid_records.append(r)
                    seen_ids.add(iid)
            
            if len(valid_records) < len(raw_records):
                diff = len(raw_records) - len(valid_records)
                print(f"[{COMPANY_NAME}] ⚠️ พบข้อมูลเก่าที่ไม่สมบูรณ์ (ไม่มีราคา/ที่อยู่) {diff:,} รายการ -> ละทิ้งและจะดึงใหม่", flush=True)
                records = valid_records
            else:
                records = valid_records
                
            print(f"[{COMPANY_NAME}] 🔄 Smart Resume: โหลดข้อมูลเดิมจาก {filename} พบแล้ว {len(records):,} รายการ", flush=True)
        except Exception as e:
            print_alert(f"ไม่สามารถอ่านไฟล์สะสมเดิม {filename}: {e}", level="WARNING")
    return records, seen_ids

def check_link_health(session):
    url = f"{BASE_URL}&page=1"
    def _probe():
        res = safe_ssl_get(session, url, headers=HEADERS, timeout=100, ssl_fallback_on_gov=False)
        if res.status_code != 200:
            res.raise_for_status()
        return res

    try:
        res = execute_with_retry(_probe, company_name=COMPANY_NAME, context_msg="Baania Health Probe", max_retries=4, max_cooldown_cycles=1)
        status_code = res.status_code
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', res.text)
        if not match:
            print_structure_alert(COMPANY_NAME, "ไม่พบแท็ก <script id='__NEXT_DATA__'> ในหน้าเว็บ (Baania อาจเปลี่ยนสถาปัตยกรรม SSR/Next.js)")
            return False, status_code, 0, 0

        try:
            data = json.loads(match.group(1))
        except Exception as e:
            print_structure_alert(COMPANY_NAME, f"ไม่สามารถแปลง JSON __NEXT_DATA__ ได้: {e}")
            return False, status_code, 0, 0

        hits_obj = (((data.get("props") or {}).get("pageProps") or {}).get("defaultData") or {}).get("hits") or {}
        raw_hits = hits_obj.get("hits")
        if not isinstance(raw_hits, list) or len(raw_hits) == 0:
            print_structure_alert(COMPANY_NAME, "ไม่พบรายการทรัพย์ใน Path 'props.pageProps.defaultData.hits.hits' (Schema JSON อาจเปลี่ยน)")
            return False, status_code, 0, 0

        sample_valid = 0
        for sample_hit in raw_hits[:5]:
            src = sample_hit.get("_source", {})
            vd = src.get("view_data", {})
            item_id = str(sample_hit.get("_id") or vd.get("pkid") or "").strip()
            if item_id:
                sample_valid += 1

        if sample_valid == 0:
            print_structure_alert(COMPANY_NAME, "ไม่สามารถสกัด ID/รหัสทรัพย์ จากรายการตัวอย่างหน้าแรกได้ (Data Schema เปลี่ยนแปลง)")
            return False, status_code, 0, 0

        tot = hits_obj.get("total")
        total_val = 0
        if isinstance(tot, dict):
            total_val = tot.get("value", 0)
        elif isinstance(tot, (int, float)):
            total_val = int(tot)

        pages = (total_val + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE if total_val > 0 else 1
        pages = min(MAX_PAGES_CAP, pages)
        total_val = min(pages * ITEMS_PER_PAGE, total_val)
        return True, status_code, total_val, pages
    except Exception:
        return False, 0, 0, 0

def fetch_page_items(session, page_num, cooldown_cycles=0):
    url = f"{BASE_URL}&page={page_num}"
    def _fetch_html():
        res = safe_ssl_get(session, url, timeout=100, ssl_fallback_on_gov=False)
        if res.status_code == 404 and page_num >= MAX_PAGES_CAP:
            return None, True
        if res.status_code != 200:
            res.raise_for_status()
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', res.text)
        if not match:
            raise TimeoutError(f"ไม่พบ __NEXT_DATA__ ในหน้า {page_num}")
        return match.group(1), False

    try:
        json_str, is_eof = execute_with_retry(_fetch_html, company_name=COMPANY_NAME, context_msg=f"หน้า {page_num}", max_retries=6, max_cooldown_cycles=2)
        if is_eof:
            return []
        data = json.loads(json_str)
        hits = ((((data.get("props") or {}).get("pageProps") or {}).get("defaultData") or {}).get("hits") or {}).get("hits") or []
        records = []
        scrape_time = datetime.now().strftime("%Y-%m-%d")

        for item in hits:
            src = item.get("_source", {})
            vd = src.get("view_data", {})
            addr = src.get("address", {})
            loc = src.get("location", {})
            flt = src.get("filter", {})

            item_id = clean_text(item.get("_id") or vd.get("pkid") or vd.get("keyId") or "")
            code = clean_text(vd.get("code") or vd.get("project_code") or vd.get("listing_code") or "")
            if not code or code.lower() in ["none", "null", "nan", "-"]:
                code = item_id

            proj_title = vd.get("project_title")
            proj_name = clean_text(proj_title.get("th") if isinstance(proj_title, dict) else str(proj_title or ""))

            title = vd.get("title")
            title_th = clean_text(title.get("th") if isinstance(title, dict) else str(title or ""))

            p_type = parse_property_type(vd)
            sale_type = parse_sell_state(vd)
            if sale_type == "เช่า":
                continue  # Filter out pure rental listings
            price = extract_price(vd, flt)

            subdist = clean_text(extract_addr_part(addr.get("subdistrict")))
            dist = clean_text(extract_addr_part(addr.get("district")))
            prov = clean_text(extract_addr_part(addr.get("province")))
            if "กรุงเทพ" in prov: prov = "กรุงเทพมหานคร"

            slug = vd.get("slug")
            url_obj = vd.get("url", {})
            source_url = url_obj.get("source_url") if isinstance(url_obj, dict) else None
            if source_url:
                link = f"https://www.baania.com/th/{source_url}" if not source_url.startswith("http") else source_url
            elif slug:
                link = f"https://www.baania.com/th/listing/{slug}"
            else:
                link = f"https://www.baania.com/th/listing/{item_id}"

            floor_val = clean_floor_val(vd.get("floor") or vd.get("floors") or vd.get("number_of_floors") or flt.get("floor") or flt.get("floors"))
            if not floor_val:
                floor_val = extract_floor_from_text(title_th, proj_name, asset_type=p_type)

            record = {
                "บริษัท": COMPANY_NAME,
                "ID": item_id,
                "รหัสทรัพย์": code if code else item_id,
                "ชื่อโครงการ": (clean_project_name(proj_name, tambon=subdist, amphoe=dist, province=prov, company=COMPANY_NAME) if proj_name else (extract_project_from_title(title_th, tambon=subdist, amphoe=dist, province=prov, company=COMPANY_NAME) if extract_project_from_title else "")) if clean_project_name else proj_name,
                "ประเภททรัพย์": p_type,
                "ประเภทการขาย": sale_type,
                "ราคา": price,
                "ตำบล": subdist,
                "อำเภอ": dist,
                "จังหวัด": prov,
                "ละติจูด": loc.get("lat") if isinstance(loc, dict) else None,
                "ลองจิจูด": loc.get("lon") if isinstance(loc, dict) else None,
                "ชื่อประกาศ": title_th,
                "ลิงก์": link,
                "เนื้อที่ (ตร.ว.)": convert_to_rai_ngan_wah(clean_text(parse_land_area(vd.get("area_total")))),
                "พื้นที่ใช้สอย (ตร.ม.)": vd.get("area_usable"),
                "วันที่ดึงข้อมูล": scrape_time,
                "ห้องนอน": vd.get("bedroom"),
                "ห้องน้ำ": vd.get("bathroom"),
                "ที่จอดรถ": vd.get("parking"),
                "ชั้น": floor_val or "",
                "วันประกาศ": extract_publish_date(vd, flt, src)
            }
            clean_row_location(record)
            records.append(record)
        return records
    except Exception:
        log_warning(COMPANY_NAME, f"ข้ามหน้า {page_num} เนื่องจากพักรอและลองซ้ำไม่สำเร็จ")
        return None

def save_to_csv(records, filename):
    return atomic_write_csv(records, filename, COLUMNS, company_name=COMPANY_NAME)

def main():
    print(f"==================================================", flush=True)
    print(f"🚀 เริ่มต้นการ Scrape [{COMPANY_NAME}] (Monthly Mode)", flush=True)
    init_gis()
    print(f"📁 บันทึกข้อมูลลงไฟล์: {OUTPUT_CSV}", flush=True)
    print(f"==================================================", flush=True)

    session = AuditedCurlSession(company_name=COMPANY_NAME, impersonate="chrome120")

    is_ok, code, total_items, total_pages = check_link_health(session)
    if is_ok:
        if total_items <= 0:
            total_items = total_pages * ITEMS_PER_PAGE
        status_msg = f"🌐 สถานะลิงก์: ปกติ (HTTP {code}) | ทั้งหมด {total_pages:,} หน้า | {ITEMS_PER_PAGE} รายการ/หน้า (พบทั้งหมด {total_items:,} รายการ)"
        print(f"[{COMPANY_NAME}] {status_msg}", flush=True)
    else:
        print_alert("ไม่สามารถเชื่อมต่อเว็บ Baania ได้", level="CRITICAL")
        sys.exit(1)

    all_records, seen_ids = load_existing_csv(OUTPUT_CSV)
    saved_state = load_scraper_state(COMPANY_NAME, MONTH_STR)
    prev_failed_pages = [int(p) for p in (saved_state.get("failed_pages") or []) if str(p).isdigit()]

    if not prev_failed_pages and total_items > 0 and (len(all_records) >= total_items or saved_state.get("status") == "COMPLETED"):
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลใน CSV ครบถ้วน 100% แล้ว ({total_pages:5,d}/{total_pages:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{total_items:,d} รายการ -> สแครปเสร็จสมบูรณ์ทันที!", flush=True)
        save_to_csv(all_records, OUTPUT_CSV)
        save_scraper_state(
            company_name=COMPANY_NAME,
            month_str=MONTH_STR,
            completed_pages=total_pages,
            total_pages=total_pages,
            total_records=len(all_records),
            status="COMPLETED"
        )
        return

    if saved_state and saved_state.get("completed_pages", 0) > 0:
        completed_pages = min(total_pages - 1, int(saved_state.get("completed_pages", 0)))
    else:
        completed_pages = min(total_pages - 1, len(all_records) // ITEMS_PER_PAGE)
    start_page = completed_pages + 1

    saved_milestones = set()
    failed_pages = []

    if completed_pages > 0:
        pct_start = int((completed_pages / total_pages) * 100)
        for target_pct in range(5, pct_start + 1, 5):
            saved_milestones.add(target_pct)
        saved_milestones.add("initial_page")
        print(f"[{COMPANY_NAME}] ⏩ Fast-Forward Resume: ข้าม {completed_pages:,} หน้าแรกที่เคยดึงแล้ว -> เริ่มสแครปหน้า {start_page:,} ต่อทันที", flush=True)

    start_time = time.time()
    new_added = 0
    processed_pages = completed_pages
    pages_to_run = sorted(set([p for p in prev_failed_pages if 1 <= p < start_page] + list(range(start_page, total_pages + 1))))

    for page in pages_to_run:
        if not failed_pages and total_items > 0 and len(all_records) >= total_items and page >= total_pages:
            print(f"\n[{COMPANY_NAME}] 🎉 สะสมข้อมูลครบถ้วนทั้งหมดแล้ว ({len(all_records):,}/{total_items:,} รายการ) -> สิ้นสุดการสแครป!", flush=True)
            break
        items = fetch_page_items(session, page)
        if items is None:
            failed_pages.append(page)
            print(f"\n[{COMPANY_NAME}] ⚠️ ข้ามหน้า {page} เนื่องจากดึงข้อมูลไม่สำเร็จหลังจากลองหลายครั้ง", flush=True)
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

        if page_added > 0:
            save_to_csv(all_records, OUTPUT_CSV)

        if not failed_pages:
            processed_pages = max(processed_pages, page)

        save_scraper_state(
            company_name=COMPANY_NAME,
            month_str=MONTH_STR,
            completed_pages=processed_pages,
            total_pages=total_pages,
            total_records=len(all_records),
            status="RUNNING",
            extra={"failed_pages": failed_pages}
        )

        pct = int((processed_pages / total_pages) * 100) if total_pages > 0 else 0
        elapsed_sec = time.time() - start_time
        eta_msg = format_eta(elapsed_sec, processed_pages, total_pages, start_unit=start_page)
        pbar = make_progress_bar(pct)

        print(f"[{COMPANY_NAME:<13s}] {pbar} | ({processed_pages:5,d}/{total_pages:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{total_items:,d} รายการ | {eta_msg}", flush=True)

        if "initial_page" not in saved_milestones and len(all_records) > 0:
            saved_milestones.add("initial_page")
            print(f"\n💾 [{COMPANY_NAME}] ครบหน้าแรก -> บันทึกไฟล์เริ่มต้นลง {OUTPUT_CSV}...", flush=True)
            log_milestone(COMPANY_NAME, f"💾 บันทึกเริ่มต้น (ครบหน้าแรก) {len(all_records):,} รายการลง " + os.path.basename(OUTPUT_CSV))

        for target_pct in range(5, 105, 5):
            if pct >= target_pct and target_pct not in saved_milestones:
                saved_milestones.add(target_pct)
                print(f"\n💾 [{COMPANY_NAME}] ครบ Milestone {target_pct}% -> บันทึกสำรองลง {OUTPUT_CSV}...", flush=True)
                log_milestone(COMPANY_NAME, f"💾 บันทึก Milestone สำรอง {target_pct}% ({len(all_records):,} รายการ) ลง " + os.path.basename(OUTPUT_CSV))
                save_to_csv(all_records, OUTPUT_CSV)

        if not items and page >= total_pages:
            break

        time.sleep(get_scraper_delay())  # หน่วงเวลาอย่างน้อย 15 วินาทีต่อหน้า เพื่อความปลอดภัยสูงสุด

    print("", flush=True)
    save_to_csv(all_records, OUTPUT_CSV)
    elapsed = time.time() - start_time
    if failed_pages:
        final_status = "FAILED" if len(all_records) == 0 else "PARTIAL"
        save_scraper_state(
            company_name=COMPANY_NAME,
            month_str=MONTH_STR,
            completed_pages=processed_pages,
            total_pages=total_pages,
            total_records=len(all_records),
            status=final_status,
            extra={"failed_pages": failed_pages}
        )
        print(f"\n==================================================", flush=True)
        print(f"⚠️ [{COMPANY_NAME}] สแครปเสร็จแบบมีหน้าล้มเหลว ({final_status}) | ({processed_pages:5,d}/{total_pages:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{total_items:,d} รายการ", flush=True)
        print(f"⚠️ รายการหน้าที่ข้าม/ดึงไม่ได้ ({len(failed_pages)} หน้า): {sorted(failed_pages)}", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที | 💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        log_warning(COMPANY_NAME, f"⚠️ สแครปเสร็จแบบ {final_status}: ดึงไม่ได้ {len(failed_pages)} หน้า")
        sys.exit(1 if len(all_records) == 0 else 2)
    else:
        save_scraper_state(
            company_name=COMPANY_NAME,
            month_str=MONTH_STR,
            completed_pages=total_pages,
            total_pages=total_pages,
            total_records=len(all_records),
            status="COMPLETED",
            extra={"failed_pages": []}
        )
        print(f"\n==================================================", flush=True)
        print(f"✅ [{COMPANY_NAME}] สแครปเสร็จสมบูรณ์! | ({processed_pages:5,d}/{total_pages:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{total_items:,d} รายการ", flush=True)
        print(f"📊 ได้ข้อมูลทั้งหมด: {len(all_records):,} รายการ (เพิ่มใหม่ในรอบนี้: {new_added:,} รายการ)", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที", flush=True)
        print(f"💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        print(f"✅ ดึงข้อมูลได้ครบถ้วนสำเร็จ 100% (ไม่มีหน้าล้มเหลว)", flush=True)
        print(f"==================================================", flush=True)
        log_success(COMPANY_NAME, f"✅ สแครปเสร็จสมบูรณ์! ได้ข้อมูลทั้งหมดสะสม {len(all_records):,} รายการลง {os.path.basename(OUTPUT_CSV)}")

if __name__ == "__main__":
    main()
