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
    read_csv_resume,
    atomic_write_csv,
    print_structure_alert,
)
from timeout_handler import wait_1hr_on_timeout, handle_timeout_retry, execute_with_retry
from curl_cffi import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import os
import time
from time_window_util import get_scraper_delay, get_scraper_delay_range
import random
from datetime import datetime
import concurrent.futures
import threading
import sys
from clean_location_util import clean_row_location, reverse_geocode_location, init_gis, clean_floor_val, extract_floor_from_text
try:
    from clean_project_util import clean_project_name, extract_project_from_title
except ImportError:
    clean_project_name = lambda x, **kwargs: str(x).strip()
    extract_project_from_title = lambda x, **kwargs: ""

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

COMPANY_NAME = "GHB"
MONTH_STR = datetime.now().strftime("%Y_%m")

_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR
OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"GHB_NPA_New_{MONTH_STR}.csv")

PAGE_WORKERS = 1
DETAIL_WORKERS = 1

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

def check_link_health(session):
    url = "https://www.ghbhomecenter.com/property-for-sale"
    def _probe():
        r = safe_ssl_get(session, url, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code != 200:
            r.raise_for_status()
        return r

    try:
        r = execute_with_retry(_probe, company_name=COMPANY_NAME, context_msg="GHB Health Probe", max_retries=4, max_cooldown_cycles=1)
        soup = BeautifulSoup(r.text, 'html.parser')
        cards = soup.find_all('div', class_='card d-block')
        if not cards:
            cards = soup.find_all('a', href=re.compile(r'/property-\d+'))

        if not cards:
            print_structure_alert(COMPANY_NAME, "ไม่พบการ์ดรายการทรัพย์ 'div.card.d-block' หรือลิงก์ '/property-ID' บนเว็บ GHB (โครงสร้างเว็บเปลี่ยนแปลง)")
            return False, r.status_code, 0, 0

        page_links = [a.get_text().strip() for a in soup.find_all('a', class_='page-link')]
        p_nums = [int(p) for p in page_links if p.isdigit()]
        total_pages = max(p_nums) if p_nums else 0
        total_items = total_pages * 20

        m_items = re.search(r'ค้นพบทรัพย์\s*([\d,]+)\s*รายการ', r.text)
        if m_items:
            total_items = int(m_items.group(1).replace(",", ""))
            total_pages = (total_items + 19) // 20

        if total_pages <= 0:
            print_structure_alert(COMPANY_NAME, "ไม่พบจำนวนหน้า/รายการทรัพย์ทั้งหมดบนเว็บ GHB")
            return False, r.status_code, 0, 0

        return True, r.status_code, total_items, total_pages
    except Exception:
        print_alert("ไม่สามารถเชื่อมต่อเว็บ GHB ได้ (Timeout / Connection Error)", level="CRITICAL")
        return False, 0, 0, 0

def fetch_detail_coords(session, item):
    pid = item.get("ID")
    if not pid:
        clean_row_location(item)
        return item
    url = f"https://www.ghbhomecenter.com/property-{pid}"
    for attempt in range(3):
        try:
            time.sleep(get_scraper_delay()) # หน่วงเวลาอย่างน้อย 15 วินาที
            resp = safe_ssl_get(session, url, timeout=100, ssl_fallback_on_gov=False)
            if resp.status_code == 200:
                html = resp.text
                lat, lng = None, None
                
                # 1. พิกัดจริงจากตัวแปร JavaScript (geoLat, geoLong)
                m_lat = re.search(r'(?:var\s+)?geoLat\s*=\s*["\']?([0-9\.\-]+)["\']?', html)
                m_lng = re.search(r'(?:var\s+)?geoLong\s*=\s*["\']?([0-9\.\-]+)["\']?', html)
                if m_lat and m_lng:
                    try:
                        v1 = float(m_lat.group(1))
                        v2 = float(m_lng.group(1))
                        if 5.0 <= v1 <= 21.0 and 97.0 <= v2 <= 106.0:
                            lat, lng = v1, v2
                    except Exception: pass
                
                # 2. พิกัดจริงจาก Google Maps Embed / Query / Directions
                if not lat or not lng:
                    m_gmaps = (
                        re.search(r'(?:maps\.google\.com|google\.com/maps)[^"\']*(?:[?&]q|[?&]daddr|[?&]center|[?&]ll)=([0-9\.\-]+)[,%2C]+([0-9\.\-]+)', html)
                        or re.search(r'daddr=([0-9\.\-]+)[,%2C]+([0-9\.\-]+)', html)
                        or re.search(r'(?:destination|center_lat_lng|map_center)\s*=\s*["\']?([0-9\.\-]+)[,%2C\s]+([0-9\.\-]+)["\']?', html)
                        or re.search(r'latitude["\']?\s*[:=]\s*["\']?([0-9\.\-]+)["\']?.*?[,]?\s*longitude["\']?\s*[:=]\s*["\']?([0-9\.\-]+)["\']?', html, re.I)
                    )
                    if m_gmaps:
                        try:
                            v1 = float(m_gmaps.group(1))
                            v2 = float(m_gmaps.group(2))
                            if 5.0 <= v1 <= 21.0 and 97.0 <= v2 <= 106.0:
                                lat, lng = v1, v2
                        except Exception: pass
                
                # 3. พิกัดจริงจาก Hidden Input Tags (lat2_{pid} / long2_{pid})
                if not lat or not lng:
                    m_inp_lat = re.search(r'id=["\'](?:lat2_|lat_)' + str(pid) + r'["\'][^>]*value=["\']([0-9\.\-]+)["\']', html)
                    m_inp_lng = re.search(r'id=["\'](?:long2_|long_)' + str(pid) + r'["\'][^>]*value=["\']([0-9\.\-]+)["\']', html)
                    if m_inp_lat and m_inp_lng:
                        try:
                            v1 = float(m_inp_lat.group(1))
                            v2 = float(m_inp_lng.group(1))
                            if 5.0 <= v1 <= 21.0 and 97.0 <= v2 <= 106.0:
                                lat, lng = v1, v2
                        except Exception: pass

                # เมื่อได้พิกัดจริง -> บันทึกลงแถวข้อมูล และ Reverse Geocode ตำบล/อำเภอ
                if lat and lng:
                    item["ละติจูด"] = lat
                    item["ลองจิจูด"] = lng
                    try:
                        sd_gis, d_gis, p_gis = reverse_geocode_location(lat, lng)
                        if sd_gis and not item.get("ตำบล"): item["ตำบล"] = sd_gis
                        if d_gis and not item.get("อำเภอ"): item["อำเภอ"] = d_gis
                        if p_gis and not item.get("จังหวัด"): item["จังหวัด"] = p_gis
                    except Exception:
                        pass
                
                # สกัดห้องนอน / ห้องน้ำ / ที่จอดรถ / ชั้น จากหน้าประกาศ
                m_bed = re.search(r'(\d+)\s*ห้องนอน', html)
                if m_bed:
                    try: item["ห้องนอน"] = int(m_bed.group(1))
                    except Exception: pass
                m_bath = re.search(r'(\d+)\s*ห้องน้ำ', html)
                if m_bath:
                    try: item["ห้องน้ำ"] = int(m_bath.group(1))
                    except Exception: pass
                m_park = re.search(r'(\d+)\s*(?:ที่)?จอดรถ', html)
                if m_park:
                    try: item["ที่จอดรถ"] = int(m_park.group(1))
                    except Exception: pass
                floor_val = extract_floor_from_text(html, item.get("ชื่อประกาศ", ""), asset_type=item.get("ประเภททรัพย์", ""))
                if floor_val:
                    item["ชั้น"] = floor_val
                break
            elif resp.status_code == 423:
                time.sleep(1.0)
        except Exception:
            time.sleep(1.0)
    
    # 4. GIS Centroid Fallback: หากรายการใดไม่มีพิกัดจริงบนเว็บ clean_row_location จะคำนวณจุด Centroid ให้โดยอัตโนมัติ
    clean_row_location(item)
    return item

def fetch_page_items(session, page_no, today_str, seen_ids=None):
    url = f"https://www.ghbhomecenter.com/property-for-sale?pg={page_no}"

    def _fetch_html():
        time.sleep(get_scraper_delay()) # หน่วงเวลาอย่างน้อย 15 วินาทีต่อหน้า
        r = safe_ssl_get(session, url, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code != 200:
            r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        cards = soup.find_all('div', class_='card d-block')
        if not cards:
            raise TimeoutError(f"ไม่พบการ์ดในหน้า {page_no}")
        return cards

    try:
        cards = execute_with_retry(_fetch_html, company_name=COMPANY_NAME, context_msg=f"หน้า {page_no}", max_retries=4, max_cooldown_cycles=1)
    except Exception:
        log_warning(COMPANY_NAME, f"ข้ามหน้า {page_no} เนื่องจากเชื่อมต่อไม่สำเร็จครบหลังพักรอแล้ว")
        return None

    page_records = []
    for c in cards:
        a_link = c.find('a', href=re.compile(r'/property-\d+'))
        link = a_link.get('href') if a_link else ""
        if link and not link.startswith('http'):
            link = f"https://www.ghbhomecenter.com{link}"
        m_id = re.search(r'/property-(\d+)', link)
        p_id = m_id.group(1) if m_id else ""
        if not p_id:
            continue

        price = None
        price_div = c.find(class_='text-propertyprice')
        if price_div:
            m_p = re.search(r'([\d,]+)', price_div.text)
            if m_p:
                try: price = float(m_p.group(1).replace(",", ""))
                except Exception: pass

        header_div = c.find(class_='text-header-titletype')
        title_raw = clean_text(header_div.get_text()) if header_div else ""

        p_type = ""
        proj_name = ""
        m_pt = re.search(r'ขาย\s*([^\(\s]+)', title_raw)
        if m_pt: p_type = clean_text(m_pt.group(1))
        m_proj = re.search(r'\((.*?)\)', title_raw)
        if m_proj: proj_name = clean_text(m_proj.group(1))

        sub_d, dist, prov = "", "", ""
        loc_div = c.find(class_='text-location')
        if loc_div:
            loc_text = clean_text(loc_div.get_text())
            parts = [p.strip() for p in loc_text.split(',') if p.strip()]
            if len(parts) == 3:
                sub_d, dist, prov = parts[0], parts[1], parts[2]
            elif len(parts) == 2:
                dist, prov = parts[0], parts[1]
            elif len(parts) == 1:
                prov = parts[0]

        # Clean and validate project name (filter out "(แปลงมุม)", "(ชั้น 4)", etc.)
        if proj_name and clean_project_name:
            proj_name = clean_project_name(proj_name, tambon=sub_d, amphoe=dist, province=prov, company=COMPANY_NAME)
        if not proj_name and title_raw and extract_project_from_title:
            proj_name = extract_project_from_title(title_raw, tambon=sub_d, amphoe=dist, province=prov, company=COMPANY_NAME)

        land_area, use_area = None, None
        area_div = c.find(class_='text-area')
        if area_div:
            area_text = area_div.get_text()
            m_sqm = re.search(r'([\d\.,]+)\s*(?:ตร\.ม\.|ตารางเมตร)', area_text)
            if m_sqm:
                try: use_area = float(m_sqm.group(1).replace(",", ""))
                except Exception: pass
            m_sqw = re.search(r'([\d\.,]+)\s*(?:ตร\.ว\.|ตารางวา)', area_text)
            if m_sqw:
                land_area = m_sqw.group(1).replace(",", "")
            elif any(u in area_text for u in ['ไร่', 'งาน', 'วา']):
                land_area = area_text

        code = p_id
        card_text = c.get_text()
        m_code = re.search(r'รหัสทรัพย์\s*[:\s]*(\d+)', card_text)
        if m_code: code = m_code.group(1).strip()

        tag_div = c.find(class_='card-tag')
        sale_type = clean_text(tag_div.get_text()) if tag_div else "ทรัพย์ธนาคาร"
        if not sale_type:
            sale_type = "ทรัพย์ธนาคาร"

        record = {
            "บริษัท": COMPANY_NAME,
            "ID": p_id,
            "รหัสทรัพย์": code,
            "ชื่อโครงการ": proj_name,
            "ประเภททรัพย์": p_type,
            "ประเภทการขาย": sale_type,
            "ราคา": price,
            "ตำบล": sub_d,
            "อำเภอ": dist,
            "จังหวัด": prov,
            "ละติจูด": None,
            "ลองจิจูด": None,
            "ชื่อประกาศ": title_raw,
            "ลิงก์": link,
            "เนื้อที่ (ตร.ว.)": convert_to_rai_ngan_wah(land_area),
            "พื้นที่ใช้สอย (ตร.ม.)": use_area,
            "วันที่ดึงข้อมูล": today_str,
            "ห้องนอน": None,
            "ห้องน้ำ": None,
            "ที่จอดรถ": None,
            "ชั้น": "",
            "วันประกาศ": None
        }
        page_records.append(record)

    # Enrich รายการด้วยพิกัดจริงและรายละเอียดจากหน้าเว็บแบบทีละรายการ (Sequential Detail Fetching)
    if page_records:
        enriched_records = []
        for r in page_records:
            iid = r.get("ID")
            if seen_ids and iid and iid in seen_ids:
                enriched_records.append(r)
                continue
            try:
                enriched_records.append(fetch_detail_coords(session, r))
            except Exception:
                clean_row_location(r)
                enriched_records.append(r)
        return enriched_records
    return page_records

def save_to_csv(records, filename):
    return atomic_write_csv(records, filename, COLUMNS, company_name=COMPANY_NAME)

def load_existing_csv(filename):
    if "--fresh" in sys.argv or "--force-restart" in sys.argv:
        print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นดึงข้อมูลใหม่ทั้งหมดจากหน้า 1 (โหมด --fresh)", flush=True)
        reset_scraper_state(COMPANY_NAME, MONTH_STR)
        return [], set()
    return read_csv_resume(filename, COLUMNS, id_col="ID", company_name=COMPANY_NAME)

def main():
    global progress_counter, start_time_global
    print(f"==================================================", flush=True)
    print(f"🚀 เริ่มต้นการ Scrape [{COMPANY_NAME}] (Fast Monthly Mode + Offline GIS)", flush=True)
    print(f"📁 บันทึกข้อมูลลงไฟล์: {OUTPUT_CSV}", flush=True)
    print(f"==================================================", flush=True)
    
    init_gis()
    session = AuditedCurlSession(company_name=COMPANY_NAME, impersonate="chrome120")
    
    healthy, code, total_items, total_pages = check_link_health(session)
    if not healthy:
        print_alert(f"ไม่สามารถเชื่อมต่อ GHB Web ได้ (HTTP Status: {code})", level="CRITICAL")
        sys.exit(1)

    print(f"[{COMPANY_NAME}] 🌐 ตรวจสอบสถานะลิงก์ปลายทาง: HTTP {code} OK! พบทั้งหมด ~{total_items:,} รายการ ({total_pages:,} หน้า)", flush=True)

    records, seen_ids = load_existing_csv(OUTPUT_CSV)

    # 1. Coordinates Enrichment check: apply fast offline GIS for existing records missing coordinates
    missing_coords = [r for r in records if not r.get("ละติจูด") or pd.isna(r.get("ละติจูด")) or str(r.get("ละติจูด")).strip() in ["", "nan", "None", "0.0", "0"]]
    if missing_coords:
        print(f"[{COMPANY_NAME}] 📍 ทำความสะอาดและจับคู่พิกัด GIS ออฟไลน์สำหรับ {len(missing_coords):,} รายการ...", flush=True)
        for r in missing_coords:
            clean_row_location(r)
        save_to_csv(records, OUTPUT_CSV)
        print(f"[{COMPANY_NAME}] ✅ บันทึกพิกัดและข้อมูลครบถ้วนแล้ว {len(records):,} รายการ!", flush=True)

    saved_state = load_scraper_state(COMPANY_NAME, MONTH_STR)
    prev_failed_pages = [int(p) for p in (saved_state.get("failed_pages") or []) if str(p).isdigit()]

    # 2. Fast-Forward check: only when CSV full and no pending failed pages
    if not prev_failed_pages and total_items > 0 and (len(records) >= total_items or saved_state.get("status") == "COMPLETED"):
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลใน CSV ครบถ้วน 100% แล้ว ({total_pages:5,d}/{total_pages:5,d} หน้า) | สะสม: {len(records):,d} รายการ -> สแครปเสร็จสมบูรณ์ทันที!", flush=True)
        save_to_csv(records, OUTPUT_CSV)
        save_scraper_state(COMPANY_NAME, total_pages, total_pages, len(records), status="COMPLETED", month_str=MONTH_STR)
        log_success(COMPANY_NAME, f"✅ ข้อมูลใน CSV ครบถ้วน 100% อยู่แล้ว ({len(records):,} รายการ)")
        return pd.DataFrame(records)

    # 3. Smart Resume: Calculate completed pages
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

    # Pure Single Session Sequential Fetching (1 page at a time)
    for p_no in pages_to_run:
        raw_items = fetch_page_items(session, p_no, today_str, seen_ids=seen_ids)
        page_added = 0
        if raw_items is not None:
            for item in raw_items:
                iid = item.get("ID")
                if iid and iid not in seen_ids:
                    seen_ids.add(iid)
                    records.append(item)
                    page_added += 1
                    new_added += 1
            if not failed_pages:
                progress_counter = max(progress_counter, p_no)
        else:
            failed_pages.append(p_no)

        pct = int(progress_counter * 100 / total_pages) if total_pages > 0 else 0
        elapsed = time.time() - start_time_global
        p_bar = make_progress_bar(pct, length=20)
        eta_str = format_eta(elapsed, max(1, progress_counter - completed_pages), max(1, total_pages - completed_pages), 1)

        status_line = (
            f"[{COMPANY_NAME:<13s}] {p_bar} | "
            f"({progress_counter:4d}/{total_pages:4d} หน้า) | "
            f"สะสม: {len(records):>6,d}/{total_items:,d} รายการ | {eta_str}"
        )
        print(f"{status_line}", flush=True)

        if page_added > 0:
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
