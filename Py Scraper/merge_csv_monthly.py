import os
import glob
import sys
import time
import re
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build", "csv_output"] else _BASE_DIR

for _p in [_ROOT_DIR, os.path.join(_ROOT_DIR, "Py Scraper"), os.path.join(_ROOT_DIR, "Monthly all new")]:
    if _p not in sys.path and os.path.exists(_p):
        sys.path.insert(0, _p)

import clean_location_util
from clean_location_util import clean_row_location, clean_location_field, clean_price_val, clean_floor_val, init_gis, get_known_centroids_set, is_centroid_coord, clean_plaintiff_name
try:
    from clean_project_util import clean_sam_project_name, clean_project_name, extract_project_from_title
except ImportError:
    clean_sam_project_name = None
    clean_project_name = None
    extract_project_from_title = None
BASE_DIR = _ROOT_DIR
CURRENT_YM = datetime.now().strftime("%Y_%m")
MONTHLY_DIR = os.path.join(BASE_DIR, "CSV_Output", CURRENT_YM)
CSV_DIR = MONTHLY_DIR if os.path.exists(MONTHLY_DIR) else os.path.join(BASE_DIR, "CSV_Output")
CURRENT_YM_DISPLAY = datetime.now().strftime("%Y-%m")

# บันทึกแค่ไฟล์เดียวที่มีปี_เดือน
MASTER_CSV_TIMED = os.path.join(CSV_DIR, f"all_assets_monthly_{CURRENT_YM}.csv")

ROOT_DIR = _ROOT_DIR
ROOT_PARQUET = os.path.join(ROOT_DIR, "all_assets.parquet")

COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคา",
    "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ", "เลขโฉนด", "โจทก์", "ศาล",
    "ยอดเข้าชม", "ยอดคลิก", "ราคาขายได้", "วันที่ขาย"
]

# ตารางการจัดกลุ่มและแปลงประเภททรัพย์สินให้เป็นมาตรฐานเดียวกันทุกค่าย
_DEFAULT_PROPERTY_TYPE_MAPPING = {
    # 1. หมวดบ้านเดี่ยว
    "บ้าน": "บ้านเดี่ยว",
    "บ้านครึ่งตึกครึ่งไม้": "บ้านเดี่ยว",
    "บ้านพร้อมกิจการ": "บ้านเดี่ยว",
    
    # 2. หมวดคอนโดมิเนียม / ห้องชุด
    "ห้องชุด": "ห้องชุดพักอาศัย",
    "คอนโด": "ห้องชุดพักอาศัย",
    "คอนโดมิเนียม": "ห้องชุดพักอาศัย",
    "ห้องชุด/คอนโดมิเนียม": "ห้องชุดพักอาศัย",
    "ห้องชุด/ตอนโดมิเนียม": "ห้องชุดพักอาศัย",
    "คอนโดมิเนียม/อาคารชุด": "ห้องชุดพักอาศัย",
    "คอนโด/อาคารชุด/ห้องชุด": "ห้องชุดพักอาศัย",
    
    # 3. หมวดทาวน์เฮ้าส์ / ทาวน์โฮม
    "ทาวน์โฮม": "ทาวน์เฮ้าส์",
    "ทาวน์เฮาส์": "ทาวน์เฮ้าส์",
    "ทาวน์เฮ้าส์/ทาวน์โฮม": "ทาวน์เฮ้าส์",
    "ทาวน์โฮม/ทาวน์เฮ้าส์": "ทาวน์เฮ้าส์",
    "ทาวน์เฮาส์/ทาวน์โฮม": "ทาวน์เฮ้าส์",
    "ทาวน์โฮม/ทาวน์เฮาส์": "ทาวน์เฮ้าส์",
    
    # 4. หมวดที่ดิน
    "ที่ดิน": "ที่ดินเปล่า",
    "ที่ดินเปล่า": "ที่ดินเปล่า",
    "ที่ดินเกษตรกรรม": "ที่ดินเปล่า",
    "ที่ดินว่างเปล่า": "ที่ดินเปล่า",
    "ที่ดินพร้อมสิ่งปลูกสร้าง": "ที่ดินพร้อมสิ่งปลูกสร้าง",
    "สวนเกษตร": "ที่ดินเปล่า",
    
    # 5. หมวดโรงงาน / โกดัง
    "โรงงาน": "โรงงาน/โกดัง",
    "โกดัง": "โรงงาน/โกดัง",
    "อาคารโรงงาน": "โรงงาน/โกดัง",
    "โกดัง/โรงงาน": "โรงงาน/โกดัง",
    "โกดัง / โรงงาน": "โรงงาน/โกดัง",
    "มินิแฟคตอรี่": "โรงงาน/โกดัง",
    "โรงสี": "โรงงาน/โกดัง",
    
    # 6. หมวดอพาร์ทเมนท์ / หอพัก
    "อพาร์ทเม้นท์": "อพาร์ทเมนท์",
    "อพาร์ตเมนต์": "อพาร์ทเมนท์",
    "อพาตเมนต์": "อพาร์ทเมนท์",
    "หอพัก": "อพาร์ทเมนท์",
    "หอพัก/อพาร์ทเมนท์": "อพาร์ทเมนท์",
    "อพาร์ทเม้นท์/หอพัก": "อพาร์ทเมนท์",
    "แฟลต": "อพาร์ทเมนท์",
    "อาคารพักอาศัย": "อพาร์ทเมนท์",
    
    # 7. หมวดอาคารพาณิชย์ / ตึกแถว / ร้านค้า
    "ตึกแถว": "อาคารพาณิชย์",
    "ห้องแถว": "อาคารพาณิชย์",
    "ร้านค้า": "อาคารพาณิชย์",
    "ร้านอาหาร": "อาคารพาณิชย์",
    "ตลาดสด": "อาคารพาณิชย์",
    "ศูนย์จำหน่ายสินค้า": "อาคารพาณิชย์",
    "ห้างสรรพสินค้า": "อาคารพาณิชย์",
    "โชว์รูม": "อาคารพาณิชย์",
    
    # 8. หมวดสำนักงาน
    "สำนักงาน": "อาคารสำนักงาน",
    "อาคารที่ทำการสาขา": "อาคารสำนักงาน",
    "ห้องชุดสำนักงาน": "ห้องชุดพาณิชยกรรม/สำนักงาน",
    "ห้องชุดพาณิชยกรรม": "ห้องชุดพาณิชยกรรม/สำนักงาน",
    "Office": "อาคารสำนักงาน",
    "Office Building": "อาคารสำนักงาน",

    # 8.1 หมวดโฮมออฟฟิศ (แยกอิสระจากอาคารพาณิชย์และอาคารสำนักงาน)
    "โฮมออฟฟิศ": "โฮมออฟฟิศ",
    "โฮมออฟฟิต": "โฮมออฟฟิศ",
    "Home Office": "โฮมออฟฟิศ",
    "home office": "โฮมออฟฟิศ",
    "Homeoffice": "โฮมออฟฟิศ",
    "homeoffice": "โฮมออฟฟิศ",
    
    # 9. หมวดโรงแรม / รีสอร์ท
    "Hotel Building": "โรงแรม/รีสอร์ท",
    "โรงแรม": "โรงแรม/รีสอร์ท",
    "รีสอร์ท": "โรงแรม/รีสอร์ท",
    
    # 10. หมวดสังหาริมทรัพย์ & อื่นๆ
    "เครื่องจักร": "สังหาริมทรัพย์",
    "บัตรสมาชิกสนามกอล์ฟ": "สังหาริมทรัพย์",
    "ส่วนโล่งหลังคาคลุม": "อื่นๆ",
    "ฟาร์มเลี้ยงสัตว์": "ฟาร์ม",
    "สถานีบริการน้ำมัน": "ปั๊มน้ำมัน",
    "ศูนย์บริการ/โชว์รูม/ปั้มน้ำมัน": "ปั๊มน้ำมัน",
    "โรงภาพยนต์": "อื่นๆ",
    "สวนน้ำ": "อื่นๆ",
    "โรงพยาบาล": "อื่นๆ",
    "อาคารจอดรถ": "อื่นๆ",
    "บ้านพักคนงาน": "อื่นๆ",
    "อาคาร": "อื่นๆ",
    "Public Service": "อื่นๆ",
    "โครงการที่พักอาศัย/พาณิชยกรรม": "อื่นๆ",
    "อสังหาริมทรัพย์อื่นๆ": "อื่นๆ",
}
try:
    from modules.config.constants import (
        PROPERTY_TYPE_MAPPING as _CONST_PROP_MAP,
        SALE_TYPE_MAPPING as _CONST_SALE_MAP,
    )
    PROPERTY_TYPE_MAPPING = {**_DEFAULT_PROPERTY_TYPE_MAPPING, **_CONST_PROP_MAP}
