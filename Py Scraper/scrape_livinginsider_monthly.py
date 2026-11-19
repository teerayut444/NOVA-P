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
    print_structure_alert,
)
from clean_location_util import clean_row_location, init_gis, clean_floor_val, extract_floor_from_text, reverse_geocode_location, forward_geocode_location, translate_amphoe_en_to_th
try:
    from clean_project_util import clean_project_name, extract_project_from_title
except ImportError:
    clean_project_name = lambda x, **kwargs: str(x).strip()
    extract_project_from_title = lambda x, **kwargs: ""
import requests
from curl_cffi import requests as cffi_requests
import json
import re
import os
import sys
import time
from time_window_util import get_scraper_delay, get_scraper_delay_range
import random
import urllib.parse
from datetime import datetime, timedelta
import pandas as pd
from bs4 import BeautifulSoup
import concurrent.futures
import threading

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

COMPANY_NAME = "Livinginsider"
MONTH_STR = datetime.now().strftime("%Y_%m")

_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR
OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"Livinginsider_NPA_New_{MONTH_STR}.csv")

FAILED_PAGES_DIR = os.path.join(_ROOT_DIR, "logs", MONTH_STR)
os.makedirs(FAILED_PAGES_DIR, exist_ok=True)
FAILED_PAGES_JSON = os.path.join(FAILED_PAGES_DIR, "livinginsider_failed_pages.json")

