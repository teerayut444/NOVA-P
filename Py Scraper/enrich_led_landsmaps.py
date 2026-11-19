"""
Enrich Legal Execution Department (LED) assets with exact real GPS coordinates
scraped from Department of Lands (LandsMaps: https://landsmaps.dol.go.th/).

Features:
- Automatic Session Reset / Bypass for the 20-request anonymous rate limit via
  `POST /apiService/LandsMaps/LoginSocial` (upgrades token from `register_type_seq: 8`
  anonymous to `register_type_seq: 1` authenticated member session, and rotates UUID
  sessions automatically whenever needed).
- Fast Parallel REST API mode (`--mode api`, default) that queries
  `GetParcelByParcelNo/{pvcode}/{amcode}/{parcelno}` directly at 10-20x speed.
- Browser mode (`--mode browser`) that injects the authenticated `LoginSocial` token
  into `sessionStorage.userinfo` so the browser UI also bypasses the 20-request limit.
- Incremental caching in Parquet format (`data/led_coords_cache.parquet`) + in-place
  CSV syncing (`LED_NPA_New_2026_09.csv`) so work can be stopped and resumed anytime.
"""

import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["tools", "py scraper", "monthly all new", "dist", "build"] else _BASE_DIR

import time
import random
import re
import glob
import json
import uuid
import urllib.parse
import argparse
import threading
from contextlib import contextmanager
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import requests

from time_window_util import wait_for_active_window, get_scraper_delay, get_scraper_delay_range
from logger_util import safe_ssl_get, safe_ssl_post
try:
    from clean_location_util import get_known_centroids_set, is_centroid_coord
except ImportError:
    def get_known_centroids_set():
        return set()
    def is_centroid_coord(lat, lng, centroids_set=None):
        return False

CACHE_PATH = os.path.join(_ROOT_DIR, "data", "led_coords_cache.parquet")


def _resolve_master_codes_path():
    candidates = [
        os.path.join(_BASE_DIR, "dol_master_codes.json"),
        os.path.join(_ROOT_DIR, "Py Scraper", "dol_master_codes.json"),
        os.path.join(_ROOT_DIR, "offline_landsmaps", "data", "dol_master_codes.json"),
    ]
    if getattr(sys, '_MEIPASS', None):
        candidates.insert(0, os.path.join(sys._MEIPASS, "dol_master_codes.json"))
        candidates.append(os.path.join(sys._MEIPASS, "offline_landsmaps", "data", "dol_master_codes.json"))
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


MASTER_CODES_PATH = _resolve_master_codes_path()
STORAGE_INFO_PATH = os.path.join(_ROOT_DIR, "scratch", "storage_info.json")
COORD_REGEX = re.compile(r'(\d{1,2}\.\d{5,})\s*,\s*(\d{2,3}\.\d{5,})')

_CACHE_THREAD_LOCK = threading.Lock()
_KNOWN_CENTROIDS = None

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Referer": "https://landsmaps.dol.go.th/",
    "Accept": "application/json, text/plain, */*"
}

_SPINNER_CHARS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_spinner_frame = 0


def make_progress_bar(pct, length=18):
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


def _get_centroids():
    global _KNOWN_CENTROIDS
    if _KNOWN_CENTROIDS is None:
        _KNOWN_CENTROIDS = get_known_centroids_set()
    return _KNOWN_CENTROIDS


def is_valid_thailand_real_coord(lat_val, lon_val, centroids_set=None):
    """Return True iff coordinates fall within Thailand bounds and are NOT a known subdistrict/district centroid."""
    try:
        s_lat = str(lat_val or "").strip()
        s_lon = str(lon_val or "").strip()
        if not s_lat or not s_lon or s_lat.lower() in ("nan", "none", "null") or s_lon.lower() in ("nan", "none", "null"):
            return False
        lat_f = float(s_lat)
        lon_f = float(s_lon)
    except (ValueError, TypeError):
        return False
    if not (5.5 <= lat_f <= 20.6 and 97.3 <= lon_f <= 105.7):
        return False
    cset = centroids_set if centroids_set is not None else _get_centroids()
    if cset:
        c_key = f"{round(lat_f, 5)},{round(lon_f, 5)}"
        if c_key in cset:
            return False
        if centroids_set is None and is_centroid_coord(lat_f, lon_f, cset):
            return False
    elif centroids_set is None and is_centroid_coord(lat_f, lon_f):
        return False
    return True