except ImportError:
    PROPERTY_TYPE_MAPPING = _DEFAULT_PROPERTY_TYPE_MAPPING
    _CONST_SALE_MAP = None

def parse_rai_ngan_wah_robust(s):
    if s is None or pd.isna(s):
        return None, None, None
    s = str(s).strip()
    if not s or s.lower() in ["nan", "none", "null", "$undefined", "-", "0", "0.0", "."]:
        return None, None, None
    
    # 1. Dash pattern: R-N-W
    m_dash = re.match(r'^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$', s)
    if m_dash:
        try:
            return float(m_dash.group(1)), float(m_dash.group(2)), float(m_dash.group(3))
        except ValueError:
            pass
        
    # 2. Thai explicit units: ไร่, งาน, วา / ตร.ว. / ตารางวา
    has_thai_units = any(u in s for u in ['ไร่', 'งาน', 'วา', 'ตร.ว', 'ตารางวา', 'ตร.ว.'])
    if has_thai_units:
        m_r = re.search(r'([\d\.,]+)\s*ไร่', s)
        m_g = re.search(r'([\d\.,]+)\s*งาน', s)
        m_w = re.search(r'([\d\.,]+)\s*(?:ตร\.?ว\.?|ตารางวา|วา)', s)
        
        r, g, w = 0.0, 0.0, 0.0
        try:
            if m_r: r = float(m_r.group(1).replace(',', ''))
        except ValueError: pass
        try:
            if m_g: g = float(m_g.group(1).replace(',', ''))
        except ValueError: pass
        try:
            if m_w: w = float(m_w.group(1).replace(',', ''))
        except ValueError: pass
        
        if r > 0 or g > 0 or w > 0:
            return r, g, w

    # 3. Clean numeric with optional unit suffix
    clean_num = re.sub(r'[^\d\.]', '', s)
    if clean_num and clean_num != '.' and clean_num != '..':
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

