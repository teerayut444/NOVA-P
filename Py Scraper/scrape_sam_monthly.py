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

from clean_location_util import clean_floor_val, extract_floor_from_text, clean_row_location, init_gis
try:
    from clean_project_util import clean_sam_project_name, extract_project_from_title
except ImportError:
    clean_sam_project_name = lambda x: x
    extract_project_from_title = lambda x, **kw: ""

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

COMPANY_NAME = "SAM"
MONTH_STR = datetime.now().strftime("%Y_%m")

_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR
OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"SAM_NPA_New_{MONTH_STR}.csv")

THREAD_POOL_SIZE = 1

COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคา",
    "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ"
]

print_lock = threading.Lock()
progress_counter = 0
start_time_global = None
failed_items = []

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
        print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นดึงข้อมูลใหม่ทั้งหมด (โหมด --fresh)", flush=True)
        reset_scraper_state(COMPANY_NAME, MONTH_STR)
        return [], set()
    return read_csv_resume(filename, COLUMNS, id_col="ID", company_name=COMPANY_NAME)

def check_link_health(session=None):
    url = "https://sam.or.th/site/npa/page_list.php"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    if session is None:
        session = AuditedSession(company_name=COMPANY_NAME)

    page_limit = 10000
    all_blogs = []
    first_code = 0
    page_num = 1
    while page_num <= 20:
        data = {"layout": "list", "limit": str(page_limit), "sort": "", "order": "", "page": str(page_num)}

        def _post_list():
            r = safe_ssl_post(session, url, headers=headers, data=data, timeout=100, ssl_fallback_on_gov=False)
            if r.status_code != 200:
                r.raise_for_status()
            return r

        try:
            r = execute_with_retry(_post_list, company_name=COMPANY_NAME, context_msg=f"SAM NPA List (page {page_num})", max_retries=4, max_cooldown_cycles=1)
        except Exception:
            if page_num == 1:
                return False, 0, 0, 0, []
            break

        if page_num == 1:
            first_code = r.status_code

        soup = BeautifulSoup(r.text, 'html.parser')
        blogs = soup.find_all(class_='full_blog')
        if not blogs:
            blogs = soup.find_all(class_=lambda c: c and 'blog' in c.lower())

        if page_num == 1:
            if not blogs:
                print_structure_alert(COMPANY_NAME, "ไม่พบ Element รายการทรัพย์ 'div.full_blog' ในหน้าค้นหา SAM (โครงสร้างเว็บเปลี่ยนแปลง)")
                return False, first_code, 0, 0, []

            valid_links = 0
            for b in blogs[:5]:
                a_tag = b.find('a', href=True)
                img_div = b.find(class_='card-img')
                onclick = img_div.get('onclick', '') if img_div else ''
                if (a_tag and a_tag['href']) or 'gotoDetail' in str(onclick):
                    valid_links += 1

            if valid_links == 0:
                print_structure_alert(COMPANY_NAME, "ไม่พบลิงก์ไปยังหน้ารายละเอียดทรัพย์ในการ์ดของ SAM (HTML Pattern เปลี่ยนแปลง)")
                return False, first_code, 0, 0, []

        if not blogs:
            break
        all_blogs.extend(blogs)
        if len(blogs) < page_limit:
            break
        page_num += 1
        time.sleep(get_scraper_delay())

    return True, first_code, len(all_blogs), page_num, all_blogs