class DolSessionRotator:
    """
    Manages LandsMaps JWT sessions and bypasses the 20-request anonymous limit.
    How it works:
    1. Calls `GET /apiService/JWT/GetJWTAccessToken` to obtain an initial public token (`register_type_seq: 8`).
    2. Calls `POST /apiService/LandsMaps/LoginSocial` with a fresh random `user_id` UUID and `register_type_seq: 1`.
    3. Receives an authenticated member session (`register_type_seq: 1`) with its own `access_token` that is NOT subject
       to the 20-request anonymous quota.
    4. Automatically rotates to a new `LoginSocial` UUID session every `max_uses_per_token` requests or on any quota error.
    """
    def __init__(self, max_uses_per_token=60):
        self._lock = threading.Lock()
        self._http = requests.Session()
        self._token = None
        self._userinfo = None
        self._uses = 0
        self._rotation_count = 0
        self._max_uses = max_uses_per_token

    def create_fresh_social_session(self, allow_stale_fallback=True):
        last_err = None
        for retry in range(15):
            try:
                # Step 1: Get anonymous public JWT token
                r_pub = safe_ssl_get(
                    self._http,
                    "https://landsmaps.dol.go.th/apiService/JWT/GetJWTAccessToken",
                    headers=HEADERS_BASE,
                    timeout=15,
                    ssl_fallback_on_gov=True,
                )
                r_pub.raise_for_status()
                pub_tok = r_pub.json()["result"][0]["access_token"]

                # Step 2: Upgrade session via LoginSocial with a fresh random UUID
                uid = uuid.uuid4().hex[:20]
                payload = {
                    "user_id": uid,
                    "first_name": f"User{uid[:5]}",
                    "last_name": "",
                    "mid_name": "",
                    "mail": f"member_{uid[:10]}@gmail.com",
                    "register_type_seq": 1
                }
                r_login = safe_ssl_post(
                    self._http,
                    "https://landsmaps.dol.go.th/apiService/LandsMaps/LoginSocial",
                    json=payload,
                    headers={**HEADERS_BASE, "Authorization": f"Bearer {pub_tok}"},
                    timeout=15,
                    ssl_fallback_on_gov=True,
                )
                r_login.raise_for_status()
                uinfo = r_login.json()["result"][0]
                return uinfo["access_token"], uinfo
            except Exception as e:
                last_err = e
                time.sleep(min(10.0, 2.0 * (retry + 1)))
        if allow_stale_fallback and self._token:
            return self._token, self._userinfo
        raise RuntimeError(f"Failed to rotate session after 15 retries: {last_err}")

    def get_token(self, force_rotate=False):
        with self._lock:
            if self._token is None or force_rotate or self._uses >= self._max_uses:
                tok, uinfo = self.create_fresh_social_session(allow_stale_fallback=(not force_rotate))
                self._token = tok
                self._userinfo = uinfo
                self._uses = 0
                self._rotation_count += 1
                if self._rotation_count > 1:
                    print(f"[LandsMaps    ] 🔄 [SESSION ROT] สลับ Token อัตโนมัติสำเร็จ (รอบที่ {self._rotation_count}) | ปลดล็อคโควต้า 20 ครั้ง/Token", flush=True)
            self._uses += 1
            return self._token

    @property
    def rotation_count(self):
        return self._rotation_count


@contextmanager
def _acquire_cache_lock(cache_file=CACHE_PATH, timeout=30.0):
    os.makedirs(os.path.dirname(os.path.abspath(cache_file)), exist_ok=True)
    lock_path = f"{cache_file}.lock"
    deadline = time.time() + timeout
    with _CACHE_THREAD_LOCK:
        acquired = False
        while time.time() < deadline:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(fd, f"{os.getpid()}".encode("ascii", errors="ignore"))
                os.close(fd)
                acquired = True
                break
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(lock_path) > 120.0:
                        os.remove(lock_path)
                        continue
                except OSError:
                    pass
                time.sleep(0.1)
            except OSError:
                time.sleep(0.1)
        try:
            yield acquired
        finally:
            if acquired and os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                except OSError:
                    pass


def _dedup_cache_df(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=['จังหวัด', 'อำเภอ', 'เลขโฉนด', 'ละติจูด', 'ลองจิจูด', 'สถานะ', 'วันที่ดึง'])
    out = df.copy()
    rank_map = {'FOUND': 0, 'NOT_FOUND': 1, 'DISTRICT_NOT_FOUND': 2, 'PROVINCE_NOT_FOUND': 3}
    out['_rank'] = out['สถานะ'].astype(str).map(lambda s: rank_map.get(s, 4))
    out = out.sort_values(by=['_rank', 'ละติจูด'], ascending=[True, False], na_position='last')
    out = out.drop_duplicates(subset=['จังหวัด', 'อำเภอ', 'เลขโฉนด'], keep='first')
    return out.drop(columns=['_rank']).reset_index(drop=True)


def load_cache(cache_file=CACHE_PATH):
    """Load existing cache or create an empty DataFrame."""
    if os.path.exists(cache_file):
        try:
            return pd.read_parquet(cache_file)
        except Exception as e:
            print(f"[CACHE] Warning: Failed to read {cache_file} ({e}), starting fresh.")
    return pd.DataFrame(columns=[
        'จังหวัด', 'อำเภอ', 'เลขโฉนด', 'ละติจูด', 'ลองจิจูด', 'สถานะ', 'วันที่ดึง'
    ])


def save_cache(cache_df, cache_file=CACHE_PATH, merge_disk=False):
    """Save cache to parquet file atomically with lock & optional RMW reload-merge."""
    with _acquire_cache_lock(cache_file):
        final_df = cache_df
        if merge_disk and os.path.exists(cache_file):
            try:
                disk_df = pd.read_parquet(cache_file)
                if disk_df is not None and not disk_df.empty:
                    final_df = _dedup_cache_df(pd.concat([disk_df, cache_df], ignore_index=True))
            except Exception:
                final_df = _dedup_cache_df(cache_df)
        else:
            final_df = _dedup_cache_df(cache_df)

        os.makedirs(os.path.dirname(os.path.abspath(cache_file)), exist_ok=True)
        temp_file = f"{cache_file}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            final_df.to_parquet(temp_file, index=False)
            for attempt in range(5):
                try:
                    os.replace(temp_file, cache_file)
                    return final_df
                except (PermissionError, OSError):
                    time.sleep(0.5)
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass
    return final_df