def resolve_mixed_property_types(df):
    """Resolves fallback mixed property types (e.g. 'บ้านเดี่ยว/ทาวน์เฮาส์', 'อาคารพาณิชย์/โฮมออฟฟิศ') based on listing title."""
    if 'ประเภททรัพย์' not in df.columns:
        return df

    # แยก 'อาคารพาณิชย์/โฮมออฟฟิศ' ออกเป็น อาคารพาณิชย์ และ โฮมออฟฟิศ
    comm_mask = df['ประเภททรัพย์'].astype(str).str.contains('อาคารพาณิชย์/โฮมออฟฟิศ|โฮมออฟฟิศ/อาคารพาณิชย์', na=False)
    if comm_mask.any():
        def resolve_comm_row(row):
            title = (str(row.get('ชื่อประกาศ', '')) + ' ' + str(row.get('ชื่อโครงการ', ''))).lower()
            if any(k in title for k in ['โฮมออฟฟิศ', 'โฮมออฟฟิต', 'home office', 'homeoffice']):
                return 'โฮมออฟฟิศ'
            return 'อาคารพาณิชย์'
        df.loc[comm_mask, 'ประเภททรัพย์'] = df[comm_mask].apply(resolve_comm_row, axis=1)
    
    mask = df['ประเภททรัพย์'].astype(str).str.contains('บ้านเดี่ยว/ทาวน์', na=False)
    if not mask.any():
        return df
        
    def resolve_row(row):
        title = str(row.get('ชื่อประกาศ', '')) + ' ' + str(row.get('ชื่อโครงการ', ''))
        t = title.lower()
        if any(k in t for k in ['ตึกแถว', 'อาคารพาณิชย์', 'shophouse', 'พาณิชย์']):
            return 'อาคารพาณิชย์'
        if any(k in t for k in ['โฮมออฟฟิศ', 'โฮมออฟฟิต', 'home office', 'homeoffice']):
            return 'โฮมออฟฟิศ'
        if any(k in t for k in ['สำนักงาน', 'office']):
            return 'อาคารสำนักงาน'
        if any(k in t for k in ['โกดัง', 'โรงงาน', 'warehouse', 'factory']):
            return 'โรงงาน/โกดัง'
        if any(k in t for k in ['ทาวน์โฮม', 'ทาวน์เฮ้าส์', 'ทาวน์เฮาส์', 'townhome', 'townhouse', 'ทาวน์']):
            return 'ทาวน์เฮ้าส์'
        if any(k in t for k in ['ที่ดิน', 'land']):
            return 'ที่ดินเปล่า'
        if any(k in t for k in ['คอนโด', 'ห้องชุด', 'condo']):
            return 'ห้องชุดพักอาศัย'
        return 'บ้านเดี่ยว'
        
    df.loc[mask, 'ประเภททรัพย์'] = df[mask].apply(resolve_row, axis=1)
    return df

