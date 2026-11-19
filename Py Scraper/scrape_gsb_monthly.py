from logger_util import (
    AuditedSession,
    log_http_audit,
    log_txn,
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
    read_csv_resume,
    atomic_write_csv,
    print_structure_alert,
)
from timeout_handler import wait_1hr_on_timeout, handle_timeout_retry, execute_with_retry
import os
import sys
import json
import re
import time
from time_window_util import get_scraper_delay, get_scraper_delay_range
import random
import subprocess
import threading
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from clean_location_util import clean_floor_val, extract_floor_from_text, forward_geocode_location, clean_row_location
try:
    from clean_project_util import clean_project_name, extract_project_from_title
except ImportError:
    clean_project_name = lambda x, **kwargs: str(x).strip()
    extract_project_from_title = lambda x, **kwargs: ""

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

COMPANY_NAME = "GSB"
MONTH_STR = datetime.now().strftime("%Y_%m")

_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "monthly all new", "dist", "build"] else _BASE_DIR
OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output", MONTH_STR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"GSB_NPA_New_{MONTH_STR}.csv")

SUBDISTRICT_GEOJSON = os.path.join(_BASE_DIR, "subdistricts.geojson")

COLUMNS = [
    "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคา",
    "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ชื่อประกาศ", "ลิงก์",
    "เนื้อที่ (ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
    "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ", "เลขโฉนด"
]

print_lock = threading.Lock()
geo_lookup = {}

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

def load_geo_lookup():
    global geo_lookup
    candidates = []
    if getattr(sys, '_MEIPASS', None):
        candidates.append(os.path.join(sys._MEIPASS, "subdistricts.geojson"))
        candidates.append(os.path.join(sys._MEIPASS, "data", "subdistricts.geojson"))
    candidates.append(os.path.join(_BASE_DIR, "subdistricts.geojson"))
    candidates.append(os.path.join(_BASE_DIR, "data", "subdistricts.geojson"))
    candidates.append(os.path.join(os.path.dirname(_BASE_DIR), "subdistricts.geojson"))
    candidates.append(os.path.join(os.path.dirname(_BASE_DIR), "data", "subdistricts.geojson"))
    
    geojson_path = next((p for p in candidates if os.path.exists(p)), None)
    
    if geojson_path:
        try:
            with open(geojson_path, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            for feat in data.get('features', []):
                props = feat.get('properties', {})
                geom = feat.get('geometry', {})
                t_name = clean_text(props.get('tam_th'))
                a_name = clean_text(props.get('amp_th'))
                p_name = clean_text(props.get('pro_th'))
                
                coords = geom.get('coordinates', [])
                if coords:
                    def get_centroid(c_list):
                        pts = []
                        def extract_pts(cl):
                            if isinstance(cl, (list, tuple)) and len(cl) == 2 and isinstance(cl[0], (int, float)):
                                pts.append(cl)
                            elif isinstance(cl, (list, tuple)):
                                for sub in cl:
                                    extract_pts(sub)
                        extract_pts(c_list)
                        if pts:
                            avg_lon = sum(p[0] for p in pts) / len(pts)
                            avg_lat = sum(p[1] for p in pts) / len(pts)
                            return avg_lat, avg_lon
                        return None, None
                    lat, lon = get_centroid(coords)
                    if lat and lon:
                        key = f"{t_name}|{a_name}|{p_name}"
                        geo_lookup[key] = (round(lat, 6), round(lon, 6))
                        key_short = f"{a_name}|{p_name}"
                        if key_short not in geo_lookup:
                            geo_lookup[key_short] = (round(lat, 6), round(lon, 6))
        except Exception:
            pass

def get_coordinates(sub_d, dist, prov):
    lat_c, lng_c = forward_geocode_location(sub_d, dist, prov)
    if lat_c and lng_c:
        return lat_c, lng_c
    t = clean_text(sub_d).replace("ต.", "").replace("ตำบล", "").strip()
    a = clean_text(dist).replace("อ.", "").replace("อำเภอ", "").replace("เขต", "").strip()
    p = clean_text(prov).replace("จ.", "").replace("จังหวัด", "").strip()
    
    key1 = f"{t}|{a}|{p}"
    if key1 in geo_lookup:
        return geo_lookup[key1]
        
    key2 = f"{a}|{p}"
    if key2 in geo_lookup:
        return geo_lookup[key2]
        
    return None, None

def parse_rai_ngan_wah_robust(s):
    if s is None or pd.isna(s):
        return None, None, None
    s = str(s).strip()
    if not s or s.lower() in ["nan", "none", "null", "$undefined", "-", "0", "0.0", "."]:
        return None, None, None
    
    m_dash = re.match(r'^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$', s)
    if m_dash:
        try:
            return float(m_dash.group(1)), float(m_dash.group(2)), float(m_dash.group(3))
        except ValueError:
            pass
        
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


def extract_gsb_property_type(subtype, main_type):
    st = clean_text(subtype or "")
    mt = clean_text(main_type or "")
    
    if st and st.lower() not in ["none", "null", "-", ""]:
        parts = [p.strip() for p in st.split(",") if p.strip()]
        concrete = [p for p in parts if p != 'อื่นๆ']
        if concrete:
            return concrete[0]
        return parts[0]
        
    if mt and mt.lower() not in ["none", "null", "-", ""]:
        return mt
        
    return "ทรัพย์สิน"

def fetch_gsb_detail_subtype(session, item):
    code = item.get("asset_group_id_npa") or item.get("asset_group_id")
    asset_type_id = item.get("asset_type_id") or "342"
    url = f"https://npa-assets.gsb.or.th/asset/npa?id={code}&asset_type_id={asset_type_id}&type_id=asset_group_id_npa"
    try:
        r = safe_ssl_get(session, url, timeout=100, ssl_fallback_on_gov=False)
        if r.status_code == 200:
            m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text)
            if m:
                info = json.loads(m.group(1)).get('props', {}).get('pageProps', {}).get('info', {})
                return code, info.get('asset_subtype_desc'), info.get('square_meter'), info.get('builded_year')
    except Exception:
        pass
    return code, None, None, None