def merge_and_save_cache(new_rows, cache_df, cache_file=CACHE_PATH):
    """Safely merge new_rows into cache_df + disk cache atomically under lock."""
    batch_df = pd.DataFrame(new_rows)
    if batch_df.empty:
        return cache_df
    combined = pd.concat([cache_df, batch_df], ignore_index=True) if cache_df is not None and not cache_df.empty else batch_df
    return save_cache(combined, cache_file=cache_file, merge_disk=True)


def find_latest_led_csv():
    """Auto-detect the most recent LED CSV output."""
    csv_files = glob.glob(os.path.join(_ROOT_DIR, "CSV_Output", "**", "LED_NPA_New_*.csv"), recursive=True)
    if not csv_files:
        csv_files = [
            f for f in glob.glob(os.path.join(_ROOT_DIR, "CSV_Output", "**", "LED_*.csv"), recursive=True)
            if not os.path.basename(f).startswith("LED_Legal_report") and not os.path.basename(f).startswith("LED_Legal_merge")
        ]
    if csv_files:
        csv_files.sort(key=os.path.getmtime, reverse=True)
        return csv_files[0]
    return None


def find_latest_led_merge_csv():
    """Auto-detect the most recent LED_Legal_merge (LED Legal) CSV output."""
    csv_files = glob.glob(os.path.join(_ROOT_DIR, "CSV_Output", "**", "LED_Legal_merge_*.csv"), recursive=True)
    csv_files = [f for f in csv_files if not f.endswith("_BACKUP.csv")]
    if csv_files:
        csv_files.sort(key=os.path.getmtime, reverse=True)
        return csv_files[0]
    return None


def clean_deed_number(val):
    """Standardize deed string."""
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s.endswith('.0'):
        s = s[:-2]
    s = re.sub(r'\.0$', '', s)
    s = s.strip()
    return s if s and s != '-' and s != '0' else None


def clean_district_name(val):
    """Normalize district name to match LandsMaps options without corrupting hyphenated names like สุไหงโก-ลก."""
    if pd.isna(val):
        return ""
    d = str(val).strip()
    d = re.sub(r'^[0-9A-Za-z]+-\s*', '', d)
    d = re.sub(r'^(อ\.|อำเภอ|เขต)', '', d).strip()
    return d


def clean_province_name(val):
    """Normalize province name including common abbreviations and typos."""
    if pd.isna(val):
        return ""
    p = str(val).strip()
    p = re.sub(r'^(จ\.|จังหวัด)', '', p).strip()
    if p in ("กรุงเทพ", "กรุงเทพฯ", "กทม", "กทม.") or p.startswith("กรุงเทพมหานคร"):
        return "กรุงเทพมหานคร"
    if p == "อุตรดิต":
        return "อุตรดิตถ์"
    return p