def merge_monthly_csv(target_ym=None, generate_parquet=True):
    global CSV_DIR, CURRENT_YM, CURRENT_YM_DISPLAY, MASTER_CSV_TIMED
    
    if target_ym:
        CURRENT_YM = target_ym
        MONTHLY_DIR = os.path.join(BASE_DIR, "CSV_Output", CURRENT_YM)
        CSV_DIR = MONTHLY_DIR if os.path.exists(MONTHLY_DIR) else os.path.join(BASE_DIR, "CSV_Output")
        CURRENT_YM_DISPLAY = CURRENT_YM.replace("_", "-")
        MASTER_CSV_TIMED = os.path.join(CSV_DIR, f"all_assets_monthly_{CURRENT_YM}.csv")
    else:
        # Check if current CSV_DIR has raw scraper files
        curr_files = [f for f in glob.glob(os.path.join(CSV_DIR, "*.csv")) if not os.path.basename(f).startswith("all_assets")]
        if not curr_files:
            all_subdirs = sorted([d for d in glob.glob(os.path.join(BASE_DIR, "CSV_Output", "*")) if os.path.isdir(d) and " - " not in os.path.basename(d)], reverse=True)
            for sub in all_subdirs:
                sub_files = [f for f in glob.glob(os.path.join(sub, "*.csv")) if not os.path.basename(f).startswith("all_assets")]
                if sub_files:
                    CSV_DIR = sub
                    CURRENT_YM = os.path.basename(sub)
                    CURRENT_YM_DISPLAY = CURRENT_YM.replace("_", "-")
                    MASTER_CSV_TIMED = os.path.join(CSV_DIR, f"all_assets_monthly_{CURRENT_YM}.csv")
                    break

    print("==========================================================================", flush=True)
    print("📊 เริ่มต้นการรวมไฟล์ CSV ทั้งหมดจาก Py Scraper/CSV_Output/", flush=True)
    print(f"📅 ประจำรอบเดือน-ปี: {CURRENT_YM_DISPLAY}", flush=True)
    print("==========================================================================", flush=True)
    
    t_merge_start = time.time()
    t_merge_clock = datetime.now().strftime("%H:%M:%S")
    try:
        from logger_util import log_start
        log_start("MERGE", f"เวลาเริ่ม: {t_merge_clock} (เริ่มต้นรวมไฟล์ข้อมูล Monthly CSV)", start_clock=t_merge_clock)
    except Exception:
        pass
    
    csv_files = glob.glob(os.path.join(CSV_DIR, "*.csv"))
    csv_files = [
        f for f in csv_files 
        if not os.path.basename(f).startswith("all_assets_monthly")
        and not os.path.basename(f).startswith("all_assets_")
        and not os.path.basename(f).startswith("LED_Legal_report")
        and not f.endswith("_BACKUP.csv")
        and not f.endswith(".bak")
        and " - copy" not in os.path.basename(f).lower()
    ]
    
    # ตรวจสอบและเลือกไฟล์ผลขายทอดตลาด (LED_Legal_merge):
    # หากมีไฟล์รวมหลายเดือน (เช่น LED_Legal_merge_2026_9-10.csv หรือข้ามปี 2026_12-2027_1) ให้ใช้ไฟล์รวมนี้เป็นหลัก
    # และตัดไฟล์รายเดือนเดี่ยว (เช่น LED_Legal_merge_2026_10.csv) ออกเพื่อป้องกันการนับซ้ำ
    multi_led_pattern = re.compile(r"^LED_Legal_merge_\d{4}_\d{1,2}-(?:\d{4}_)?\d{1,2}\.csv$", re.IGNORECASE)
    multi_led_merge = [f for f in csv_files if multi_led_pattern.match(os.path.basename(f))]
    if not multi_led_merge:
        # ลองค้นหาไฟล์รวมหลายเดือนเฉพาะในโฟลเดอร์เดือนปัจจุบัน, CSV_Output หลัก และเดือนก่อนหน้า (ไม่ค้นหาทั้ง tree เก่า)
        search_dirs = [CSV_DIR, os.path.join(BASE_DIR, "CSV_Output")]
        try:
            cur_dt = datetime.strptime(CURRENT_YM, "%Y_%m")
            prev_ym = (cur_dt.replace(day=1) - timedelta(days=1)).strftime("%Y_%m")
            search_dirs.append(os.path.join(BASE_DIR, "CSV_Output", prev_ym))
        except Exception:
            pass
        cands_multi = []
        for sdir in search_dirs:
            if os.path.isdir(sdir):
                for p in glob.glob(os.path.join(sdir, "LED_Legal_merge_*.csv")):
                    if multi_led_pattern.match(os.path.basename(p)) and os.path.exists(p):
                        cands_multi.append(os.path.abspath(p))
        cands_multi = list(set(cands_multi))
        if cands_multi:
            cands_multi.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            chosen_cand = cands_multi[0]
            multi_led_merge = [chosen_cand]
            csv_files.append(chosen_cand)
            print(f"  📎 ดึงผลการขายทอดตลาดรวมหลายเดือนมารวม: {os.path.basename(chosen_cand)}", flush=True)

    if multi_led_merge:
        chosen_multi = sorted(multi_led_merge, key=lambda p: os.path.getmtime(p), reverse=True)[0]
        # คัดเอาเฉพาะ chosen_multi และตัดไฟล์ LED_Legal_merge ตัวอื่นๆ ออก
        csv_files = [f for f in csv_files if not os.path.basename(f).startswith("LED_Legal_merge") or os.path.abspath(f) == os.path.abspath(chosen_multi)]
        print(f"  🎯 ใช้ไฟล์ผลการขายทอดตลาดแบบรวมหลายเดือน: {os.path.basename(chosen_multi)}", flush=True)
    else:
        # หากไม่มีไฟล์รวมหลายเดือน ตรวจสอบและดึงไฟล์เดือนก่อนหน้าตามปกติ
        has_led_merge = any(os.path.basename(f).startswith("LED_Legal_merge") for f in csv_files)
        if not has_led_merge:
            try:
                cur_dt = datetime.strptime(CURRENT_YM, "%Y_%m")
                prev_dt = cur_dt.replace(day=1) - timedelta(days=1)
                prev_ym = prev_dt.strftime("%Y_%m")
                prev_led_merge = os.path.join(BASE_DIR, "CSV_Output", prev_ym, f"LED_Legal_merge_{prev_ym}.csv")
                if os.path.exists(prev_led_merge):
                    csv_files.append(prev_led_merge)
                    print(f"  📎 ดึงผลการขายทอดตลาดเดือนก่อนหน้ามารวม: {os.path.basename(prev_led_merge)}", flush=True)
            except Exception:
                pass
    
    if not csv_files:
        print(f"⚠️ ไม่พบไฟล์ CSV ในโฟลเดอร์ {CSV_DIR}", flush=True)
        return False
        
    init_gis()
    try:
        from enrich_led_landsmaps import (
            clean_deed_number as _lm_clean_deed,
            clean_district_name as _lm_clean_dist,
            clean_province_name as _lm_clean_prov,
            is_valid_thailand_real_coord as _lm_valid_coord,
        )
    except ImportError:
        _lm_clean_deed = None
        _lm_clean_dist = None
        _lm_clean_prov = None
        _lm_valid_coord = None

    dfs = []
    for f in sorted(csv_files):
        try:
            df = pd.read_csv(f, encoding="utf-8-sig", dtype=str)
            orig_owner = (
                df['บริษัทเจ้าของทรัพย์'].copy()
                if 'บริษัทเจ้าของทรัพย์' in df.columns
                else (df['บริษัท'].copy() if 'บริษัท' in df.columns else pd.Series("", index=df.index))
            )
            for col in COLUMNS:
                if col not in df.columns:
                    df[col] = ""
            df = df[COLUMNS]
            df['บริษัทเจ้าของทรัพย์'] = orig_owner.fillna('').astype(str)
            
            # แปลงคอลัมน์ เนื้อที่ (ตร.ว.) ให้เป็นรูปแบบ ไร่-งาน-ตร.ว. (เช่น 1-1-1, 0-1-1, 0-0-1)
            if 'เนื้อที่ (ตร.ว.)' in df.columns:
                df['เนื้อที่ (ตร.ว.)'] = df['เนื้อที่ (ตร.ว.)'].apply(convert_to_rai_ngan_wah)

            # คลีนราคา: ราคาต่ำกว่า 500 บาท ให้เว้นว่างไว้ (None / "")
            if 'ราคา' in df.columns:
                df['ราคา'] = df['ราคา'].apply(clean_price_val)
            if 'ราคาขายได้' in df.columns:
                df['ราคาขายได้'] = df['ราคาขายได้'].apply(clean_price_val)

            # คัดกรองรายการที่เป็นเงินวางหลักประกันออกจาก LED_Legal_merge (ราคาขายได้ < 50% ของราคาประเมิน)
            is_led_sold = os.path.basename(f).startswith("LED_Legal_merge")
            if is_led_sold and 'ราคาขายได้' in df.columns and 'ราคา' in df.columns:
                p_appr = pd.to_numeric(df['ราคา'].astype(str).str.replace(',', '').str.strip(), errors='coerce')
                p_sold = pd.to_numeric(df['ราคาขายได้'].astype(str).str.replace(',', '').str.strip(), errors='coerce')
                is_deposit_mask = (p_appr > 0) & (p_sold > 0) & ((p_sold / p_appr) < 0.50)
                if is_deposit_mask.any():
                    drop_cnt = int(is_deposit_mask.sum())
                    df = df[~is_deposit_mask].copy()
                    print(f"  🛡️ คัดกรองรายการเงินวางหลักประกันออกจาก {os.path.basename(f)} จำนวน {drop_cnt:,} รายการ (< 50% ของราคาประเมิน)", flush=True)

            # ทำความสะอาดคอลัมน์ชั้น
            if 'ชั้น' in df.columns:
                if 'พื้นที่ใช้สอย (ตร.ม.)' in df.columns:
                    df['ชั้น'] = [clean_floor_val(fl, u) for fl, u in zip(df['ชั้น'], df['พื้นที่ใช้สอย (ตร.ม.)'])]
                else:
                    df['ชั้น'] = df['ชั้น'].apply(clean_floor_val)

            # ทำความสะอาดคอลัมน์ที่อยู่ (ตำบล, อำเภอ, จังหวัด) และซิงค์พิกัด GIS ความเร็วสูง
            is_led_sold = os.path.basename(f).startswith("LED_Legal_merge")
            records = df.to_dict(orient="records")
            for r in records:
                if is_led_sold:
                    clean_row_location(r, impute_coords=False)
                    if is_centroid_coord(r.get("ละติจูด"), r.get("ลองจิจูด")):
                        r["ละติจูด"] = ""
                        r["ลองจิจูด"] = ""
                else:
                    clean_row_location(r)
            df = pd.DataFrame(records)
            # คลีนสตริง 'nan' ในคอลัมน์ที่อยู่และพิกัด (เว้นว่างไว้หากไม่มีพิกัดจริง)
            for tc in ['ตำบล', 'อำเภอ', 'จังหวัด', 'ละติจูด', 'ลองจิจูด']:
                if tc in df.columns:
                    df[tc] = df[tc].astype(str).replace({'nan': '', 'None': '', 'null': '', 'undefined': '', '<NA>': '', 'NaN': ''})
                    df[tc] = df[tc].apply(lambda x: '' if str(x).strip().lower() in ['nan', 'none', 'null', 'undefined'] else str(x).strip())

            # ทำความสะอาดและจัดมาตรฐานชื่อโครงการ (Project Name Normalization & Recovery)
            if 'ชื่อโครงการ' in df.columns:
                fn_clean = clean_project_name or clean_sam_project_name
                if fn_clean is not None:
                    has_geo = all(c in df.columns for c in ['ตำบล', 'อำเภอ', 'จังหวัด'])
                    clean_cache = {}
                    title_cache = {}
                    cleaned_projs = []
                    
                    projs = df['ชื่อโครงการ'].fillna('').astype(str).tolist()
                    titles = df['ชื่อประกาศ'].fillna('').astype(str).tolist() if 'ชื่อประกาศ' in df.columns else [''] * len(df)
                    tbs = df['ตำบล'].fillna('').astype(str).tolist() if 'ตำบล' in df.columns else [''] * len(df)
                    aps = df['อำเภอ'].fillna('').astype(str).tolist() if 'อำเภอ' in df.columns else [''] * len(df)
                    pvs = df['จังหวัด'].fillna('').astype(str).tolist() if 'จังหวัด' in df.columns else [''] * len(df)
                    cps = df['บริษัท'].fillna('').astype(str).tolist() if 'บริษัท' in df.columns else [''] * len(df)
                    
                    for orig_p, title_p, tb, ap, pv, cp in zip(projs, titles, tbs, aps, pvs, cps):
                        ckey = (orig_p, tb, ap, pv, cp)
                        if ckey in clean_cache:
                            cln = clean_cache[ckey]
                        else:
                            cln = fn_clean(orig_p, tambon=tb, amphoe=ap, province=pv, company=cp) if has_geo else fn_clean(orig_p)
                            clean_cache[ckey] = cln
                        
                        if not cln and title_p and extract_project_from_title is not None:
                            tkey = (title_p, tb, ap, pv, cp)
                            if tkey in title_cache:
                                cln = title_cache[tkey]
                            else:
                                cln = extract_project_from_title(title_p, tambon=tb, amphoe=ap, province=pv, company=cp)
                                title_cache[tkey] = cln
                        cleaned_projs.append(cln)
                    df['ชื่อโครงการ'] = cleaned_projs

            has_owner_col = 'บริษัทเจ้าของทรัพย์' in df.columns
            out_cols = list(COLUMNS) + (['บริษัทเจ้าของทรัพย์'] if has_owner_col else [])
            for col in COLUMNS:
                if col not in df.columns:
                    df[col] = ""
            df = df[out_cols]

            company_name = "LED Legal" if os.path.basename(f).startswith("LED_Legal_merge") else os.path.basename(f).split('_')[0]
            # Ensure primary company name is set correctly for dashboard filters while preserving owner company
            if company_name in ['Baania', 'BAM', 'SAM', 'ZmyHome', 'Chayo555', 'NaYoo', 'GHB', 'KBANK', 'KTB', 'SCB', 'GSB', 'LED', 'LED Legal', 'LED_SOLD', 'DDproperty', 'Livinginsider']:
                if not has_owner_col:
                    df['บริษัทเจ้าของทรัพย์'] = df['บริษัท']
                df['บริษัท'] = company_name

            # ซิงค์พิกัดจริงจาก LandsMaps ให้กับ กรมบังคับคดี (LED) หากมีข้อมูลในแคช
            if company_name in ('LED', 'LED Legal', 'LED_SOLD'):
                cache_file = os.path.join(ROOT_DIR, "data", "led_coords_cache.parquet")
                if os.path.exists(cache_file):
                    try:
                        cache_df = pd.read_parquet(cache_file)
                        cset = get_known_centroids_set()
                        found_cache = cache_df[cache_df['สถานะ'] == 'FOUND'].dropna(subset=['ละติจูด', 'ลองจิจูด']).copy()
                        if not found_cache.empty:
                            if _lm_valid_coord is not None:
                                valid_coord_mask = [_lm_valid_coord(la, lo, cset) for la, lo in zip(found_cache['ละติจูด'], found_cache['ลองจิจูด'])]
                            else:
                                la_n = pd.to_numeric(found_cache['ละติจูด'], errors='coerce')
                                lo_n = pd.to_numeric(found_cache['ลองจิจูด'], errors='coerce')
                                valid_coord_mask = (la_n.between(5.5, 20.6) & lo_n.between(97.3, 105.7))
                            found_cache = found_cache[valid_coord_mask].copy()

                        if not found_cache.empty and 'เลขโฉนด' in df.columns:
                            def _clean_d(v):
                                if _lm_clean_deed is not None:
                                    return _lm_clean_deed(v)
                                if pd.isna(v): return ''
                                s = str(v).strip()
                                if s.endswith('.0'): s = s[:-2]
                                m_first = re.search(r'\d+', s)
                                return m_first.group(0).lstrip('0') or '0' if m_first else s

                            def _clean_pv(p_val):
                                if _lm_clean_prov is not None:
                                    return _lm_clean_prov(p_val)
                                s = '' if pd.isna(p_val) else re.sub(r'^(จ\.|จังหวัด)\s*', '', str(p_val)).strip()
                                return 'อุตรดิตถ์' if s == 'อุตรดิต' else s

                            def _clean_amp(a_val, p_val):
                                if _lm_clean_dist is not None:
                                    a_s = _lm_clean_dist(a_val)
                                else:
                                    a_s = '' if pd.isna(a_val) else re.sub(r'^(อ\.|อำเภอ|เขต)\s*', '', str(a_val)).strip()
                                    a_s = re.sub(r'\(.*?\)', '', a_s).strip()
                                p_s = _clean_pv(p_val)
                                if a_s == 'เมือง' and p_s:
                                    a_s = f'เมือง{p_s}'
                                return a_s

                            found_cache['deed_key'] = found_cache['เลขโฉนด'].apply(_clean_d)
                            found_cache['prov_key'] = found_cache['จังหวัด'].apply(_clean_pv)
                            if 'อำเภอ' in found_cache.columns:
                                found_cache['amp_key'] = [_clean_amp(a, p) for a, p in zip(found_cache['อำเภอ'], found_cache['prov_key'])]
                            else:
                                found_cache['amp_key'] = ''
                            valid_cache = found_cache[(found_cache['deed_key'] != '') & (found_cache['prov_key'] != '') & (found_cache['amp_key'] != '')]
                            coord_lookup = dict(zip(
                                zip(valid_cache['prov_key'], valid_cache['amp_key'], valid_cache['deed_key']),
                                zip(valid_cache['ละติจูด'].astype(str), valid_cache['ลองจิจูด'].astype(str))
                            ))
                            
                            df_deed = df['เลขโฉนด'].apply(_clean_d)
                            df_prov = df['จังหวัด'].apply(_clean_pv)
                            df_amp = [_clean_amp(a, p) for a, p in zip(df['อำเภอ'], df_prov)] if 'อำเภอ' in df.columns else [''] * len(df)
                            keys = list(zip(df_prov, df_amp, df_deed))
                            matched = [coord_lookup.get(k) for k in keys]
                            mask = [m is not None for m in matched]
                            enrich_cnt = sum(mask)
                            if enrich_cnt > 0:
                                df.loc[mask, 'ละติจูด'] = [m[0] for m in matched if m is not None]
                                df.loc[mask, 'ลองจิจูด'] = [m[1] for m in matched if m is not None]
                                print(f"  🎯 ซิงค์พิกัดจริงจาก LandsMaps ให้กับ {company_name} สำเร็จ {enrich_cnt:,d} รายการ (จาก cache โดยไม่เขียนทับไฟล์ดิบ)", flush=True)
                    except Exception as e_cache:
                        print(f"  [!] ไม่สามารถอ่าน LandsMaps Cache ได้: {e_cache}", flush=True)

            if company_name in ("LED Legal", "LED_SOLD") and 'ละติจูด' in df.columns and 'ลองจิจูด' in df.columns:
                cset = get_known_centroids_set()
                lat_s = pd.to_numeric(df['ละติจูด'], errors='coerce')
                lon_s = pd.to_numeric(df['ลองจิจูด'], errors='coerce')
                valid_th = lat_s.between(5.5, 20.6) & lon_s.between(97.3, 105.7)
                c_keys = lat_s.round(5).astype(str) + ',' + lon_s.round(5).astype(str)
                bad_c = (~valid_th) | (c_keys.isin(cset) if cset else False)
                bad_c &= (lat_s.notna() | lon_s.notna())
                if bad_c.any():
                    df.loc[bad_c, ['ละติจูด', 'ลองจิจูด']] = ''

            print(f"  [+] โหลด {company_name:<13s}: {len(df):,d} รายการ ({os.path.basename(f)})", flush=True)
            dfs.append(df)
        except Exception as e:
            print(f"  [-] อ่านไฟล์ {f} ล้มเหลว: {e}", flush=True)
            
    if not dfs:
        print("❌ ไม่พบข้อมูลสำหรับรวมไฟล์", flush=True)
        return False
        
    combined_df = pd.concat(dfs, ignore_index=True)
    
    # ทำความสะอาดและจัดกลุ่มประเภททรัพย์สินให้เป็นมาตรฐานเดียวกัน
    if 'ประเภททรัพย์' in combined_df.columns:
        combined_df['ประเภททรัพย์'] = (
            combined_df['ประเภททรัพย์']
            .fillna('')
            .astype(str)
            .str.strip()
            .replace({'nan': '', 'None': '', 'null': '', '<NA>': '', 'ไม่มีข้อมูล': ''})
            .replace(PROPERTY_TYPE_MAPPING)
        )
        combined_df = resolve_mixed_property_types(combined_df)
        combined_df['ประเภททรัพย์'] = (
            combined_df['ประเภททรัพย์']
            .astype(str)
            .str.strip()
            .replace({'': 'อื่นๆ'})
            .replace(PROPERTY_TYPE_MAPPING)
        )
        print("  ✨ จัดกลุ่มประเภททรัพย์สิน (Property Type Normalization) เรียบร้อยแล้ว", flush=True)
        
    # ทำความสะอาดและจัดกลุ่มประเภทการขาย (ตัด 'ให้เช่า' และ 'ทรัพย์ NPL' ออก)
    if 'ประเภทการขาย' in combined_df.columns:
        combined_df = combined_df[~combined_df['ประเภทการขาย'].astype(str).str.strip().isin(['ให้เช่า', 'เช่า'])]
        combined_df = combined_df[~combined_df['ประเภทการขาย'].astype(str).str.contains('NPL', case=False, na=False)]
        sale_map = _CONST_SALE_MAP if _CONST_SALE_MAP is not None else {
            # ขายทอดตลาด (ปลอดจำนอง)
            'ปลอดการจำนอง': 'ขายทอดตลาด (ปลอดจำนอง)',
            'ไม่มีภาระจำนอง': 'ขายทอดตลาด (ปลอดจำนอง)',
            'ปลอดภาระผูกพัน': 'ขายทอดตลาด (ปลอดจำนอง)',
            'ไม่มีภาระจำนำ': 'ขายทอดตลาด (ปลอดจำนอง)',
            'ประมูล': 'ขายทอดตลาด (ปลอดจำนอง)',
            
            # ขายทอดตลาด (จำนองติดไป)
            'การจำนองติดไป': 'ขายทอดตลาด (จำนองติดไป)',
            'การจำนำติดไป': 'ขายทอดตลาด (จำนองติดไป)',
            
            # ขายตรง
            'ซื้อตรง': 'ขาย',
            'ทรัพย์ธนาคาร': 'ขาย',
            'ทรัพย์โปรโมชั่นราคาพิเศษ': 'ขาย',
            'ทรัพย์โปรโมชันราคาพิเศษ': 'ขาย',
            'โปรโมชั่น': 'ขาย',
            'โปรโมชัน': 'ขาย',
            'ทรัพย์ฝากขาย': 'ขาย',
            'ฝากขาย': 'ขาย',
            'ขายดาวน์': 'ขาย',
            'ขาย/เช่า': 'ขาย',
            'ไม่มีข้อมูล': 'ขาย',
        }
        combined_df['ประเภทการขาย'] = (
            combined_df['ประเภทการขาย']
            .fillna('ขาย')
            .astype(str)
            .str.strip()
            .replace({'': 'ขาย', 'nan': 'ขาย', 'None': 'ขาย', '<NA>': 'ขาย', 'ไม่มีข้อมูล': 'ขาย'})
            .replace(sale_map)
        )
        print("  ✨ จัดกลุ่มประเภทการขาย (ขายทอดตลาด ปลอดจำนอง/จำนองติดไป, รวมทรัพย์ธนาคารเข้า 'ขาย', ตัด 'ให้เช่า' และ 'ทรัพย์ NPL' ออก) เรียบร้อยแล้ว", flush=True)
    
    # แปลงคอลัมน์ เนื้อที่ (ตร.ว.) ให้เป็นรูปแบบ ไร่-งาน-ตร.ว. (เช่น 1-1-1, 0-1-1, 0-0-1)
    if 'เนื้อที่ (ตร.ว.)' in combined_df.columns:
        combined_df['เนื้อที่ (ตร.ว.)'] = combined_df['เนื้อที่ (ตร.ว.)'].apply(convert_to_rai_ngan_wah)
        if 'บริษัท' in combined_df.columns and 'ประเภททรัพย์' in combined_df.columns:
            zmy_condo_mask = (combined_df['บริษัท'] == 'ZmyHome') & (combined_df['ประเภททรัพย์'].astype(str).str.contains('ห้องชุด|คอนโด', na=False))
            if zmy_condo_mask.any():
                combined_df.loc[zmy_condo_mask, 'เนื้อที่ (ตร.ว.)'] = ''
            zmy_land_mask = (combined_df['บริษัท'] == 'ZmyHome') & (combined_df['ประเภททรัพย์'].astype(str).isin(['ที่ดิน', 'ที่ดินเปล่า', 'ที่ดินเกษตรกรรม', 'ที่ดินว่างเปล่า']))
            if zmy_land_mask.any() and 'พื้นที่ใช้สอย (ตร.ม.)' in combined_df.columns:
                combined_df.loc[zmy_land_mask, 'พื้นที่ใช้สอย (ตร.ม.)'] = ''
        print("  ✨ แปลงคอลัมน์ 'เนื้อที่ (ตร.ว.)' เป็นรูปแบบ ไร่-งาน-ตร.ว. (เช่น 1-1-1, 0-1-1, 0-0-1) เรียบร้อยแล้ว", flush=True)

    # คลีนสตริง 'nan', 'None' ในคอลัมน์ข้อความทั้งหมดให้เว้นว่างไว้ ""
    text_cols_to_clean = ['ตำบล', 'อำเภอ', 'จังหวัด', 'ชื่อโครงการ', 'ชื่อประกาศ', 'ลิงก์', 'เลขโฉนด', 'โจทก์', 'ศาล']
    for tc in text_cols_to_clean:
        if tc in combined_df.columns:
            combined_df[tc] = combined_df[tc].astype(str).replace({'nan': '', 'None': '', 'null': '', 'undefined': '', '<NA>': '', 'NaN': ''})
            combined_df[tc] = combined_df[tc].apply(lambda x: '' if str(x).strip().lower() in ['nan', 'none', 'null', 'undefined'] else str(x).strip())
    if 'โจทก์' in combined_df.columns:
        combined_df['โจทก์'] = combined_df['โจทก์'].apply(clean_plaintiff_name)
    print("  ✨ ล้างค่าสตริง 'nan' / 'None' ให้เป็นช่องว่างเรียบร้อยแล้ว", flush=True)

    def safe_write_csv(df_in, target_path, label):
        for attempt in range(3):
            tmp_path = target_path + f".tmp.{os.getpid()}"
            try:
                df_in.to_csv(tmp_path, index=False, encoding="utf-8-sig")
                os.replace(tmp_path, target_path)
                print(f"💾 [{label}] บันทึกสำเร็จ: {target_path}", flush=True)
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
                    df_in.to_csv(alt_path, index=False, encoding="utf-8-sig")
                    print(f"⚠️ [{label}] ไฟล์ถูกเปิดล็อกไว้ใน Excel -> บันทึกข้อมูลสำรองไว้ที่ {alt_path} แทน", flush=True)
                    return True
            except Exception:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                raise
        return False

    # บันทึกไฟล์เดียวที่มี ปี_เดือน
    safe_write_csv(combined_df, MASTER_CSV_TIMED, f"MASTER CSV ({CURRENT_YM})")
    
    # ลบไฟล์ซ้ำซ้อนที่ไม่จำเป็นออก
    redundant_files = [
        os.path.join(CSV_DIR, "all_assets_monthly.csv"),
        os.path.join(ROOT_DIR, "all_assets.csv"),
        os.path.join(ROOT_DIR, f"all_assets_{CURRENT_YM}.csv"),
        os.path.join(ROOT_DIR, "all_asset.parquet"),
        os.path.join(BASE_DIR, "CSV_Output", "all_asset.parquet"),
        os.path.join(BASE_DIR, "CSV_Output", "all_assets.parquet"),
    ]
    for rf in redundant_files:
        if os.path.exists(rf):
            try:
                os.remove(rf)
            except Exception:
                pass
                
    # แปลงและอัปเดต Parquet ความเร็วสูงสำหรับ Dashboard (เฉพาะ Root all_assets.parquet และสำเนารายเดือน 1 ชุด)
    if not generate_parquet:
        print("⏭️ [PARQUET]    ข้ามการบันทึกไฟล์ Parquet ตามที่กำหนด (บันทึกเฉพาะ CSV เท่านั้น)", flush=True)
    else:
        monthly_parquet_dst = os.path.join(CSV_DIR, "all_assets.parquet")
        try:
            print("🚀 [PARQUET]    เริ่มการแปลงไฟล์ Parquet ความเร็วสูงด้วยไปป์ไลน์หลัก (Deduplication + Derived Cols)...", flush=True)
            conv_script_dir = _ROOT_DIR
            if conv_script_dir not in sys.path:
                sys.path.insert(0, conv_script_dir)
            import convert_csv_to_parquet
            # Run unified conversion pipeline (writes ONLY ROOT_PARQUET)
            conv_success = convert_csv_to_parquet.convert_csv_to_parquet(
                input_path=MASTER_CSV_TIMED,
                output_path=ROOT_PARQUET,
                exclude_unwanted=True
            )
            if conv_success:
                import shutil
                if os.path.exists(ROOT_PARQUET) and os.path.abspath(monthly_parquet_dst) != os.path.abspath(ROOT_PARQUET):
                    try:
                        os.makedirs(os.path.dirname(monthly_parquet_dst), exist_ok=True)
                        _tmp_cp = f"{monthly_parquet_dst}.tmp.{os.getpid()}"
                        shutil.copy2(ROOT_PARQUET, _tmp_cp)
                        os.replace(_tmp_cp, monthly_parquet_dst)
                    except Exception:
                        pass
                print(f"🚀 [PARQUET]    บันทึกสำเนารายเดือน: {monthly_parquet_dst}", flush=True)
                print(f"🚀 [PARQUET]    อัปเดตไฟล์ความเร็วสูง Dashboard: {ROOT_PARQUET} สมบูรณ์ 100%", flush=True)
        except Exception as e:
            print(f"⚠️ เตือน: ไม่สามารถบันทึก Parquet ผ่าน convert_csv_to_parquet ได้ ({e}) -> ใช้ Fallback สำรอง...", flush=True)
            try:
                df_p = combined_df.copy()
                if 'ประเภทการขาย' in df_p.columns:
                    df_p = df_p[~df_p['ประเภทการขาย'].astype(str).str.strip().isin(['ให้เช่า', 'เช่า'])].copy()
                df_p["ราคา"] = pd.to_numeric(df_p["ราคา"], errors="coerce").astype("float64")
                df_p.loc[df_p["ราคา"] < 500, "ราคา"] = np.nan
                if "ราคาขายได้" in df_p.columns:
                    df_p["ราคาขายได้"] = pd.to_numeric(df_p["ราคาขายได้"], errors="coerce").astype("float64")
                    df_p.loc[df_p["ราคาขายได้"] <= 0, "ราคาขายได้"] = np.nan
                df_p["ละติจูด"] = pd.to_numeric(df_p["ละติจูด"], errors="coerce").astype("float64")
                df_p["ลองจิจูด"] = pd.to_numeric(df_p["ลองจิจูด"], errors="coerce").astype("float64")
                bad_c = ~(df_p["ละติจูด"].between(5.5, 20.6) & df_p["ลองจิจูด"].between(97.3, 105.7))
                df_p.loc[bad_c, ["ละติจูด", "ลองจิจูด"]] = np.nan
                for _pq_target in (ROOT_PARQUET, monthly_parquet_dst):
                    os.makedirs(os.path.dirname(os.path.abspath(_pq_target)), exist_ok=True)
                    _tmp_pq = f"{_pq_target}.tmp.{os.getpid()}"
                    df_p.to_parquet(_tmp_pq, index=False, compression="zstd")
                    os.replace(_tmp_pq, _pq_target)
            except Exception as e2:
                print(f"❌ Fallback Parquet ล้มเหลว: {e2}", flush=True)
        
    # Append merge summary to Central log and logs/ directory
    try:
        from logger_util import log_finish, format_duration
        merge_elapsed = time.time() - t_merge_start
        merge_finish_clock = datetime.now().strftime("%H:%M:%S")
        dur_str = format_duration(merge_elapsed)
        log_finish("MERGE", duration_sec=merge_elapsed, records=len(combined_df), start_clock=t_merge_clock, message=f"เวลาเริ่ม: {t_merge_clock} | เวลาเสร็จ: {merge_finish_clock} | เวลารวมที่ใช้: {dur_str} | ข้อมูลรวม: {len(combined_df):,} รายการ")
    except Exception:
        pass

    print("==========================================================================", flush=True)
    print(f"🎉 รวมข้อมูลเสร็จสมบูรณ์! ข้อมูลสุทธิทั้งหมด {len(combined_df):,} รายการ (บันทึกเฉพาะไฟล์: {os.path.basename(MASTER_CSV_TIMED)})", flush=True)
    print("==========================================================================", flush=True)
    return True

if __name__ == "__main__":
    try:
        no_pq = any(a.lower() in ["--no-parquet", "-no-parquet", "no-parquet"] for a in sys.argv)
        merge_monthly_csv(generate_parquet=not no_pq)
    except Exception as e:
        import traceback
        print("\n" + "=" * 70, flush=True)
        print("❌ เกิดข้อผิดพลาดระหว่างการทำงาน:", flush=True)
        print("=" * 70, flush=True)
        traceback.print_exc()
    finally:
        print("\n" + "=" * 70, flush=True)
        try:
            if sys.stdin and sys.stdin.isatty():
                input("กด Enter เพื่อปิดหน้าต่างนี้ (Press Enter to exit)...")
        except Exception:
            pass
