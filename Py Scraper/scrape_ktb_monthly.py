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
    safe_ssl_post,
    read_csv_resume,
    atomic_write_csv,
    print_structure_alert,
)
from timeout_handler import wait_1hr_on_timeout, handle_timeout_retry, execute_with_retry
import requests
import pandas as pd
import re
import os
import time
from time_window_util import get_scraper_delay, get_scraper_delay_range
import random
from datetime import datetime
import threading
import sys

from clean_location_util import clean_floor_val, extract_floor_from_text, clean_row_location, init_gis
try:
    from clean_project_util import clean_project_name, extract_project_from_title
except ImportError:
    clean_project_name = lambda x, **kwargs: str(x).strip()
    extract_project_from_title = lambda x, **kwargs: ""

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

COMPANY_NAME = "KTB"
MONTH_STR = datetime.now().strftime("%Y_%m")

_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR
OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"KTB_NPA_New_{MONTH_STR}.csv")

PAGE_LIMIT = 50

COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคา",
    "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ", "ยอดเข้าชม"
]

print_lock = threading.Lock()
progress_counter = 0
start_time_global = None

def print_alert(msg: str, level: str = "ERROR"):
    border = "=" * 75
    if level == "CRITICAL":
        icon = "🚨 [CRITICAL ALERT]"
    elif level == "WARNING":
        icon = "⚠️ [WARNING ALERT]"
    else:
        icon = "❌ [ERROR ALERT]"
    with print_lock:
        print(f"\n{border}\n{icon} ({COMPANY_NAME}): {msg}\n{border}\n", flush=True)
        log_txn(COMPANY_NAME, level, msg)

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

def clean_text(t):
    if t is None:
        return ""
    return re.sub(r'\s+', ' ', str(t)).strip()

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

def parse_rai_ngan_wah(area_str):
    r, g, w = parse_rai_ngan_wah_robust(area_str)
    if r is None:
        return None
    return r * 400.0 + g * 100.0 + w

def _to_int_or_none(val):
    if val is None:
        return None
    s = str(val).replace(",", "").strip()
    if not s or s.lower() in ("nan", "none", "null", "-"):
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None

def load_existing_csv(filename):
    if "--fresh" in sys.argv or "--force-restart" in sys.argv:
        print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นดึงข้อมูลใหม่ทั้งหมดจากหน้า 1 (โหมด --fresh)", flush=True)
        reset_scraper_state(COMPANY_NAME, MONTH_STR)
        return [], set()
    return read_csv_resume(filename, COLUMNS, id_col="ID", company_name=COMPANY_NAME)

CHROME_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "Origin": "https://npa.krungthai.com",
    "Referer": "https://npa.krungthai.com/searchResult",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Connection": "keep-alive"
}

def init_browser_session(session):
    """เข้าหน้าแรกจำลองการเปิดเบราว์เซอร์ เพื่อรับ Cookies และ Session เสมือนคนเปิด Chrome จริง"""
    try:
        landing_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
            "Upgrade-Insecure-Requests": "1"
        }
        safe_ssl_get(session, "https://npa.krungthai.com/searchResult", headers=landing_headers, timeout=30, ssl_fallback_on_gov=False)
        time.sleep(random.uniform(1.2, 1.8))
    except Exception:
        pass