def fetch_gsb_detail_coords(session, detail_url, max_retries=2):
    """ดึงพิกัด GPS จริง และข้อมูลเสริมจากหน้ารายละเอียดทรัพย์ GSB (Google Maps link / __NEXT_DATA__)"""
    lat, lng = None, None
    extra_sqm = None
    extra_subtype = None
    for attempt in range(max_retries + 1):
        try:
            r = safe_ssl_get(session, detail_url, timeout=100, ssl_fallback_on_gov=False)
            if r.status_code != 200:
                if attempt < max_retries:
                    time.sleep(2 + attempt * 2)
                    continue
                return None, None, None, None
            html = r.text
            # ── ลำดับที่ 1: หาจาก __NEXT_DATA__ JSON (field lat/lng ตรง) ──
            m_json = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
            if m_json:
                try:
                    info = json.loads(m_json.group(1)).get('props', {}).get('pageProps', {}).get('info', {})
                    for k in ["latitude", "lat", "geo_lat", "map_lat"]:
                        v = info.get(k)
                        if v is not None:
                            try:
                                fv = float(str(v).strip())
                                if 5.0 <= fv <= 21.0:
                                    lat = fv
                                    break
                            except (ValueError, TypeError):
                                pass
                    for k in ["longitude", "long", "lng", "geo_long", "map_lng"]:
                        v = info.get(k)
                        if v is not None:
                            try:
                                fv = float(str(v).strip())
                                if 97.0 <= fv <= 106.0:
                                    lng = fv
                                    break
                            except (ValueError, TypeError):
                                pass
                    sqm_val = info.get("square_meter")
                    if sqm_val:
                        try: extra_sqm = float(str(sqm_val).replace(",", ""))
                        except Exception: pass
                    if info.get("asset_subtype_desc"):
                        extra_subtype = clean_text(info.get("asset_subtype_desc"))
                except (json.JSONDecodeError, AttributeError):
                    pass
            # ── ลำดับที่ 2: หาจาก Google Maps URL ในหน้า HTML ──
            if not lat or not lng:
                gmap = re.search(r'maps\.google\.com/?\?q=([0-9.\-]+),\s*([0-9.\-]+)', html)
                if gmap:
                    try:
                        v1, v2 = float(gmap.group(1)), float(gmap.group(2))
                        if 5.0 <= v1 <= 21.0 and 97.0 <= v2 <= 106.0:
                            lat, lng = v1, v2
                    except (ValueError, TypeError):
                        pass
            return lat, lng, extra_sqm, extra_subtype
        except Exception:
            if attempt < max_retries:
                time.sleep(2 + attempt * 2)
            else:
                pass
    return lat, lng, extra_sqm, extra_subtype

