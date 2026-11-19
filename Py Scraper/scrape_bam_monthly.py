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
import json
import re
import os
import sys
import time
from time_window_util import get_scraper_delay, get_scraper_delay_range
import math
import random
from datetime import datetime
import pandas as pd
from bs4 import BeautifulSoup
import concurrent.futures

from clean_location_util import clean_floor_val, extract_floor_from_text, clean_row_location, init_gis
try:
    from clean_project_util import clean_bam_project_name, extract_project_from_title
except ImportError:
    clean_bam_project_name = lambda x, **kw: x
    extract_project_from_title = lambda x, **kw: ""

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

COMPANY_NAME = "BAM"
MONTH_STR = datetime.now().strftime("%Y_%m")

_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR
OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"BAM_NPA_New_{MONTH_STR}.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.bam.co.th/th/npa/property/search"
}

COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคา",
    "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ"
]

ITEMS_PER_PAGE = 24

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
    if not val or str(val).strip().lower() in ["none", "null", "$undefined", "undefined"]:
        return ""
    cleaned = re.sub(r"\s+", " ", str(val)).strip()
    return "" if cleaned.lower() in ["none", "null", "$undefined", "undefined"] else cleaned

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

def clean_num(val):
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in ["none", "null", "$undefined", "undefined", ""]:
        return None
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None

def _clean_val(val):
    if val is None or str(val).strip().startswith('$undefined') or str(val).strip() == "":
        return None
    return str(val).strip()

def format_land_area(item):
    land_obj = item.get("landArea")
    parts = []
    if isinstance(land_obj, dict):
        rai = _clean_val(land_obj.get("rai"))
        ngan = _clean_val(land_obj.get("ngan"))
        wa = _clean_val(land_obj.get("sqWa") or land_obj.get("wa"))
        if rai and rai != "0": parts.append(f"{rai} ไร่")
        if ngan and ngan != "0": parts.append(f"{ngan} งาน")
        if wa and wa != "0": parts.append(f"{wa} ตร.ว.")
    
    if not parts:
        rai = _clean_val(item.get("landRai") or item.get("rai"))
        ngan = _clean_val(item.get("landNgan") or item.get("ngan"))
        wa = _clean_val(item.get("landWa") or item.get("wa"))
        if rai and rai != "0": parts.append(f"{rai} ไร่")
        if ngan and ngan != "0": parts.append(f"{ngan} งาน")
        if wa and wa != "0": parts.append(f"{wa} ตร.ว.")
        
    return " ".join(parts)

def format_usable_area(item):
    b_area = item.get("buildingArea") or item.get("usableArea")
    val = _clean_val(b_area)
    if val and val != "0":
        return val
    return ""

def load_existing_csv(filename):
    if "--fresh" in sys.argv or "--force-restart" in sys.argv:
        print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นดึงข้อมูลใหม่ทั้งหมดจากหน้า 1 (โหมด --fresh)", flush=True)
        reset_scraper_state(COMPANY_NAME, MONTH_STR)
        return [], set()
    return read_csv_resume(filename, COLUMNS, id_col="ID", company_name=COMPANY_NAME)