def check_link_health(session=None):
    if session is None:
        session = AuditedSession(company_name=COMPANY_NAME)
    init_browser_session(session)
    url = "https://npa.krungthai.com/api/v1/product/searchAll"
    headers = CHROME_HEADERS
    payload = {
        "paging": {
            "currentPage": 1,
            "rowsPerPage": PAGE_LIMIT,
            "totalRows": 0
        }
    }

    def _probe():
        r = safe_ssl_post(session, url, headers=headers, json=payload, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code != 200:
            r.raise_for_status()
        return r

    try:
        r = execute_with_retry(_probe, company_name=COMPANY_NAME, context_msg="KTB Health Probe", max_retries=4, max_cooldown_cycles=1)
        data = r.json()
        data_resp = data.get("dataResponse")
        if data_resp is None or not isinstance(data_resp, list):
            print_structure_alert(COMPANY_NAME, "ไม่พบ Array 'dataResponse' ในผลลัพธ์ของ KTB NPA API (API Schema เปลี่ยนแปลง)")
            return False, r.status_code, 0, 0

        if len(data_resp) == 0:
            print_structure_alert(COMPANY_NAME, "Array 'dataResponse' ของ KTB NPA API ว่างเปล่า (0 รายการ)")
            return False, r.status_code, 0, 0

        sample_valid = sum(1 for it in data_resp[:5] if it.get("collGrpId") or it.get("collCode") or it.get("collTId"))
        if sample_valid == 0:
            print_structure_alert(COMPANY_NAME, "ไม่พบฟิลด์ 'collGrpId' หรือ 'collCode' ในข้อมูลทรัพย์ของ KTB API")
            return False, r.status_code, 0, 0

        paging = data.get("paging") or {}
        total_items = int(paging.get("totalRows") or len(data_resp))
        total_pages = (total_items + PAGE_LIMIT - 1) // PAGE_LIMIT if total_items > 0 else 1
        return True, r.status_code, total_items, total_pages
    except Exception:
        print_alert("ไม่สามารถเชื่อมต่อ KTB NPA API ได้ (Timeout / Connection Error)", level="CRITICAL")
        return False, 0, 0, 0

def fetch_page_items_individually(page_no, session, page_limit=PAGE_LIMIT):
    """
    Fallback เมื่อเซิร์ฟเวอร์ KTB เกิด HTTP 500 (เช่น ข้อมูลบางรายการใน Database ของ KTB มีฟิลด์ผิดพลาด)
    จะสลับมากวาดทีละรายการ (rowsPerPage=1) เพื่อข้ามเฉพาะรายการที่เสีย และกู้คืนรายการปกติที่เหลือทั้งหมด
    """
    start_offset = (page_no - 1) * page_limit + 1
    recovered_items = []
    skipped_count = 0
    url = "https://npa.krungthai.com/api/v1/product/searchAll"
    headers = CHROME_HEADERS

    print(f"\n[{COMPANY_NAME}] 🛠️ หน้า {page_no} เซิร์ฟเวอร์ KTB ตอบ HTTP 500 -> เริ่มต้น Safe Item Fallback รายการที่ {start_offset}..{start_offset + page_limit - 1}...", flush=True)
    for idx in range(start_offset, start_offset + page_limit):
        p = {"paging": {"currentPage": idx, "rowsPerPage": 1, "totalRows": 0}}
        try:
            time.sleep(max(1.5, min(3.0, get_scraper_delay() / 5.0)))
            r = safe_ssl_post(session, url, headers=headers, json=p, timeout=30, ssl_fallback_on_gov=False)
            if r.status_code == 200:
                items = r.json().get("dataResponse") or []
                recovered_items.extend(items)
            else:
                skipped_count += 1
                log_warning(COMPANY_NAME, f"ข้ามรายการลำดับ {idx} เนื่องจากเซิร์ฟเวอร์ KTB เกิด HTTP {r.status_code}")
        except Exception as e:
            skipped_count += 1
            log_warning(COMPANY_NAME, f"ข้ามรายการลำดับ {idx} เนื่องจาก Exception: {e}")

    print(f"[{COMPANY_NAME}] ✅ Safe Item Fallback หน้า {page_no} สำเร็จ: กู้คืนได้ {len(recovered_items)} รายการ (ข้ามรายการเสีย {skipped_count} รายการ)\n", flush=True)
    return recovered_items

def fetch_page(page_no, session, max_retries=4):
    url = "https://npa.krungthai.com/api/v1/product/searchAll"
    headers = CHROME_HEADERS
    payload = {
        "paging": {
            "currentPage": page_no,
            "rowsPerPage": PAGE_LIMIT,
            "totalRows": 0
        }
    }

    def _fetch():
        time.sleep(get_scraper_delay())
        r = safe_ssl_post(session, url, headers=headers, json=payload, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code == 200:
            return r.json().get("dataResponse") or []
        if r.status_code == 500:
            log_warning(COMPANY_NAME, f"หน้า {page_no} เซิร์ฟเวอร์ KTB ตอบ HTTP 500 -> สลับใช้ Safe Item Fallback")
            return fetch_page_items_individually(page_no, session, page_limit=PAGE_LIMIT)
        r.raise_for_status()
        return []

    try:
        return execute_with_retry(_fetch, company_name=COMPANY_NAME, context_msg=f"หน้า {page_no}", max_retries=max_retries, max_cooldown_cycles=1)
    except Exception:
        log_warning(COMPANY_NAME, f"ข้ามหน้า {page_no} เนื่องจากเชื่อมต่อไม่สำเร็จครบหลังพักรอแล้ว")
        return None

def save_to_csv(records, filename):
    return atomic_write_csv(records, filename, COLUMNS, company_name=COMPANY_NAME)

def main():
    global start_time_global, progress_counter
    print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นการดึงข้อมูลประจำเดือน {MONTH_STR}", flush=True)
    init_gis()
    session = AuditedSession(company_name=COMPANY_NAME)
    adapter = requests.adapters.HTTPAdapter(pool_connections=15, pool_maxsize=15)
    session.mount('https://', adapter)
    session.mount('http://', adapter)

    healthy, code, total_items, total_pages = check_link_health(session)
    if not healthy:
        print_alert(f"ไม่สามารถเชื่อมต่อ KTB API ได้ (HTTP Status: {code})", level="CRITICAL")
        sys.exit(1)

    print(f"[{COMPANY_NAME}] 🌐 ตรวจสอบสถานะลิงก์ปลายทาง: HTTP {code} OK! พบทั้งหมด ~{total_items:,} รายการ ({total_pages:,} หน้า)", flush=True)

    records, seen_ids = load_existing_csv(OUTPUT_CSV)
    saved_state = load_scraper_state(COMPANY_NAME, MONTH_STR)
    prev_failed_pages = [int(p) for p in (saved_state.get("failed_pages") or []) if str(p).isdigit()]

    # 1. Fast-Forward check: only when CSV full and no pending failed pages
    if not prev_failed_pages and total_items > 0 and (len(records) >= total_items or saved_state.get("status") == "COMPLETED"):
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลใน CSV ครบถ้วน 100% แล้ว ({total_pages:5,d}/{total_pages:5,d} หน้า) | สะสม: {len(records):,d} รายการ -> สแครปเสร็จสมบูรณ์ทันที!", flush=True)
        save_to_csv(records, OUTPUT_CSV)
        save_scraper_state(COMPANY_NAME, total_pages, total_pages, len(records), status="COMPLETED", month_str=MONTH_STR)
        return pd.DataFrame(records)

    # 2. Smart Resume: Calculate completed pages
    items_per_p = total_items // total_pages if total_pages > 0 else 20
    saved_page = int(saved_state.get("completed_pages", 0) or 0)
    calc_pages = min(total_pages - 1, len(records) // items_per_p) if total_pages > 0 else 0
    completed_pages = max(saved_page, calc_pages)
    completed_pages = min(total_pages - 1, completed_pages) if total_pages > 0 else 0
    progress_counter = completed_pages
    start_page = completed_pages + 1

    saved_milestones = set()
    if completed_pages > 0:
        pct_start = int(progress_counter * 100 / total_pages) if total_pages > 0 else 0
        for target_pct in range(5, pct_start + 1, 5):
            saved_milestones.add(target_pct)
        saved_milestones.add("initial_page")
        print(f"[{COMPANY_NAME}] ⏩ Smart Fast-Forward: ข้ามหน้าที่เคยดึงแล้ว 1..{completed_pages:,} หน้า ({pct_start}%) -> กระโดดไปต่อหน้าที่ {start_page:,} ทันที!", flush=True)
        p_bar = make_progress_bar(pct_start, length=20)
        print(f"[{COMPANY_NAME:<13s}] {p_bar} | ({progress_counter:4d}/{total_pages:4d} หน้า) | สะสม: {len(records):>6,d}/{total_items:,d} รายการ", flush=True)

    start_time_global = time.time()
    today_str = datetime.now().strftime("%Y-%m-%d")

    failed_pages = []
    new_added = 0
    pages_to_run = sorted(set([p for p in prev_failed_pages if 1 <= p < start_page] + list(range(start_page, total_pages + 1))))

    for page_no in pages_to_run:
        items = fetch_page(page_no, session)
        if items is None:
            failed_pages.append(page_no)
            continue

        new_page_count = 0
        for item in items:
            p_id = str(item.get("collGrpId") or item.get("collCode") or "").strip()
            if not p_id or p_id in seen_ids:
                continue
            
            seen_ids.add(p_id)
            new_page_count += 1
            new_added += 1
            
            p_code = clean_text(item.get("collCode") or p_id)
            p_type = clean_text(item.get("collCateName") or item.get("assetTypeDetail") or item.get("collTypeName") or "")
            proj_name = clean_text(item.get("propertyName") or "")
            
            price_raw = str(item.get("price") or item.get("nmlPrice") or item.get("priceNumber") or "").replace(",", "").strip()
            try:
                price = float(price_raw) if price_raw else None
            except Exception:
                price = None
                
            sub_d = clean_text(item.get("shrTambonName") or "").replace("ตำบล", "").replace("แขวง", "").strip()
            dist = clean_text(item.get("shrAmphurName") or "").replace("อำเภอ", "").replace("เขต", "").strip()
            prov = clean_text(item.get("shrProvinceName") or "").replace("จังหวัด", "").strip()
            
            lat = None
            lng = None
            try:
                if item.get("lat"):
                    v1 = float(item["lat"])
                    if 5.0 <= v1 <= 21.0:
                        lat = v1
                if item.get("lon"):
                    v2 = float(item["lon"])
                    if 97.0 <= v2 <= 106.0:
                        lng = v2
            except Exception:
                pass
                
            link = clean_text(item.get("shareURL") or f"https://npa.krungthai.com/propertyDetail/{p_code or p_id}")
            
            # Title
            title = clean_text(item.get("collDesc") or "")
            if not title:
                title = f"{p_type} {proj_name} {dist} {prov}".strip()
                
            # Area
            area_str = item.get("area") or item.get("calSumAreaCollGrpId")
            land_area = parse_rai_ngan_wah(area_str)
            
            use_area = None
            try:
                if item.get("sumAreaNum"): use_area = float(item["sumAreaNum"])
            except Exception:
                pass
                
            bedroom = item.get("bedroomNum")
            bathroom = item.get("bathroomNum")
            publish_date = item.get("priceStrDt")

            floor_val = clean_floor_val(item.get("floorNum") or item.get("floor") or item.get("floors") or item.get("totalFloor") or item.get("floorTotal"))
            if not floor_val:
                floor_val = extract_floor_from_text(title, proj_name, item.get("collDesc") or "", asset_type=p_type)

            if proj_name and clean_project_name:
                proj_name = clean_project_name(proj_name, tambon=sub_d, amphoe=dist, province=prov, company=COMPANY_NAME)
            if not proj_name and title and extract_project_from_title:
                proj_name = extract_project_from_title(title, tambon=sub_d, amphoe=dist, province=prov, company=COMPANY_NAME)

            record = {
                "บริษัท": COMPANY_NAME,
                "ID": p_id,
                "รหัสทรัพย์": p_code,
                "ชื่อโครงการ": proj_name,
                "ประเภททรัพย์": p_type,
                "ประเภทการขาย": "ทรัพย์ธนาคาร",
                "ราคา": price,
                "ตำบล": sub_d,
                "อำเภอ": dist,
                "จังหวัด": prov,
                "ละติจูด": lat,
                "ลองจิจูด": lng,
                "ชื่อประกาศ": title,
                "ลิงก์": link,
                "เนื้อที่ (ตร.ว.)": convert_to_rai_ngan_wah(land_area),
                "พื้นที่ใช้สอย (ตร.ม.)": use_area,
                "วันที่ดึงข้อมูล": today_str,
                "ห้องนอน": bedroom if bedroom is not None and str(bedroom).isdigit() else None,
                "ห้องน้ำ": bathroom if bathroom is not None and str(bathroom).isdigit() else None,
                "ที่จอดรถ": None,
                "ชั้น": floor_val or "",
                "วันประกาศ": publish_date,
                "ยอดเข้าชม": int(item["productCountView"]) if item.get("productCountView") is not None and str(item.get("productCountView")).isdigit() else None
            }
            clean_row_location(record)
            records.append(record)

        progress_counter += 1
        pct = int(progress_counter * 100 / total_pages)
        elapsed = time.time() - start_time_global
        p_bar = make_progress_bar(pct, length=20)
        eta_str = format_eta(elapsed, progress_counter, total_pages, start_unit=start_page if 'start_page' in locals() else 1)
        
        status_line = (
            f"[{COMPANY_NAME:<13s}] {p_bar} | "
            f"({progress_counter:4d}/{total_pages:4d} หน้า) | "
            f"สะสม: {len(records):>6,d}/{total_items:,d} รายการ | {eta_str}"
        )
        print(status_line, flush=True)

        if new_page_count > 0:
            save_to_csv(records, OUTPUT_CSV)
            save_scraper_state(COMPANY_NAME, progress_counter, total_pages, len(records), status="RUNNING", month_str=MONTH_STR, extra={"failed_pages": failed_pages})

        if "initial_page" not in saved_milestones and len(records) > 0:
            saved_milestones.add("initial_page")
            save_scraper_state(COMPANY_NAME, progress_counter, total_pages, len(records), status="RUNNING", month_str=MONTH_STR, extra={"failed_pages": failed_pages})
            print(f"\n💾 [{COMPANY_NAME}] ครบหน้าแรก -> บันทึกไฟล์เริ่มต้นลง {OUTPUT_CSV}...", flush=True)
            log_milestone(COMPANY_NAME, f"💾 บันทึกเริ่มต้น (ครบหน้าแรก) {len(records):,} รายการลง " + os.path.basename(OUTPUT_CSV))

        for target_pct in range(5, 105, 5):
            if pct >= target_pct and target_pct not in saved_milestones:
                saved_milestones.add(target_pct)
                save_scraper_state(COMPANY_NAME, progress_counter, total_pages, len(records), status="RUNNING", month_str=MONTH_STR, extra={"failed_pages": failed_pages})
                print(f"\n💾 [{COMPANY_NAME}] ครบ Milestone {target_pct}% -> บันทึกสำรองลง {OUTPUT_CSV}...", flush=True)
                log_milestone(COMPANY_NAME, f"💾 บันทึก Milestone สำรอง {target_pct}% ({len(records):,} รายการ) ลง " + os.path.basename(OUTPUT_CSV))
                save_to_csv(records, OUTPUT_CSV)

        save_to_csv(records, OUTPUT_CSV)
    elapsed = time.time() - start_time_global
    if failed_pages:
        final_status = "FAILED" if len(records) == 0 else "PARTIAL"
        save_scraper_state(COMPANY_NAME, progress_counter, total_pages, len(records), status=final_status, month_str=MONTH_STR, extra={"failed_pages": failed_pages})
        print(f"\n==================================================", flush=True)
        print(f"⚠️ [{COMPANY_NAME}] สแครปเสร็จแบบมีหน้าล้มเหลว ({final_status}) | ({progress_counter:4d}/{total_pages:4d} หน้า) | สะสม: {len(records):,d} รายการ", flush=True)
        print(f"⚠️ รายการหน้าที่ข้าม/ดึงไม่ได้ ({len(failed_pages)} หน้า): {sorted(failed_pages)}", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที | 💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        log_warning(COMPANY_NAME, f"⚠️ สแครปเสร็จแบบ {final_status}: ดึงไม่ได้ {len(failed_pages)} หน้า")
        sys.exit(1 if len(records) == 0 else 2)
    else:
        save_scraper_state(COMPANY_NAME, progress_counter, total_pages, len(records), status="COMPLETED", month_str=MONTH_STR, extra={"failed_pages": []})
        print(f"\n==================================================", flush=True)
        print(f"✅ [{COMPANY_NAME}] สแครปเสร็จสมบูรณ์! | ({progress_counter:4d}/{total_pages:4d} หน้า) | สะสม: {len(records):,d} รายการ", flush=True)
        print(f"📊 ได้ข้อมูลทั้งหมด: {len(records):,} รายการ (เพิ่มใหม่ในรอบนี้: {new_added:,} รายการ)", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที", flush=True)
        print(f"💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        print(f"✅ ดึงข้อมูลได้ครบถ้วนสำเร็จ 100% (ไม่มีหน้าล้มเหลว)", flush=True)
        print(f"==================================================", flush=True)
        log_success(COMPANY_NAME, f"✅ สแครปเสร็จสมบูรณ์! ได้ข้อมูลทั้งหมดสะสมลง {os.path.basename(OUTPUT_CSV)}")

if __name__ == "__main__":
    main()