def parse_property_detail(prop_id, html):
    soup = BeautifulSoup(html, 'html.parser')
    container = soup.find(class_='detail_sec01_detail') or soup.find(class_='detail_sec01') or soup
    container_text = re.sub(r'\s+', ' ', container.text).strip()
    
    code = ""
    m_code = re.search(r'รหัสทรัพย์สิน\s*:\s*([A-Za-z0-9\-_]+)', container_text)
    if m_code: code = m_code.group(1).strip()
    
    prop_type = ""
    m_type = re.search(r'ประเภททรัพย์สิน\s*:\s*([^:]+?)(?=\s*(?:เอกสารสิทธิ์|หนังสือ|จำนวน|เนื้อที่|ที่ตั้ง|ราคา|$))', container_text)
    if m_type:
        raw_ptype = m_type.group(1).strip()
        prop_type = re.sub(r'\s*ประเภท(?:เอกสารสิทธิ์)?.*$', '', raw_ptype).strip()
        
    price = None
    m_price = re.search(r'ราคาประกาศขาย\s*:\s*([\d,]+)', container_text)
    if m_price:
        price = float(m_price.group(1).replace(",", ""))
    else:
        btn_price = soup.find(class_='btn-price')
        if btn_price:
            m = re.search(r'([\d,]+)', btn_price.text)
            if m: price = float(m.group(1).replace(",", ""))
            
    sub_district, district, province, project_name = "", "", "", ""
    m_loc = re.search(r'ที่ตั้ง\s*:\s*(.*?)(?=\s*(?:เขตพื้นที่|ราคา|รายละเอียด|$))', container_text)
    loc_str = m_loc.group(1).strip() if m_loc else container_text
    
    m_sd = re.search(r'(?:ตำบล|ต\.|แขวง)\s*([^\s,]+)', loc_str)
    if m_sd: sub_district = m_sd.group(1).strip()
    
    m_d = re.search(r'(?:อำเภอ|อ\.|เขต)\s*([^\s,]+)', loc_str)
    if m_d: district = m_d.group(1).strip()
    
    m_p = re.search(r'(?:จังหวัด|จ\.)\s*([^\s,]+)', loc_str)
    if m_p: province = m_p.group(1).strip()
    
    m_proj = re.search(r'(?:หมู่บ้าน/โครงการ|โครงการ|หมู่บ้าน|อาคารชุด|คอนโด)\s*[:\s]*([^\n\r,]+?)(?=\s*(?:เลขที่|ถนน|ตำบล|แขวง|อำเภอ|เขต|จังหวัด|โซน|รายละเอียด|$))', loc_str)
    if m_proj:
        p_raw = m_proj.group(1).strip()
        p_clean = re.sub(r'^[/\s]+', '', p_raw).strip()
        if p_clean and p_clean.lower() not in ["none", "null", "-", "/", "โครงการ", "หมู่บ้าน/โครงการ", "หมู่บ้าน"]:
            p_std = clean_sam_project_name(p_clean)
            project_name = p_std if p_std else p_clean
    if not project_name and extract_project_from_title:
        project_name = extract_project_from_title(loc_str, tambon=sub_district, amphoe=district, province=province, company=COMPANY_NAME)
        
    lat, lng = None, None
    for pat in (
        r'google\.com/maps/(?:dir//|dir/|search/|@)?([\d\.-]+),([\d\.-]+)',
        r'maps\.google\.com/[^"\'<>\s]*[?&](?:q|ll|query)=([\d\.-]+),([\d\.-]+)',
        r'([\d]{1,2}\.[\d]{4,15})\s*,\s*([\d]{2,3}\.[\d]{4,15})'
    ):
        for m_map in re.finditer(pat, html, re.I):
            try:
                lat_val = float(m_map.group(1))
                lon_val = float(m_map.group(2))
                if 5.0 <= lat_val <= 21.0 and 97.0 <= lon_val <= 106.0:
                    lat, lng = lat_val, lon_val
                    break
            except Exception:
                pass
        if lat is not None and lng is not None:
            break
            
    # Compose clean, rich title
    loc_parts = [x for x in [sub_district, district, province] if x]
    loc_str_title = " ".join(loc_parts)
    
    if project_name:
        clean_title = f"{prop_type} {project_name} {loc_str_title}".strip()
    elif loc_str_title:
        clean_title = f"{prop_type} {loc_str_title}".strip()
    else:
        clean_title = f"{prop_type} SAM ({code or prop_id})".strip()
        
    if code and f"({code})" not in clean_title:
        clean_title = f"{clean_title} ({code})".strip()
    
    land_area = ""
    usable_area = ""
    
    m_area = re.search(r'(?:เนื้อที่|พื้นที่|ขนาดพื้นที่)\s*:\s*([^:]+?)(?=\s*(?:ห้องนอน|ห้องน้ำ|ที่ตั้ง|เขตพื้นที่|หน้ากว้าง|ราคา|$))', container_text)
    area_str = m_area.group(1).strip() if m_area else ""
    
    if re.search(r'ตร\.ม\.|ตารางเมตร', area_str):
        m_num = re.search(r'([\d\.,]+)\s*(?:ตร\.ม\.|ตารางเมตร)', area_str)
        if m_num:
            usable_area = m_num.group(1).replace(',', '').strip()
        else:
            usable_area = area_str
    elif area_str:
        # เก็บตามที่เว็บระบุโดยตรง เช่น "96.8 ตร.ว.", "1 งาน 12.0 ตร.ว.", "3 ไร่ 2 งาน 68.9 ตร.ว."
        clean_a = area_str.strip()
        clean_a = re.sub(r'(?<=\d|\s)(?:ตร\.วา|ตารางวา|วา)\b', 'ตร.ว.', clean_a)
        land_area = clean_a
            
    if not usable_area:
        m_u = re.search(r'พื้นที่ใช้สอย\s*:\s*([\d\.,]+)\s*(?:ตร\.ม\.|ตารางเมตร)?', container_text) or re.search(r'([\d\.,]+)\s*(?:ตร\.ม\.|ตารางเมตร)', container_text)
        if m_u:
            usable_area = m_u.group(1).replace(',', '').strip()
    
    full_text = re.sub(r'\s+', ' ', soup.text).strip()
    
    beds, baths, parking = None, None, None
    
    # 1. ห้องนอน (Bedrooms)
    bed_match = (
        re.search(r'ห้องนอน\s*[:\s]*(\d+)', container_text) or
        re.search(r'(\d+)\s*ห้องนอน', container_text) or
        re.search(r'ห้องนอน\s*[:\s]*(\d+)', full_text) or
        re.search(r'(\d+)\s*ห้องนอน', full_text)
    )
    if bed_match:
        try: beds = int(bed_match.group(1))
        except Exception: pass
        
    # 2. ห้องน้ำ (Bathrooms)
    bath_match = (
        re.search(r'ห้องน้ำ\s*[:\s]*(\d+)', container_text) or
        re.search(r'(\d+)\s*ห้องน้ำ', container_text) or
        re.search(r'ห้องน้ำ\s*[:\s]*(\d+)', full_text) or
        re.search(r'(\d+)\s*ห้องน้ำ', full_text)
    )
    if bath_match:
        try: baths = int(bath_match.group(1))
        except Exception: pass
        
    # 3. ที่จอดรถ (Parking)
    park_match = (
        re.search(r'(?:ที่จอดรถ|จอดรถ|โรงจอดรถ)\s*[:\s]*(\d+)', container_text) or
        re.search(r'(\d+)\s*(?:ที่จอดรถ|จอดรถ)', container_text) or
        re.search(r'(?:ที่จอดรถ|จอดรถ|โรงจอดรถ)\s*[:\s]*(\d+)', full_text) or
        re.search(r'จอดรถ(?:ได้)?\s*(\d+)\s*คัน', full_text) or
        re.search(r'ที่จอดรถ\s*(\d+)\s*คัน', full_text)
    )
    if park_match:
        try: parking = int(park_match.group(1))
        except Exception: pass
    
    m_post = re.search(
        r'(?:วันที่ประกาศ|วันที่สร้าง|ปีที่สร้าง|วันที่ปรับปรุง)\s*[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}|\d{1,2}\s+[ก-๙.]+\s+\d{4})',
        container_text
    )
    post_date = clean_text(m_post.group(1)) if m_post else ""
    
    # 4. ชั้น (Floor)
    floor = ""
    m_floor = re.search(r'ชั้นที่\s*[:\s]+([0-9A-Za-z]+)', container_text)
    if m_floor:
        floor = clean_floor_val(m_floor.group(1)) or ""
    else:
        floor = extract_floor_from_text(container_text, full_text, clean_title, asset_type=prop_type) or ""

    record = {
        "บริษัท": COMPANY_NAME,
        "รหัสทรัพย์": code,
        "ชื่อโครงการ": project_name,
        "ประเภททรัพย์": prop_type,
        "ราคา": price,
        "ตำบล": sub_district,
        "อำเภอ": district,
        "จังหวัด": province,
        "ละติจูด": lat,
        "ลองจิจูด": lng,
        "ชื่อประกาศ": clean_title,
        "เนื้อที่ (ตร.ว.)": convert_to_rai_ngan_wah(land_area),
        "พื้นที่ใช้สอย (ตร.ม.)": usable_area,
        "วันประกาศ": post_date,
        "ห้องนอน": beds,
        "ห้องน้ำ": baths,
        "ที่จอดรถ": parking,
        "ชั้น": floor or ""
    }
    clean_row_location(record)
    return record

