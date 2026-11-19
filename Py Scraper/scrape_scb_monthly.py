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

COMPANY_NAME = "SCB"
MONTH_STR = datetime.now().strftime("%Y_%m")

_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR
OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"SCB_NPA_New_{MONTH_STR}.csv")

PAGE_LIMIT = 50

COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคา",
    "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ"
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

def load_existing_csv(filename):
    if "--fresh" in sys.argv or "--force-restart" in sys.argv:
        print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นดึงข้อมูลใหม่ทั้งหมดจากหน้า 1 (โหมด --fresh)", flush=True)
        reset_scraper_state(COMPANY_NAME, MONTH_STR)
        return [], set()
    return read_csv_resume(filename, COLUMNS, id_col="ID", company_name=COMPANY_NAME)

def parse_address_fields(addr_detail, short_addr):
    sub_district, district, province, project_name = "", "", "", ""
    text = f"{addr_detail} {short_addr}".strip()

    # Project name (stop before address markers and reject address-only tokens like หมู่ 4 ตำบล...)
    m_proj = re.search(r'(?:โครงการ|หมู่บ้าน|คอนโด|อาคารชุด)\s*[:\s]*([^,\n]+)', text)
    if m_proj:
        cand = re.split(r'\s+(?:หมู่ที่|หมู่\s*\d|ต\.|ตำบล|แขวง|อ\.|อำเภอ|เขต|จ\.|จังหวัด|ถ\.|ถนน|ซ\.|ซอย|เลขที่)\b', m_proj.group(1))[0].strip(" :-")
        if cand and not re.match(r'^(?:หมู่(?:ที่)?\s*\d*|ซอย|ถนน|ต\.|ตำบล|แขวง|อ\.|อำเภอ|เขต|จ\.|จังหวัด|เลขที่|ตาม|\d+)$', cand):
            project_name = " ".join(cand.split()[:6])

    # Subdistrict
    m_sd = re.search(r'(?:ตำบล|แขวง|ต\.)\s*([^\s,]+)', text)
    if m_sd:
        sub_district = m_sd.group(1).strip()

    # District
    m_d = re.search(r'(?:อำเภอ|เขต|อ\.)\s*([^\s,]+)', text)
    if m_d:
        district = m_d.group(1).strip()

    # Province
    m_p = re.search(r'(?:จังหวัด|จ\.)\s*([^\s,]+)', text)
    if m_p:
        province = m_p.group(1).strip()
    elif short_addr and ',' in short_addr:
        parts = [p.strip() for p in short_addr.split(',')]
        if len(parts) >= 2:
            if not district: district = parts[0]
            if not province: province = parts[1]

    return sub_district, district, province, project_name

CHROME_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://asset.home.scb/project",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Connection": "keep-alive"
}

def init_browser_session(session):
    """เข้าหน้าเว็บโครงการจำลองการเปิดเบราว์เซอร์ เพื่อรับ Cookies และ Session เสมือนคนเปิด Chrome จริง"""
    try:
        landing_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
            "Upgrade-Insecure-Requests": "1"
        }
        safe_ssl_get(session, "https://asset.home.scb/project", headers=landing_headers, timeout=30, ssl_fallback_on_gov=False)
        time.sleep(random.uniform(1.2, 1.8))
    except Exception:
        pass