def load_master_codes(rotator=None):
    """Load province and district code mappings for direct REST API queries."""
    prov_map = {}
    amp_map = {}

    codes_path = _resolve_master_codes_path()
    if os.path.exists(codes_path):
        try:
            with open(codes_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.get("provinces", {}).items():
                pvn = clean_province_name(k)
                if pvn and v:
                    prov_map[pvn] = str(v).strip()
            for k, v in data.get("amphurs", {}).items():
                pvc, amn_raw = k.split("|", 1)
                amn = clean_district_name(amn_raw)
                if pvc and amn:
                    amp_map.setdefault((pvc, amn), [])
                    for code in (v if isinstance(v, list) else [v]):
                        if code and code not in amp_map[(pvc, amn)]:
                            amp_map[(pvc, amn)].append(code)
                    base_amn = re.sub(r"\(.*?\)", "", amn).strip()
                    if base_amn and base_amn != amn:
                        amp_map.setdefault((pvc, base_amn), [])
                        for code in (v if isinstance(v, list) else [v]):
                            if code and code not in amp_map[(pvc, base_amn)]:
                                amp_map[(pvc, base_amn)].append(code)
        except Exception:
            pass

    if not prov_map and rotator is not None:
        tok = rotator.get_token()
        r = safe_ssl_get(
            rotator._http,
            "https://landsmaps.dol.go.th/apiService/Master/GetProvince",
            headers={**HEADERS_BASE, "Authorization": f"Bearer {tok}"},
            timeout=15,
            ssl_fallback_on_gov=True,
        )
        r.raise_for_status()
        provs = r.json().get("result", [])
        for p in provs:
            pvc = str(p.get("pvcode", "")).strip()
            pvn = clean_province_name(p.get("pvnamethai", ""))
            if pvc and pvc != "00" and pvn:
                prov_map[pvn] = pvc

    if not amp_map and rotator is not None:
        try:
            tok = rotator.get_token()
            r_amp = safe_ssl_get(
                rotator._http,
                "https://landsmaps.dol.go.th/apiService/Master/GetAmphur",
                headers={**HEADERS_BASE, "Authorization": f"Bearer {tok}"},
                timeout=15,
                ssl_fallback_on_gov=True,
            )
            if r_amp.status_code == 200:
                for a in r_amp.json().get("result", []):
                    pvc = str(a.get("pvcode", "")).strip()
                    amc = str(a.get("amcode", "")).strip()
                    amn = clean_district_name(a.get("amnamethai", ""))
                    if pvc and amc and amc != "00" and amn:
                        amp_map.setdefault((pvc, amn), [])
                        if amc not in amp_map[(pvc, amn)]:
                            amp_map[(pvc, amn)].append(amc)
                        base_amn = re.sub(r"\(.*?\)", "", amn).strip()
                        if base_amn and base_amn != amn:
                            amp_map.setdefault((pvc, base_amn), [])
                            if amc not in amp_map[(pvc, base_amn)]:
                                amp_map[(pvc, base_amn)].append(amc)
        except Exception:
            pass

    if not amp_map and os.path.exists(STORAGE_INFO_PATH):
        try:
            with open(STORAGE_INFO_PATH, "r", encoding="utf-8") as f:
                sinfo = json.load(f)
            amp_raw = json.loads(sinfo.get("sessionStorage", {}).get("amphur", "{}")).get("result", [])
            for a in amp_raw:
                pvc = str(a.get("pvcode", "")).strip()
                amc = str(a.get("amcode", "")).strip()
                amn = clean_district_name(a.get("amnamethai", ""))
                if pvc and amc and amc != "00" and amn:
                    amp_map.setdefault((pvc, amn), [])
                    if amc not in amp_map[(pvc, amn)]:
                        amp_map[(pvc, amn)].append(amc)
                    base_amn = re.sub(r"\(.*?\)", "", amn).strip()
                    if base_amn and base_amn != amn:
                        amp_map.setdefault((pvc, base_amn), [])
                        if amc not in amp_map[(pvc, base_amn)]:
                            amp_map[(pvc, base_amn)].append(amc)
        except Exception:
            pass

    return prov_map, amp_map


def resolve_pv_am_codes(prov_name, dist_name, prov_map, amp_map):
    pv = clean_province_name(prov_name)
    dt = clean_district_name(dist_name)
    if not pv:
        return None, []
    pvc = prov_map.get(pv)
    if not pvc:
        for k, v in prov_map.items():
            if pv in k or k in pv:
                pvc = v
                break
    if not pvc:
        return None, []

    if not dt:
        return pvc, []

    if dt == "เมือง":
        dt = f"เมือง{pv}"

    dt_no_branch = re.sub(r'\s*\(.*?\)', '', dt).strip()
    am_codes = list(amp_map.get((pvc, dt), []))
    if not am_codes and dt_no_branch and dt_no_branch != dt:
        am_codes = list(amp_map.get((pvc, dt_no_branch), []))

    if not am_codes and dt.startswith("เมือง"):
        am_codes = list(amp_map.get((pvc, f"เมือง{pv}"), []))

    if not am_codes:
        cand_dt = dt_no_branch or dt
        for (p_k, d_k), codes in amp_map.items():
            if p_k != pvc:
                continue
            d_base = re.sub(r'\s*\(.*?\)', '', d_k).strip()
            if (
                cand_dt == d_base
                or (len(cand_dt) >= 3 and cand_dt in d_base)
                or (len(d_base) >= 3 and d_base in cand_dt)
            ):
                for c in codes:
                    if c not in am_codes:
                        am_codes.append(c)

    # Prioritize numeric 2-digit codes first (e.g. "01", "05")
    num_codes = [c for c in am_codes if str(c).isdigit()]
    other_codes = [c for c in am_codes if not str(c).isdigit()]
    return pvc, num_codes + other_codes


def sync_cache_to_csv(input_csv, cache_df):
    """
    Sync FOUND real coordinates from cache_df directly into input_csv in-place.
    Requires (province, district, deed) 3-tuple to prevent cross-district collisions,
    and rejects invalid 0/out-of-bounds or known centroid coordinates.
    """
    if not input_csv or not os.path.exists(input_csv) or not input_csv.lower().endswith('.csv'):
        return 0

    if cache_df is None or cache_df.empty:
        return 0

    found = cache_df[cache_df['สถานะ'] == 'FOUND'].dropna(subset=['ละติจูด', 'ลองจิจูด'])
    if found.empty:
        return 0

    cset = _get_centroids()
    coord_lookup = {}
    for pv_raw, dt_raw, dd_raw, lat_raw, lon_raw in zip(
        found['จังหวัด'].fillna(''),
        found['อำเภอ'].fillna(''),
        found['เลขโฉนด'].fillna(''),
        found['ละติจูด'].fillna(''),
        found['ลองจิจูด'].fillna(''),
    ):
        pv = clean_province_name(pv_raw)
        dt = clean_district_name(dt_raw)
        dd = clean_deed_number(dd_raw)
        if not (pv and dt and dd):
            continue
        if is_valid_thailand_real_coord(lat_raw, lon_raw, cset):
            coord_lookup[(pv, dt, dd)] = (str(lat_raw).strip(), str(lon_raw).strip())

    if not coord_lookup:
        return 0

    try:
        df = pd.read_csv(input_csv, dtype=str, low_memory=False)
        if 'เลขโฉนด' not in df.columns or 'จังหวัด' not in df.columns:
            return 0

        if 'ละติจูด' not in df.columns:
            df['ละติจูด'] = ""
        if 'ลองจิจูด' not in df.columns:
            df['ลองจิจูด'] = ""

        updated_count = 0
        prov_list = df['จังหวัด'].apply(clean_province_name).tolist()
        deed_list = df['เลขโฉนด'].apply(clean_deed_number).tolist()
        dist_list = df['อำเภอ'].apply(clean_district_name).tolist() if 'อำเภอ' in df.columns else None
        lat_col = df['ละติจูด'].fillna('').astype(str).tolist()
        lon_col = df['ลองจิจูด'].fillna('').astype(str).tolist()

        for idx in range(len(df)):
            pv = prov_list[idx]
            dd = deed_list[idx]
            dt = dist_list[idx] if dist_list is not None else ""
            if not pv or not dt or not dd:
                continue

            target_coords = coord_lookup.get((pv, dt, dd))
            if not target_coords:
                for tok in re.findall(r'\d+', dd):
                    target_coords = coord_lookup.get((pv, dt, tok))
                    if target_coords:
                        break

            if target_coords:
                new_lat, new_lon = target_coords
                if lat_col[idx].strip() != new_lat or lon_col[idx].strip() != new_lon:
                    lat_col[idx] = new_lat
                    lon_col[idx] = new_lon
                    updated_count += 1

        if updated_count > 0:
            df['ละติจูด'] = lat_col
            df['ลองจิจูด'] = lon_col
            for attempt in range(5):
                tmp_csv = f"{input_csv}.{os.getpid()}.{threading.get_ident()}.tmp"
                try:
                    df.to_csv(tmp_csv, index=False, encoding='utf-8-sig')
                    os.replace(tmp_csv, input_csv)
                    print(f"  💾 [CSV IN-PLACE] ซิงค์พิกัดจริงลง {os.path.basename(input_csv)} สำเร็จ {updated_count:,d} รายการ", flush=True)
                    break
                except (PermissionError, OSError):
                    time.sleep(1)
                finally:
                    if os.path.exists(tmp_csv):
                        try:
                            os.remove(tmp_csv)
                        except OSError:
                            pass
        return updated_count
    except Exception as e:
        print(f"  ⚠️ [CSV SYNC] ไม่สามารถอัปเดตไฟล์ CSV ได้: {e}", flush=True)
        return 0


def trigger_dashboard_merge():
    """Trigger merge_csv_monthly to update all_assets.parquet with newly enriched coordinates."""
    print("\n🔄 กำลังซิงค์ข้อมูลและอัปเดต Dashboard (all_assets.parquet)...", flush=True)
    try:
        py_scraper_dir = os.path.join(_ROOT_DIR, "Py Scraper")
        if py_scraper_dir not in sys.path:
            sys.path.insert(0, py_scraper_dir)
        import merge_csv_monthly
        merge_csv_monthly.merge_monthly_csv()
        print("✅ ซิงค์พิกัดจริงเข้าสู่ Dashboard เรียบร้อยแล้ว! พร้อมใช้งานทันที", flush=True)
    except Exception as e:
        print(f"⚠️ เกิดข้อผิดพลาดในการซิงค์เข้า Dashboard: {e}", flush=True)


def query_single_deed_api(item, prov_map, amp_map, rotator, req_delay=None):
    """Query LandsMaps REST API sequentially (1 Thread) with standard delay (15-16s) per request and LoginSocial session rotation."""
    prov = item['จังหวัด']
    dist = item['อำเภอ']
    deed = item['เลขโฉนด']

    pvc, am_codes = resolve_pv_am_codes(prov, dist, prov_map, amp_map)
    if not pvc:
        return item, 'PROVINCE_NOT_FOUND', None, None
    if not am_codes:
        return item, 'DISTRICT_NOT_FOUND', None, None

    # Extract clean numeric deed candidates (handles ranges like '26108-26111,138773')
    deed_candidates = [d for d in re.findall(r'\d+', str(deed)) if d and d != '0']
    if not deed_candidates:
        return item, 'NOT_FOUND', None, None

    cset = _get_centroids()
    force_rotate_next = False
    for deed_primary in deed_candidates[:2]:
        for amc in am_codes[:2]:
            url = (
                f"https://landsmaps.dol.go.th/apiService/LandsMaps/GetParcelByParcelNo/"
                f"{urllib.parse.quote(pvc)}/{urllib.parse.quote(amc)}/{urllib.parse.quote(deed_primary)}"
            )
            for attempt in range(2):
                tok = rotator.get_token(force_rotate=force_rotate_next)
                force_rotate_next = False
                # Enforce randomized delay (อิง delay 15-16 วิ เหมือนตัว scrap อื่น)
                if req_delay is not None and req_delay > 0:
                    time.sleep(random.uniform(req_delay, req_delay + 0.8))
                else:
                    time.sleep(get_scraper_delay())
                try:
                    t_req0 = time.time()
                    r_api = safe_ssl_get(
                        rotator._http,
                        url,
                        headers={**HEADERS_BASE, "Authorization": f"Bearer {tok}"},
                        timeout=12,
                        ssl_fallback_on_gov=True,
                    )
                    r_api.raise_for_status()
                    res = r_api.json()
                    req_elapsed = time.time() - t_req0
                    print(f"[HTTP-REQ ] LandsMaps -> GET /GetParcelByParcelNo/{pvc}/{amc}/{deed_primary} <- 200 OK ({req_elapsed:.2f}s)", flush=True)
                    # Check if quota exceeded or server error -> mark next attempt to rotate session ONCE
                    if res.get("status") == 500 or res.get("error"):
                        force_rotate_next = True
                        continue
                    r_list = res.get("result")
                    if r_list and r_list[0]:
                        p0 = r_list[0]
                        lat_v = p0.get("parcellat")
                        lon_v = p0.get("parcellon")
                        if is_valid_thailand_real_coord(lat_v, lon_v, cset):
                            return item, 'FOUND', float(lat_v), float(lon_v)
                    break
                except Exception as e:
                    print(f"[HTTP-REQ ] LandsMaps -> GET /GetParcelByParcelNo/{pvc}/{amc}/{deed_primary} <- ERR ({e})", flush=True)
                    force_rotate_next = True
                    if attempt == 0:
                        time.sleep(1.0)
    return item, 'NOT_FOUND', None, None


def run_enrichment(
    input_file=None,
    cache_file=CACHE_PATH,
    province_filter=None,
    limit=None,
    delay=None,
    headless=True,
    auto_merge=False,
    retry_not_found=False,
    workers=1
):
    if any(a.lower() in ["--now", "-now", "now", "--ignore-window", "--force-now", "--no-window"] for a in sys.argv):
        os.environ["SCRAPER_IGNORE_WINDOW"] = "1"
    wait_for_active_window("LandsMaps")

    if delay is not None:
        req_delay = max(0.5, float(delay))
        delay_display = f"{req_delay:.1f}s"
    else:
        req_delay = None
        d_min, d_max = get_scraper_delay_range()
        delay_display = f"{d_min:.0f}-{d_max:.0f}s"
    workers = 1  # Strictly enforce 1 Thread as requested

    explicit_input = bool(input_file)
    target_files = []
    if not explicit_input:
        primary_csv = find_latest_led_csv()
        merge_csv = find_latest_led_merge_csv()
        target_files = [f for f in [primary_csv, merge_csv] if f and os.path.exists(f)]
        if not target_files:
            print(f"[ERROR] No LED CSV found in {os.path.join(_ROOT_DIR, 'CSV_Output')}. Please specify --input.")
            sys.exit(1)
        input_file = target_files[0]
    else:
        target_files = [input_file]

    print(f"=== LandsMaps Real Coordinates Scraper (1-Thread Safe Mode, All Provinces) ===")
    print(f"Input file : {', '.join(os.path.basename(f) for f in target_files)}")
    print(f"Cache file : {cache_file}")
    if province_filter:
        print(f"Province   : {province_filter}")
    else:
        print(f"Province   : ทุกจังหวัดทั่วประเทศ (Round-Robin Interleaved)")
    print(f"Rate Limit : 1 Thread | Delay {delay_display} per request (อิงมาตรฐาน Scraper) | Auto Session Reset (LoginSocial)")
    print("=" * 78)

    dfs = []
    for tf in target_files:
        part_df = None
        for attempt in range(5):
            try:
                if tf.endswith('.parquet'):
                    part_df = pd.read_parquet(tf)
                else:
                    part_df = pd.read_csv(tf, dtype=str, low_memory=False)
                break
            except (PermissionError, Exception) as e:
                if attempt < 4:
                    time.sleep(2)
                else:
                    print(f"[WARN] ไม่สามารถอ่านไฟล์ข้อมูล {tf}: {e}")
        if part_df is not None and not part_df.empty:
            dfs.append(part_df)

    if not dfs:
        print("[ERROR] ไม่สามารถโหลดข้อมูลจากไฟล์เป้าหมายได้")
        return
    df = pd.concat(dfs, ignore_index=True)

    if 'บริษัท' in df.columns:
        df = df[df['บริษัท'].astype(str).str.contains('กรมบังคับคดี|LED', na=False)]

    if 'เลขโฉนด' not in df.columns or 'จังหวัด' not in df.columns or 'อำเภอ' not in df.columns:
        print("[ERROR] Input data must have 'จังหวัด', 'อำเภอ', and 'เลขโฉนด' columns.")
        return

    df = df.copy()
    df['deed_clean'] = df['เลขโฉนด'].apply(clean_deed_number)
    df = df[df['deed_clean'].notna()]

    df['prov_clean'] = df['จังหวัด'].apply(clean_province_name)
    df['dist_clean'] = df['อำเภอ'].apply(clean_district_name)

    if province_filter:
        target_pv = clean_province_name(province_filter)
        df = df[df['prov_clean'].str.contains(target_pv, na=False, regex=False)]

    if df.empty:
        print("[INFO] No matching records found with valid deeds.")
        return

    cache_df = load_cache(cache_file)
    if retry_not_found and not cache_df.empty:
        before_cnt = len(cache_df)
        cache_df = cache_df[cache_df['สถานะ'] == 'FOUND'].copy()
        save_cache(cache_df, cache_file)
        print(f"[CACHE] Cleared {before_cnt - len(cache_df):,d} non-FOUND entries (--retry-not-found). Remaining FOUND: {len(cache_df):,d}")

    cached_keys = set()
    if not cache_df.empty:
        for _, row in cache_df.iterrows():
            pv = clean_province_name(row.get('จังหวัด', ''))
            dt = clean_district_name(row.get('อำเภอ', ''))
            dd = clean_deed_number(row.get('เลขโฉนด', ''))
            if pv and dd:
                cached_keys.add((pv, dt, dd))

    print(f"[CACHE] Loaded {len(cache_df):,d} records from cache ({len(cached_keys):,d} unique entries).")

    for tf in target_files:
        if tf and tf.lower().endswith('.csv'):
            sync_cnt = sync_cache_to_csv(tf, cache_df)
            if sync_cnt > 0:
                print(f"[CSV SYNC] Pre-synced {sync_cnt:,d} existing coordinates to {os.path.basename(tf)}")

    pending_records_raw = []
    seen = set()
    for row in df[['จังหวัด', 'อำเภอ', 'เลขโฉนด', 'prov_clean', 'dist_clean', 'deed_clean']].to_dict('records'):
        key = (row['prov_clean'], row['dist_clean'], row['deed_clean'])
        if key not in cached_keys and key not in seen:
            seen.add(key)
            pending_records_raw.append({
                'จังหวัด_orig': row['จังหวัด'],
                'อำเภอ_orig': row['อำเภอ'],
                'เลขโฉนด_orig': row['เลขโฉนด'],
                'จังหวัด': row['prov_clean'],
                'อำเภอ': row['dist_clean'],
                'เลขโฉนด': row['deed_clean']
            })

    # Round-Robin interleave across all provinces so all 77 provinces are covered evenly!
    if not province_filter and pending_records_raw:
        by_prov = {}
        for rec in pending_records_raw:
            by_prov.setdefault(rec['จังหวัด'], []).append(rec)
        prov_keys = sorted(by_prov.keys())
        pending_records = []
        max_len = max(len(v) for v in by_prov.values())
        for i in range(max_len):
            for pk in prov_keys:
                if i < len(by_prov[pk]):
                    pending_records.append(by_prov[pk][i])
    else:
        pending_records = pending_records_raw

    print(f"[STATUS] Total candidate deeds in file: {len(df):,d}")
    print(f"[STATUS] Already cached: {len(df) - len(pending_records):,d}")
    print(f"[STATUS] Pending search: {len(pending_records):,d}")

    if not pending_records:
        total_found_all = int((cache_df['สถานะ'] == 'FOUND').sum()) if not cache_df.empty else 0
        print(f"[{'LandsMaps':<13s}] ✅ สแครปเสร็จสมบูรณ์ ({len(df):,d}/{len(df):,d} โฉนด) | สะสม: {total_found_all:,d} รายการ", flush=True)
        print("🎉 Completed! ข้อมูลโฉนดทั้งหมดมีพิกัดในแคชสมบูรณ์ครบถ้วน 100% แล้ว", flush=True)
        return

    if limit and limit > 0:
        pending_records = pending_records[:limit]
        print(f"[STATUS] Processing limit applied: {len(pending_records):,d} deeds.")

    rotator = DolSessionRotator(max_uses_per_token=20)
    prov_map, amp_map = load_master_codes(rotator)
    print(f"[MASTER] Loaded {len(prov_map)} provinces and {len(amp_map)} district mappings.")

    new_results = []
    processed_count = 0
    found_in_session = 0
    not_found_in_session = 0
    total_pending = len(pending_records)
    start_all_time = time.time()

    print("\n" + "=" * 78, flush=True)
    print(f"🚀 เริ่มค้นหาพิกัดจริง LandsMaps ทุกจังหวัด ({total_pending:,d} รายการ | 1 Thread | Delay >= {delay_display})", flush=True)
    print("=" * 78, flush=True)

    try:
        for item in pending_records:
            wait_for_active_window("LandsMaps")
            processed_count += 1
            try:
                item, status, lat_found, lon_found = query_single_deed_api(
                    item, prov_map, amp_map, rotator, req_delay=req_delay
                )
            except Exception as loop_err:
                print(f"  ⚠️ [NETWORK RETRY] พักรอการเชื่อมต่อชั่วคราว 5 วินาที ({loop_err})...", flush=True)
                time.sleep(5.0)
                continue
            if status == 'FOUND':
                found_in_session += 1
                res_desc = f"🎯 พิกัดจริง: ({lat_found:.6f}, {lon_found:.6f})"
            elif status == 'NOT_FOUND':
                not_found_in_session += 1
                res_desc = "❌ ไม่พบข้อมูลแปลงที่ดิน"
            else:
                res_desc = f"⚠️ {status}"

            new_results.append({
                'จังหวัด': item['จังหวัด'],
                'อำเภอ': item['อำเภอ'],
                'เลขโฉนด': item['เลขโฉนด'],
                'ละติจูด': lat_found,
                'ลองจิจูด': lon_found,
                'สถานะ': status,
                'วันที่ดึง': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })

            total_found_all = int((cache_df['สถานะ'] == 'FOUND').sum()) + found_in_session

            pct = int((processed_count / total_pending) * 100)
            pbar = make_progress_bar(pct, length=18)
            elapsed = time.time() - start_all_time
            eta_str = format_eta(elapsed, processed_count, total_pending, 1)

            # Smart CLI Progress Bar Line
            prog_line = f"[{'LandsMaps':<13s}] {pbar} | ({processed_count:5d}/{total_pending:5d} โฉนด) | สะสม: {total_found_all:,d} รายการ | {eta_str}"
            print(prog_line, flush=True)

            # Smart CLI Detail Line
            detail_line = f"[{'LandsMaps':<13s}] ➔ {item['จังหวัด']} > {item['อำเภอ']} > โฉนด {item['เลขโฉนด']}: {res_desc}"
            print(detail_line, flush=True)

            # Save cache & sync CSV every 15 deeds (with atomic RMW reload-merge)
            if len(new_results) >= 15:
                cache_df = merge_and_save_cache(new_results, cache_df, cache_file=cache_file)
                if not explicit_input:
                    latest_merge = find_latest_led_merge_csv()
                    if latest_merge and os.path.abspath(latest_merge) not in [os.path.abspath(x) for x in target_files]:
                        target_files.append(latest_merge)
                for tf in target_files:
                    if tf and tf.lower().endswith('.csv'):
                        sync_cache_to_csv(tf, cache_df)
                new_results.clear()
                total_found_all = int((cache_df['สถานะ'] == 'FOUND').sum())
                print(f"[{'LandsMaps':<13s}] 💾 [SAVED] อัปเดตแคชเรียบร้อย (รวมในแคช: {len(cache_df):,d} แปลง | พิกัดจริงสะสม: {total_found_all:,d} แปลง)", flush=True)

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] User cancelled process. Saving current progress...")
    finally:
        if new_results:
            cache_df = merge_and_save_cache(new_results, cache_df, cache_file=cache_file)
        if not explicit_input:
            latest_merge = find_latest_led_merge_csv()
            if latest_merge and os.path.abspath(latest_merge) not in [os.path.abspath(x) for x in target_files]:
                target_files.append(latest_merge)
        for tf in target_files:
            if tf and tf.lower().endswith('.csv'):
                sync_cache_to_csv(tf, cache_df)

    elapsed = time.time() - start_all_time
    total_found_all = int((cache_df['สถานะ'] == 'FOUND').sum()) if not cache_df.empty else 0
    print("\n" + "=" * 78, flush=True)
    print(f"[{'LandsMaps':<13s}] ✅ สแครปเสร็จสมบูรณ์ ({processed_count:,d}/{total_pending:,d} โฉนด) | สะสม: {total_found_all:,d} รายการ", flush=True)
    print(f"🎉 Completed! Processed {processed_count:,d} deeds in {elapsed:.1f} seconds ({rotator.rotation_count} rotated sessions).", flush=True)
    if not cache_df.empty:
        found_cnt = int((cache_df['สถานะ'] == 'FOUND').sum())
        not_found_cnt = int((cache_df['สถานะ'] == 'NOT_FOUND').sum())
        print(f"Cache summary:")
        print(f" - FOUND real GPS : {found_cnt:,d} assets")
        print(f" - NOT FOUND      : {not_found_cnt:,d} assets")
        print(f" - Total in cache : {len(cache_df):,d}")
    print("=" * 78)

    if auto_merge:
        trigger_dashboard_merge()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Scrape real coordinates from LandsMaps for LED assets (1-Thread Safe Mode)")
    parser.add_argument('--input', type=str, help="Input CSV or Parquet file path")
    parser.add_argument('--cache', type=str, default=CACHE_PATH, help="Cache Parquet file path")
    parser.add_argument('--province', type=str, help="Filter search to specific province")
    parser.add_argument('--limit', type=int, default=0, help="Limit number of deeds to process (0 = all)")
    parser.add_argument('--delay', type=float, default=None, help="Delay between requests in seconds (default: follow scraper delay 15-16s)")
    parser.add_argument('--workers', type=int, default=1, help="Number of workers (locked to 1 Thread)")
    parser.add_argument('--headless', action='store_true', help="Run browser in headless mode")
    parser.add_argument('--no-merge', action='store_true', help="Do not auto-merge into all_assets.parquet after completion")
    parser.add_argument('--retry-not-found', action='store_true', help="Clear NOT_FOUND/TIMEOUT entries from cache before running")
    parser.add_argument('--now', '-now', '--ignore-window', action='store_true', help="Ignore active window and run immediately")

    args, _unknown = parser.parse_known_args()
    if args.now:
        os.environ["SCRAPER_IGNORE_WINDOW"] = "1"
    run_enrichment(
        input_file=args.input,
        cache_file=args.cache,
        province_filter=args.province,
        limit=args.limit,
        delay=args.delay,
        headless=args.headless,
        auto_merge=not args.no_merge,
        retry_not_found=args.retry_not_found,
        workers=1
    )
