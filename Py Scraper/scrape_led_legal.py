import os
import sys
import glob
import hashlib
import json
import time
import threading
from time_window_util import get_scraper_delay, get_scraper_delay_range
import random
import re
import calendar
import urllib.parse
from datetime import datetime, timedelta
import pandas as pd
from bs4 import BeautifulSoup

from logger_util import (
    AuditedSession,
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
    safe_ssl_post,
)
from timeout_handler import handle_timeout_retry, execute_with_retry
from clean_location_util import clean_price_val, get_known_centroids_set, is_centroid_coord, clean_plaintiff_name

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

COMPANY_NAME = "LED_Legal"
COMPANY_DISPLAY = "รายงานผลการขายทอดตลาด กรมบังคับคดี (LED Legal Report)"
MERGED_COMPANY_NAME = "LED Legal"

# 1-Thread Safe Mode & Default Delay Settings (ปรับเปลี่ยนได้จากจุดเดียว)
MAX_WORKERS = 1
DEFAULT_DELAY_MIN = 15.0  # ปรับเป็น 15-16s ทุกตัว
DEFAULT_DELAY_MAX = 16.0

def get_target_report_month():
    """Return (year_ce, month, ym_padded) for last month (or --month YYYY_MM override)."""
    for i, arg in enumerate(sys.argv):
        if arg == "--month" and i + 1 < len(sys.argv):
            val = sys.argv[i + 1].strip().replace("-", "_")
            m = re.match(r'^(\d{4})_(\d{1,2})$', val)
            if m:
                y_ce = int(m.group(1))
                if y_ce > 2400:
                    y_ce -= 543
                mo = int(m.group(2))
                return y_ce, mo, f"{y_ce}_{mo:02d}"
    now = datetime.now()
    first_of_this_month = now.replace(day=1)
    last_month_dt = first_of_this_month - timedelta(days=1)
    return last_month_dt.year, last_month_dt.month, f"{last_month_dt.year}_{last_month_dt.month:02d}"

CURRENT_MONTH_STR = datetime.now().strftime("%Y_%m")
REPORT_YEAR_CE, REPORT_MONTH, REPORT_MONTH_STR = get_target_report_month()
REPORT_YEAR_BE = REPORT_YEAR_CE + 543

_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR

OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", CURRENT_MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)

REPORT_CSV = os.path.join(OUTPUT_DIR, f"LED_Legal_report_{REPORT_MONTH_STR}.csv")
MERGE_CSV = os.path.join(OUTPUT_DIR, f"LED_Legal_merge_{REPORT_MONTH_STR}.csv")
COORDS_CACHE_PATH = os.path.join(_ROOT_DIR, "data", "led_coords_cache.parquet")

REPORT_URL = "https://asset.led.go.th/report/report.asp"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept-Language': 'th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Origin': 'https://asset.led.go.th',
    'Referer': 'https://asset.led.go.th/report/report.asp'
}

REPORT_COLUMNS = [
    "สำนักงานบังคับคดี/กอง",
    "รหัสหน่วยงาน",
    "วันที่ขาย",
    "ลำดับที่",
    "ศาล",
    "เลขคดีแดง",
    "ที่ดินโฉนด",
    "โจทก์",
    "ประเภททรัพย์",
    "ราคาประเมิน",
    "ผลการขาย",
    "ราคาขายได้ / ราคาเสนอสูงสุด",
]

MERGE_COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคา",
    "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ", "เลขโฉนด", "โจทก์", "ศาล",
    "ยอดเข้าชม", "ยอดคลิก", "ราคาขายได้", "วันที่ขาย"
]

DEFAULT_AGENCIES_134 = [
    ('805', 'กระบี่'),
    ('012', 'กองจำหน่ายทรัพย์สิน'),
    ('041', 'กองฟื้นฟูกิจการของลูกหนี้'),
    ('027', 'กองล้มละลาย'),
    ('704', 'กาญจนบุรี'),
    ('709', 'กาญจนบุรี สาขาทองผาภูมิ'),
    ('404', 'กาฬสินธุ์'),
    ('603', 'กำแพงเพชร'),
    ('401', 'ขอนแก่น'),
    ('415', 'ขอนแก่น สาขาชุมแพ'),
    ('413', 'ขอนแก่น สาขาพล'),
    ('207', 'จันทบุรี'),
    ('203', 'ฉะเชิงเทรา'),
    ('201', 'ชลบุรี'),
    ('210', 'ชลบุรี สาขาพัทยา'),
    ('110', 'ชัยนาท'),
    ('306', 'ชัยภูมิ'),
    ('310', 'ชัยภูมิ สาขาภูเขียว'),
    ('806', 'ชุมพร'),
    ('809', 'ชุมพร สาขาหลังสวน'),
    ('502', 'เชียงราย'),
    ('511', 'เชียงราย สาขาเทิง'),
    ('501', 'เชียงใหม่'),
    ('510', 'เชียงใหม่ สาขาฝาง'),
    ('513', 'เชียงใหม่ สาขาฮอด'),
    ('903', 'ตรัง'),
    ('206', 'ตราด'),
    ('608', 'ตาก'),
    ('612', 'ตาก สาขาแม่สอด'),
    ('042', 'ทางปกครอง'),
    ('204', 'นครนายก'),
    ('701', 'นครปฐม'),
    ('408', 'นครพนม'),
    ('301', 'นครราชสีมา'),
    ('319', 'นครราชสีมา สาขาบัวใหญ่'),
    ('317', 'นครราชสีมา สาขาพิมาย'),
    ('312', 'นครราชสีมา สาขาสีคิ้ว'),
    ('802', 'นครศรีธรรมราช'),
    ('808', 'นครศรีธรรมราช สาขาทุ่งสง'),
    ('810', 'นครศรีธรรมราช สาขาปากพนัง'),
    ('602', 'นครสวรรค์'),
    ('101', 'นนทบุรี'),
    ('904', 'นราธิวาส'),
    ('506', 'น่าน'),
    ('414', 'บึงกาฬ'),
    ('305', 'บุรีรัมย์'),
    ('315', 'บุรีรัมย์ สาขานางรอง'),
    ('104', 'ปทุมธานี'),
    ('107', 'ปทุมธานี สาขาธัญบุรี'),
    ('707', 'ประจวบคีรีขันธ์'),
    ('710', 'ประจวบคีรีขันธ์ สาขาหัวหิน'),
    ('205', 'ปราจีนบุรี'),
    ('209', 'ปราจีนบุรี สาขากบินทร์บุรี'),
    ('906', 'ปัตตานี'),
    ('105', 'พระนครศรีอยุธยา'),
    ('505', 'พะเยา'),
    ('514', 'พะเยา สาขาเชียงคำ'),
    ('807', 'พังงา'),
    ('812', 'พังงา สาขาตะกั่วป่า'),
    ('902', 'พัทลุง'),
    ('605', 'พิจิตร'),
    ('601', 'พิษณุโลก'),
    ('705', 'เพชรบุรี'),
    ('606', 'เพชรบูรณ์'),
    ('613', 'เพชรบูรณ์ สาขาวิเชียรบุรี'),
    ('610', 'เพชรบูรณ์ สาขาหล่มสัก'),
    ('034', 'แพ่งกรุงเทพมหานคร 1'),
    ('035', 'แพ่งกรุงเทพมหานคร 2'),
    ('039', 'แพ่งกรุงเทพมหานคร 3'),
    ('036', 'แพ่งกรุงเทพมหานคร 4'),
    ('037', 'แพ่งกรุงเทพมหานคร 5'),
    ('038', 'แพ่งกรุงเทพมหานคร 6'),
    ('043', 'แพ่งกรุงเทพมหานคร 7'),
    ('507', 'แพร่'),
    ('028', 'ภ.บ.ท. 5 หน่วยที่'),
    ('803', 'ภูเก็ต'),
    ('406', 'มหาสารคาม'),
    ('410', 'มุกดาหาร'),
    ('508', 'แม่ฮ่องสอน'),
    ('509', 'แม่ฮ่องสอน สาขาแม่สะเรียง'),
    ('512', 'แม่ฮ่องสอน (เคลื่อนที่ปาย)'),
    ('307', 'ยโสธร'),
    ('905', 'ยะลา'),
    ('908', 'ยะลา สาขาเบตง'),
    ('403', 'ร้อยเอ็ด'),
    ('804', 'ระนอง'),
    ('202', 'ระยอง'),
    ('703', 'ราชบุรี'),
    ('108', 'ลพบุรี'),
    ('112', 'ลพบุรี สาขาชัยบาดาล'),
    ('025', 'ล้มละลาย สถาบันการเงิน'),
    ('020', 'ล้มละลาย 1'),
    ('021', 'ล้มละลาย 2'),
    ('022', 'ล้มละลาย 3'),
    ('023', 'ล้มละลาย 4'),
    ('024', 'ล้มละลาย 5'),
    ('040', 'ล้มละลาย 6'),
    ('503', 'ลำปาง'),
    ('504', 'ลำพูน'),
    ('409', 'เลย'),
    ('303', 'ศรีสะเกษ'),
    ('313', 'ศรีสะเกษ สาขากันทรลักษ์'),
    ('405', 'สกลนคร'),
    ('412', 'สกลนคร สาขาสว่างแดนดิน'),
    ('901', 'สงขลา'),
    ('909', 'สงขลา สาขานาทวี'),
    ('907', 'สตูล'),
    ('102', 'สมุทรปราการ'),
    ('708', 'สมุทรสงคราม'),
    ('706', 'สมุทรสาคร'),
    ('208', 'สระแก้ว'),
    ('106', 'สระบุรี'),
    ('314', 'สำนักงานบังคับคดีและวางทรัพย์ภูมิภาคที่ 3'),
    ('044', 'สำนักงานบังคับทางปกครอง'),
    ('026', 'สำนักงานวางทรัพย์กลาง'),
    ('109', 'สิงห์บุรี'),
    ('607', 'สุโขทัย'),
    ('611', 'สุโขทัย สาขาสวรรคโลก'),
    ('702', 'สุพรรณบุรี'),
    ('801', 'สุราษฎร์ธานี'),
    ('813', 'สุราษฎร์ธานี สาขาเกาะสมุย'),
    ('811', 'สุราษฎร์ธานี สาขาไชยา'),
    ('814', 'สุราษฎร์ธานี สาขาเวียงสระ'),
    ('304', 'สุรินทร์'),
    ('311', 'สุรินทร์ สาขารัตนบุรี'),
    ('407', 'หนองคาย'),
    ('411', 'หนองบัวลำภู'),
    ('111', 'อ่างทอง'),
    ('308', 'อำนาจเจริญ'),
    ('402', 'อุดรธานี'),
    ('604', 'อุตรดิตถ์'),
    ('609', 'อุทัยธานี'),
    ('302', 'อุบลราชธานี'),
    ('316', 'อุบลราชธานี สาขาเดชอุดม'),
]