def fetch_detail_worker(session, prop_item, total_count, results_list, saved_milestones, total_inventory=None):
    global progress_counter, start_time_global, failed_items
    url = prop_item["ลิงก์"]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    def _get_detail():
        time.sleep(get_scraper_delay()) # หน่วงเวลาอย่างน้อย 15 วินาที
        r = safe_ssl_get(session, url, headers=headers, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code != 200:
            r.raise_for_status()
        return r

    html = ""
    try:
        r = execute_with_retry(_get_detail, company_name=COMPANY_NAME, context_msg=f"รายละเอียด {prop_item['ID']}", max_retries=3, max_cooldown_cycles=1)
        html = r.content.decode('utf-8', errors='replace')
    except Exception:
        html = ""
            
    detail_data = None
    if html:
        try:
            details = parse_property_detail(prop_item["ID"], html)
            prop_item.update(details)
            # รอประกาศราคา = ยังไม่มีราคา → ล้างราคาที่ดึงมาจาก HTML (เป็นราคาเก่า/cached)
            sale_type = str(prop_item.get("ประเภทการขาย") or "").strip()
            if "รอประกาศราคา" in sale_type:
                prop_item["ราคา"] = None
            results_list.append(prop_item)
            detail_data = details
        except Exception as e:
            failed_items.append(prop_item["ID"])
    else:
        failed_items.append(prop_item["ID"])
            
    progress_counter += 1
    current = progress_counter
    pct = int((current / total_count) * 100)
    elapsed_sec = time.time() - start_time_global if start_time_global else 1.0
    eta_msg = format_eta(elapsed_sec, current, total_count)
    pbar = make_progress_bar(pct)
    
    tot_display = total_inventory if total_inventory else total_count
    print(f"[{COMPANY_NAME:<13s}] {pbar} | ({current:5,d}/{total_count:5,d} รายการ) | สะสม: {len(results_list):>6,d}/{tot_display:,d} รายการ | {eta_msg}", flush=True)
        
    if "initial_page" not in saved_milestones and len(results_list) > 0:
            saved_milestones.add("initial_page")
            save_scraper_state(COMPANY_NAME, current, total_count, len(results_list), status="RUNNING", month_str=MONTH_STR)
            print(f"\n💾 [{COMPANY_NAME}] ครบหน้าแรก -> บันทึกไฟล์เริ่มต้นลง {OUTPUT_CSV}...", flush=True)
            log_milestone(COMPANY_NAME, f"💾 บันทึกเริ่มต้น (ครบหน้าแรก) {len(results_list):,} รายการลง " + os.path.basename(OUTPUT_CSV))
            save_to_csv(results_list, OUTPUT_CSV)
    elif detail_data and len(results_list) % 50 == 0:
        save_to_csv(results_list, OUTPUT_CSV)
        save_scraper_state(COMPANY_NAME, current, total_count, len(results_list), status="RUNNING", month_str=MONTH_STR)

    for target_pct in range(5, 105, 5):
        if pct >= target_pct and target_pct not in saved_milestones:
            saved_milestones.add(target_pct)
            save_scraper_state(COMPANY_NAME, current, total_count, len(results_list), status="RUNNING", month_str=MONTH_STR)
            print(f"\n💾 [{COMPANY_NAME}] ครบ Milestone {target_pct}% -> บันทึกสำรองลง {OUTPUT_CSV}...", flush=True)
            log_milestone(COMPANY_NAME, f"💾 บันทึก Milestone สำรอง {target_pct}% ({len(results_list):,} รายการ) ลง " + os.path.basename(OUTPUT_CSV))
            save_to_csv(results_list, OUTPUT_CSV)

def save_to_csv(records, filename):
    return atomic_write_csv(records, filename, COLUMNS, company_name=COMPANY_NAME)

def main():
    global start_time_global
    print(f"==================================================", flush=True)
    print(f"🚀 เริ่มต้นการ Scrape [{COMPANY_NAME}] (Monthly Mode: ดึงข้อมูลแม่นยำ 100%)", flush=True)
    print(f"📁 บันทึกข้อมูลลงไฟล์: {OUTPUT_CSV}", flush=True)
    print(f"==================================================", flush=True)

    init_gis()
    session = AuditedSession(company_name=COMPANY_NAME)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

    is_ok, code, total_items, pages_count, blogs = check_link_health(session)
    if is_ok:
        status_msg = f"🌐 สถานะลิงก์: ปกติ (HTTP {code}) | ทั้งหมด {pages_count} API List | พบทั้งหมด {total_items:,} รายการ"
        print(f"[{COMPANY_NAME}] {status_msg}", flush=True)
    else:
        print_alert("ไม่สามารถดึงรายการทรัพย์สิน SAM ได้ (ระบบขัดข้อง)", level="CRITICAL")
        sys.exit(1)

    # โหลด/รีเซ็ตข้อมูลหลังจาก Health Check ผ่านแล้วเท่านั้น
    existing_records, seen_ids = load_existing_csv(OUTPUT_CSV)
        
    total_pages = (total_items + 19) // 20 if total_items > 0 else 247
    if total_items > 0 and len(existing_records) >= total_items:
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลใน CSV ครบถ้วน 100% แล้ว ({total_pages:5,d}/{total_pages:5,d} หน้า) | สะสม: {len(existing_records):>6,d}/{total_items:,d} รายการ -> สแครปเสร็จสมบูรณ์ทันที!", flush=True)
        save_to_csv(existing_records, OUTPUT_CSV)
        log_success(COMPANY_NAME, f"✅ ข้อมูลใน CSV ครบถ้วน 100% อยู่แล้ว ({len(existing_records):,} รายการ)")
        return
        
    scrape_date = datetime.now().strftime('%Y-%m-%d')
    base_properties = []
    
    for blog in blogs:
        img_div = blog.find(class_='card-img')
        onclick = img_div.get('onclick') if img_div else ""
        id_match = re.search(r'gotoDetail\((\d+)\)', str(onclick or ""))
        prop_id = id_match.group(1) if id_match else None
        if not prop_id:
            for a_tag in blog.find_all('a', href=True):
                m_href = re.search(r'(?:detail\.php\?[^"\']*?\bid=|gotoDetail\()(\d+)', a_tag['href'])
                if m_href:
                    prop_id = m_href.group(1)
                    break
        if not prop_id:
            m_any = re.search(r'(?:gotoDetail\(|\bdetail\.php\?[^"\']*?\bid=)(\d+)', str(blog))
            if m_any:
                prop_id = m_any.group(1)
        if not prop_id: continue
        
        iid_str = str(prop_id).strip()
        if iid_str in seen_ids:
            continue
            
        status_span = blog.find(class_=re.compile("icon_status"))
        sale_type = status_span.text.strip() if status_span else "ขาย"
        detail_link = f"https://sam.or.th/site/npa/detail.php?id={prop_id}&keyref="
        
        base_properties.append({
            "บริษัท": COMPANY_NAME,
            "ID": prop_id,
            "รหัสทรัพย์": "",
            "ชื่อโครงการ": "",
            "ประเภททรัพย์": "",
            "ประเภทการขาย": sale_type,
            "ราคา": None,
            "ตำบล": "",
            "อำเภอ": "",
            "จังหวัด": "",
            "ละติจูด": None,
            "ลองจิจูด": None,
            "ชื่อประกาศ": "",
            "ลิงก์": detail_link,
            "เนื้อที่ (ตร.ว.)": convert_to_rai_ngan_wah(""),
            "พื้นที่ใช้สอย (ตร.ม.)": "",
            "วันที่ดึงข้อมูล": scrape_date,
            "ห้องนอน": None,
            "ห้องน้ำ": None,
            "ที่จอดรถ": None,
            "ชั้น": "",
            "วันประกาศ": ""
        })
        
    base_properties.reverse()
    total_new_needed = len(base_properties)
    
    if total_new_needed == 0:
        print(f"[{COMPANY_NAME}] ✅ ข้อมูลทุกรายการถูกดึงครบถ้วนแล้วใน {OUTPUT_CSV} (ไม่มีรายการใหม่)", flush=True)
        return
        
    if len(existing_records) > 0 and total_new_needed > 0:
        pct_start = int((len(existing_records) / max(1, total_items)) * 100)
        print(f"[{COMPANY_NAME}] ⏩ Smart Fast-Forward: ข้าม {len(existing_records):,} รายการเดิม ({pct_start}%) -> ดึงเฉพาะรายการใหม่ {total_new_needed:,} รายการต่อทันที", flush=True)
    else:
        print(f"[{COMPANY_NAME}] กำลังสแครปรายละเอียดทรัพย์สินใหม่ {total_new_needed:,} รายการ...", flush=True)
    start_time_global = time.time()
    
    results_list = list(existing_records)
    saved_milestones = set()
    if len(existing_records) > 0 and total_items > 0:
        pct_start = int((len(existing_records) / total_items) * 100)
        for target_pct in range(5, pct_start + 1, 5):
            saved_milestones.add(target_pct)
        saved_milestones.add("initial_page")

    # Pure Single Session Sequential Mode (1 request at a time)
    for prop in base_properties:
        fetch_detail_worker(session, prop, total_new_needed, results_list, saved_milestones, total_items)
        
    print("", flush=True)
    save_to_csv(results_list, OUTPUT_CSV)
    elapsed = time.time() - start_time_global
    actual_new_added = max(0, len(results_list) - len(existing_records))
    if failed_items:
        final_status = "FAILED" if len(results_list) == 0 else "PARTIAL"
        save_scraper_state(COMPANY_NAME, max(0, total_new_needed - len(failed_items)), total_new_needed, len(results_list), status=final_status, month_str=MONTH_STR)
        print(f"\n==================================================", flush=True)
        print(f"⚠️ [{COMPANY_NAME}] สแครปเสร็จแบบมีรายการล้มเหลว ({final_status}) | สะสม: {len(results_list):>6,d}/{total_items:,d} รายการ", flush=True)
        print(f"⚠️ รายการรายละเอียดที่ข้าม/ดึงไม่ได้ ({len(failed_items)} รายการ): {sorted(failed_items)[:30]}", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที | 💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        log_warning(COMPANY_NAME, f"⚠️ สแครปเสร็จแบบ {final_status}: ดึงไม่ได้ {len(failed_items)} รายการ")
        sys.exit(1 if len(results_list) == 0 else 2)
    else:
        save_scraper_state(COMPANY_NAME, total_new_needed, total_new_needed, len(results_list), status="COMPLETED", month_str=MONTH_STR)
        print(f"\n==================================================", flush=True)
        print(f"✅ [{COMPANY_NAME}] สแครปเสร็จสมบูรณ์! | ({total_new_needed:5,d}/{total_new_needed:5,d} รายการ) | สะสม: {len(results_list):>6,d}/{total_items:,d} รายการ", flush=True)
        print(f"📊 ได้ข้อมูลทั้งหมด: {len(results_list):,} รายการ (เพิ่มใหม่รอบนี้: {actual_new_added:,} รายการ)", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที", flush=True)
        print(f"💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        print(f"✅ ดึงข้อมูลได้ครบถ้วนสำเร็จ 100% (ไม่มีรายการล้มเหลว)", flush=True)
        print(f"==================================================", flush=True)
        log_success(COMPANY_NAME, f"✅ สแครปเสร็จสมบูรณ์! ได้ข้อมูลทั้งหมดสะสม {len(results_list):,} รายการ")

if __name__ == "__main__":
    main()