def check_link_health(session=None):
    if session is None:
        session = AuditedSession(company_name=COMPANY_NAME)
    init_browser_session(session)
    url = "https://asset.home.scb/api/project/cmd"
    headers = CHROME_HEADERS
    params = {
        "type": "project",
        "page": 1,
        "limit": PAGE_LIMIT,
        "sortBy": "all",
        "command": "get_project"
    }
    def _probe():
        r = safe_ssl_get(session, url, headers=headers, params=params, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code != 200:
            r.raise_for_status()
        return r

    try:
        r = execute_with_retry(_probe, company_name=COMPANY_NAME, context_msg="SCB Health Probe", max_retries=4, max_cooldown_cycles=1)
        data = r.json()
        if data.get('s') != 'y':
            print_structure_alert(COMPANY_NAME, "SCB NPA API ตอบกลับสถานะไม่สำเร็จ (s != 'y') โครงสร้าง API อาจเปลี่ยนแปลง")
            return False, r.status_code, 0, 0

        items = data.get('d') or data.get('data') or data.get('items') or []
        if not items:
            print_structure_alert(COMPANY_NAME, "ไม่พบข้อมูลรายการทรัพย์ในฟิลด์ 'd' ของ SCB API")
            return False, r.status_code, 0, 0

        try:
            total_items = int(data.get('total') or len(items))
        except (ValueError, TypeError):
            total_items = len(items)
        total_pages = (total_items + PAGE_LIMIT - 1) // PAGE_LIMIT if total_items > 0 else 1
        return True, r.status_code, total_items, total_pages
    except Exception:
        print_alert("ไม่สามารถเชื่อมต่อ SCB NPA API ได้ (Timeout / Connection Error)", level="CRITICAL")
        return False, 0, 0, 0

def fetch_page(page_no, session, max_retries=4):
    url = "https://asset.home.scb/api/project/cmd"
    headers = CHROME_HEADERS
    params = {
        "type": "project",
        "page": page_no,
        "limit": PAGE_LIMIT,
        "sortBy": "all",
        "command": "get_project"
    }
    def _fetch():
        time.sleep(get_scraper_delay())
        r = safe_ssl_get(session, url, headers=headers, params=params, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code != 200:
            r.raise_for_status()
        data = r.json()
        if data.get('s') != 'y':
            raise TimeoutError(f"SCB API status {data.get('s')} on page {page_no}")
        return data.get('d') or []

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
        print_alert(f"ไม่สามารถเชื่อมต่อ SCB API ได้ (HTTP Status: {code})", level="CRITICAL")
        sys.exit(1)

    print(f"[{COMPANY_NAME}] 🌐 ตรวจสอบสถานะลิงก์ปลายทาง: HTTP {code} OK! พบทั้งหมด ~{total_items:,} รายการ ({total_pages:,} หน้า)", flush=True)

    records, seen_ids = load_existing_csv(OUTPUT_CSV)
    saved_state = load_scraper_state(COMPANY_NAME, MONTH_STR)
    prev_failed_pages = [int(p) for p in (saved_state.get("failed_pages") or []) if str(p).isdigit()]

    # 1. Fast-Forward check: only when CSV full and no outstanding failed pages
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
            p_id = str(item.get("project_id") or "").strip()
            if not p_id or p_id in seen_ids:
                continue
            
            seen_ids.add(p_id)
            new_page_count += 1
            new_added += 1
            
            p_code = clean_text(item.get("project_id_gen") or p_id)
            p_title = clean_text(item.get("project_title") or "")
            p_type = clean_text(item.get("project_type_name") or "")
            
            price_raw = str(item.get("price") or "").replace(",", "").strip()
            try:
                price = float(price_raw) if price_raw else None
            except Exception:
                price = None
                
            addr_detail = clean_text(item.get("project_address_detail") or "")
            short_addr = clean_text(item.get("project_address") or "")
            sub_d, dist, prov, proj_n = parse_address_fields(addr_detail, short_addr)
            
            lat = None
            lng = None
            try:
                if item.get("latitude"):
                    v1 = float(item["latitude"])
                    if 5.0 <= v1 <= 21.0:
                        lat = v1
                if item.get("longitude"):
                    v2 = float(item["longitude"])
                    if 97.0 <= v2 <= 106.0:
                        lng = v2
            except Exception:
                pass
                
            slug = item.get("slug")
            link = f"https://asset.home.scb/project/{slug}" if slug else f"https://asset.home.scb/project/{p_id}"
            
            land_area = None
            raw_land = item.get("land_area")
            if raw_land is not None and str(raw_land).strip() not in ["", "None", "null", "nan"]:
                try:
                    land_area = float(str(raw_land).replace(",", "").strip())
                except (ValueError, TypeError):
                    land_area = str(raw_land).strip()

            use_area = None
            try:
                if item.get("area_use") is not None and str(item.get("area_use")).strip() not in ["", "None", "null", "nan"]:
                    use_area = float(str(item["area_use"]).replace(",", "").strip())
            except Exception:
                pass
                
            publish_date = None
            if item.get("create_date"):
                publish_date = str(item["create_date"])[:10]

            floor_val = clean_floor_val(item.get("floor") or item.get("floors") or item.get("total_floor") or item.get("number_of_floors") or item.get("story"))
            if not floor_val:
                floor_val = extract_floor_from_text(p_title, proj_n, addr_detail, asset_type=p_type)

            if proj_n and clean_project_name:
                proj_n = clean_project_name(proj_n, tambon=sub_d, amphoe=dist, province=prov, company=COMPANY_NAME)
            if not proj_n and p_title and extract_project_from_title:
                proj_n = extract_project_from_title(p_title, tambon=sub_d, amphoe=dist, province=prov, company=COMPANY_NAME)

            record = {
                "บริษัท": COMPANY_NAME,
                "ID": p_id,
                "รหัสทรัพย์": p_code,
                "ชื่อโครงการ": proj_n,
                "ประเภททรัพย์": p_type,
                "ประเภทการขาย": "ทรัพย์ธนาคาร",
                "ราคา": price,
                "ตำบล": sub_d,
                "อำเภอ": dist,
                "จังหวัด": prov,
                "ละติจูด": lat,
                "ลองจิจูด": lng,
                "ชื่อประกาศ": p_title,
                "ลิงก์": link,
                "เนื้อที่ (ตร.ว.)": convert_to_rai_ngan_wah(land_area),
                "พื้นที่ใช้สอย (ตร.ม.)": use_area,
                "วันที่ดึงข้อมูล": today_str,
                "ห้องนอน": None,
                "ห้องน้ำ": None,
                "ที่จอดรถ": None,
                "ชั้น": floor_val or "",
                "วันประกาศ": publish_date
            }
            clean_row_location(record)
            records.append(record)

        if not failed_pages:
            progress_counter = max(progress_counter, page_no)
        pct = int(progress_counter * 100 / total_pages) if total_pages > 0 else 0
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