_SPINNER_CHARS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_spinner_frame = 0

def make_progress_bar(pct, length=20):
    global _spinner_frame
    _spinner_frame = (_spinner_frame + 1) % len(_SPINNER_CHARS)
    spin = _SPINNER_CHARS[_spinner_frame]
    pct = max(0, min(100, pct))
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
    eta_seconds = remaining_units / rate
    finish_timestamp = time.time() + eta_seconds
    finish_clock = datetime.fromtimestamp(finish_timestamp).strftime('%H:%M:%S')

    if eta_seconds < 60:
        return f"เหลืออีก ~{int(eta_seconds)}ว. ({finish_clock} น.)"
    elif eta_seconds < 3600:
        mins = int(eta_seconds // 60)
        secs = int(eta_seconds % 60)
        return f"เหลืออีก ~{mins}น. {secs}ว. ({finish_clock} น.)"
    else:
        hours = int(eta_seconds // 3600)
        mins = int((eta_seconds % 3600) // 60)
        return f"เหลืออีก ~{hours}ชม. {mins}น. ({finish_clock} น.)"

def clean_cell_text(val):
    if val is None:
        return ""
    return " ".join(str(val).replace("\xa0", " ").split()).strip()

def parse_price_float(val):
    if val is None:
        return 0.0
    s = re.sub(r'[^\d.-]', '', str(val).strip())
    s = re.sub(r'(?<!^)-', '', s).rstrip('.-')
    if not s or s in ['-', '.']:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0

def is_valid_sold_row(result_str, sold_val):
    """Filter strictly for genuine sold items ('ขายได้' in ผลการขาย and sold price > 1 Baht)."""
    return ("ขายได้" in str(result_str or "")) and (sold_val > 1.0)

def convert_thai_date_to_iso(saledate_str):
    """Convert DD/MM/YYYY (Buddhist Era e.g. 15/09/2569) into ISO YYYY-MM-DD (2026-09-15)."""
    s = str(saledate_str or "").strip()
    if not s:
        return ""
    m_iso = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', s)
    if m_iso:
        y = int(m_iso.group(1))
        if y > 2400:
            y -= 543
        return f"{y:04d}-{m_iso.group(2)}-{m_iso.group(3)}"
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y > 2400:
            y -= 543
        return f"{y:04d}-{mo:02d}-{d:02d}"
    return s

def get_initial_agencies(session):
    """Fetch initial report.asp page and extract (prov_id, prov_name) list."""
    def _fetch():
        r = safe_ssl_get(session, REPORT_URL, timeout=45, ssl_fallback_on_gov=True)
        if r.status_code != 200:
            r.raise_for_status()
        return r

    try:
        r = execute_with_retry(_fetch, company_name=COMPANY_NAME, context_msg="หน้าเริ่มต้น Report", max_retries=4, max_cooldown_cycles=1)
        html = r.content.decode('utf-8', errors='ignore')
        soup = BeautifulSoup(html, 'html.parser')
        sel = soup.find('select', {'name': 'PROVINCE_ID'})
        agencies = []
        if sel:
            for opt in sel.find_all('option'):
                val = (opt.get('value') or '').strip()
                txt = clean_cell_text(opt.get_text(' ', strip=True))
                if val and val != '999' and txt and 'เลือกหน่วยงาน' not in txt:
                    agencies.append((val, txt))
        if len(agencies) >= 100:
            return True, r.status_code, agencies
        return True, r.status_code, list(DEFAULT_AGENCIES_134)
    except Exception:
        return False, 0, list(DEFAULT_AGENCIES_134)

def parse_report_rows(html_content, prov_id, prov_name, saledate):
    """Parse table rows from report.asp response and return genuine sold rows."""
    if isinstance(html_content, bytes):
        html_content = html_content.decode('utf-8', errors='ignore')
    soup = BeautifulSoup(html_content, 'html.parser')
    trs = soup.find_all('tr')
    if len(trs) <= 1:
        return []

    sold_rows = []
    for tr in trs[1:]:
        cells = [clean_cell_text(c.get_text(' ', strip=True)) for c in tr.find_all(['th', 'td'])]
        if len(cells) < 9:
            continue
        if cells[0] == "ลำดับที่" or "ไม่พบข้อมูล" in cells[0]:
            continue
        seq_no, court, suit_no, deed_no, plaintiff_raw, prop_type, appraised_str, result_str, sold_price_str = cells[:9]
        plaintiff = clean_plaintiff_name(plaintiff_raw)
        sold_val = parse_price_float(sold_price_str)
        if is_valid_sold_row(result_str, sold_val):
            sold_rows.append({
                "สำนักงานบังคับคดี/กอง": prov_name,
                "รหัสหน่วยงาน": prov_id,
                "วันที่ขาย": saledate,
                "ลำดับที่": seq_no,
                "ศาล": court,
                "เลขคดีแดง": suit_no,
                "ที่ดินโฉนด": deed_no,
                "โจทก์": plaintiff,
                "ประเภททรัพย์": prop_type,
                "ราคาประเมิน": appraised_str,
                "ผลการขาย": result_str,
                "ราคาขายได้ / ราคาเสนอสูงสุด": sold_price_str,
            })
    return sold_rows

def load_existing_report_csv(csv_path):
    if "--fresh" in sys.argv or "--force-restart" in sys.argv:
        print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นดึงข้อมูลใหม่ทั้งหมด (โหมด --fresh)", flush=True)
        reset_scraper_state(COMPANY_NAME, REPORT_MONTH_STR)
        return [], set()
    if not os.path.exists(csv_path):
        return [], set()
    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str).fillna("")
        raw_records = df.to_dict(orient="records")
        records = []
        seen_keys = set()
        for r in raw_records:
            sold_val = parse_price_float(r.get("ราคาขายได้ / ราคาเสนอสูงสุด", ""))
            if not is_valid_sold_row(r.get("ผลการขาย", ""), sold_val):
                continue
            k = (
                str(r.get("รหัสหน่วยงาน", "")).strip(),
                str(r.get("วันที่ขาย", "")).strip(),
                str(r.get("ลำดับที่", "")).strip(),
                str(r.get("เลขคดีแดง", "")).strip(),
                str(r.get("ที่ดินโฉนด", "")).strip(),
            )
            if k not in seen_keys:
                seen_keys.add(k)
                records.append(r)
        return records, seen_keys
    except Exception as e:
        log_warning(COMPANY_NAME, f"ไม่สามารถโหลดไฟล์เดิม {csv_path}: {e}")
        return [], set()

def save_csv_safe(records, columns, target_path):
    df = pd.DataFrame(records) if records else pd.DataFrame(columns=columns)
    for c in columns:
        if c not in df.columns:
            df[c] = ""
    df = df[columns]
    for attempt in range(3):
        tmp_path = f"{target_path}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
            os.replace(tmp_path, target_path)
            return True
        except PermissionError:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            if attempt < 2:
                time.sleep(1)
            else:
                alt_path = target_path.replace(".csv", "_BACKUP.csv")
                df.to_csv(alt_path, index=False, encoding="utf-8-sig")
                return True
        except Exception as e:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            log_error(COMPANY_NAME, f"บันทึก CSV ไม่สำเร็จ ({os.path.basename(target_path)}): {e}")
            return False
    return False

def _clean_str_val(v, strip_dot_zero=False):
    if v is None:
        return ""
    s = str(v).strip()
    if s in ("nan", "None", "<NA>", "NaT", "null"):
        return ""
    if strip_dot_zero and s.endswith(".0") and s[:-2].replace("-", "").isdigit():
        s = s[:-2]
    return s

def _norm_suit(s):
    return re.sub(r'\s+', '', str(s or '')).strip()

def _norm_deed_tokens(s):
    s = _clean_str_val(s, strip_dot_zero=True)
    if not s or s == '-':
        return set()
    return {tok for tok in re.findall(r'\d+', s) if tok and tok != '0'}

def _norm_court(s):
    s = _clean_str_val(s)
    s = re.sub(r'^ศาล', '', s).strip()
    return re.sub(r'\s+', '', s)

def _clean_prov(val):
    p = _clean_str_val(val)
    p = re.sub(r'^(จ\.|จังหวัด)', '', p).strip()
    return "อุตรดิตถ์" if p == "อุตรดิต" else p

def _clean_dist(val):
    d = _clean_str_val(val)
    d = re.sub(r'^[0-9A-Za-z]+-\s*', '', d)
    return re.sub(r'^(อ\.|อำเภอ|เขต)', '', d).strip()

def _report_dedup_key(r):
    """Deduplication key for sold LED report rows; preserves distinct condo units when deed is '-' or blank."""
    office = str(r.get("สำนักงานบังคับคดี/กอง", "")).strip()
    suit = str(r.get("เลขคดีแดง", "")).strip()
    deed = str(r.get("ที่ดินโฉนด", "")).strip()
    if not deed or deed in ("-", "ไม่มี", "ไม่มีข้อมูล"):
        return (
            office,
            suit,
            deed,
            str(r.get("วันที่ขาย", "")).strip(),
            str(r.get("ลำดับที่", "")).strip(),
            str(r.get("ราคาประเมิน", "")).strip(),
        )
    return (office, suit, deed)

def _alloc_unique_id(base_id, seen_ids, extra_hint=""):
    """Ensure merged LED Legal row ID never collides across multi-parcel or condo fallback rows."""
    candidate = base_id
    if extra_hint:
        candidate = f"{base_id}_{extra_hint}"
    if candidate not in seen_ids:
        seen_ids.add(candidate)
        return candidate
    idx = 2
    while f"{candidate}_{idx}" in seen_ids:
        idx += 1
    unique = f"{candidate}_{idx}"
    seen_ids.add(unique)
    return unique

def _extract_province_from_agency(agency_name):
    a = _clean_str_val(agency_name)
    if 'กรุงเทพ' in a or 'ล้มละลาย' in a or 'กอง' in a or 'ทางปกครอง' in a or 'วางทรัพย์กลาง' in a:
        return 'กรุงเทพมหานคร'
    return a.split()[0].strip() if a else ''

def get_report_month_led_npa_file(target_ym=None):
    """
    Find LED_NPA_New CSV strictly for the report's month (last month, e.g. CSV_Output/2026_10/LED_NPA_New_2026_10.csv).
    Crucial: Sold properties reported in last month were listed in last month's active catalog (LED_NPA_New_<target_ym>.csv).
    Strictly uses that month's LED_NPA_New file only.
    """
    if not target_ym:
        target_ym = REPORT_MONTH_STR

    # 1. Exact match in CSV_Output/<target_ym>/LED_NPA_New_<target_ym>.csv
    target_f1 = os.path.join(_ROOT_DIR, "CSV_Output", target_ym, f"LED_NPA_New_{target_ym}.csv")
    if os.path.exists(target_f1):
        return target_f1

    # 2. Exact match in CSV_Output/LED_NPA_New_<target_ym>.csv
    target_f2 = os.path.join(_ROOT_DIR, "CSV_Output", f"LED_NPA_New_{target_ym}.csv")
    if os.path.exists(target_f2):
        return target_f2

    # 3. Recursive search specifically for LED_NPA_New_<target_ym>.csv
    candidates = glob.glob(os.path.join(_ROOT_DIR, "CSV_Output", "**", f"LED_NPA_New_{target_ym}.csv"), recursive=True)
    candidates = [c for c in candidates if "_BACKUP" not in c and not c.endswith(".bak")]
    if candidates:
        candidates.sort(key=os.path.getmtime, reverse=True)
        return candidates[0]

    # 4. Fallback to current month if prior month missing
    current_f1 = os.path.join(_ROOT_DIR, "CSV_Output", CURRENT_MONTH_STR, f"LED_NPA_New_{CURRENT_MONTH_STR}.csv")
    if os.path.exists(current_f1):
        return current_f1
    current_f2 = os.path.join(_ROOT_DIR, "CSV_Output", f"LED_NPA_New_{CURRENT_MONTH_STR}.csv")
    if os.path.exists(current_f2):
        return current_f2

    return ""

def get_current_month_led_npa_file(target_ym=None):
    """Backwards compatibility alias for get_report_month_led_npa_file."""
    return get_report_month_led_npa_file(target_ym)

def load_report_month_led_listings(target_ym=None):
    """Load active LED listings strictly from report month's LED_NPA_New CSV (e.g. LED_NPA_New_2026_10.csv)."""
    fpath = get_report_month_led_npa_file(target_ym)
    if not fpath or not os.path.exists(fpath):
        return [], ""
    try:
        df = pd.read_csv(fpath, encoding="utf-8-sig", dtype=str, low_memory=False).fillna("")
        comp_s = df.get("บริษัท", pd.Series(dtype=str)).astype(str).str.strip()
        df = df[~comp_s.str.upper().isin(["LED LEGAL", "LED_LEGAL", "LED_SOLD"])]
        base_cols = [c for c in MERGE_COLUMNS if c not in ("ราคาขายได้", "วันที่ขาย")]
        for col in base_cols:
            if col not in df.columns:
                df[col] = ""
        int_like_cols = {"ID", "เลขโฉนด", "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ยอดเข้าชม", "ยอดคลิก"}
        rows = []
        for raw in df.to_dict(orient="records"):
            cleaned = {}
            for col in base_cols:
                cleaned[col] = _clean_str_val(raw.get(col, ""), strip_dot_zero=(col in int_like_cols))
            cleaned["บริษัท"] = "LED"
            if _norm_suit(cleaned.get("รหัสทรัพย์", "")):
                rows.append(cleaned)
        return rows, fpath
    except Exception as e:
        log_warning(COMPANY_NAME, f"อ่านไฟล์อ้างอิง {os.path.basename(fpath)} ไม่สำเร็จ: {e}")
        return [], fpath

def load_current_month_led_listings(target_ym=None):
    """Backwards compatibility alias for load_report_month_led_listings."""
    return load_report_month_led_listings(target_ym)

def load_landsmaps_coords_lookup():
    """Load FOUND real parcel GPS coordinates from data/led_coords_cache.parquet."""
    if not os.path.exists(COORDS_CACHE_PATH):
        return {}
    try:
        cdf = pd.read_parquet(COORDS_CACHE_PATH)
        if cdf.empty or "สถานะ" not in cdf.columns:
            return {}
        found = cdf[cdf["สถานะ"] == "FOUND"].dropna(subset=["ละติจูด", "ลองจิจูด"])
        lookup = {}
        for r in found.to_dict(orient="records"):
            pv = _clean_prov(r.get("จังหวัด", ""))
            dt = _clean_dist(r.get("อำเภอ", ""))
            dd_raw = _clean_str_val(r.get("เลขโฉนด", ""), strip_dot_zero=True)
            lat = _clean_str_val(r.get("ละติจูด", ""))
            lon = _clean_str_val(r.get("ลองจิจูด", ""))
            if not (pv and dd_raw and lat and lon):
                continue
            if dt:
                lookup[(pv, dt, dd_raw)] = (lat, lon)
                for tok in _norm_deed_tokens(dd_raw):
                    if (pv, dt, tok) not in lookup:
                        lookup[(pv, dt, tok)] = (lat, lon)
        return lookup
    except Exception as e:
        log_warning(COMPANY_NAME, f"อ่านแคชพิกัด {COORDS_CACHE_PATH} ไม่สำเร็จ: {e}")
        return {}

def build_led_legal_merge(report_records=None, report_csv_path=REPORT_CSV, merge_csv_path=MERGE_CSV):
    """
    Merge LED_Legal_report with report month's LED_NPA_New_<REPORT_MONTH_STR>.csv (last month, e.g. 2026_10)
    using LED_Legal_report as the PRIMARY source of truth for all overlapping fields
    (รหัสทรัพย์=เลขคดีแดง, เลขโฉนด=ที่ดินโฉนด, ศาล, โจทก์, ราคา=ราคาประเมิน, ราคาขายได้).
    """
    # Detect target report month from report_csv_path (or fallback to REPORT_MONTH_STR)
    target_report_ym = None
    if report_csv_path:
        m = re.search(r'LED_Legal_report_(\d{4}[_-]\d{1,2})', os.path.basename(report_csv_path))
        if m:
            target_report_ym = m.group(1).replace('-', '_')
    if not target_report_ym:
        target_report_ym = REPORT_MONTH_STR

    loaded_from_disk = False
    if report_records is None:
        if not os.path.exists(report_csv_path):
            print(f"[{COMPANY_NAME}] ⚠️ ไม่พบไฟล์รายงาน {report_csv_path} สำหรับเชื่อมข้อมูล", flush=True)
            return []
        df_rep = pd.read_csv(report_csv_path, encoding="utf-8-sig", dtype=str).fillna("")
        report_records = df_rep.to_dict(orient="records")
        loaded_from_disk = True

    # Strictly filter for genuine sold rows ('ขายได้' in ผลการขาย and sold price > 1 Baht)
    valid_reports = []
    for rep in report_records:
        sold_val = parse_price_float(rep.get("ราคาขายได้ / ราคาเสนอสูงสุด", ""))
        if is_valid_sold_row(rep.get("ผลการขาย", ""), sold_val):
            valid_reports.append(rep)

    # If existing report CSV on disk contained non-ขายได้ rows, persist cleaned report back safely
    if loaded_from_disk and len(valid_reports) != len(report_records):
        removed_cnt = len(report_records) - len(valid_reports)
        save_csv_safe(valid_reports, REPORT_COLUMNS, report_csv_path)
        print(f"[{COMPANY_NAME}] 🧹 คัดกรองรายการงดขาย/ค้านราคาออกจาก {os.path.basename(report_csv_path)} จำนวน {removed_cnt:,} แถว (คงเหลือขายได้จริง {len(valid_reports):,} แถว)", flush=True)

    # Sort chronologically by ISO sale date so 21-day auction lot repeats retain the earliest sale date
    valid_reports.sort(key=lambda r: (
        convert_thai_date_to_iso(r.get("วันที่ขาย", "")),
        str(r.get("รหัสหน่วยงาน", "")).strip(),
        str(r.get("ลำดับที่", "")).strip(),
    ))

    # ตัดนัดประมูลซ้ำของทรัพย์เดิมออก: ยึดเฉพาะนัดแรกสุดที่ขายได้จริง (สำนักงาน, เลขคดีแดง, ที่ดินโฉนด/ข้อมูลห้องชุด)
    seen_report_props = set()
    deduped_reports = []
    for r in valid_reports:
        prop_k = _report_dedup_key(r)
        if prop_k not in seen_report_props:
            seen_report_props.add(prop_k)
            deduped_reports.append(r)

    rep_diff = len(valid_reports) - len(deduped_reports)
    if rep_diff > 0:
        print(f"[{COMPANY_NAME}] 🧹 ตัดนัดประมูลซ้ำของทรัพย์เดิมออก {rep_diff:,} แถว (คงเหลือนัดแรกสุดที่ขายได้จริงสุทธิ {len(deduped_reports):,} รายการ)", flush=True)
    valid_reports = deduped_reports

    # บันทึกไฟล์รายงานผลการขายทอดตลาดสุทธิ (ตัดนัดประมูลซ้ำเหลือเฉพาะนัดแรกสุดที่ขายได้จริง 16,556 รายการ)
    if report_csv_path and (rep_diff > 0 or loaded_from_disk):
        save_csv_safe(valid_reports, REPORT_COLUMNS, report_csv_path)
        report_dir_csv = os.path.join(_ROOT_DIR, "CSV_Output", target_report_ym, f"LED_Legal_report_{target_report_ym}.csv")
        if os.path.exists(os.path.dirname(report_dir_csv)) and os.path.abspath(report_csv_path) != os.path.abspath(report_dir_csv):
            save_csv_safe(valid_reports, REPORT_COLUMNS, report_dir_csv)
        print(f"[{COMPANY_NAME}] 💾 บันทึกไฟล์รายงานผลการขายสุทธิ (ตัดนัดซ้ำแล้ว) สำเร็จ: {os.path.basename(report_csv_path)} ({len(valid_reports):,} รายการ)", flush=True)

    catalog_rows, npa_path = load_report_month_led_listings(target_report_ym)
    if not catalog_rows:
        print(f"[{COMPANY_NAME}] ⚠️ ไม่พบข้อมูลอ้างอิง LED_NPA_New_{target_report_ym}.csv สำหรับเชื่อมข้อมูล -> สร้างเรคคอร์ดจากรายงานผลการขายโดยตรง...", flush=True)
        catalog_rows = []
        npa_path = "" 

    coords_lookup = load_landsmaps_coords_lookup()
    centroids_set = get_known_centroids_set()
    print(f"[{COMPANY_NAME}] 🔗 กำลังเชื่อมข้อมูลกับ {os.path.basename(npa_path)} ({len(catalog_rows):,} รายการ | แคชพิกัดจริง LandsMaps {len(coords_lookup):,} คีย์ | ตรวจจุดกึ่งกลาง {len(centroids_set):,} จุด)...", flush=True)

    suit_index = {}
    for row in catalog_rows:
        sk = _norm_suit(row.get("รหัสทรัพย์", ""))
        if sk:
            row["_deed_tokens"] = _norm_deed_tokens(row.get("เลขโฉนด", ""))
            row["_price_val"] = parse_price_float(row.get("ราคา", ""))
            row["_prov_clean"] = _clean_prov(row.get("จังหวัด", ""))
            row["_court_norm"] = _norm_court(row.get("ศาล", ""))
            suit_index.setdefault(sk, []).append(row)

    merged_records = []
    seen_property_keys = set()
    seen_merge_ids = set()
    used_condo_ids = set()
    gps_enriched_count = 0
    skipped_deposit_count = 0

    for rep in valid_reports:
        suit_raw = str(rep.get("เลขคดีแดง", "")).strip()
        sk = _norm_suit(suit_raw)
        cands = suit_index.get(sk, []) if sk else []
        rep_deeds = _norm_deed_tokens(rep.get("ที่ดินโฉนด", ""))
        rep_court = _norm_court(rep.get("ศาล", ""))
        rep_agency = str(rep.get("สำนักงานบังคับคดี/กอง", ""))
        rep_prov = _clean_prov(_extract_province_from_agency(rep_agency))
        is_central = any(k in rep_agency for k in ("ล้มละลาย", "กอง", "ทางปกครอง", "วางทรัพย์กลาง"))
        rep_appr_val = parse_price_float(rep.get("ราคาประเมิน", ""))
        rep_sold_val = parse_price_float(rep.get("ราคาขายได้ / ราคาเสนอสูงสุด", ""))

        # กรองรายการที่เป็นเงินวางหลักประกันออก (ราคาขายได้ < 50% ของราคาประเมิน) ไม่นำเข้า merge.csv (คงไว้เฉพาะใน report.csv)
        eff_appr_val = rep_appr_val if rep_appr_val > 0 else (cands[0].get("_price_val", 0) if cands else 0)
        if eff_appr_val > 0 and rep_sold_val > 0 and (rep_sold_val / eff_appr_val) < 0.50:
            skipped_deposit_count += 1
            continue

        matched_row = None

        # Priority 1: Exact Suit + Deed overlap in the SAME province (unless central Bangkok agency)
        if rep_deeds:
            for c in cands:
                if (rep_deeds & c["_deed_tokens"]) and (is_central or not rep_prov or c["_prov_clean"] == rep_prov):
                    matched_row = c
                    break
            # Fallback if deed in catalog was blank but province + appraised price match
            if not matched_row and rep_appr_val > 0:
                for c in cands:
                    if not c["_deed_tokens"] and abs(c["_price_val"] - rep_appr_val) < 10.0 and (is_central or not rep_prov or c["_prov_clean"] == rep_prov):
                        matched_row = c
                        break
        else:
            # Priority 2: Condos / items where ที่ดินโฉนด is '-' (Match by Suit + Appraised Price in SAME province)
            if rep_appr_val > 0:
                for c in cands:
                    if (is_central or not rep_prov or c["_prov_clean"] == rep_prov) and abs(c["_price_val"] - rep_appr_val) < 10.0:
                        cid = c.get("ID", "")
                        if cid and cid in used_condo_ids:
                            continue
                        matched_row = c
                        break
            # Priority 3: Match by Suit + Court in SAME province
            if not matched_row and rep_court:
                court_cands = [c for c in cands if c["_court_norm"] and c["_court_norm"] == rep_court and (is_central or not rep_prov or c["_prov_clean"] == rep_prov)]
                if len(court_cands) == 1:
                    matched_row = court_cands[0]

        if not matched_row:
            # Fallback: create record directly from report so sold property is NOT lost
            fallback_row = {col: "" for col in MERGE_COLUMNS}
            fallback_row["บริษัท"] = MERGED_COMPANY_NAME
            base_fb_id = f"{sk}_{rep_prov}" if rep_prov else sk
            rep_deed_str = _clean_str_val(rep.get("ที่ดินโฉนด", ""), strip_dot_zero=True)
            if rep_deed_str and rep_deed_str != "-":
                deed_sig = "_".join(sorted(_norm_deed_tokens(rep_deed_str))[:2])
                extra_hint = deed_sig
            else:
                unit_sig = f"{rep.get('วันที่ขาย','')}|{rep.get('ลำดับที่','')}|{rep_appr_val}"
                extra_hint = hashlib.md5(unit_sig.encode("utf-8")).hexdigest()[:6]
            fallback_row["ID"] = _alloc_unique_id(base_fb_id, seen_merge_ids, extra_hint=extra_hint)
            fallback_row["รหัสทรัพย์"] = f"{sk}_{rep_prov}" if rep_prov else sk
            if rep_deed_str and rep_deed_str != "-":
                fallback_row["เลขโฉนด"] = rep_deed_str
            fallback_row["ศาล"] = _clean_str_val(rep.get("ศาล", ""))
            fallback_row["โจทก์"] = clean_plaintiff_name(rep.get("โจทก์", ""))
            if rep_appr_val > 0:
                cleaned_appr = clean_price_val(rep_appr_val)
                fallback_row["ราคา"] = str(cleaned_appr) if cleaned_appr is not None else str(rep_appr_val)
            fallback_row["ประเภททรัพย์"] = _clean_str_val(rep.get("ประเภททรัพย์", ""))
            fallback_row["จังหวัด"] = rep_prov
            fallback_row["ประเภทการขาย"] = "ขายทอดตลาด (ปลอดจำนอง)"
            p_type = fallback_row["ประเภททรัพย์"]
            if rep_deed_str and rep_deed_str != "-":
                fallback_row["ชื่อประกาศ"] = f"ทรัพย์ขายทอดตลาด กรมบังคับคดี {sk} {p_type} {rep_prov} (โฉนดเลขที่ {rep_deed_str})"
            else:
                fallback_row["ชื่อประกาศ"] = f"ทรัพย์ขายทอดตลาด กรมบังคับคดี {sk} {p_type} {rep_prov}"
            fallback_row["วันที่ดึงข้อมูล"] = datetime.now().strftime("%Y-%m-%d")
            cleaned_sold = clean_price_val(rep_sold_val)
            fallback_row["ราคาขายได้"] = str(cleaned_sold) if cleaned_sold is not None else str(rep_sold_val)
            fallback_row["วันที่ขาย"] = convert_thai_date_to_iso(rep.get("วันที่ขาย", ""))
            s_pure = re.sub(r'_[^_]+$', '', sk).strip()
            if '/' in s_pure:
                parts = s_pure.split('/', 1)
                fallback_row["ลิงก์"] = f"app/static/led_legal_bridge.html?suit_no={urllib.parse.quote(parts[0].strip())}&suit_year={urllib.parse.quote(parts[1].strip())}"
            else:
                fallback_row["ลิงก์"] = f"app/static/led_legal_bridge.html?suit_no={urllib.parse.quote(s_pure)}"
            merged_records.append(fallback_row)
            continue

        if not rep_deeds and matched_row.get("ID"):
            used_condo_ids.add(matched_row["ID"])

        # Construct merged row: start with matched listings details
        new_row = {}
        for col in MERGE_COLUMNS:
            new_row[col] = _clean_str_val(matched_row.get(col, ""))

        new_row["บริษัท"] = MERGED_COMPANY_NAME  # LED Legal

        # Strict OVERRIDE: Report is the PRIMARY source of truth for all its fields
        matched_prov = _clean_str_val(matched_row.get("จังหวัด", "") or rep_prov, strip_dot_zero=True)
        new_row["รหัสทรัพย์"] = f"{sk}_{matched_prov}" if matched_prov and matched_prov != "-" else sk
        base_m_id = _clean_str_val(new_row.get("ID", ""), strip_dot_zero=True) or new_row["รหัสทรัพย์"]
        new_row["ID"] = _alloc_unique_id(base_m_id, seen_merge_ids)
        rep_deed_str = _clean_str_val(rep.get("ที่ดินโฉนด", ""), strip_dot_zero=True)
        if rep_deed_str and rep_deed_str != "-":
            new_row["เลขโฉนด"] = rep_deed_str
        if rep.get("ศาล"):
            new_row["ศาล"] = _clean_str_val(rep.get("ศาล", ""))
        if rep.get("โจทก์"):
            new_row["โจทก์"] = clean_plaintiff_name(rep.get("โจทก์", ""))
        elif matched_row.get("โจทก์"):
            new_row["โจทก์"] = clean_plaintiff_name(matched_row.get("โจทก์", ""))
        if rep_appr_val > 0:
            cleaned_appr = clean_price_val(rep_appr_val)
            new_row["ราคา"] = str(cleaned_appr) if cleaned_appr is not None else str(rep_appr_val)
        if rep.get("ประเภททรัพย์") and not new_row.get("ประเภททรัพย์"):
            new_row["ประเภททรัพย์"] = _clean_str_val(rep.get("ประเภททรัพย์", ""))
        new_row["จังหวัด"] = matched_prov
        if not new_row.get("ประเภทการขาย"):
            new_row["ประเภทการขาย"] = "ขายทอดตลาด (ปลอดจำนอง)"

        if not new_row.get("ชื่อประกาศ"):
            p_type = new_row.get("ประเภททรัพย์", "")
            if rep_deed_str and rep_deed_str != "-":
                new_row["ชื่อประกาศ"] = f"ทรัพย์ขายทอดตลาด กรมบังคับคดี {sk} {p_type} {matched_prov} (โฉนดเลขที่ {rep_deed_str})"
            else:
                new_row["ชื่อประกาศ"] = f"ทรัพย์ขายทอดตลาด กรมบังคับคดี {sk} {p_type} {matched_prov}"

        if not new_row.get("วันที่ดึงข้อมูล"):
            new_row["วันที่ดึงข้อมูล"] = datetime.now().strftime("%Y-%m-%d")

        # Always ensure LED Legal link points to dedicated led_legal_bridge.html
        s_pure = re.sub(r'_[^_]+$', '', sk).strip()
        if '/' in s_pure:
            parts = s_pure.split('/', 1)
            new_row["ลิงก์"] = f"app/static/led_legal_bridge.html?suit_no={urllib.parse.quote(parts[0].strip())}&suit_year={urllib.parse.quote(parts[1].strip())}"
        else:
            new_row["ลิงก์"] = f"app/static/led_legal_bridge.html?suit_no={urllib.parse.quote(s_pure)}"

        # Sync real parcel GPS coordinates from LandsMaps cache (requires 3-tuple to prevent cross-district collision)
        pv_k = _clean_prov(new_row.get("จังหวัด", ""))
        dt_k = _clean_dist(new_row.get("อำเภอ", ""))
        dd_k = _clean_str_val(new_row.get("เลขโฉนด", ""), strip_dot_zero=True)
        if pv_k and dt_k and dd_k and coords_lookup:
            real_coords = coords_lookup.get((pv_k, dt_k, dd_k))
            if not real_coords:
                for tok in _norm_deed_tokens(dd_k):
                    real_coords = coords_lookup.get((pv_k, dt_k, tok))
                    if real_coords:
                        break
            if real_coords:
                new_row["ละติจูด"], new_row["ลองจิจูด"] = real_coords
                gps_enriched_count += 1

        # If coordinates are a centroid (จุดกึ่งกลาง), do NOT include them - leave blank
        if is_centroid_coord(new_row.get("ละติจูด"), new_row.get("ลองจิจูด"), centroids_set):
            new_row["ละติจูด"] = ""
            new_row["ลองจิจูด"] = ""

        cleaned_sold = clean_price_val(rep_sold_val)
        new_row["ราคาขายได้"] = str(cleaned_sold) if cleaned_sold is not None else str(rep_sold_val)
        new_row["วันที่ขาย"] = convert_thai_date_to_iso(rep.get("วันที่ขาย", ""))

        merged_records.append(new_row)

    if skipped_deposit_count > 0:
        print(f"[{COMPANY_NAME}] 🛡️ กรองรายการเงินวางหลักประกันออก {skipped_deposit_count:,} รายการ (< 50% ของราคาประเมิน คงไว้ใน report.csv ไม่นำเข้า merge.csv)", flush=True)

    save_csv_safe(merged_records, MERGE_COLUMNS, merge_csv_path)
    # Sync a copy into report month's folder if it exists
    report_dir_merge_path = os.path.join(_ROOT_DIR, "CSV_Output", target_report_ym, f"LED_Legal_merge_{target_report_ym}.csv")
    if os.path.exists(os.path.dirname(report_dir_merge_path)) and os.path.abspath(merge_csv_path) != os.path.abspath(report_dir_merge_path):
        save_csv_safe(merged_records, MERGE_COLUMNS, report_dir_merge_path)
    print(f"[{COMPANY_NAME}] ✅ สร้างไฟล์ {os.path.basename(merge_csv_path)} สำเร็จ (บริษัท={MERGED_COMPANY_NAME}) จำนวน {len(merged_records):,} รายการ (ซิงค์พิกัดโฉนดจริง LandsMaps {gps_enriched_count:,} แปลง)", flush=True)
    return merged_records

def main():
    if any(a.lower() in ["--now", "-now", "now", "--ignore-window", "--force-now", "--no-window"] for a in sys.argv):
        os.environ["SCRAPER_IGNORE_WINDOW"] = "1"
    delay_min, delay_max = get_scraper_delay_range()
    limit_agencies = 0
    merge_only = "--merge-only" in sys.argv

    for i, arg in enumerate(sys.argv):
        if arg == "--delay" and i + 1 < len(sys.argv):
            try:
                v = float(sys.argv[i + 1])
                delay_min = max(0.1, v)
                delay_max = max(0.1, v + 0.3)
            except ValueError:
                pass
        elif arg == "--limit-agencies" and i + 1 < len(sys.argv):
            try:
                limit_agencies = int(sys.argv[i + 1])
            except ValueError:
                pass

    num_days_in_month = calendar.monthrange(REPORT_YEAR_CE, REPORT_MONTH)[1]
    all_dates = [f"{d:02d}/{REPORT_MONTH:02d}/{REPORT_YEAR_BE}" for d in range(1, num_days_in_month + 1)]

    print("==================================================", flush=True)
    print(f"🚀 เริ่มต้นการ Scrape [{COMPANY_NAME}] ({COMPANY_DISPLAY}) (1-Thread Mode)", flush=True)
    print(f"📅 รอบเดือนที่ดึงผลขายทอดตลาด: {REPORT_MONTH:02d}/{REPORT_YEAR_BE} ({all_dates[0]} - {all_dates[-1]})", flush=True)
    print(f"📁 ไฟล์รายงานผลขาย: {REPORT_CSV}", flush=True)
    print(f"📁 ไฟล์เชื่อมข้อมูล ({MERGED_COMPANY_NAME}): {MERGE_CSV}", flush=True)
    print("==================================================", flush=True)

    if merge_only:
        build_led_legal_merge(report_csv_path=REPORT_CSV, merge_csv_path=MERGE_CSV)
        return

    session = AuditedSession(company_name=COMPANY_NAME)
    session.headers.update(HEADERS)

    is_ok, code, agencies = get_initial_agencies(session)
    if not is_ok:
        print_alert("❌ ไม่สามารถเชื่อมต่อหน้าเว็บรายงานผลการขายทอดตลาด (LED Report) ได้", level="CRITICAL")
        sys.exit(1)

    if limit_agencies > 0:
        agencies = agencies[:limit_agencies]

    total_agencies = len(agencies)
    print(f"[{COMPANY_NAME}] 🌐 สถานะลิงก์: ปกติ (HTTP {code}) | ครอบคลุม {total_agencies} หน่วยงาน × {len(all_dates)} วัน (1-Thread)", flush=True)

    all_report_records, seen_report_keys = load_existing_report_csv(REPORT_CSV)
    saved_state = load_scraper_state(COMPANY_NAME, REPORT_MONTH_STR)
    done_agencies = set(saved_state.get("completed_agencies", []))
    partial_agency = str(saved_state.get("partial_agency") or "").strip()
    try:
        partial_day_idx = int(saved_state.get("partial_day_idx") or 0)
    except (TypeError, ValueError):
        partial_day_idx = 0
    partial_completed_days = {
        int(d) for d in (saved_state.get("partial_completed_days") or [])
        if str(d).isdigit()
    }

    if len(done_agencies) >= total_agencies and len(all_report_records) > 0 and limit_agencies == 0:
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลรายงานผลขายทอดตลาดครบ 100% ทุกหน่วยงานแล้ว ({total_agencies}/{total_agencies} หน่วย) | สะสม: {len(all_report_records):,d} รายการ", flush=True)
        save_csv_safe(all_report_records, REPORT_COLUMNS, REPORT_CSV)
        build_led_legal_merge(report_records=all_report_records, report_csv_path=REPORT_CSV, merge_csv_path=MERGE_CSV)
        save_scraper_state(COMPANY_NAME, total_agencies, total_agencies, len(all_report_records), status="COMPLETED", month_str=REPORT_MONTH_STR, extra={"completed_agencies": [a[0] for a in agencies], "partial_agency": "", "partial_day_idx": 0, "partial_completed_days": []})
        return

    start_time = time.time()
    new_added = 0
    failed_units = []
    saved_milestones = set()

    if done_agencies:
        print(f"[{COMPANY_NAME}] 🔄 Smart Resume: ดึงเสร็จแล้ว {len(done_agencies)}/{total_agencies} หน่วยงาน (สะสม {len(all_report_records):,} รายการ) -> ดึงต่อหน่วยงานที่เหลือ...", flush=True)
    elif partial_agency and (partial_day_idx > 0 or partial_completed_days):
        print(f"[{COMPANY_NAME}] 🔄 Smart Resume: พบรอยต่อค้างอยู่ที่หน่วยงาน {partial_agency} วันที่ {partial_day_idx}/{len(all_dates)} (สะสม {len(all_report_records):,} รายการ)", flush=True)

    current_agency_id = ""
    current_agency_name = ""
    current_day_idx = 0
    current_agency_done_days = set()
    try:
        for a_idx, (prov_id, prov_name) in enumerate(agencies, 1):
            if prov_id in done_agencies:
                pct = int((a_idx / total_agencies) * 100)
                pbar = make_progress_bar(pct, length=20)
                print(f"[{COMPANY_NAME:<13s}] {pbar} | ({a_idx:3d}/{total_agencies:3d} หน่วย) | สะสม: {len(all_report_records):7,d} รายการ | ⏩ ข้าม {prov_name}", flush=True)
                continue

            current_agency_id = prov_id
            current_agency_name = prov_name
            current_day_idx = 0
            agency_ok = True
            if prov_id == partial_agency and partial_completed_days:
                agency_done_days = set(partial_completed_days)
            elif prov_id == partial_agency and partial_day_idx > 0:
                agency_done_days = set(range(1, partial_day_idx + 1))
            else:
                agency_done_days = set()
            current_agency_done_days = agency_done_days
            if agency_done_days:
                print(f"[{COMPANY_NAME}] ⏩ Smart Resume หน่วยงาน {prov_name}: ข้าม {len(agency_done_days)} วันเดิม -> ดึงวันที่เหลือถึง {len(all_dates)}", flush=True)

            for d_idx, saledate in enumerate(all_dates, 1):
                if d_idx in agency_done_days:
                    current_day_idx = d_idx
                    continue
                payload = {
                    'PROVINCE_ID': prov_id,
                    'saledate': saledate,
                    'Action': ''
                }

                def _fetch_day():
                    r = safe_ssl_post(session, REPORT_URL, data=payload, timeout=60, ssl_fallback_on_gov=True)
                    if r.status_code != 200:
                        r.raise_for_status()
                    return r

                try:
                    resp = execute_with_retry(_fetch_day, company_name=COMPANY_NAME, context_msg=f"{prov_name} วันที่ {saledate}", max_retries=4, max_cooldown_cycles=1)
                except Exception:
                    resp = None

                if resp is None or resp.status_code != 200:
                    failed_units.append(f"{prov_name} ({saledate})")
                    agency_ok = False
                    continue

                sold_rows = parse_report_rows(resp.content, prov_id, prov_name, saledate)
                for row in sold_rows:
                    rk = (
                        row["รหัสหน่วยงาน"],
                        row["วันที่ขาย"],
                        row["ลำดับที่"],
                        row["เลขคดีแดง"],
                        row["ที่ดินโฉนด"],
                    )
                    if rk not in seen_report_keys:
                        seen_report_keys.add(rk)
                        all_report_records.append(row)
                        new_added += 1

                agency_done_days.add(d_idx)
                current_day_idx = d_idx
                # Update live CLI progress and checkpoint every 10 days within an agency
                if d_idx % 10 == 0 or d_idx == len(all_dates):
                    frac_done = (a_idx - 1) + (d_idx / len(all_dates))
                    pct = int((frac_done / total_agencies) * 100)
                    pbar = make_progress_bar(pct, length=20)
                    elapsed = time.time() - start_time
                    eta_str = format_eta(elapsed, frac_done, total_agencies, 1)
                    print(f"[{COMPANY_NAME:<13s}] {pbar} | ({a_idx:3d}/{total_agencies:3d} หน่วย) | สะสม: {len(all_report_records):7,d} รายการ | {eta_str}", flush=True)
                    save_csv_safe(all_report_records, REPORT_COLUMNS, REPORT_CSV)
                    safe_partial_day = max((d for d in agency_done_days if d == 1 or d - 1 in agency_done_days), default=0)
                    save_scraper_state(
                        COMPANY_NAME,
                        len(done_agencies),
                        total_agencies,
                        len(all_report_records),
                        status="RUNNING",
                        month_str=REPORT_MONTH_STR,
                        extra={
                            "completed_agencies": list(done_agencies),
                            "current_agency": prov_name,
                            "partial_agency": prov_id,
                            "partial_day_idx": safe_partial_day,
                            "partial_completed_days": sorted(agency_done_days),
                        }
                    )

                time.sleep(get_scraper_delay())

            if agency_ok and len(agency_done_days) >= len(all_dates):
                done_agencies.add(prov_id)
                partial_agency = ""
                partial_day_idx = 0
                partial_completed_days = set()
                current_day_idx = 0
                current_agency_done_days = set()

            # Save incremental report CSV and state after each agency
            save_csv_safe(all_report_records, REPORT_COLUMNS, REPORT_CSV)
            save_scraper_state(
                COMPANY_NAME,
                len(done_agencies),
                total_agencies,
                len(all_report_records),
                status="RUNNING",
                month_str=REPORT_MONTH_STR,
                extra={
                    "completed_agencies": list(done_agencies),
                    "current_agency": prov_name,
                    "partial_agency": "" if prov_id in done_agencies else prov_id,
                    "partial_day_idx": 0 if prov_id in done_agencies else current_day_idx,
                    "partial_completed_days": [] if prov_id in done_agencies else sorted(agency_done_days),
                }
            )

            pct = int((a_idx / total_agencies) * 100)
            for target_pct in range(10, 105, 10):
                if pct >= target_pct and target_pct not in saved_milestones:
                    saved_milestones.add(target_pct)
                    log_milestone(COMPANY_NAME, f"💾 บันทึก Milestone {target_pct}% ({len(all_report_records):,} รายการ) ลง {os.path.basename(REPORT_CSV)}")
    except (KeyboardInterrupt, SystemExit):
        print(f"\n⚠️ [{COMPANY_NAME}] ได้รับสัญญาณหยุดทำงาน -> กำลังบันทึกข้อมูลสะสม ({len(all_report_records):,} รายการ) ลง {REPORT_CSV}...", flush=True)
        save_csv_safe(all_report_records, REPORT_COLUMNS, REPORT_CSV)
        save_scraper_state(
            COMPANY_NAME,
            len(done_agencies),
            total_agencies,
            len(all_report_records),
            status="PAUSED",
            month_str=REPORT_MONTH_STR,
            extra={
                "completed_agencies": list(done_agencies),
                "current_agency": current_agency_name,
                "partial_agency": current_agency_id if current_agency_id not in done_agencies else "",
                "partial_day_idx": current_day_idx if current_agency_id not in done_agencies else 0,
                "partial_completed_days": sorted(current_agency_done_days) if current_agency_id not in done_agencies else [],
            }
        )
        raise

    # Final save of LED_Legal_report: ตัดการประมูลนัดซ้ำของทรัพย์เดิมออก ยึดนัดแรกสุดที่ขายได้จริง
    all_report_records.sort(key=lambda r: (
        convert_thai_date_to_iso(r.get("วันที่ขาย", "")),
        str(r.get("รหัสหน่วยงาน", "")).strip(),
        str(r.get("ลำดับที่", "")).strip(),
    ))
    seen_final_props = set()
    clean_final_reports = []
    for r in all_report_records:
        prop_k = _report_dedup_key(r)
        if prop_k not in seen_final_props:
            seen_final_props.add(prop_k)
            clean_final_reports.append(r)
    all_report_records = clean_final_reports
    save_csv_safe(all_report_records, REPORT_COLUMNS, REPORT_CSV)

    # Merge with LED_NPA_New + historical catalog -> LED_Legal_merge (บริษัท = LED Legal)
    merged_records = build_led_legal_merge(report_records=all_report_records, report_csv_path=REPORT_CSV, merge_csv_path=MERGE_CSV)

    elapsed = time.time() - start_time
    if failed_units:
        final_status = "FAILED" if len(all_report_records) == 0 else "PARTIAL"
        save_scraper_state(
            COMPANY_NAME,
            len(done_agencies),
            total_agencies,
            len(all_report_records),
            status=final_status,
            month_str=REPORT_MONTH_STR,
            extra={"completed_agencies": list(done_agencies), "failed_units": failed_units[:100]}
        )
        print("\n==================================================", flush=True)
        print(f"⚠️ [{COMPANY_NAME}] สแครปเสร็จแบบมีรายการล้มเหลว ({final_status}) | สำเร็จ {len(done_agencies)}/{total_agencies} หน่วย | สะสม: {len(all_report_records):,d} รายการ", flush=True)
        print(f"⚠️ รายการที่ข้าม/ดึงไม่ได้ ({len(failed_units)} รายการ): {failed_units[:20]}", flush=True)
        print(f"🔗 เชื่อมข้อมูลสะสม (LED_Legal_merge / {MERGED_COMPANY_NAME}): {len(merged_records):,} รายการ", flush=True)
        log_warning(COMPANY_NAME, f"⚠️ สแครปเสร็จแบบ {final_status}: สำเร็จ {len(done_agencies)}/{total_agencies} หน่วย (ล้มเหลว {len(failed_units)} รายการ)")
        sys.exit(1 if len(all_report_records) == 0 else 2)

    save_scraper_state(
        COMPANY_NAME,
        total_agencies,
        total_agencies,
        len(all_report_records),
        status="COMPLETED",
        month_str=REPORT_MONTH_STR,
        extra={"completed_agencies": [a[0] for a in agencies], "partial_agency": "", "partial_day_idx": 0, "partial_completed_days": []}
    )

    print("\n==================================================", flush=True)
    print(f"✅ [{COMPANY_NAME}] สแครปและเชื่อมข้อมูลเสร็จสมบูรณ์! | ({total_agencies:3d}/{total_agencies:3d} หน่วย) | สะสม: {len(all_report_records):,d} รายการ", flush=True)
    print(f"📊 รายงานผลการขายได้ (LED_Legal_report): {len(all_report_records):,} รายการ (เพิ่มใหม่: {new_added:,} รายการ)", flush=True)
    print(f"🔗 เชื่อมข้อมูลสำเร็จ (LED_Legal_merge / {MERGED_COMPANY_NAME}): {len(merged_records):,} รายการ", flush=True)
    print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที", flush=True)
    print(f"💾 ไฟล์ Report CSV: {REPORT_CSV}", flush=True)
    print(f"💾 ไฟล์ Merge CSV : {MERGE_CSV}", flush=True)
    print("==================================================", flush=True)
    log_success(COMPANY_NAME, f"✅ สแครปเสร็จสมบูรณ์! Report {len(all_report_records):,} รายการ | Merge ({MERGED_COMPANY_NAME}) {len(merged_records):,} รายการ")

if __name__ == "__main__":
    main()