def parse_gsb_item(item, dev_type, today_str):
    if not isinstance(item, dict):
        return None
        
    p_id = clean_text(item.get("asset_id") or item.get("id"))
    if not p_id:
        return None
        
    code = clean_text(item.get("asset_group_id_npa") or item.get("asset_group_id_npl") or item.get("asset_group_id") or p_id)
    p_type = extract_gsb_property_type(item.get("asset_subtype_desc"), item.get("asset_type_desc"))
    
    price = None
    for p_field in ["xprice", "current_offer_price", "xprice_normal", "group_sell_price"]:
        if item.get(p_field) is not None:
            try:
                price = float(str(item[p_field]).replace(",", ""))
                if price > 0:
                    break
            except Exception:
                pass
                
    sub_d = clean_text(item.get("sub_district_name"))
    dist = clean_text(item.get("district_name"))
    prov = clean_text(item.get("province_name"))
    
    lat, lng = "", ""
    for lat_k in ["latitude", "lat", "geo_lat", "location_lat", "map_lat"]:
        if item.get(lat_k):
            try:
                v = float(str(item[lat_k]).strip())
                if 5.0 <= v <= 21.0:
                    lat = v
                    break
            except Exception: pass
    for lng_k in ["longitude", "long", "lng", "geo_long", "location_lon", "location_lng", "map_lng"]:
        if item.get(lng_k):
            try:
                v = float(str(item[lng_k]).strip())
                if 97.0 <= v <= 106.0:
                    lng = v
                    break
            except Exception: pass
            
    # Search any embedded Google Maps or coord strings in item values
    if not lat or not lng:
        for val in item.values():
            if val and isinstance(val, str) and any(x in val.lower() for x in ["map", "q=", "center=", "ll="]):
                m_gmap = re.search(r'(?:q|center|ll|markers)=([0-9\.\-]+)[,%2C]+([0-9\.\-]+)', val)
                if m_gmap:
                    try:
                        v1, v2 = float(m_gmap.group(1)), float(m_gmap.group(2))
                        if 5.0 <= v1 <= 21.0 and 97.0 <= v2 <= 106.0:
                            lat, lng = v1, v2
                            break
                    except Exception: pass

    # NOTE: ไม่ใช้ centroid ที่นี่ — จะดึงพิกัดจริงจากหน้า detail ก่อน แล้วค่อย fallback centroid ทีหลัง
    proj_name = clean_text(item.get("asset_name") or item.get("building_name") or item.get("village_head"))
    if proj_name == "-":
        proj_name = ""
    title = f"ขาย{p_type} {proj_name}".strip() if proj_name else f"ขาย{p_type} {dist} {prov}".strip()
    
    # Area (strip commas before combining rai-ngan-wah e.g. sum_square_wa='1,200')
    rai = str(item.get("sum_rai") or 0).replace(",", "").strip() or "0"
    ngan = str(item.get("sum_ngan") or 0).replace(",", "").strip() or "0"
    wah = str(item.get("sum_square_wa") or 0).replace(",", "").strip() or "0"
    rai_str = item.get("rai_ngan_wa") or ""

    if rai != "0" or ngan != "0" or wah != "0":
        area_fmt = convert_to_rai_ngan_wah(f"{rai}-{ngan}-{wah}")
    elif rai_str:
        area_fmt = convert_to_rai_ngan_wah(rai_str)
    else:
        area_fmt = ""
        
    usable_area = None
    sqm = item.get("square_meter")
    if sqm:
        try: usable_area = float(str(sqm).replace(",", ""))
        except Exception: pass
        
    sale_type = "ทรัพย์ธนาคาร"
    if dev_type.lower() == "npl":
        sale_type = "ทรัพย์ NPL"
    elif dev_type.lower() == "gsb":
        sale_type = "ทรัพย์ธนาคาร (GSB)"

    type_id_param = "asset_group_id_npl" if dev_type.lower() == "npl" else "asset_group_id_npa"
    asset_type_id = clean_text(item.get("asset_type_id") or "")
    if not asset_type_id:
        c_upper = code.upper()
        if "-LD-" in c_upper or "GSBLD" in c_upper:
            asset_type_id = "341"
        elif "-LB-" in c_upper or "GSBLB" in c_upper:
            asset_type_id = "342"
        elif "-CD-" in c_upper or "GSBCD" in c_upper:
            asset_type_id = "343"
        elif "-BD-" in c_upper or "GSBBD" in c_upper:
            asset_type_id = "344"
        else:
            asset_type_id = "341"
            
    link = f"https://npa-assets.gsb.or.th/asset/npa?id={code}&asset_type_id={asset_type_id}&type_id={type_id_param}"
    
    floor_val = clean_floor_val(item.get("floor") or item.get("floors") or item.get("total_floor") or item.get("number_of_floors") or item.get("storey") or item.get("story"))
    if not floor_val:
        floor_val = extract_floor_from_text(title, proj_name, item.get("asset_desc") or "", item.get("detail") or "", asset_type=p_type)
    
    deed_no = clean_text(item.get("deed_info") or "")

    if proj_name and clean_project_name:
        proj_name = clean_project_name(proj_name, tambon=sub_d, amphoe=dist, province=prov, company=COMPANY_NAME)
    if not proj_name and title and extract_project_from_title:
        proj_name = extract_project_from_title(title, tambon=sub_d, amphoe=dist, province=prov, company=COMPANY_NAME)

    rec = {
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
        "ละติจูด": lat,
        "ลองจิจูด": lng,
        "ชื่อประกาศ": title,
        "ลิงก์": link,
        "เนื้อที่ (ตร.ว.)": area_fmt,
        "พื้นที่ใช้สอย (ตร.ม.)": usable_area,
        "วันที่ดึงข้อมูล": today_str,
        "ห้องนอน": None,
        "ห้องน้ำ": None,
        "ที่จอดรถ": None,
        "ชั้น": floor_val or "",
        "วันประกาศ": None,
        "เลขโฉนด": deed_no
    }
    clean_row_location(rec)
    return rec