def load_failed_pages():
    if os.path.exists(FAILED_PAGES_JSON):
        try:
            with open(FAILED_PAGES_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("failed_pages", [])
        except Exception:
            return []
    return []

def record_failed_page(page_num, reason="HTTP Error"):
    try:
        pages = load_failed_pages()
        existing = {p["page"] for p in pages if isinstance(p, dict) and "page" in p}
        if page_num not in existing:
            pages.append({
                "page": page_num,
                "error": str(reason),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        data = {
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_failed": len(pages),
            "failed_pages": sorted(pages, key=lambda x: x.get("page", 0))
        }
        with open(FAILED_PAGES_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[{COMPANY_NAME}] ⚠️ ไม่สามารถบันทึก failed_pages.json: {e}", flush=True)

def remove_resolved_failed_page(page_num):
    try:
        pages = load_failed_pages()
        pages = [p for p in pages if p.get("page") != page_num]
        data = {
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_failed": len(pages),
            "failed_pages": sorted(pages, key=lambda x: x.get("page", 0))
        }
        with open(FAILED_PAGES_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

URL_TEMPLATE = "https://www.livinginsider.com/property-buysell/{page_num}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.livinginsider.com/",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}

COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคา",
    "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ", "ยอดเข้าชม", "ยอดคลิก"
]

ITEMS_PER_PAGE = 48
THREAD_POOL_SIZE = 1

ALL_PROVINCES = [
    "กรุงเทพมหานคร", "กรุงเทพ", "กระบี่", "กาญจนบุรี", "กาฬสินธุ์", "กำแพงเพชร", "ขอนแก่น", "จันทบุรี",
    "ฉะเชิงเทรา", "ชลบุรี", "ชัยนาท", "ชัยภูมิ", "ชุมพร", "เชียงราย", "เชียงใหม่", "ตรัง", "ตราด",
    "ตาก", "นครนายก", "นครปฐม", "นครพนม", "นครราชสีมา", "นครศรีธรรมราช", "นครสวรรค์", "นนทบุรี",
    "นราธิวาส", "น่าน", "บึงกาฬ", "บุรีรัมย์", "ปทุมธานี", "ประจวบคีรีขันธ์", "ปราจีนบุรี", "ปัตตานี",
    "พระนครศรีอยุธยา", "อยุธยา", "พะเยา", "พังงา", "พัทลุง", "พิจิตร", "พิษณุโลก", "เพชรบุรี",
    "เพชรบูรณ์", "แพร่", "ภูเก็ต", "มหาสารคาม", "มุกดาหาร", "แม่ฮ่องสอน", "ยโสธร", "ยะลา", "ร้อยเอ็ด",
    "ระนอง", "ระยอง", "ราชบุรี", "ลพบุรี", "ลำปาง", "ลำพูน", "เลย", "ศรีสะเกษ", "สกลนคร", "สงขลา",
    "สตูล", "สมุทรปราการ", "สมุทรสงคราม", "สมุทรสาคร", "สระแก้ว", "สระบุรี", "สิงห์บุรี", "สุโขทัย",
    "สุพรรณบุรี", "สุราษฎร์ธานี", "สุรินทร์", "หนองคาย", "หนองบัวลำภู", "อ่างทอง", "อำนาจเจริญ",
    "อุดรธานี", "อุตรดิตถ์", "อุทัยธานี", "อุบลราชธานี"
]

BKK_ZONES = [
    "พระราม", "สุขุมวิท", "ลาดพร้าว", "สาทร", "สีลม", "บางนา", "รัชดา", "พญาไท", "อารีย์", "บางซื่อ",
    "จตุจักร", "ดอนเมือง", "สายไหม", "มีนบุรี", "บางกะปิ", "คลองเตย", "วัฒนา", "ยานนาวา", "สาธุประดิษฐ์",
    "เพชรเกษม", "บางแค", "จรัญสนิทวงศ์", "ปิ่นเกล้า", "ท่าพระ", "ตลาดพลู", "วุฒากาศ", "เจริญกรุง", "ห้วยขวาง",
    "ดินแดง", "ประเวศ", "พัฒนาการ", "รามคำแหง", "พระโขนง", "สะพานสูง", "คันนายาว", "ทวีวัฒนา", "หนองแขม"
]

def print_alert(msg: str, level: str = "ERROR"):
    border = "=" * 75
    if level == "CRITICAL":
        icon = "🚨 [CRITICAL ALERT]"
    elif level == "WARNING":
        icon = "⚠️ [WARNING ALERT]"
    else:
        icon = "❌ [ERROR ALERT]"
    print(f"\n{border}\n{icon} ({COMPANY_NAME}): {msg}\n{border}\n", flush=True)

def make_progress_bar(pct, length=20):
    filled = int(length * pct / 100)
    bar = '█' * filled + '░' * (length - filled)
    return f"[{bar}] {pct:3d}%"

def format_eta(elapsed_sec, completed_units, total_units, start_unit=1):
    if completed_units <= 0 or total_units <= 0 or elapsed_sec <= 0:
        return "กำลังคำนวณ..."
    completed_in_session = max(1, completed_units - start_unit + 1)
    rate = completed_in_session / elapsed_sec
    remaining_units = max(0, total_units - completed_units)
    if rate <= 0:
        return "กำลังคำนวณ..."
    eta_sec = remaining_units / rate
    finish_clock = datetime.fromtimestamp(datetime.now().timestamp() + eta_sec).strftime("%H:%M:%S")
    mins = int(eta_sec // 60)
    secs = int(eta_sec % 60)
    if mins > 60:
        hrs = mins // 60
        mins = mins % 60
        return f"เหลือ ~{hrs}ชม.{mins}น. ({finish_clock} น.)"
    elif mins > 0:
        return f"เหลือ ~{mins}น.{secs}ว. ({finish_clock} น.)"
    else:
        return f"เหลือ ~{secs}ว. ({finish_clock} น.)"

def clean_text(val):
    if not val or str(val).strip().lower() in ["none", "null", "undefined"]:
        return ""
    return re.sub(r"\s+", " ", str(val)).strip()

def convert_to_rai_ngan_wah(val):
    if val is None or pd.isna(val):
        return ""
    s = str(val).strip()
    if not s or s.lower() in ["nan", "none", "null", "-", "0", "0.0"]:
        return ""
    m_dash = re.match(r'^(\d+)\s*-\s*(\d+)\s*-\s*(\d+(?:\.\d+)?)$', s)
    if m_dash:
        r, g, w = int(m_dash.group(1)), int(m_dash.group(2)), float(m_dash.group(3))
        w_str = str(int(w)) if w.is_integer() else f"{w:g}"
        return f"{r}-{g}-{w_str}"
    if any(u in s for u in ['ไร่', 'งาน', 'วา', 'ตร.ว', 'ตารางวา']):
        m_r = re.search(r'([\d\.,]+)\s*ไร่', s)
        m_g = re.search(r'([\d\.,]+)\s*งาน', s)
        m_w = re.search(r'([\d\.,]+)\s*(?:ตร\.?ว\.?|ตร\.?วา|ตารางวา|วา)', s)
        r = float(m_r.group(1).replace(',', '')) if m_r else 0.0
        g = float(m_g.group(1).replace(',', '')) if m_g else 0.0
        w = float(m_w.group(1).replace(',', '')) if m_w else 0.0
        total_wah = (r * 400.0) + (g * 100.0) + w
        if total_wah > 0:
            ri = int(total_wah // 400)
            rem = total_wah - (ri * 400)
            gi = int(rem // 100)
            wi = round(rem - (gi * 100), 2)
            w_str = str(int(wi)) if float(wi).is_integer() else f"{wi:g}"
            return f"{ri}-{gi}-{w_str}"
    clean_num = re.sub(r'[^\d\.]', '', s.replace(',', ''))
    if clean_num:
        try:
            total_wah = float(clean_num)
            if 0 < total_wah < 500000:
                ri = int(total_wah // 400)
                rem = total_wah - (ri * 400)
                gi = int(rem // 100)
                wi = round(rem - (gi * 100), 2)
                w_str = str(int(wi)) if float(wi).is_integer() else f"{wi:g}"
                return f"{ri}-{gi}-{w_str}"
        except ValueError:
            pass
    return s

def load_existing_csv(filename):
    if "--fresh" in sys.argv or "--force-restart" in sys.argv:
        print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นดึงข้อมูลใหม่ทั้งหมดจากหน้าแรก (โหมด --fresh)", flush=True)
        reset_scraper_state(COMPANY_NAME, MONTH_STR)
        return [], set()
    records = []
    seen_ids = set()
    if os.path.exists(filename):
        try:
            df = pd.read_csv(filename, encoding="utf-8-sig", dtype=str).fillna("")
            for col in COLUMNS:
                if col not in df.columns:
                    df[col] = ""
            valid_rows = []
            for r in df[COLUMNS].to_dict(orient="records"):
                link_str = str(r.get("ลิงก์") or "")
                if "living_transit" in link_str or "living_zone" in link_str:
                    continue
                iid = str(r.get("ID") or "").strip()
                if iid and iid not in ("nan", "None") and len(iid) > 4:
                    if str(r.get("จังหวัด") or "").strip() and str(r.get("ละติจูด") or "").strip():
                        r["_location_cleaned"] = True
                    seen_ids.add(iid)
                    valid_rows.append(r)
            records = valid_rows
            
            # ตรวจสอบว่าไฟล์เดิมเป็นข้อมูลรอบก่อนที่ยังไม่มีพิกัดและที่อยู่หรือไม่
            if valid_rows and len(valid_rows) > 10:
                blank_count = sum(1 for r in valid_rows if not str(r.get("ละติจูด") or "").strip() and not str(r.get("จังหวัด") or "").strip())
                if blank_count >= len(valid_rows) * 0.8:
                    backup_blank = filename.replace(".csv", "_BLANK_BACKUP.csv")
                    print(f"[{COMPANY_NAME}] ⚠️ พบข้อมูลเดิม {len(valid_rows):,} รายการ แต่ไม่มีพิกัดและจังหวัด ({blank_count:,} รายการ)", flush=True)
                    print(f"[{COMPANY_NAME}] 🔄 สำรองไฟล์เดิมไว้ที่ {os.path.basename(backup_blank)} และเริ่มสแครปใหม่เพื่อดึงพิกัดจริงหน้าเว็บ!", flush=True)
                    try:
                        df.to_csv(backup_blank, index=False, encoding="utf-8-sig")
                    except Exception:
                        pass
                    reset_scraper_state(COMPANY_NAME, MONTH_STR)
                    return [], set()

            print(f"[{COMPANY_NAME}] 🔄 Smart Resume: โหลดข้อมูลเดิมจาก {filename} พบรายการทรัพย์สินจริง {len(records):,} รายการ", flush=True)
        except Exception as e:
            print_alert(f"ไม่สามารถอ่านไฟล์สะสมเดิม {filename}: {e}", level="WARNING")
    return records, seen_ids

_CONSECUTIVE_403_COUNT = 0

def wait_for_waf_cooldown(url=None, total_wait_minutes=60):
    """
    เมื่อโดน CloudFront WAF บล็อก IP ชั่วคราว (HTTP 403 / 429)
    ระบบจะเข้าสู่โหมดพักเครื่องเงียบสนิท (Quiet Cooldown) 1 ชั่วโมง (60 นาที)
    โดยมีการส่ง Probe ทดสอบทุกๆ 30 วินาที:
    1. หากผู้ใช้สลับเครือข่ายเน็ต (เช่น ต่อ Hotspot มือถือ / VPN) จะตรวจพบและกลับมาทำงานต่อทันที!
    2. หากรอจนครบเวลา CloudFront จะปลดบล็อก IP ให้อัตโนมัติ แล้วกลับมาทำงานต่อ
    """
    global _CONSECUTIVE_403_COUNT
    check_url = url or URL_TEMPLATE.format(page_num=1)
    print("\n" + "=" * 78, flush=True)
    print(f"🚨 [{COMPANY_NAME}] ตรวจพบการบล็อก IP จาก Amazon CloudFront WAF (HTTP 403 / Rate Limit)", flush=True)
    print(f"   🛡️ ระบบเปิดใช้งาน Circuit Breaker: พักส่ง Request เป็นเวลา {total_wait_minutes} นาที (1 ชม.) เพื่อรอ CloudFront ปลดแบน...", flush=True)
    print("   💡 ทางลัด: สามารถ 'สลับเน็ต' (เช่น ต่อเน็ต Hotspot จากมือถือ) เพื่อให้ระบบไปต่อได้ทันที!", flush=True)
    print("=" * 78 + "\n", flush=True)

    get_main_session(reset=True)
    _get_detail_session(reset=True)

    max_wait_seconds = total_wait_minutes * 60
    start_wait = time.time()
    probe_interval = 30

    while (time.time() - start_wait) < max_wait_seconds:
        elapsed = time.time() - start_wait
        remaining = int(max_wait_seconds - elapsed)
        rem_m, rem_s = remaining // 60, remaining % 60
        print(f"[{COMPANY_NAME}] ⏳ กำลังรอปลดแบน... เหลือเวลา ~{rem_m:02d}:{rem_s:02d} นาที (สลับต่อเน็ตมือถือเพื่อข้ามการรอได้)", flush=True)
        time.sleep(probe_interval)

        # Probe ด้วย Session ใหม่เอี่ยม
        probe_sess = None
        try:
            probe_sess = AuditedCurlSession(company_name=COMPANY_NAME, impersonate="chrome120")
            probe_sess.headers.update(HEADERS)
            res = probe_sess.get(check_url, timeout=20)
            if res.status_code == 200 and res.headers.get("x-amzn-waf-action") != "challenge":
                print("\n" + "=" * 78, flush=True)
                print(f"🎉 [{COMPANY_NAME}] ปลดบล็อกสำเร็จ (HTTP {res.status_code})! กลับเข้าสู่กระบวนการสแครปต่อทันที...", flush=True)
                print("=" * 78 + "\n", flush=True)
                _CONSECUTIVE_403_COUNT = 0
                get_main_session(reset=True)
                _get_detail_session(reset=True)
                return True
        except Exception:
            pass
        finally:
            if probe_sess is not None:
                try:
                    probe_sess.close()
                except Exception:
                    pass

    print(f"\n[{COMPANY_NAME}] ⏰ ครบกำหนดเวลารอ {total_wait_minutes} นาที -> ลองเชื่อมต่อใหม่อีกครั้ง...", flush=True)
    _CONSECUTIVE_403_COUNT = 0
    get_main_session(reset=True)
    _get_detail_session(reset=True)
    return True

def check_link_health(session):
    url = URL_TEMPLATE.format(page_num=1)
    for attempt in range(5):
        try:
            curr_sess = get_main_session()
            r = curr_sess.get(url, timeout=60)
            status_code = r.status_code
            if status_code == 200 and r.headers.get("x-amzn-waf-action") != "challenge":
                pages = [int(m) for m in re.findall(r'/property-buysell/(\d+)', r.text)]
                if not pages:
                    pages = [int(m) for m in re.findall(r'[?&]page=(\d+)', r.text)]
                if not pages:
                    pages = [int(m) for m in re.findall(r'/searchword/all/[^/]+/(\d+)/', r.text)]
                
                if not pages or max(pages) < 10:
                    try:
                        soup = BeautifulSoup(r.text, 'html.parser')
                        for a in soup.find_all('a', href=True):
                            txt = a.get_text().strip()
                            if txt.isdigit():
                                pages.append(int(txt))
                    except Exception:
                        pass

                m_tot = re.search(r'(?:มากกว่า|พบทั้งหมด|รวม)\s*([\d,]+)\s*(?:รายการ|ประกาศ)', r.text)
                if m_tot:
                    tot_raw = int(m_tot.group(1).replace(",", ""))
                    max_p = max(pages + [(tot_raw // ITEMS_PER_PAGE) + 1]) if pages else (tot_raw // ITEMS_PER_PAGE) + 1
                    tot_est = tot_raw
                else:
                    max_p = max(pages) if pages else 0
                    if max_p <= 0:
                        print_structure_alert(COMPANY_NAME, "ไม่พบเลขหน้าสูงสุด (Pagination) ในหน้า Livinginsider")
                        return False, status_code, 0, 0
                    tot_est = max_p * ITEMS_PER_PAGE
                return True, status_code, tot_est, max_p
            elif status_code in [403, 429]:
                print_alert(f"ตรวจพบการบล็อกชั่วคราว HTTP {status_code} ตั้งแต่ขั้นตอนเริ่มระบบ", level="WARNING")
                wait_for_waf_cooldown(url=url, total_wait_minutes=60)
            elif status_code == 202 or r.headers.get("x-amzn-waf-action") == "challenge":
                print_alert(f"ตรวจพบ CloudFront WAF Challenge (HTTP 202) -> กำลังสลับ Session ใหม่และลองอีกครั้ง...", level="WARNING")
                get_main_session(reset=True)
                time.sleep(3 + attempt * 2)
        except Exception as e:
            time.sleep(3 + attempt)
    return False, 0, 0, 0

def parse_location_from_card(card, title="", link=""):
    """
    สกัดข้อมูลทำเลเบื้องต้นจากการ์ดประกาศในหน้าค้นหา (Search Card)
    เพื่อให้มี ตำบล/อำเภอ/จังหวัด ทันทีตั้งแต่ขั้นตอนแรก ไม่ให้แถวข้อมูลว่างเปล่า
    """
    subdist, dist, prov = "", "", ""
    card_text = card.get_text() if card else ""

    # 1. ค้นหา Location Element ในการ์ด (เช่น .item-location, .location-text, .location-badge)
    loc_el = card.find(class_=re.compile(r'location|zone|area|badge-loc|pin', re.I)) if card else None
    loc_text = loc_el.get_text().strip() if loc_el else ""

    full_hint = f"{loc_text} {card_text} {title} {link}"

    # 2. Province
    for p in ALL_PROVINCES:
        if p in full_hint:
            prov = "กรุงเทพมหานคร" if p in ["กรุงเทพ", "กรุงเทพมหานคร"] else p
            break
    if not prov and any(bz in full_hint for bz in BKK_ZONES):
        prov = "กรุงเทพมหานคร"

    # 3. Explicit District & Subdistrict
    m_sd = re.search(r'(?:ตำบล|ต\.|แขวง)\s*([^\s,\|<"\'\(\)\/\d\-\:\.]+)', full_hint)
    if m_sd:
        cand_sd = m_sd.group(1).strip()
        if len(cand_sd) > 1 and cand_sd not in ["โซน", "ถนน", "ซอย", "โครงการ", "อื่นๆ", "ทำเล"]:
            subdist = cand_sd

    m_d = re.search(r'(?:อำเภอ|อ\.|เขต)\s*([^\s,\|<"\'\(\)\/\d\-\:\.]+)', full_hint)
    if m_d:
        cand_d = m_d.group(1).strip()
        if len(cand_d) > 1 and cand_d not in ["โซน", "ถนน", "ซอย", "โครงการ", "อื่นๆ", "ทำเล"]:
            dist = cand_d

    # 4. Check URL slug for district / province
    if (not dist or not prov) and link:
        slug = link.split("/")[-1].replace(".html", "").replace(".php", "").lower()
        slug_parts = re.split(r'[-_]+', slug)
        for part in slug_parts:
            if part.isdigit() or len(part) < 3:
                continue
            th_amp = translate_amphoe_en_to_th(part)
            if th_amp and not th_amp.isdigit() and len(th_amp) > 2 and not dist:
                dist = th_amp
            if part in ["bangkok", "bkk"] and not prov:
                prov = "กรุงเทพมหานคร"
            elif part in ["phuket"] and not prov:
                prov = "ภูเก็ต"
            elif part in ["pattaya", "chonburi"] and not prov:
                prov = "ชลบุรี"
            elif part in ["chiangmai", "chiang-mai"] and not prov:
                prov = "เชียงใหม่"
            elif part in ["nonthaburi"] and not prov:
                prov = "นนทบุรี"
            elif part in ["samutprakan", "samut-prakan"] and not prov:
                prov = "สมุทรปราการ"
            elif part in ["prachuap", "hua-hin"] and not prov:
                prov = "ประจวบคีรีขันธ์"

    return subdist, dist, prov

def extract_living_coordinates(html):
    """
    ดึงพิกัด GPS จริง (ละติจูด, ลองจิจูด) จากหน้าเว็บประกาศ Livinginsider โดยตรง:
    1. Direct React / Next.js State / JSON State (__NEXT_DATA__, __INITIAL_STATE__, state scripts)
    2. Google Maps URL parameters (q, query, center, ll, destination, markers)
    3. HTML data attributes (data-lat, data-lng, data-latitude, data-longitude, etc.)
    4. JSON-LD Schema (GeoCoordinates / hasMap)
    5. Inline JavaScript variables (window.lat, lat, lng, LatLng)
    """
    if not html:
        return None, None

    lat_v, lng_v = None, None

    # 1. --- JSON / State Data (React Server Components, Next.js, Redux State) ---
    # 1.1 Pair: latitude then longitude (quoted or unquoted numbers)
    m_pair1 = re.search(
        r'\\?["\']latitude\\?["\']\s*[:=]\s*\\?["\']?([5-9]\.\d+|1[0-9]\.\d+|2[0-1]\.\d+)\\?["\']?'
        r'[\s,]+(?:\\?["\']?[a-zA-Z0-9_\-]+\\?["\']?\s*[:=]\s*[^,{}]+,)*\s*'
        r'\\?["\']longitude\\?["\']\s*[:=]\s*\\?["\']?(9[7-9]\.\d+|10[0-6]\.\d+)\\?["\']?',
        html, re.I
    )
    if m_pair1:
        lat_v, lng_v = float(m_pair1.group(1)), float(m_pair1.group(2))

    # 1.2 Pair: longitude then latitude
    if not lat_v or not lng_v:
        m_pair2 = re.search(
            r'\\?["\']longitude\\?["\']\s*[:=]\s*\\?["\']?(9[7-9]\.\d+|10[0-6]\.\d+)\\?["\']?'
            r'[\s,]+(?:\\?["\']?[a-zA-Z0-9_\-]+\\?["\']?\s*[:=]\s*[^,{}]+,)*\s*'
            r'\\?["\']latitude\\?["\']\s*[:=]\s*\\?["\']?([5-9]\.\d+|1[0-9]\.\d+|2[0-1]\.\d+)\\?["\']?',
            html, re.I
        )
        if m_pair2:
            lng_v, lat_v = float(m_pair2.group(1)), float(m_pair2.group(2))

    # 1.3 Pair: lat then lng/lon/long
    if not lat_v or not lng_v:
        m_pair3 = re.search(
            r'\\?["\']lat\\?["\']\s*[:=]\s*\\?["\']?([5-9]\.\d+|1[0-9]\.\d+|2[0-1]\.\d+)\\?["\']?'
            r'[\s,]+(?:\\?["\']?[a-zA-Z0-9_\-]+\\?["\']?\s*[:=]\s*[^,{}]+,)*\s*'
            r'\\?["\'](?:lng|lon|long)\\?["\']\s*[:=]\s*\\?["\']?(9[7-9]\.\d+|10[0-6]\.\d+)\\?["\']?',
            html, re.I
        )
        if m_pair3:
            lat_v, lng_v = float(m_pair3.group(1)), float(m_pair3.group(2))

    # 1.4 Pair: lng/lon/long then lat
    if not lat_v or not lng_v:
        m_pair4 = re.search(
            r'\\?["\'](?:lng|lon|long)\\?["\']\s*[:=]\s*\\?["\']?(9[7-9]\.\d+|10[0-6]\.\d+)\\?["\']?'
            r'[\s,]+(?:\\?["\']?[a-zA-Z0-9_\-]+\\?["\']?\s*[:=]\s*[^,{}]+,)*\s*'
            r'\\?["\']lat\\?["\']\s*[:=]\s*\\?["\']?([5-9]\.\d+|1[0-9]\.\d+|2[0-1]\.\d+)\\?["\']?',
            html, re.I
        )
        if m_pair4:
            lng_v, lat_v = float(m_pair4.group(1)), float(m_pair4.group(2))

    # 1.5 Individual regex for latitude and longitude in property/location state
    if not lat_v or not lng_v:
        m_lat = re.search(r'\\?["\'](?:latitude|prop_lat|map_lat|lat)\\?["\']\s*[:=]\s*\\?["\']?([5-9]\.\d+|1[0-9]\.\d+|2[0-1]\.\d+)\\?["\']?', html, re.I)
        m_lng = re.search(r'\\?["\'](?:longitude|prop_lng|map_lng|lng|lon|long)\\?["\']\s*[:=]\s*\\?["\']?(9[7-9]\.\d+|10[0-6]\.\d+)\\?["\']?', html, re.I)
        if m_lat and m_lng:
            lat_v = float(m_lat.group(1))
            lng_v = float(m_lng.group(1))

    # 2. --- Google Maps URL Parameters (query, destination, q, center, ll, markers) ---
    if not lat_v or not lng_v:
        m_gmap = re.search(r'(?:query|destination|q|center|ll|markers)=\s*([5-9]\.\d+|1[0-9]\.\d+|2[0-1]\.\d+)(?:%2C|,)\s*(9[7-9]\.\d+|10[0-6]\.\d+)', html, re.I)
        if m_gmap:
            lat_v = float(m_gmap.group(1))
            lng_v = float(m_gmap.group(2))

    # 2.2 Google Maps Embed link or iframe src
    if not lat_v or not lng_v:
        m_maps = re.search(r'(?:maps\.google\.com|google\.com/maps|maps\.googleapis\.com)[^"\'\s]*[?&](?:q|query|ll|center|destination|markers)=([5-9]\.\d+|1[0-9]\.\d+|2[0-1]\.\d+)(?:%2C|,)(9[7-9]\.\d+|10[0-6]\.\d+)', html, re.I)
        if m_maps:
            lat_v = float(m_maps.group(1))
            lng_v = float(m_maps.group(2))

    # 2.3 Google Maps path /@lat,lng or /place/lat+lng
    if not lat_v or not lng_v:
        m_path = re.search(r'(?:maps\.google\.com|google\.com/maps)[^"\'\s]*/@([5-9]\.\d+|1[0-9]\.\d+|2[0-1]\.\d+),(9[7-9]\.\d+|10[0-6]\.\d+)', html, re.I)
        if m_path:
            lat_v = float(m_path.group(1))
            lng_v = float(m_path.group(2))

    # 3. --- HTML Data Attributes ---
    if not lat_v or not lng_v:
        m_attr = re.search(r'data-(?:map-)?lat(?:itude)?=["\']([5-9]\.\d+|1[0-9]\.\d+|2[0-1]\.\d+)["\'][^>]*data-(?:map-)?(?:lng|lon|long(?:itude)?)?=["\'](9[7-9]\.\d+|10[0-6]\.\d+)["\']', html, re.I)
        if m_attr:
            lat_v = float(m_attr.group(1))
            lng_v = float(m_attr.group(2))
        else:
            m_attr_rev = re.search(r'data-(?:map-)?(?:lng|lon|long(?:itude)?)?=["\'](9[7-9]\.\d+|10[0-6]\.\d+)["\'][^>]*data-(?:map-)?lat(?:itude)?=["\']([5-9]\.\d+|1[0-9]\.\d+|2[0-1]\.\d+)["\']', html, re.I)
            if m_attr_rev:
                lng_v = float(m_attr_rev.group(1))
                lat_v = float(m_attr_rev.group(2))

    # 4. --- Inline JS constructor (e.g. LatLng(lat, lng) or [lat, lng]) ---
    if not lat_v or not lng_v:
        m_js = re.search(r'(?:LatLng|marker)\(\s*([5-9]\.\d+|1[0-9]\.\d+|2[0-1]\.\d+)\s*,\s*(9[7-9]\.\d+|10[0-6]\.\d+)\s*\)', html, re.I)
        if m_js:
            lat_v = float(m_js.group(1))
            lng_v = float(m_js.group(2))

    # 5. Coordinate bounds check for Thailand
    if lat_v and lng_v:
        if 5.0 <= lat_v <= 21.0 and 97.0 <= lng_v <= 106.0:
            return round(lat_v, 7), round(lng_v, 7)

    return None, None

LIVING_ZONE_TO_LOCATION = {
    'pinklao-charansanitwong': ('บางกอกน้อย', 'กรุงเทพมหานคร'),
    'pak-chong-khaoyai': ('ปากช่อง', 'นครราชสีมา'),
    'bang-kae-phetkasem': ('บางแค', 'กรุงเทพมหานคร'),
    'ratchadapisek-huaikwang-suttisan': ('ห้วยขวาง', 'กรุงเทพมหานคร'),
    'chiang-mai': ('เมืองเชียงใหม่', 'เชียงใหม่'),
    'rama3-riversidesatupadit': ('ยานนาวา', 'กรุงเทพมหานคร'),
    'min-buri-romklao': ('มีนบุรี', 'กรุงเทพมหานคร'),
    'sukhumvit-asoke-thonglor': ('วัฒนา', 'กรุงเทพมหานคร'),
    'สุขุมวิท-อโศก-ทองหล่อ': ('วัฒนา', 'กรุงเทพมหานคร'),
    'ท่าพระ-ตลาดพลู': ('ธนบุรี', 'กรุงเทพมหานคร'),
    'พระราม-9-เพชรบุรีตัดใหม่': ('ห้วยขวาง', 'กรุงเทพมหานคร'),
    'hua-hin-prachuap': ('หัวหิน', 'ประจวบคีรีขันธ์'),
    'uthai-thani': ('เมืองอุทัยธานี', 'อุทัยธานี'),
    'prachin-buri': ('เมืองปราจีนบุรี', 'ปราจีนบุรี'),
    'pattanakan-srinakarin': ('สวนหลวง', 'กรุงเทพมหานคร'),
    'rathburana-suksawat': ('ราษฎร์บูรณะ', 'กรุงเทพมหานคร'),
    'nakhon-pathom': ('เมืองนครปฐม', 'นครปฐม'),
    'bangkruai-ratchapruek': ('บางกรวย', 'นนทบุรี'),
    'onnut-udomsuk': ('พระโขนง', 'กรุงเทพมหานคร'),
    'rangsit-pathum-thani': ('ธัญบุรี', 'ปทุมธานี'),
    'nawamin-ramindra': ('คันนายาว', 'กรุงเทพมหานคร'),
    'rama-2-bang-khun-thian': ('บางขุนเทียน', 'กรุงเทพมหานคร'),
    'rama9-rca-petchaburi': ('ห้วยขวาง', 'กรุงเทพมหานคร'),
    'sathorn-narathiwat': ('สาทร', 'กรุงเทพมหานคร'),
    'ladprao-central-ladprao': ('จตุจักร', 'กรุงเทพมหานคร'),
    'kasetsart-ratchayothin': ('จตุจักร', 'กรุงเทพมหานคร'),
    'rattanathibet-sanambinna': ('เมืองนนทบุรี', 'นนทบุรี'),
    'ratchathewiphayathai': ('ราชเทวี', 'กรุงเทพมหานคร'),
    'ramkhamhaeng-hua-mak': ('บางกะปิ', 'กรุงเทพมหานคร'),
    'sriracha-laem-chabang': ('ศรีราชา', 'ชลบุรี'),
    'ramkhamhaeng-nida-seri-thai': ('บึงกุ่ม', 'กรุงเทพมหานคร'),
    'ladprao101-the-mall-bang-kapi': ('บางกะปิ', 'กรุงเทพมหานคร'),
    'phutthamonthon-salaya': ('พุทธมณฑล', 'นครปฐม'),
    'bangbuathong-sainoi': ('บางบัวทอง', 'นนทบุรี'),
    'bang-sue-wong-sawang': ('บางซื่อ', 'กรุงเทพมหานคร'),
    'rayong': ('เมืองระยอง', 'ระยอง'),
    'kaset-nawaminladplakao': ('ลาดพร้าว', 'กรุงเทพมหานคร'),
    'suwannaphum-airport': ('ลาดกระบัง', 'กรุงเทพมหานคร'),
    'ladkrabang': ('ลาดกระบัง', 'กรุงเทพมหานคร'),
    'chaengwatana-muangthong': ('ปากเกร็ด', 'นนทบุรี'),
    'vipawadee-don-mueang-lak-si': ('หลักสี่', 'กรุงเทพมหานคร'),
    'ubon-ratchathani': ('เมืองอุบลราชธานี', 'อุบลราชธานี'),
    'daokanongbang-bon': ('บางบอน', 'กรุงเทพมหานคร'),
    'loei': ('เมืองเลย', 'เลย'),
    'udon-thani': ('เมืองอุดรธานี', 'อุดรธานี'),
    'nong-khai': ('เมืองหนองคาย', 'หนองคาย'),
}

def parse_living_detail_address(soup, html, link="", title=""):
    """
    สกัด ตำบล, อำเภอ, จังหวัด จากหน้ารายละเอียด Livinginsider:
    1. BreadcrumbList จาก JSON-LD Schema
    2. Container elements: .detail-text-zone, .location-detail, .detail-address, .ic-detail-zone, .box-zone-select2-sel
    3. Meta tags: og:description, description, og:title, <title>
    4. Livinginsider Zone dictionary mapping
    5. URL slug analysis (e.g. hua-hin-prachuap, asoke, rama-2-bang-khun-thian)
    """
    subdist, dist, prov = "", "", ""
    loc_raw = ""

    # 1. BreadcrumbList (JSON-LD)
    IGNORE_BREADCRUMBS = {
        "หน้าแรก", "คอนโด", "บ้านเดี่ยว", "ทาวน์โฮม", "ที่ดิน", "รวมประกาศขาย",
        "รายการ ขาย ให้เช่า", "รายการขายให้เช่า", "รายการ", "ขาย", "ให้เช่า",
        "อสังหาริมทรัพย์", "living-area", "living-zone", "living-transit"
    }
    if soup:
        for sc in soup.find_all('script', type='application/ld+json'):
            if not sc.string: continue
            try:
                data = json.loads(sc.string)
                if isinstance(data, dict) and data.get('@type') == 'BreadcrumbList':
                    items = data.get('itemListElement', [])
                    for it in items:
                        name = str(it.get('name') or '').strip()
                        if not name or name in IGNORE_BREADCRUMBS or "รายการ ขาย ให้เช่า" in name or name == title or len(name) > 60:
                            continue
                        # Match province
                        if not prov:
                            for p in ALL_PROVINCES:
                                if p in name:
                                    prov = "กรุงเทพมหานคร" if p in ["กรุงเทพ", "กรุงเทพมหานคร"] else p
                                    break
                        # Match district
                        if not dist and name not in ALL_PROVINCES:
                            clean_n = re.sub(r'^(?:เขต|อำเภอ|อ\.)\s*', '', name).strip()
                            if len(clean_n) > 2 and clean_n not in ["โซน", "ถนน", "ซอย", "โครงการ", "ทำเล"]:
                                dist = clean_n
                        # Match subdistrict
                        elif not subdist and name not in [prov, dist]:
                            clean_t = re.sub(r'^(?:แขวง|ตำบล|ต\.)\s*', '', name).strip()
                            if len(clean_t) > 2 and clean_t not in ["โซน", "ถนน", "ซอย", "โครงการ", "ทำเล"]:
                                subdist = clean_t
            except Exception:
                pass

    # 2. Extract from explicit HTML Zone/Location elements
    if soup:
        for selector in ['.detail-text-zone', '.location-detail', '.detail-address', '.ic-detail-zone', '.text_location', '.box-zone-select2-sel', '.detail-zone']:
            el = soup.select_one(selector)
            if el and el.get_text().strip():
                loc_raw += " " + el.get_text().strip()

    if not loc_raw and html:
        m_zone = re.search(r'class=["\'](?:detail-text-zone|ic-detail-zone|text_location|box-zone-select2-sel|location-detail)["\'][^>]*>(.*?)<', html)
        if m_zone:
            loc_raw = m_zone.group(1).strip()

    if not loc_raw and soup:
        m_meta = soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})
        if m_meta and m_meta.get('content'):
            loc_raw = m_meta['content'].strip()

    combined_text = f"{loc_raw} {title} {link}"

    # 3. Match Livinginsider Zone dictionary from link / text
    if link:
        slug_lower = link.split("/")[-1].replace(".html", "").replace(".php", "").lower()
        for z_key, (z_dist, z_prov) in LIVING_ZONE_TO_LOCATION.items():
            if z_key in slug_lower or z_key in combined_text.lower():
                if not dist or dist in IGNORE_BREADCRUMBS:
                    dist = z_dist
                if not prov:
                    prov = z_prov
                break

    # 4. Match Province
    if not prov:
        for p in ALL_PROVINCES:
            if p in combined_text:
                prov = "กรุงเทพมหานคร" if p in ["กรุงเทพ", "กรุงเทพมหานคร"] else p
                break
    if not prov and any(bz in combined_text for bz in BKK_ZONES):
        prov = "กรุงเทพมหานคร"

    # 5. Explicit subdistrict / district prefixes
    m_sd = re.search(r'(?:ตำบล|ต\.|แขวง)\s*([^\s,\|<"\'\(\)\/\d\-\:\.]+)', loc_raw or combined_text)
    if m_sd and not subdist:
        cand_sd = m_sd.group(1).strip()
        if len(cand_sd) > 1 and cand_sd not in ["โซน", "ถนน", "ซอย", "โครงการ", "อื่นๆ", "ทำเล"]:
            subdist = cand_sd

    m_d = re.search(r'(?:อำเภอ|อ\.|เขต)\s*([^\s,\|<"\'\(\)\/\d\-\:\.]+)', loc_raw or combined_text)
    if m_d and not dist:
        cand_d = m_d.group(1).strip()
        if len(cand_d) > 1 and cand_d not in ["โซน", "ถนน", "ซอย", "โครงการ", "อื่นๆ", "ทำเล"]:
            dist = cand_d

    # 6. Extract from URL slug if still missing
    if (not dist or not prov) and link:
        slug = link.split("/")[-1].replace(".html", "").replace(".php", "").lower()
        slug_parts = re.split(r'[-_]+', slug)
        for part in slug_parts:
            th_amp = translate_amphoe_en_to_th(part)
            if th_amp and not dist:
                dist = th_amp
            if part in ["bangkok", "bkk"] and not prov:
                prov = "กรุงเทพมหานคร"
            elif part in ["phuket"] and not prov:
                prov = "ภูเก็ต"
            elif part in ["pattaya", "chonburi"] and not prov:
                prov = "ชลบุรี"
            elif part in ["chiangmai", "chiang-mai"] and not prov:
                prov = "เชียงใหม่"
            elif part in ["nonthaburi"] and not prov:
                prov = "นนทบุรี"
            elif part in ["samutprakan", "samut-prakan"] and not prov:
                prov = "สมุทรปราการ"
            elif part in ["prachuap", "hua-hin"] and not prov:
                prov = "ประจวบคีรีขันธ์"

    return subdist, dist, prov

def extract_living_project_name(soup, title):
    b_items = []
    if soup:
        for sc in soup.find_all('script', type='application/ld+json'):
            if not sc.string: continue
            try:
                data = json.loads(sc.string)
                if isinstance(data, dict) and data.get('@type') == 'BreadcrumbList':
                    b_items = data.get('itemListElement', [])
                    break
            except Exception: pass

        for elem in b_items:
            item_url = str(elem.get('item') or '')
            name = str(elem.get('name') or '').strip()
            if 'living_project' in item_url:
                if name and name not in ["ดูโครงการทั้งหมด", "โครงการทั้งหมด", "หน้าแรก", "รายการ ขาย เช่า"]:
                    return name

        proj_tag = soup.find('a', href=re.compile(r'living_project/'))
        if proj_tag:
            p_name = proj_tag.get_text().strip()
            if p_name and p_name not in ["ดูโครงการทั้งหมด", "โครงการทั้งหมด", "รายการ ขาย เช่า"]:
                return p_name
            
    m_proj = re.search(r'(?:โครงการ|หมู่บ้าน|คอนโด)\s*([A-Za-z0-9\u0E00-\u0E7F\s\-\.]{3,30}?)(?=\s*(?:ซอย|ถนน|ตำบล|แขวง|อำเภอ|เขต|จังหวัด|ชั้น|ขนาด|ราคา|ให้เช่า|ขาย|$))', title)
    if m_proj:
        p_cand = m_proj.group(1).strip()
        p_cand = re.sub(r'^[/\s]+', '', p_cand).strip()
        if p_cand and p_cand.lower() not in ["none", "null", "-", "/", "โครงการ", "หมู่บ้าน", "รายการ ขาย เช่า"]:
            return p_cand
            
    return ""  # Leave blank if no project name

def detect_living_property_type(html_or_text, title="", link=""):
    """Detect property type based on title, link, or card content."""
    title_link = f"{title} {link}".lower()
    
    # 1. High-priority keyword matches in title/link
    if any(x in title_link for x in ["ทาวน์โฮม", "ทาวน์เฮ้าส์", "townhome", "townhouse", "town-home", "town-house"]):
        return "ทาวน์โฮม"
    if any(x in title_link for x in ["บ้านเดี่ยว", "บ้านแฝด", "single-house", "single house", "house-for-sale"]):
        return "บ้านเดี่ยว"
    if any(x in title_link for x in ["อาคารพาณิชย์", "ตึกแถว", "shophouse", "commercial", "office"]):
        return "อาคารพาณิชย์"
    if any(x in title_link for x in ["ที่ดิน", "land-for-sale", "land"]):
        return "ที่ดิน"
    if any(x in title_link for x in ["โรงงาน", "โกดัง", "factory", "warehouse"]):
        return "โรงงาน/โกดัง"
    if any(x in title_link for x in ["อพาร์ทเม้นท์", "หอพัก", "apartment"]):
        return "อพาร์ทเม้นท์"
    if any(x in title_link for x in ["คอนโด", "condo"]):
        return "คอนโด"
    if any(x in title_link for x in ["บ้าน", "house"]):
        return "บ้านเดี่ยว"
        
    # 2. Check main content text (excluding html header/footer links)
    clean_text = re.sub(r'<footer.*?</footer>', '', str(html_or_text), flags=re.DOTALL | re.I)
    clean_text = re.sub(r'<header.*?</header>', '', clean_text, flags=re.DOTALL | re.I).lower()
    
    if "ทาวน์โฮม" in clean_text or "ทาวน์เฮ้าส์" in clean_text:
        return "ทาวน์โฮม"
    if "บ้านเดี่ยว" in clean_text or "บ้านแฝด" in clean_text:
        return "บ้านเดี่ยว"
    if "อาคารพาณิชย์" in clean_text or "ตึกแถว" in clean_text:
        return "อาคารพาณิชย์"
    if "ที่ดิน" in clean_text:
        return "ที่ดิน"
    if "โรงงาน" in clean_text or "โกดัง" in clean_text:
        return "โรงงาน/โกดัง"
    if "อพาร์ทเม้นท์" in clean_text or "หอพัก" in clean_text:
        return "อพาร์ทเม้นท์"
    if "คอนโด" in clean_text:
        return "คอนโด"

    return "อื่นๆ"

def parse_living_card(card):
    try:
        a_tag = card.find('a', href=re.compile(r'/detail/|living_detail'))
        if not a_tag:
            a_tag = card.find('a', href=True)
        
        link = a_tag['href'] if a_tag else ""
        if link and not link.startswith("http"):
            link = "https://www.livinginsider.com" + link
            
        if any(x in link for x in ["living_transit", "living_zone", "living_project", "manual.php"]):
            return None
            
        m_id = re.search(r'living_detail/(\d+)', link) or re.search(r'-(\d+)(?:\.html|\?|$)', link)
        if not m_id:
            return None
        item_id = m_id.group(1)
        
        title = ""
        if a_tag and a_tag.get('aria-label'):
            title = clean_text(a_tag['aria-label'])
        if not title:
            a_title = card.find('h2') or card.find('h3') or card.find('p', title=True) or card.find('a', title=True)
            if a_title:
                title = clean_text(a_title.get('title') or a_title.text)
        if not title or title in ["คอนโด", "ทาวน์โฮม", "ทาวน์เฮ้าส์", "บ้านเดี่ยว", "บ้าน", "ที่ดิน", "อาคารพาณิชย์"]:
            title_tag = card.find(class_=lambda c: c and ("title" in c.lower() or "heading" in c.lower()) and "type" not in c.lower() and "cat" not in c.lower())
            if title_tag:
                title = clean_text(title_tag.text)
        if not title:
            title = clean_text(card.text[:100])
        
        card_text_full = card.get_text(" ", strip=True)
        # Filter out pure rental listings (no sale)
        has_rent = any(w in title or w in card_text_full for w in ["ให้เช่า", "เช่า", "for rent", "/เดือน", "/month"])
        has_sale = any(w in title or w in card_text_full for w in ["ขาย", "for sale"])
        if has_rent and not has_sale:
            return None
        if re.search(r'(?:฿|บาท)?\s*[\d,]+(?:\.\d+)?\s*/\s*(?:เดือน|ด\.|month|mo\b)', card_text_full, re.I) and not has_sale:
            return None

        # Baseline location from card & title & URL (must be extracted BEFORE project name cleaning)
        c_subdist, c_dist, c_prov = parse_location_from_card(card, title, link)

        # Project name
        proj_name = ""
        p_span = card.find('span', class_=re.compile(r'line-clamp-1', re.I))
        if p_span:
            p_text = clean_text(p_span.text)
            if p_text and p_text != title and len(p_text) > 1 and not any(w in p_text for w in ["คอนโด", "บ้านเดี่ยว", "ทาวน์โฮม", "ขาย", "เช่า"]):
                proj_name = p_text
                
        # If proj_name is still empty or needs cleaning, extract from title
        if not proj_name and title:
            if extract_project_from_title:
                proj_name = extract_project_from_title(title, tambon=c_subdist, amphoe=c_dist, province=c_prov, company=COMPANY_NAME)
        elif proj_name and clean_project_name:
            proj_name = clean_project_name(proj_name, tambon=c_subdist, amphoe=c_dist, province=c_prov, company=COMPANY_NAME)

        # Price (handle ล้าน / ลบ. / M safely without crashing card)
        price = None
        price_tag = card.find(class_=lambda c: c and "price" in c.lower())
        price_str = clean_text(price_tag.text) if price_tag else ""
        if not price_str:
            m_baht = re.search(r'฿\s*([\d,]+(?:\.\d+)?(?:\s*(?:ล้าน|ลบ\.?|M\b))?)', card.text, re.I)
            if m_baht:
                price_str = m_baht.group(1)
        if price_str:
            if re.search(r'/\s*(?:เดือน|ด\.|month|mo\b)', price_str, re.I) and not has_sale:
                return None
            is_million = bool(re.search(r'(?:ล้าน|ลบ\.?|\bM\b|\bMB\b)', price_str, re.I))
            m_pnum = re.search(r'(\d+(?:\.\d+)?)', price_str.replace(",", ""))
            if m_pnum:
                try:
                    p_val = float(m_pnum.group(1))
                    if is_million and p_val < 10000:
                        p_val *= 1_000_000.0
                    if p_val >= 500.0:
                        price = p_val
                except ValueError:
                    price = None
        
        now_str = datetime.now().strftime("%Y-%m-%d")
        ptype = detect_living_property_type(card.text, title, link)

        # Extract basic specs directly from card-prop-item or span elements
        bed, bath, floor_val, usable_area, land_area = None, None, "", "", ""
        elements = card.find_all(class_=re.compile(r'card-prop-item|card-prop-area-row', re.I))
        if not elements:
            elements = card.find_all('span')
        for p_el in elements:
            txt = p_el.get_text().strip()
            if any(u in txt for u in ['ตร.ว.', 'ตร.วา', 'ตารางวา', 'ไร่', 'งาน']):
                if not land_area:
                    land_area = convert_to_rai_ngan_wah(txt)
            elif 'ตร.ม.' in txt or 'ตารางเมตร' in txt:
                m_u = re.search(r'([\d\.,]+)', txt)
                if m_u and not usable_area: usable_area = m_u.group(1).replace(',', '')
            elif 'ชั้น' in txt and not floor_val:
                floor_val = clean_floor_val(txt.replace('\n', ' ').strip())
            elif 'สตูดิโอ' in txt or 'studio' in txt.lower():
                bed = 0
            elif re.match(r'^\d+$', txt) and len(txt) <= 2:
                val_num = int(txt)
                if bed is None: bed = val_num
                elif bath is None: bath = val_num

        if land_area:
            land_area = convert_to_rai_ngan_wah(land_area)

        # วันประกาศจะถูกดึงจาก "สร้างเมื่อ" บนหน้าเว็บประกาศ (Detail page) โดยตรง
        post_date = ""
        
        # View count from card bottom
        views = None
        m_v = re.search(r'(?:ดัน\s*[^<]*?ที่แล้ว.*?|ยอดดู|ดู)\s*(\d+)', card.text)
        if m_v:
            views = int(m_v.group(1))

        return {
            "บริษัท": COMPANY_NAME,
            "ID": item_id,
            "รหัสทรัพย์": item_id,
            "ชื่อโครงการ": proj_name,
            "ประเภททรัพย์": ptype,
            "ประเภทการขาย": "ขาย",
            "ราคา": price,
            "ตำบล": c_subdist,
            "อำเภอ": c_dist,
            "จังหวัด": c_prov,
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
            "ยอดเข้าชม": views,
            "ยอดคลิก": None
        }
    except Exception:
        return None

_detail_session = None
_session_lock = threading.Lock()

def _get_detail_session(reset=False):
    return get_main_session(reset=reset)

_main_session = None
_main_session_lock = threading.Lock()

def get_main_session(reset=False):
    global _main_session
    with _main_session_lock:
        if reset and _main_session is not None:
            try:
                _main_session.close()
            except Exception:
                pass
            _main_session = None
        if _main_session is None:
            s = AuditedCurlSession(company_name=COMPANY_NAME, impersonate="chrome120")
            s.headers.update(HEADERS)
            try:
                # ส่งคำขอไปหน้าแรกเพื่อรับ Session Cookies เริ่มต้นจาก CloudFront WAF
                s.get("https://www.livinginsider.com/", timeout=15)
            except Exception:
                pass
            _main_session = s
    return _main_session

def enrich_living_detail_location(session, item):
    """
    Detail page enrichment:
    1. พิกัดจริงจากเว็บโดยตรงเป็นอันดับแรก (Google Maps Query / Location Pin Coords / State)
    2. ทำ Reverse Geocode ผ่าน GIS ออฟไลน์ทันที เพื่อให้ได้ ตำบล/อำเภอ/จังหวัด ที่ตรงกับพิกัดจริง 100%
    3. สกัด ที่ตั้ง/โซนทำเล (ตำบล/อำเภอ/จังหวัด) จาก Breadcrumbs & โครงสร้าง HTML
    4. สกัด วันประกาศ (สร้างเมื่อ / อัปเดตเมื่อ) และ ยอดเข้าชม / ยอดคลิก
    5. GIS Fallback: หากรายการใดไม่มีพิกัดจริงบนเว็บ clean_row_location จะทำ Centroid Imputation
    """
    link = item.get("ลิงก์")
    if not link:
        clean_row_location(item)
        return item
    try:
        req_session = session if session is not None else get_main_session()
        time.sleep(get_scraper_delay())  # Standard delay
        
        detail_headers = dict(HEADERS)
        detail_headers["Referer"] = "https://www.livinginsider.com/property-buysell"
        
        r = req_session.get(link, headers=detail_headers, timeout=20, allow_redirects=True)
        if r.status_code == 200 and r.headers.get("x-amzn-waf-action") != "challenge":
            html = r.text
            soup = BeautifulSoup(html, 'html.parser')

            # 1. --- พิกัด GPS จริงจากเว็บโดยตรงเป็นอันดับแรก ---
            lat_v, lng_v = extract_living_coordinates(html)
            if lat_v and lng_v:
                item["ละติจูด"] = lat_v
                item["ลองจิจูด"] = lng_v
                
                # Reverse Geocode จากพิกัดจริงทันที เพื่อความแม่นยำระดับ 100%
                try:
                    sd_gis, d_gis, p_gis = reverse_geocode_location(lat_v, lng_v)
                    if p_gis:
                        if sd_gis: item["ตำบล"] = str(sd_gis).strip()
                        if d_gis: item["อำเภอ"] = str(d_gis).strip()
                        item["จังหวัด"] = str(p_gis).strip()
                except Exception:
                    pass

            # 2. --- ที่ตั้งและทำเล (ตำบล / อำเภอ / จังหวัด) จาก Breadcrumbs & Detail HTML ---
            d_subdist, d_dist, d_prov = parse_living_detail_address(soup, html, link, item.get("ชื่อประกาศ", ""))
            if d_prov and not item.get("จังหวัด"):
                item["จังหวัด"] = d_prov
            if d_dist and not item.get("อำเภอ"):
                item["อำเภอ"] = d_dist
            if d_subdist and not item.get("ตำบล"):
                item["ตำบล"] = d_subdist

            # 3. --- ชื่อโครงการจาก Breadcrumbs / Project Tag ---
            if not item.get("ชื่อโครงการ"):
                p_name = extract_living_project_name(soup, item.get("ชื่อประกาศ", ""))
                if p_name:
                    item["ชื่อโครงการ"] = clean_project_name(p_name, tambon=item.get("ตำบล", ""), amphoe=item.get("อำเภอ", ""), province=item.get("จังหวัด", ""), company=COMPANY_NAME) if clean_project_name else p_name
                elif extract_project_from_title:
                    item["ชื่อโครงการ"] = extract_project_from_title(item.get("ชื่อประกาศ", ""), tambon=item.get("ตำบล", ""), amphoe=item.get("อำเภอ", ""), province=item.get("จังหวัด", ""), company=COMPANY_NAME)

            # 4. --- สเปคเพิ่มเติม (ถ้าในการ์ดยังว่างอยู่) ---
            if not item.get("ห้องนอน"):
                m_bed = re.search(r'(\d+)\s*ห้องนอน', html)
                if m_bed: item["ห้องนอน"] = int(m_bed.group(1))
            if not item.get("ห้องน้ำ"):
                m_bath = re.search(r'(\d+)\s*ห้องน้ำ', html)
                if m_bath: item["ห้องน้ำ"] = int(m_bath.group(1))
            if not item.get("ที่จอดรถ"):
                m_park = re.search(r'(\d+)\s*ที่จอดรถ', html)
                if m_park: item["ที่จอดรถ"] = int(m_park.group(1))
            if not item.get("ชั้น"):
                f_val = extract_floor_from_text(html[:300000], item.get("ชื่อประกาศ", ""), asset_type=item.get("ประเภททรัพย์", ""))
                if f_val: item["ชั้น"] = f_val
            if not item.get("เนื้อที่ (ตร.ว.)") and item.get("ประเภททรัพย์") != "คอนโด":
                m_land = re.search(r'((?:\d+\s*ไร่\s*)?(?:\d+\s*งาน\s*)?[\d\.,]+\s*(?:ตร\.ว\.|ตร\.วา|ตารางวา))', html)
                if m_land:
                    item["เนื้อที่ (ตร.ว.)"] = convert_to_rai_ngan_wah(m_land.group(1))
            if not item.get("พื้นที่ใช้สอย (ตร.ม.)"):
                m_usable = re.search(r'([\d\.,]+)\s*(?:ตร\.ม\.|ตารางเมตร)', html)
                if m_usable:
                    item["พื้นที่ใช้สอย (ตร.ม.)"] = m_usable.group(1).replace(',', '').strip()

            # 5. --- วันประกาศ (สร้างเมื่อ / อัปเดตเมื่อ) ---
            # 5.1 ตรวจสอบ structured field ใน JSON / Meta ก่อนเป็นอันดับแรก (แม่นยำ รวดเร็ว ปลอดภัย ไม่ ReDoS)
            m_cd = re.search(r'\\?["\'](?:create_date|datePosted|created_at|post_date)\\?["\']\s*:\s*\\?["\'](\d{4})-(\d{2})-(\d{2})', html)
            if m_cd:
                yyyy, mm, dd = int(m_cd.group(1)), m_cd.group(2), m_cd.group(3)
                item["วันประกาศ"] = f"{dd}/{mm}/{yyyy + 543}"
            else:
                # 5.2 ค้นหาจากข้อความรอบคำว่า สร้างเมื่อ / วันที่ประกาศ ในหน้าเว็บ โดยจำกัดความยาว (ปลอดภัย ไม่ Backtracking)
                m_kw = re.search(r'(?:สร้างเมื่อ|วันที่ประกาศ|อัปเดตเมื่อ|ลงประกาศเมื่อ)', html)
                if m_kw:
                    idx = m_kw.start()
                    snippet = html[idx:idx + 300]
                    clean_snip = re.sub(r'<[^>]*>', ' ', snippet)
                    m_date = re.search(r'(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})', clean_snip)
                    if m_date:
                        d, m, y = m_date.group(1), m_date.group(2), int(m_date.group(3))
                        if y < 2400:
                            y += 543
                        item["วันประกาศ"] = f"{int(d):02d}/{int(m):02d}/{y}"
                    else:
                        now_dt = datetime.now()
                        m_rel_d = re.search(r'(\d+)\s*(?:day|วัน)', clean_snip, re.I)
                        m_rel_w = re.search(r'(\d+)\s*(?:week|สัปดาห์)', clean_snip, re.I)
                        m_rel_m = re.search(r'(\d+)\s*(?:month|เดือน)', clean_snip, re.I)
                        if m_rel_d:
                            dt = now_dt - timedelta(days=int(m_rel_d.group(1)))
                            item["วันประกาศ"] = f"{dt.day:02d}/{dt.month:02d}/{dt.year + 543}"
                        elif m_rel_w:
                            dt = now_dt - timedelta(weeks=int(m_rel_w.group(1)))
                            item["วันประกาศ"] = f"{dt.day:02d}/{dt.month:02d}/{dt.year + 543}"
                        elif m_rel_m:
                            dt = now_dt - timedelta(days=int(m_rel_m.group(1)) * 30)
                            item["วันประกาศ"] = f"{dt.day:02d}/{dt.month:02d}/{dt.year + 543}"
                        elif any(w in clean_snip.lower() for w in ['yesterday', 'เมื่อวาน']):
                            dt = now_dt - timedelta(days=1)
                            item["วันประกาศ"] = f"{dt.day:02d}/{dt.month:02d}/{dt.year + 543}"
                        elif any(w in clean_snip.lower() for w in ['today', 'วันนี้', 'hour', 'ชั่วโมง', 'minute', 'นาที']):
                            item["วันประกาศ"] = f"{now_dt.day:02d}/{now_dt.month:02d}/{now_dt.year + 543}"

            # 5.5 --- สถิติยอดเข้าชม และยอดคลิก ---
            m_stats = re.search(r'stats["\']?\s*:\s*\{([^}]+)\}', html) or re.search(r'stats\\?"\s*:\s*\{([^}]+)\}', html)
            if m_stats:
                st_block = m_stats.group(1)
                m_v = re.search(r'views["\']?\s*:\s*(\d+)', st_block) or re.search(r'views\\?"\s*:\s*(\d+)', st_block)
                if m_v and not item.get("ยอดเข้าชม"):
                    item["ยอดเข้าชม"] = int(m_v.group(1))
                m_c = re.search(r'clicks["\']?\s*:\s*(\d+)', st_block) or re.search(r'clicks\\?"\s*:\s*(\d+)', st_block)
                if m_c:
                    item["ยอดคลิก"] = int(m_c.group(1))
        elif r.status_code != 202:
            print(f"[{COMPANY_NAME}] ⚠️ HTTP {r.status_code} เมื่อเปิดหน้ารายละเอียด ID {item.get('ID')}", flush=True)
    except Exception as e:
        pass

    # 6. --- GIS FALLBACK & LOCATION NORMALIZATION ---
    # หากรายการใดไม่มีพิกัดจริงบนเว็บ (ละติจูด/ลองจิจูดเป็น None) clean_row_location จะทำ Centroid Imputation อัตโนมัติ
    clean_row_location(item)
    item["_location_cleaned"] = True
    return item

def fetch_living_page(session, page_num, seen_ids=None):
    global _CONSECUTIVE_403_COUNT
    url = URL_TEMPLATE.format(page_num=page_num)
    max_retries = 4
    for attempt in range(max_retries):
        try:
            curr_session = get_main_session() if (session is None or (_main_session is not None and session is not _main_session)) else session
            r = curr_session.get(url, timeout=60)
            
            if r.status_code in [202, 429, 403, 503] or r.headers.get("x-amzn-waf-action") == "challenge":
                waf_type = "CloudFront WAF Challenge (HTTP 202)" if r.status_code == 202 else f"HTTP {r.status_code}"
                if r.status_code in [403, 429]:
                    _CONSECUTIVE_403_COUNT += 1
                    if _CONSECUTIVE_403_COUNT >= 2:
                        # WAF IP Block confirmed! Trigger circuit breaker (1 hour)
                        print_alert(f"ตรวจพบ {waf_type} ต่อเนื่องในหน้า {page_num} -> เปิดโหมดพักเครื่อง Circuit Breaker", level="WARNING")
                        wait_for_waf_cooldown(url=url, total_wait_minutes=60)
                        session = get_main_session(reset=True)
                        curr_session = session
                        continue
                        
                # WAF / Rate Limit / 202 -> Exponential backoff (10s, 20s, 30s, 40s) + Clean Session
                wait_sec = [10, 20, 30, 40][min(attempt, 3)] + random.uniform(1.0, 3.0)
                print_alert(f"HTTP Status {r.status_code} ({waf_type}) ในหน้า {page_num} (พยายามที่ {attempt+1}/{max_retries}) -> สร้าง Session ใหม่ และพักรอ {wait_sec:.0f} วินาที...", level="WARNING")
                session = get_main_session(reset=True)
                curr_session = session
                _get_detail_session(reset=True)
                time.sleep(wait_sec)
                continue
                
            if r.status_code != 200:
                print_alert(f"HTTP Status {r.status_code} ในหน้า {page_num} (พยายามที่ {attempt+1}/{max_retries})", level="WARNING")
                time.sleep(3 + attempt * 2)
                continue
                
            # Reset consecutive 403 counter on success
            _CONSECUTIVE_403_COUNT = 0
            
            soup = BeautifulSoup(r.text, 'html.parser')
            cards = soup.find_all(['li', 'div'], class_=re.compile(r'listing-card-contain|istock-list|item-list', re.I))
            if not cards:
                cards = soup.find_all(['li', 'div'], class_=re.compile(r'listing|item|card', re.I))
            raw_records = []
            seen_page_ids = set()
            for card in cards:
                item = parse_living_card(card)
                if item and item.get("ID") and item["ID"] not in seen_page_ids:
                    seen_page_ids.add(item["ID"])
                    raw_records.append(item)

            # Enrich with location & coords from detail pages sequentially (skip items already in seen_ids)
            records = []
            for item in raw_records:
                iid = str(item.get("ID") or "").strip()
                if seen_ids and iid in seen_ids:
                    continue
                try:
                    res = enrich_living_detail_location(curr_session, item)
                    if res:
                        records.append(res)
                except Exception as ex:
                    print(f"[{COMPANY_NAME}] ⚠️ ข้อผิดพลาดในการดึงรายละเอียด: {ex}", flush=True)
                        
            # Safe breather between search pages (3.0 - 5.0 seconds) to maintain polite request rate
            time.sleep(get_scraper_delay())
            return records
        except Exception as e:
            print_alert(f"เกิดข้อผิดพลาดในการดึงข้อมูลหน้า {page_num} (พยายามที่ {attempt+1}/{max_retries}): {e}", level="WARNING")
            time.sleep(5 + attempt * 4)

    # หากลองครบทุกครั้งแล้วยังไม่ผ่าน -> บันทึกเข้า failed_pages และข้ามหน้านั้นไปทำหน้าถัดไปทันที (ไม่ล็อกค้างทั้งระบบ!)
    err_reason = f"HTTP Error/Timeout after {max_retries} attempts"
    record_failed_page(page_num, err_reason)
    print_alert(f"⚠️ ข้ามหน้า {page_num} ชั่วคราว (บันทึกไว้ใน failed_pages.json เรียบร้อย) -> ดำเนินการหน้าถัดไปต่อทันที", level="WARNING")
    return None

def save_to_csv(records, filename):
    try:
        if not records:
            if os.path.exists(filename) and os.path.getsize(filename) > 5000:
                print(f"\n[{COMPANY_NAME}] ⚠️ ข้ามการบันทึก: records ว่างเปล่า และมีไฟล์เดิมอยู่แล้ว ({os.path.getsize(filename):,} bytes) เพื่อป้องกันการเขียนทับ", flush=True)
                return True
        for r in records:
            if not r.get("_location_cleaned"):
                clean_row_location(r)
                r["_location_cleaned"] = True
        df = pd.DataFrame(records)
        return atomic_write_csv(df.to_dict(orient="records"), filename, COLUMNS, company_name=COMPANY_NAME)
    except Exception as e:
        print_alert(f"เกิดข้อผิดพลาดในการเซฟไฟล์ CSV '{filename}': {e}", level="CRITICAL")
        return False

def main():
    print(f"==================================================", flush=True)
    print(f"🚀 เริ่มต้นการ Scrape [{COMPANY_NAME}] (Monthly Mode: วันประกาศ + พิกัด + ที่ตั้ง + พื้นที่ครบถ้วน)", flush=True)
    print(f"📁 บันทึกข้อมูลลงไฟล์: {OUTPUT_CSV}", flush=True)
    print(f"==================================================", flush=True)

    init_gis()
    session = get_main_session()

    is_ok, code, total_count, max_page = check_link_health(session)
    if is_ok:
        status_msg = f"🌐 สถานะลิงก์: ปกติ (HTTP {code}) | ทั้งหมด {max_page:,} หน้า | {ITEMS_PER_PAGE} รายการ/หน้า ({total_count:,} รายการ)"
        print(f"[{COMPANY_NAME}] {status_msg}", flush=True)
    else:
        print_alert("ไม่สามารถเข้าถึงเว็บ Livinginsider ได้", level="CRITICAL")
        sys.exit(1)

    all_records, seen_ids = load_existing_csv(OUTPUT_CSV)
    saved_state = load_scraper_state(COMPANY_NAME, MONTH_STR)
    done_pages_set = {int(p) for p in (saved_state.get("done_pages") or []) if str(p).isdigit()}
    prev_failed_pages = [int(p) for p in (saved_state.get("failed_pages") or []) if str(p).isdigit()]

    if not prev_failed_pages and not load_failed_pages() and len(all_records) > 0 and total_count > 1000 and (len(all_records) >= total_count or saved_state.get("status") == "COMPLETED"):
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลใน CSV ครบถ้วน 100% แล้ว ({len(all_records):,}/{total_count:,} รายการ) -> สแครปเสร็จสมบูรณ์ทันที!", flush=True)
        save_to_csv(all_records, OUTPUT_CSV)
        save_scraper_state(COMPANY_NAME, max_page, max_page, len(all_records), status="COMPLETED", month_str=MONTH_STR)
        log_success(COMPANY_NAME, f"✅ ข้อมูลใน CSV ครบถ้วน 100% อยู่แล้ว ({len(all_records):,} รายการ)")
        return

    saved_milestones = set()
    failed_pages = []
    start_time = time.time()
    items_per_p = ITEMS_PER_PAGE
    new_added = 0

    retry_mode = "--retry-failed" in sys.argv
    fresh_mode = "--fresh" in sys.argv or "--force-restart" in sys.argv
    resume_mode = ("--resume" in sys.argv or "--fast-forward" in sys.argv) or (len(all_records) > 0 and not fresh_mode)

    if retry_mode:
        failed_data = load_failed_pages()
        unique_failed = sorted(list({p["page"] for p in failed_data if isinstance(p, dict) and "page" in p}), reverse=True)
        if not unique_failed:
            print(f"[{COMPANY_NAME}] ℹ️ ไม่พบหน้าที่ล้มเหลวใน {FAILED_PAGES_JSON} (ข้อมูลสมบูรณ์ครบถ้วน 100%)", flush=True)
            return
        print(f"\n[{COMPANY_NAME}] 🎯 เปิดใช้งานโหมดเก็บตก (--retry-failed): พบหน้าที่ตกหล่น {len(unique_failed)} หน้า -> เริ่มเก็บตกทันที", flush=True)
        pages_order = unique_failed
        max_page = len(pages_order)
        processed_count = 0
    elif resume_mode:
        if not done_pages_set:
            saved_page = int(saved_state.get("completed_pages", 0) or 0)
            calc_pages = min(max_page - 1, len(all_records) // items_per_p) if max_page > 0 else 0
            completed_pages = max(saved_page, calc_pages)
            completed_pages = min(max_page - 1, completed_pages) if max_page > 0 else 0
            if completed_pages > 0:
                done_pages_set = set(range(max_page, max(0, max_page - completed_pages), -1))
        failed_set = set(prev_failed_pages)
        pages_order = [p for p in range(max_page, 0, -1) if p not in done_pages_set or p in failed_set]
        processed_count = len(done_pages_set & set(range(1, max_page + 1)))
        if processed_count > 0:
            pct_start = int((processed_count / max_page) * 100) if max_page > 0 else 0
            for t_pct in range(5, pct_start + 1, 5):
                saved_milestones.add(t_pct)
            print(f"[{COMPANY_NAME}] ⏩ Resume Mode: เคยดึงสำเร็จแล้ว {processed_count:,}/{max_page:,} หน้า ({pct_start}%) -> เหลืออีก {len(pages_order):,} หน้า", flush=True)
    else:
        done_pages_set = set()
        pages_order = list(range(max_page, 0, -1))
        processed_count = 0
        print(f"[{COMPANY_NAME}] 🚀 เริ่มสแครปใหม่ทั้งหมดทุกหน้าเป็นค่าเริ่มต้น ({max_page:,} หน้า) กวาดลงมาตั้งแต่ {max_page:,} -> 1", flush=True)

    for page in pages_order:
        if not retry_mode and not failed_pages and total_count > 0 and len(all_records) >= total_count and len(done_pages_set) >= max_page:
            print(f"\n[{COMPANY_NAME}] 🎉 สะสมข้อมูลครบถ้วนทั้งหมดแล้ว ({len(all_records):,}/{total_count:,} รายการ) -> สิ้นสุดการสแครป!", flush=True)
            break
        session = get_main_session()
        items = fetch_living_page(session, page, seen_ids=seen_ids)
        if items is None:
            failed_pages.append(page)
            print(f"\n[{COMPANY_NAME}] ⚠️ ข้ามหน้า {page} เนื่องจากดึงข้อมูลไม่สำเร็จหลังจากลองหลายครั้ง", flush=True)
            continue

        remove_resolved_failed_page(page)
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

        if not retry_mode:
            done_pages_set.add(page)
            processed_count = len(done_pages_set)
        else:
            processed_count += 1

        pct = int((processed_count / max_page) * 100) if max_page > 0 else 0
        elapsed_sec = time.time() - start_time
        eta_msg = format_eta(elapsed_sec, processed_count, max_page)
        pbar = make_progress_bar(pct)

        mode_label = "เก็บตก" if retry_mode else COMPANY_NAME
        print(f"[{mode_label:<13s}] {pbar} | ({processed_count:5,d}/{max_page:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{total_count:,d} รายการ | {eta_msg}", flush=True)

        if page_added > 0:
            save_to_csv(all_records, OUTPUT_CSV)
        save_scraper_state(
            COMPANY_NAME, processed_count, max_page, len(all_records),
            status="RUNNING", month_str=MONTH_STR,
            extra={"done_pages": sorted(done_pages_set), "failed_pages": failed_pages}
        )

        if len(all_records) >= 10 and "initial_10" not in saved_milestones:
            saved_milestones.add("initial_10")
            log_milestone(COMPANY_NAME, f"💾 บันทึก 10 รายการแรก ({len(all_records):,} รายการ)")
            save_to_csv(all_records, OUTPUT_CSV)

        for target_pct in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]:
            if pct >= target_pct and target_pct not in saved_milestones:
                saved_milestones.add(target_pct)
                log_milestone(COMPANY_NAME, f"💾 บันทึกข้อมูล Milestone {target_pct}% ({len(all_records):,} รายการ)")
                save_to_csv(all_records, OUTPUT_CSV)

        time.sleep(get_scraper_delay())

    print("", flush=True)

    # 7. Auto-Retry Phase for missed/failed pages
    pending_failed = load_failed_pages()
    if pending_failed and not retry_mode:
        failed_pages_to_retry = [p["page"] for p in pending_failed if isinstance(p, dict) and "page" in p]
        print(f"\n[{COMPANY_NAME}] 🔄 เข้าสู่โหมดเก็บตกอัตโนมัติ: ลองดึงซ้ำสำหรับหน้าที่เคยข้ามไป ({len(failed_pages_to_retry)} หน้า)...", flush=True)
        time.sleep(3)
        still_failed = []
        for fp in failed_pages_to_retry:
            print(f"[{COMPANY_NAME}] 🔁 กำลังลองดึงซ้ำหน้า {fp}...", flush=True)
            session = get_main_session()
            retry_items = fetch_living_page(session, fp, seen_ids=seen_ids)
            if retry_items is not None:
                page_added = 0
                for item in retry_items:
                    iid = str(item["ID"]).strip()
                    if iid and iid in seen_ids:
                        continue
                    if iid:
                        seen_ids.add(iid)
                    all_records.append(item)
                    page_added += 1
                    new_added += 1
                done_pages_set.add(fp)
                remove_resolved_failed_page(fp)
                print(f"[{COMPANY_NAME}] ✅ ดึงเก็บตกหน้า {fp} สำเร็จ! (+{page_added} รายการ)", flush=True)
            else:
                still_failed.append(fp)
            time.sleep(get_scraper_delay())
        failed_pages = still_failed
        processed_count = len(done_pages_set)

    save_to_csv(all_records, OUTPUT_CSV)
    elapsed = time.time() - start_time
    if failed_pages:
        final_status = "FAILED" if len(all_records) == 0 else "PARTIAL"
        save_scraper_state(
            COMPANY_NAME, processed_count, max_page, len(all_records),
            status=final_status, month_str=MONTH_STR,
            extra={"done_pages": sorted(done_pages_set), "failed_pages": failed_pages}
        )
        print(f"\n==================================================", flush=True)
        print(f"⚠️ [{COMPANY_NAME}] สแครปเสร็จแบบมีหน้าล้มเหลว ({final_status}) | ({processed_count:5,d}/{max_page:5,d} หน้า) | สะสม: {len(all_records):,d} รายการ", flush=True)
        print(f"⚠️ รายการหน้าที่ข้าม/ดึงไม่ได้ ({len(failed_pages)} หน้า): {sorted(failed_pages)}", flush=True)
        print(f"💡 สามารถตรวจสอบรายละเอียดหน้าที่ข้ามได้ที่: {FAILED_PAGES_JSON}", flush=True)
        log_warning(COMPANY_NAME, f"สแครปเสร็จแบบ {final_status} แต่มี {len(failed_pages)} หน้าที่ดึงไม่ได้ (บันทึกใน failed_pages.json)")
        sys.exit(1 if len(all_records) == 0 else 2)
    else:
        save_scraper_state(
            COMPANY_NAME, processed_count, max_page, len(all_records),
            status="COMPLETED", month_str=MONTH_STR,
            extra={"done_pages": sorted(done_pages_set), "failed_pages": []}
        )
        print(f"\n==================================================", flush=True)
        print(f"✅ [{COMPANY_NAME}] สแครปเสร็จสมบูรณ์! | ({processed_count:5,d}/{max_page:5,d} หน้า) | สะสม: {len(all_records):,d} รายการ", flush=True)
        print(f"📊 ได้ข้อมูลทั้งหมด: {len(all_records):,} รายการ (เพิ่มใหม่ในรอบนี้: {new_added:,} รายการ)", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที", flush=True)
        print(f"💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        print(f"✅ ดึงข้อมูลได้ครบถ้วนสำเร็จทุกหน้า (ไม่มีหน้าล้มเหลว)", flush=True)
        log_success(COMPANY_NAME, f"✅ สแครปเสร็จสมบูรณ์ครบถ้วน 100% ได้ข้อมูล {len(all_records):,} รายการ")
        print(f"==================================================", flush=True)

if __name__ == "__main__":
    main()