def check_link_health(session):
    url = "https://www.bam.co.th/th/npa/property/search?page=1"
    def _probe():
        r = safe_ssl_get(session, url, headers=HEADERS, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code != 200:
            r.raise_for_status()
        return r

    try:
        r = execute_with_retry(_probe, company_name=COMPANY_NAME, context_msg="BAM Health Probe", max_retries=4, max_cooldown_cycles=1)
        html = r.text
        has_props = ('"properties":' in html) or (r'\"properties\":' in html)
        m_tot = re.search(r'\\?"totalCount\\?"\s*:\s*(\d+)', html) or re.search(r'["\']?totalCount["\']?\s*[:=]\s*(\d+)', html, re.I)
        m_pages = re.search(r'\\?"totalPages\\?"\s*:\s*(\d+)', html) or re.search(r'["\']?totalPages["\']?\s*[:=]\s*(\d+)', html, re.I)

        if not has_props and not m_tot and not m_pages:
            print_structure_alert(COMPANY_NAME, "ไม่พบ Array 'properties' หรือตัวแปร 'totalCount' ในหน้าค้นหา (โครงสร้างเว็บ BAM เปลี่ยนแปลง)")
            return False, r.status_code, 0, 0

        if m_tot:
            tot_count = int(m_tot.group(1))
        elif m_pages:
            tot_count = int(m_pages.group(1)) * ITEMS_PER_PAGE
        else:
            print_structure_alert(COMPANY_NAME, "ไม่พบค่า totalCount / totalPages ในหน้าค้นหา BAM")
            return False, r.status_code, 0, 0

        tot_pages = int(m_pages.group(1)) if m_pages else max(1, math.ceil(tot_count / ITEMS_PER_PAGE))
        return True, r.status_code, tot_count, tot_pages
    except Exception:
        print_alert(f"ไม่สามารถเชื่อมต่อหน้าค้นหา BAM ได้ (Timeout / Connection Error)", level="CRITICAL")
        return False, 0, 0, 0

def fetch_item_detail(session, item_id, ptype=""):
    if not item_id: return "", "", "", None, None, None, ""
    time.sleep(get_scraper_delay()) # หน่วงเวลาอย่างน้อย 15 วินาที
    url = f"https://www.bam.co.th/th/npa/property/{item_id}"
    subdist, dist, prov, lat, lng, price, floor = "", "", "", None, None, None, ""
    for attempt in range(4):
        try:
            r = safe_ssl_get(session, url, headers=HEADERS, timeout=100, ssl_fallback_on_gov=False)
            if r.status_code == 200:
                html = r.text
                soup = BeautifulSoup(html, 'html.parser')
                meta_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
                desc_str = meta_desc.get("content", "") if meta_desc else ""
                
                if desc_str and "|" in desc_str:
                    parts = [p.strip() for p in desc_str.split("|")]
                    if len(parts) >= 2:
                        loc_part = parts[1]
                        if "," in loc_part:
                            loc_tokens = [t.strip() for t in loc_part.split(",")]
                            if len(loc_tokens) >= 3:
                                subdist = loc_tokens[0]
                                dist = loc_tokens[1]
                                prov = loc_tokens[2]
                            elif len(loc_tokens) == 2:
                                dist = loc_tokens[0]
                                prov = loc_tokens[1]
                                
                for sc in soup.find_all('script', type='application/ld+json'):
                    if not sc.string: continue
                    try:
                        data = json.loads(sc.string)
                        if isinstance(data, dict):
                            offers = data.get('offers')
                            if isinstance(offers, dict) and 'price' in offers:
                                p_val = float(offers['price'])
                                if p_val > 0:
                                    price = p_val
                                    break
                    except Exception: pass

                m_lat = re.search(r'["\']?latitude["\']?\s*:\s*([\d\.-]+)', html, re.I)
                m_lng = re.search(r'["\']?longitude["\']?\s*:\s*([\d\.-]+)', html, re.I)
                if m_lat and m_lng:
                    try:
                        v1 = float(m_lat.group(1))
                        v2 = float(m_lng.group(1))
                        if 5.0 <= v1 <= 21.0 and 97.0 <= v2 <= 106.0:
                            lat, lng = v1, v2
                    except Exception: pass
                if not lat or not lng:
                    m_map = re.search(r'(?:maps\.google\.com|google\.com/maps)[^"\']*[?&](?:q|ll|query)=([\d\.-]+),([\d\.-]+)', html) or re.search(r'q=([\d\.-]+),([\d\.-]+)', html)
                    if m_map:
                        try:
                            v1, v2 = float(m_map.group(1)), float(m_map.group(2))
                            if 5.0 <= v1 <= 21.0 and 97.0 <= v2 <= 106.0:
                                lat, lng = v1, v2
                        except Exception: pass

                # 4. ดึงข้อมูลชั้นจากหน้าเว็บรายละเอียด (การ์ดชั้นที่ / รายละเอียดทรัพย์)
                span = soup.find('span', string=re.compile(r'ชั้นที่|ชั้น'))
                if span:
                    card = span.find_parent('div', class_=re.compile(r'rounded')) or span.find_parent('div')
                    if card:
                        spans = card.find_all('span')
                        for s in spans:
                            t = s.get_text(strip=True)
                            if t and t not in ['ชั้นที่', 'ชั้น'] and re.match(r'^[0-9A-Za-z]+$', t):
                                floor = clean_floor_val(t) or ""
                                break
                                
                if not floor:
                    all_dd_text = ' '.join(dd.get_text(' ', strip=True) for dd in soup.find_all('dd'))
                    floor = extract_floor_from_text(all_dd_text, desc_str, soup.title.string if soup.title else "", asset_type=ptype) or ""
                break
        except Exception:
            time.sleep(get_scraper_delay())
    return subdist, dist, prov, lat, lng, price, floor

def fetch_bam_page(session, page_num, seen_ids=None):
    url = f"https://www.bam.co.th/th/npa/property/search?page={page_num}"

    def _fetch_html():
        r = safe_ssl_get(session, url, headers=HEADERS, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code != 200:
            r.raise_for_status()
        return r

    try:
        r = execute_with_retry(_fetch_html, company_name=COMPANY_NAME, context_msg=f"หน้า {page_num}", max_retries=4, max_cooldown_cycles=1)
        html = r.text
        escaped_json = True
        start_idx = html.find(r'\"properties\":')
        if start_idx == -1:
            escaped_json = False
            start_idx = html.find('"properties":')
        if start_idx == -1:
            return None

        bracket_start = html.find('[', start_idx)
        if bracket_start == -1:
            return None
        scan_text = html[bracket_start:]
        if escaped_json:
            scan_text = scan_text.replace(r'\\"', '__ESC_QUOTE__').replace(r'\"', '"').replace('__ESC_QUOTE__', r'\"').replace(r'\/', '/')
        balance = 0
        bracket_end = -1
        in_string = False
        escape = False
        for i, ch in enumerate(scan_text):
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if not in_string:
                if ch == '[':
                    balance += 1
                elif ch == ']':
                    balance -= 1
                    if balance == 0:
                        bracket_end = i
                        break
        if bracket_end == -1:
            return None
        items = json.loads(scan_text[:bracket_end+1])

        records = []
        now_str = datetime.now().strftime("%Y-%m-%d")

        # Polite sequential detail fetching (Standard for-loop)
        detail_results = {}
        for item in items:
            iid = clean_text(str(item.get("id") or item.get("propertyCode") or ""))
            if not iid:
                continue
            if seen_ids is not None and iid in seen_ids:
                continue
            pt = clean_text(item.get("propertyType") or item.get("category") or "")
            try:
                detail_results[iid] = fetch_item_detail(session, iid, ptype=pt)
            except Exception:
                detail_results[iid] = ("", "", "", None, None, None, "")

        for item in items:
            pid = clean_text(str(item.get("id") or item.get("propertyCode") or ""))
            pcode = clean_text(str(item.get("propertyCode") or item.get("code") or ""))
            effective_id = pid or pcode
            if seen_ids is not None and effective_id and effective_id in seen_ids:
                continue
            title = clean_text(item.get("title") or item.get("propertyName") or "")
            ptype = clean_text(item.get("propertyType") or item.get("category") or "")
            price_list = clean_num(item.get("price") or item.get("specialPrice"))
            prov_list = clean_text(item.get("province") or "")
            dist_list = clean_text(item.get("district") or "")

            subdist, dist_det, prov_det, lat, lng, price_det, floor_det = detail_results.get(pid, ("", "", "", None, None, None, ""))

            final_dist = dist_det or dist_list
            final_prov = prov_det or prov_list
            final_price = price_list if price_list is not None else price_det
            if final_price is not None:
                try:
                    if float(final_price) < 500.0:
                        final_price = None
                except Exception:
                    final_price = None

            land_str = format_land_area(item)
            usable_area = format_usable_area(item)

            link = f"https://www.bam.co.th/th/npa/property/{pid}" if pid else ""

            floor_val = floor_det or clean_floor_val(item.get("floor") or item.get("floors") or item.get("totalFloors") or item.get("story"))
            if not floor_val:
                floor_val = extract_floor_from_text(title, ptype, asset_type=ptype)

            clean_proj = clean_bam_project_name(title, tambon=subdist, amphoe=final_dist, province=final_prov)
            if not clean_proj and extract_project_from_title:
                clean_proj = extract_project_from_title(title, tambon=subdist, amphoe=final_dist, province=final_prov, company=COMPANY_NAME)

            record = {
                "บริษัท": COMPANY_NAME,
                "ID": pid or pcode,
                "รหัสทรัพย์": pcode,
                "ชื่อโครงการ": clean_proj,
                "ประเภททรัพย์": ptype,
                "ประเภทการขาย": "ขาย",
                "ราคา": final_price,
                "ตำบล": subdist,
                "อำเภอ": final_dist,
                "จังหวัด": final_prov,
                "ละติจูด": lat,
                "ลองจิจูด": lng,
                "ชื่อประกาศ": title,
                "ลิงก์": link,
                "เนื้อที่ (ตร.ว.)": convert_to_rai_ngan_wah(land_str),
                "พื้นที่ใช้สอย (ตร.ม.)": usable_area,
                "วันที่ดึงข้อมูล": now_str,
                "ห้องนอน": clean_num(item.get("bedrooms")),
                "ห้องน้ำ": clean_num(item.get("bathrooms")),
                "ที่จอดรถ": clean_num(item.get("parking")),
                "ชั้น": floor_val or "",
                "วันประกาศ": clean_text(item.get("created_at") or item.get("postDate") or "")
            }
            clean_row_location(record)
            records.append(record)
        return records
    except Exception as e:
        print_alert(f"เกิดข้อผิดพลาดในการดึงข้อมูลหน้า {page_num}: {e}", level="WARNING")
        log_warning(COMPANY_NAME, f"ข้ามหน้า {page_num} เนื่องจากดึงข้อมูลไม่สำเร็จ")
        return None

def save_to_csv(records, filename):
    return atomic_write_csv(records, filename, COLUMNS, company_name=COMPANY_NAME)

def main():
    print(f"==================================================", flush=True)
    print(f"🚀 เริ่มต้นการ Scrape [{COMPANY_NAME}] (Monthly Mode: ดึงข้อมูลแม่นยำ 100%)", flush=True)
    print(f"📁 บันทึกข้อมูลลงไฟล์: {OUTPUT_CSV}", flush=True)
    print(f"==================================================", flush=True)

    init_gis()
    session = AuditedSession(company_name=COMPANY_NAME)
    session.headers.update(HEADERS)

    is_ok, code, total_count, max_page = check_link_health(session)
    if is_ok:
        status_msg = f"🌐 สถานะลิงก์: ปกติ (HTTP {code}) | ทั้งหมด {max_page:,} หน้า | {ITEMS_PER_PAGE} รายการ/หน้า ({total_count:,} รายการ)"
        print(f"[{COMPANY_NAME}] {status_msg}", flush=True)
    else:
        print_alert("ไม่สามารถเข้าถึง API BAM ได้", level="CRITICAL")
        sys.exit(1)

    all_records, seen_ids = load_existing_csv(OUTPUT_CSV)

    items_per_p = ITEMS_PER_PAGE
    saved_state = load_scraper_state(COMPANY_NAME, MONTH_STR)
    saved_page = int(saved_state.get("completed_pages", 0) or 0)
    prev_failed_pages = [int(p) for p in (saved_state.get("failed_pages") or []) if str(p).isdigit()]
    calc_pages = min(max_page - 1, len(all_records) // items_per_p) if max_page > 0 else 0
    completed_pages = max(saved_page, calc_pages)
    completed_pages = min(max_page - 1, completed_pages) if max_page > 0 else 0
    processed_count = completed_pages
    new_added = 0

    # 1. Full Check: only when all pages completed cleanly without outstanding failed_pages
    if not prev_failed_pages and total_count > 0 and (len(all_records) >= total_count or saved_state.get("status") == "COMPLETED"):
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลใน CSV ครบถ้วน 100% แล้ว ({max_page:5,d}/{max_page:5,d} หน้า) | สะสม: {len(all_records):,d} รายการ -> สแครปเสร็จสมบูรณ์ทันที!", flush=True)
        save_to_csv(all_records, OUTPUT_CSV)
        save_scraper_state(COMPANY_NAME, max_page, max_page, len(all_records), status="COMPLETED", month_str=MONTH_STR)
        log_success(COMPANY_NAME, f"✅ ข้อมูลใน CSV ครบถ้วน 100% อยู่แล้ว ({len(all_records):,} รายการ)")
        return

    saved_milestones = set()
    failed_pages = []

    if completed_pages > 0:
        pct_start = int((completed_pages / max_page) * 100) if max_page > 0 else 0
        for target_pct in range(5, pct_start + 1, 5):
            saved_milestones.add(target_pct)
        saved_milestones.add("initial_page")

    start_time = time.time()

    start_page = completed_pages + 1
    if completed_pages > 0:
        print(f"[{COMPANY_NAME}] ⏩ Fast-Forward Resume: ข้าม {completed_pages:,} หน้าแรกที่เคยดึงแล้ว -> เริ่มสแครปหน้า {start_page:,} ต่อทันที", flush=True)

    init_pct = int((processed_count / max_page) * 100) if max_page > 0 else 0
    init_pbar = make_progress_bar(init_pct)
    init_eta = format_eta(0, processed_count, max_page, start_unit=completed_pages if completed_pages > 0 else 1)
    print(f"[{COMPANY_NAME:<13s}] {init_pbar} | ({processed_count:5,d}/{max_page:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{total_count:,d} รายการ | {init_eta}", flush=True)

    pages_to_run = sorted(set([p for p in prev_failed_pages if 1 <= p < start_page] + list(range(start_page, max_page + 1))))

    for page in pages_to_run:
        if not failed_pages and total_count > 0 and len(all_records) >= total_count:
            print(f"\n[{COMPANY_NAME}] 🎉 สะสมข้อมูลครบถ้วนทั้งหมดแล้ว ({len(all_records):,}/{total_count:,} รายการ) -> สิ้นสุดการสแครป!", flush=True)
            break
        items = fetch_bam_page(session, page, seen_ids=seen_ids)
        if items is None:
            failed_pages.append(page)
            print(f"\n[{COMPANY_NAME}] ⚠️ ข้ามหน้า {page} เนื่องจากดึงข้อมูลไม่สำเร็จ", flush=True)
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

        processed_count = max(processed_count, page) if not failed_pages else processed_count
        pct = int((processed_count / max_page) * 100) if max_page > 0 else 0
        elapsed_sec = time.time() - start_time
        eta_msg = format_eta(elapsed_sec, processed_count, max_page, start_unit=completed_pages if completed_pages > 0 else 1)
        pbar = make_progress_bar(pct)

        print(f"[{COMPANY_NAME:<13s}] {pbar} | ({processed_count:5,d}/{max_page:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{total_count:,d} รายการ | {eta_msg}", flush=True)

        # Auto-save after each page if new items were added
        saved_this_page = False
        if page_added > 0:
            save_to_csv(all_records, OUTPUT_CSV)
            save_scraper_state(COMPANY_NAME, processed_count, max_page, len(all_records), status="RUNNING", month_str=MONTH_STR, extra={"failed_pages": failed_pages})
            saved_this_page = True
            
        if "initial_page" not in saved_milestones and len(all_records) > 0:
            saved_milestones.add("initial_page")
            if not saved_this_page:
                save_to_csv(all_records, OUTPUT_CSV)
                save_scraper_state(COMPANY_NAME, processed_count, max_page, len(all_records), status="RUNNING", month_str=MONTH_STR)
                saved_this_page = True
            print(f"\n💾 [{COMPANY_NAME}] ครบหน้าแรก -> บันทึกไฟล์เริ่มต้นลง {OUTPUT_CSV}...", flush=True)
            log_milestone(COMPANY_NAME, f"💾 บันทึกเริ่มต้น (ครบหน้าแรก) {len(all_records):,} รายการลง " + os.path.basename(OUTPUT_CSV))

        for target_pct in range(5, 105, 5):
            if pct >= target_pct and target_pct not in saved_milestones:
                saved_milestones.add(target_pct)
                print(f"\n💾 [{COMPANY_NAME}] ครบ Milestone {target_pct}% -> บันทึกสำรองลง {OUTPUT_CSV}...", flush=True)
                log_milestone(COMPANY_NAME, f"💾 บันทึก Milestone สำรอง {target_pct}% ({len(all_records):,} รายการ) ลง " + os.path.basename(OUTPUT_CSV))
                if not saved_this_page:
                    save_scraper_state(COMPANY_NAME, processed_count, max_page, len(all_records), status="RUNNING", month_str=MONTH_STR)
                    save_to_csv(all_records, OUTPUT_CSV)
                    saved_this_page = True
                
        time.sleep(get_scraper_delay()) # หน่วงเวลาอย่างน้อย 15 วินาทีต่อหน้า
        
    print("", flush=True)
    save_to_csv(all_records, OUTPUT_CSV)
    elapsed = time.time() - start_time
    if failed_pages:
        final_status = "FAILED" if len(all_records) == 0 else "PARTIAL"
        save_scraper_state(
            COMPANY_NAME, processed_count, max_page, len(all_records),
            status=final_status, month_str=MONTH_STR,
            extra={"failed_pages": failed_pages}
        )
        print(f"\n==================================================", flush=True)
        print(f"⚠️ [{COMPANY_NAME}] สแครปเสร็จแบบมีหน้าล้มเหลว ({final_status}) | ({processed_count:5,d}/{max_page:5,d} หน้า) | สะสม: {len(all_records):,d} รายการ", flush=True)
        print(f"⚠️ รายการหน้าที่ข้าม/ดึงไม่ได้ ({len(failed_pages)} หน้า): {sorted(failed_pages)}", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที | 💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        print(f"==================================================", flush=True)
        log_warning(COMPANY_NAME, f"⚠️ สแครปเสร็จแบบ {final_status}: ดึงไม่ได้ {len(failed_pages)} หน้า")
        sys.exit(1 if len(all_records) == 0 else 2)
    else:
        save_scraper_state(COMPANY_NAME, processed_count, max_page, len(all_records), status="COMPLETED", month_str=MONTH_STR, extra={"failed_pages": []})
        print(f"\n==================================================", flush=True)
        print(f"✅ [{COMPANY_NAME}] สแครปเสร็จสมบูรณ์! | ({processed_count:5,d}/{max_page:5,d} หน้า) | สะสม: {len(all_records):,d} รายการ", flush=True)
        print(f"📊 ได้ข้อมูลทั้งหมด: {len(all_records):,} รายการ (เพิ่มใหม่ในรอบนี้: {new_added:,} รายการ)", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที", flush=True)
        print(f"💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        print(f"✅ ดึงข้อมูลได้ครบถ้วนสำเร็จ 100% (ไม่มีหน้าล้มเหลว)", flush=True)
        print(f"==================================================", flush=True)
        log_success(COMPANY_NAME, f"✅ สแครปเสร็จสมบูรณ์! ได้ข้อมูลทั้งหมดสะสม {len(all_records):,} รายการ")

if __name__ == "__main__":
    main()