def save_to_csv(records, filename):
    return atomic_write_csv(records, filename, COLUMNS, company_name=COMPANY_NAME)

def load_existing_csv(filename):
    if "--fresh" in sys.argv or "--force-restart" in sys.argv:
        print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นดึงข้อมูลใหม่ทั้งหมด (โหมด --fresh)", flush=True)
        reset_scraper_state(COMPANY_NAME, MONTH_STR)
        return [], set()
    return read_csv_resume(filename, COLUMNS, id_col="ID", company_name=COMPANY_NAME)

def _extract_gsb_rows_from_html(page_html):
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page_html)
    if not m:
        raise ValueError("ไม่พบโครงสร้าง __NEXT_DATA__ JSON Data ในหน้า GSB")
    next_json = json.loads(m.group(1))
    props = next_json.get("props", {}).get("pageProps", {})
    list_obj = props.get("list") or props.get("listNpa") or props.get("listNpl") or props.get("listGsb") or {}
    data_groups = list_obj.get("data", [])
    rows = []
    if isinstance(data_groups, dict):
        rows = data_groups.get("rows", [])
    elif isinstance(data_groups, list):
        for grp in data_groups:
            if isinstance(grp, dict):
                items_in_grp = grp.get("asset_list") or grp.get("data") or []
                if isinstance(items_in_grp, list):
                    rows.extend(items_in_grp)
                elif "asset_id" in grp or "id" in grp:
                    rows.append(grp)
    total_count = 0
    for tk in ("total", "totalRows", "total_count", "totalCount"):
        tv = list_obj.get(tk) if isinstance(list_obj, dict) else None
        if tv is not None and str(tv).isdigit():
            total_count = int(tv)
            break
    return rows, total_count

def main():
    print(f"[{COMPANY_NAME}] 🚀 เริ่มต้นการดึงข้อมูลประจำเดือน {MONTH_STR}", flush=True)
    load_geo_lookup()

    start_time = time.time()
    today_str = datetime.now().strftime("%Y-%m-%d")

    session = AuditedSession(COMPANY_NAME)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "x-nextjs-data": "1",
        "Referer": "https://npa-assets.gsb.or.th/"
    })

    # Establish session & check homepage reachability BEFORE --fresh
    def _probe_home():
        r = safe_ssl_get(session, "https://npa-assets.gsb.or.th/", timeout=100, ssl_fallback_on_gov=False)
        if r.status_code != 200:
            r.raise_for_status()
        return r

    try:
        r_home = execute_with_retry(_probe_home, company_name=COMPANY_NAME, context_msg="หน้าหลัก GSB", max_retries=3, max_cooldown_cycles=1)
        print(f"[{COMPANY_NAME}] 🌐 สถานะลิงก์: ปกติ (HTTP {r_home.status_code}) | เชื่อมต่อระบบ Next.js GSB สำเร็จ", flush=True)
    except Exception as e:
        print_alert(f"ไม่สามารถเชื่อมต่อระบบ GSB ได้: {e}", level="CRITICAL")
        sys.exit(1)

    all_records, seen_ids = load_existing_csv(OUTPUT_CSV)
    saved_state = load_scraper_state(COMPANY_NAME, MONTH_STR)

    # Enrich existing resumed records that are missing coordinates (even when < 4,400 items)
    missing_existing = [
        r for r in all_records
        if not r.get("ละติจูด") or pd.isna(r.get("ละติจูด")) or str(r.get("ละติจูด")).strip() in ["", "nan", "None", "0.0", "0"]
    ]
    if missing_existing:
        print(f"[{COMPANY_NAME}] 📍 พบ {len(missing_existing):,} รายการใน CSV เดิมที่ยังไม่มีพิกัด -> ดึงพิกัดจริงด้วย fetch_gsb_detail_coords...", flush=True)
        for idx, r in enumerate(missing_existing, 1):
            d_url = r.get("ลิงก์", "")
            c_lat, c_lng = None, None
            if d_url:
                time.sleep(get_scraper_delay())
                c_lat, c_lng, _, _ = fetch_gsb_detail_coords(session, d_url)
            if not (c_lat and c_lng):
                c_lat, c_lng = get_coordinates(r.get("ตำบล", ""), r.get("อำเภอ", ""), r.get("จังหวัด", ""))
            if c_lat and c_lng:
                r["ละติจูด"] = c_lat
                r["ลองจิจูด"] = c_lng
            clean_row_location(r)
            if idx % 25 == 0 or idx == len(missing_existing):
                save_to_csv(all_records, OUTPUT_CSV)
                print(f"[{COMPANY_NAME}] 💾 อัปเดตพิกัดเดิมแล้ว ({idx}/{len(missing_existing)} รายการ)...", flush=True)
        save_to_csv(all_records, OUTPUT_CSV)

    if saved_state.get("status") == "COMPLETED" and len(all_records) > 0:
        tot_expected = max(len(all_records), int(saved_state.get("total_records") or 0))
        total_pages = (len(all_records) + 59) // 60 if len(all_records) > 0 else 1
        print(f"[{COMPANY_NAME}] 🎉 ข้อมูลใน CSV ครบถ้วน 100% แล้ว ({total_pages:5,d}/{total_pages:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{tot_expected:,d} รายการ -> สแครปเสร็จสมบูรณ์ทันที!", flush=True)
        save_to_csv(all_records, OUTPUT_CSV)
        log_success(COMPANY_NAME, f"✅ ข้อมูลใน CSV ครบถ้วน 100% อยู่แล้ว ({len(all_records):,} รายการ)")
        return

    failed_units = []
    tot_expected = len(all_records)

    categories = [
        ("NPA (ทรัพย์ธนาคารทั้งหมด)", "https://npa-assets.gsb.or.th/asset/npa/all?page={page}&page_size=5000&asset_type_dev=npa", "npa")
    ]

    total_cats = len(categories)
    for c_idx, (cat_label, cat_url_tpl, cat_key) in enumerate(categories, 1):
        print(f"[{COMPANY_NAME}] 🔍 กำลังดึงข้อมูลหมวด {cat_label}...", flush=True)

        rows = []
        seen_batch_ids = set()
        page_num = 1
        page_size = 5000
        while page_num <= 50:
            cat_url = cat_url_tpl.format(page=page_num)

            def _fetch_cat_page():
                r_page = safe_ssl_get(session, cat_url, timeout=100, ssl_fallback_on_gov=False)
                if r_page.status_code != 200:
                    r_page.raise_for_status()
                return r_page.content.decode('utf-8', errors='ignore')

            try:
                page_html = execute_with_retry(_fetch_cat_page, company_name=COMPANY_NAME, context_msg=f"{cat_label} หน้า {page_num}", max_retries=4, max_cooldown_cycles=1)
                page_rows, total_reported = _extract_gsb_rows_from_html(page_html)
                if total_reported > 0:
                    tot_expected = max(tot_expected, total_reported)
            except Exception as e:
                failed_units.append(f"หมวด {cat_label} หน้า {page_num}")
                print(f"\n[{COMPANY_NAME}] ⚠️ ดึงข้อมูลหมวด {cat_label} หน้า {page_num} ไม่สำเร็จ: {e}", flush=True)
                break

            if not page_rows:
                break

            added_in_page = 0
            for it in page_rows:
                bid = clean_text(it.get("asset_id") or it.get("id"))
                if bid and bid not in seen_batch_ids:
                    seen_batch_ids.add(bid)
                    rows.append(it)
                    added_in_page += 1

            if added_in_page == 0 or len(page_rows) < page_size:
                break
            if total_reported > 0 and len(rows) >= total_reported:
                break
            page_num += 1
            time.sleep(get_scraper_delay())

        if not rows and failed_units:
            continue
                        
        # สกัดประเภทย่อยจากชื่อทรัพย์และโครงการโดยตรงเพื่อความรวดเร็วและป้องกันเซิร์ฟเวอร์ GSB ปฏิเสธการเชื่อมต่อ
        for it in rows:
            if not it.get("asset_subtype_desc") and it.get("asset_type_desc") == "ที่ดินพร้อมสิ่งปลูกสร้าง":
                name_txt = f"{it.get('asset_name') or ''} {it.get('village_head') or ''} {it.get('building_name') or ''}"
                if any(k in name_txt for k in ["ทาวน์โฮม", "ทาวน์เฮ้าส์", "ทาวน์เฮาส์"]):
                    it["asset_subtype_desc"] = "ทาวน์เฮ้าส์"
                elif any(k in name_txt for k in ["อาคารพาณิชย์", "ตึกแถว", "พาณิชย์"]):
                    it["asset_subtype_desc"] = "อาคารพาณิชย์"
                elif any(k in name_txt for k in ["คอนโด", "ห้องชุด"]):
                    it["asset_subtype_desc"] = "ห้องชุดพักอาศัย"
                else:
                    it["asset_subtype_desc"] = "บ้านเดี่ยว"

        # ── Parse listing items (ยังไม่มีพิกัด) ──
        new_records = []
        for it in rows:
            rec = parse_gsb_item(it, cat_key, today_str)
            if rec and rec["ประเภทการขาย"] != "ทรัพย์ NPL" and rec["ID"] not in seen_ids:
                seen_ids.add(rec["ID"])
                new_records.append(rec)

        # ── บันทึก CSV ทันทีหลัง parse listing (ยังไม่มีพิกัด) ──
        if new_records:
            snapshot = all_records + new_records
            save_to_csv(snapshot, OUTPUT_CSV)
            print(f"[{COMPANY_NAME}] 💾 บันทึก listing {len(new_records):,} รายการลง CSV แล้ว (ยังไม่มีพิกัด)", flush=True)

        # ── ดึงพิกัดจริงจากหน้า detail ก่อน ──
        if new_records:
            print(f"\n[{COMPANY_NAME}] 📍 กำลังดึงพิกัดจริงจากหน้ารายละเอียด {len(new_records):,} รายการ...", flush=True)
            coord_start = time.time()
            coord_found = 0
            coord_done = 0
            total_new = len(new_records)
            save_every = 25  # บันทึกทุก 25 รายการป้องกันงานสูญหาย
            last_saved_at = 0

            for i, r in enumerate(new_records):
                time.sleep(get_scraper_delay())
                try:
                    rlat, rlng, extra_sqm, extra_sub = fetch_gsb_detail_coords(session, r["ลิงก์"])
                    if rlat and rlng:
                        new_records[i]["ละติจูด"] = rlat
                        new_records[i]["ลองจิจูด"] = rlng
                        coord_found += 1
                    if extra_sqm and not new_records[i].get("พื้นที่ใช้สอย (ตร.ม.)"):
                        new_records[i]["พื้นที่ใช้สอย (ตร.ม.)"] = extra_sqm
                    if extra_sub and not new_records[i].get("ประเภททรัพย์"):
                        new_records[i]["ประเภททรัพย์"] = extra_sub
                except Exception:
                    pass
                coord_done += 1
                if coord_done % 20 == 0 or coord_done == total_new:
                    pct = int(coord_done * 100 / total_new)
                    elapsed = time.time() - coord_start
                    eta = format_eta(elapsed, coord_done, total_new)
                    with print_lock:
                        print(f"[{COMPANY_NAME}] {make_progress_bar(pct)} | ({coord_done:,}/{total_new:,} รายการ) | สะสม: {coord_done:,}/{total_new:,} รายการ | พิกัดจริง: {coord_found:,} | {eta}", flush=True)
                # ── Checkpoint: บันทึก CSV ทุก 5% ──
                if coord_done - last_saved_at >= save_every:
                    last_saved_at = coord_done
                    snapshot = all_records + new_records
                    save_to_csv(snapshot, OUTPUT_CSV)

            print(f"\n[{COMPANY_NAME}] ✅ ดึงพิกัดจริงได้ {coord_found:,}/{total_new:,} รายการ ({coord_found*100//max(1,total_new)}%)", flush=True)

        # ── Centroid fallback: เฉพาะรายการที่ยังไม่มีพิกัดจริง ──
        centroid_count = 0
        for rec in new_records:
            if not rec.get("ละติจูด") or not rec.get("ลองจิจูด"):
                c_lat, c_lng = get_coordinates(rec.get("ตำบล", ""), rec.get("อำเภอ", ""), rec.get("จังหวัด", ""))
                if c_lat and c_lng:
                    rec["ละติจูด"] = c_lat
                    rec["ลองจิจูด"] = c_lng
                    centroid_count += 1
        if centroid_count:
            print(f"[{COMPANY_NAME}] 📌 ใช้ centroid ตำบลเติม {centroid_count:,} รายการที่ไม่มีพิกัดจริง", flush=True)

        all_records.extend(new_records)
        cat_added = len(new_records)
        save_to_csv(all_records, OUTPUT_CSV)
        save_scraper_state(COMPANY_NAME, c_idx, total_cats, len(all_records), status="RUNNING", month_str=MONTH_STR)
        if len(rows) > 0:
            tot_expected = max(tot_expected, len(rows))
        total_p = (len(all_records) + 59) // 60 if len(all_records) > 0 else 74
        print(f"[{COMPANY_NAME}] [████████████████████] 100% | ({total_p:5,d}/{total_p:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{tot_expected:,d} รายการ | เสร็จสมบูรณ์", flush=True)
        time.sleep(get_scraper_delay()) # หน่วงเวลาอย่างน้อย 15 วินาทีต่อหมวด/หน้า

    save_to_csv(all_records, OUTPUT_CSV)
    elapsed = time.time() - start_time
    total_p = (len(all_records) + 59) // 60 if len(all_records) > 0 else 1
    if failed_units:
        final_status = "FAILED" if len(all_records) == 0 else "PARTIAL"
        save_scraper_state(COMPANY_NAME, max(0, total_cats - len(failed_units)), total_cats, len(all_records), status=final_status, month_str=MONTH_STR)
        print(f"\n==================================================", flush=True)
        print(f"⚠️ [{COMPANY_NAME}] สแครปเสร็จแบบมีรายการล้มเหลว ({final_status}) | สะสม: {len(all_records):>6,d}/{max(len(all_records), tot_expected):,d} รายการ", flush=True)
        print(f"⚠️ รายการที่ข้าม/ดึงไม่ได้ ({len(failed_units)} รายการ): {sorted(failed_units)}", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที | 💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        log_warning(COMPANY_NAME, f"⚠️ สแครปเสร็จแบบ {final_status}: ดึงไม่ได้ {len(failed_units)} รายการ")
        sys.exit(1 if len(all_records) == 0 else 2)
    else:
        save_scraper_state(COMPANY_NAME, total_cats, total_cats, len(all_records), status="COMPLETED", month_str=MONTH_STR)
        print(f"\n==================================================", flush=True)
        print(f"✅ [{COMPANY_NAME}] สแครปเสร็จสมบูรณ์! | ({total_p:5,d}/{total_p:5,d} หน้า) | สะสม: {len(all_records):>6,d}/{max(len(all_records), tot_expected):,d} รายการ", flush=True)
        print(f"📊 ได้ข้อมูลทั้งหมด: {len(all_records):,} รายการ", flush=True)
        print(f"⏱️ ใช้เวลาทั้งหมด: {elapsed/60:.2f} นาที", flush=True)
        print(f"💾 ไฟล์ CSV: {OUTPUT_CSV}", flush=True)
        print(f"✅ ดึงข้อมูลได้ครบถ้วนสำเร็จ 100% (ไม่มีรายการล้มเหลว)", flush=True)
        print(f"==================================================", flush=True)
        log_success(COMPANY_NAME, f"✅ สแครปเสร็จสมบูรณ์! ได้ข้อมูลทั้งหมดสะสมลง {os.path.basename(OUTPUT_CSV)}")

if __name__ == "__main__":
    main()
