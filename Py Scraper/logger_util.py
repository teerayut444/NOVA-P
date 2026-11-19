import os
import sys
import time
import json
import re
import threading
from datetime import datetime
from pathlib import Path
import requests

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Paths
_raw_base = Path(sys.executable).parent.resolve() if getattr(sys, 'frozen', False) else Path(__file__).parent.resolve()
BASE_DIR = _raw_base
ROOT_DIR = _raw_base.parent.resolve() if _raw_base.name.lower() in ["py scraper", "monthly all new", "dist", "build"] else _raw_base
MONTH_STR = datetime.now().strftime("%Y_%m")

LOGS_DIR = ROOT_DIR / "logs" / MONTH_STR
os.makedirs(LOGS_DIR, exist_ok=True)

# 1. Central Master Log (Clean & High-Level: Only START and FINISH per company)
_seen_paths = set()
CENTRAL_LOG_PATHS = []
for p in [BASE_DIR / "scraping.log", ROOT_DIR / "scraping.log"]:
    resolved_p = p.resolve()
    if resolved_p not in _seen_paths:
        _seen_paths.add(resolved_p)
        CENTRAL_LOG_PATHS.append(p)

# Kept for backward-compatibility reference
CENTRAL_MILESTONE_LOG_PATHS = CENTRAL_LOG_PATHS
CENTRAL_REQUEST_LOG_PATHS = []

_log_lock = threading.Lock()
_started_companies = {}

def get_company_log_path(company_name: str, is_request_log: bool = False, month_str: str = None) -> Path:
    m_str = month_str or MONTH_STR
    comp_dir = ROOT_DIR / "logs" / m_str
    os.makedirs(comp_dir, exist_ok=True)
    if is_request_log:
        return comp_dir / f"{company_name}_requests.log"
    return comp_dir / f"{company_name}.log"

def _format_log_line(company_name: str, level: str, message: str) -> str:
    now = datetime.now()
    full_timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    clean_level = level.upper().strip()
    return f"[{full_timestamp}] [{clean_level:<6s}] [{company_name:<13s}] {message}\n"

def _write_to_logs(log_line: str, company_name: str, month_str: str = None, company_only: bool = False):
    with _log_lock:
        if not company_only:
            # Central Master Log (scraping.log)
            for central_path in CENTRAL_LOG_PATHS:
                try:
                    with open(central_path, "a", encoding="utf-8") as f:
                        f.write(log_line)
                except Exception:
                    pass
                
        # Company Milestone Log (logs/YYYY_MM/[Company].log)
        try:
            comp_log = get_company_log_path(company_name, is_request_log=False, month_str=month_str)
            with open(comp_log, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception:
            pass

def format_duration(seconds: float) -> str:
    """แปลงวินาทีเป็นข้อความภาษาไทย เช่น '1 ชั่วโมง 15 นาที 30 วินาที' หรือ '3 นาที 45 วินาที'"""
    if seconds is None or seconds < 0:
        return "0 วินาที"
    total_sec = int(round(seconds))
    hours = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    parts = []
    if hours > 0:
        parts.append(f"{hours} ชั่วโมง")
    if mins > 0:
        parts.append(f"{mins} นาที")
    if secs > 0 or not parts:
        parts.append(f"{secs} วินาที")
    return " ".join(parts)

def log_start(company_name: str, message: str = "", start_clock: str = None, month_str: str = None):
    """
    บันทึกเวลาเริ่มทำงานของแต่ละตัว
    """
    now = datetime.now()
    clock_str = start_clock or now.strftime("%H:%M:%S")
    _started_companies[company_name] = (time.time(), clock_str)
    
    msg = message if message else f"เวลาเริ่ม: {clock_str}"
    log_line = _format_log_line(company_name, "START", msg)
    _write_to_logs(log_line, company_name, month_str=month_str)

def log_finish(company_name: str, duration_sec: float = None, records: int = None, is_error: bool = False, message: str = "", start_clock: str = None, month_str: str = None):
    """
    บันทึกเวลาเริ่ม เวลาเสร็จ และเวลารวมที่ใช้ไปของแต่ละตัว (พร้อมจำนวนข้อมูล)
    """
    now = datetime.now()
    finish_clock = now.strftime("%H:%M:%S")
    
    start_info = _started_companies.get(company_name)
    s_clock = start_clock or (start_info[1] if start_info else "")
    
    if duration_sec is None and start_info:
        duration_sec = time.time() - start_info[0]
        
    dur_text = format_duration(duration_sec) if duration_sec is not None else ""
    
    if message:
        final_msg = message
    else:
        parts = []
        if s_clock:
            parts.append(f"เวลาเริ่ม: {s_clock}")
        parts.append(f"เวลาเสร็จ: {finish_clock}")
        if dur_text:
            parts.append(f"เวลารวมที่ใช้: {dur_text}")
        if records is not None and records > 0:
            parts.append(f"ข้อมูล: {records:,} รายการ")
        if is_error:
            parts.append("❌ เกิดข้อผิดพลาด")
        final_msg = " | ".join(parts)
        
    level = "ERROR" if is_error else "FINISH"
    log_line = _format_log_line(company_name, level, final_msg)
    _write_to_logs(log_line, company_name, month_str=month_str)

def log_txn(company_name: str, level: str, message: str, month_str: str = None):
    """
    บันทึก Event สำคัญลง Master log (START, FINISH, ERROR, CRITICAL, TIMEOUT_WAIT)
    และบันทึก WARN ลงไฟล์ log ประจำบริษัทเพื่อเก็บประวัติปัญหาโดยไม่ทำให้ Master log รก
    """
    clean_level = level.upper().strip()
    if clean_level in ("START", "FINISH", "ERROR", "CRITICAL", "TIMEOUT_WAIT"):
        lvl = "CRITICAL" if clean_level == "CRITICAL" else clean_level
        log_line = _format_log_line(company_name, lvl, message)
        _write_to_logs(log_line, company_name, month_str=month_str, company_only=False)
    elif clean_level in ("WARNING", "WARN"):
        log_line = _format_log_line(company_name, "WARN", message)
        _write_to_logs(log_line, company_name, month_str=month_str, company_only=True)
    elif clean_level == "SUCCESS":
        # ถ้าเป็นการรันเดี่ยว (ไม่ได้รันผ่าน run_parallel_monthly runner) ให้บันทึกเป็น FINISH
        if os.environ.get("RUN_PARALLEL_MANAGED") != "1":
            log_finish(company_name, message=message, month_str=month_str)

def log_http_audit(company_name: str, method: str, url: str, status_code: int, elapsed_ms: int, size_kb: float, month_str: str = None):
    """
    ปิดการบันทึก HTTP Request ละเอียดยิบลงไฟล์ตามคำสั่ง เพื่อให้บันทึก log แค่เวลาเริ่มและเวลาเสร็จของแต่ละตัว
    """
    pass

def log_info(company_name: str, message: str):
    # ละเว้นข้อความทั่วไป ไม่บันทึกลงไฟล์
    pass

def log_warning(company_name: str, message: str):
    log_txn(company_name, "WARN", message)

def log_error(company_name: str, message: str):
    log_txn(company_name, "ERROR", message)

def log_timeout(company_name: str, message: str):
    log_txn(company_name, "TIMEOUT_WAIT", message)

def log_milestone(company_name: str, message: str):
    # ละเว้น milestone ย่อย (5%, 10%...) ไม่บันทึกลงไฟล์
    pass

def log_success(company_name: str, message: str):
    log_txn(company_name, "SUCCESS", message)

def print_structure_alert(company_name: str, issue_details: str):
    """
    Print an explicit, unmissable structural alert box in console and record to logs.
    """
    alert_box = (
        f"\n" + "=" * 75 + "\n"
        f"🚨 [STRUCTURE ALERT] ตรวจพบโครงสร้างเว็บของ [{company_name}] มีการเปลี่ยนแปลง!\n"
        f"⚠️  รายละเอียด: {issue_details}\n"
        f"💡 คำแนะนำ: กรุณาตรวจสอบ DOM Selectors, API Response Schema หรือ Keys ของเว็บไซต์นี้\n"
        + "=" * 75 + "\n"
    )
    print(alert_box, flush=True)
    log_txn(company_name, "ERROR", f"🚨 โครงสร้างเว็บเปลี่ยน: {issue_details}")

def print_alert(message: str, level: str = "ERROR", company_name: str = ""):
    """
    Print a generic alert box and log ERROR / CRITICAL / WARNING diagnostics.
    """
    lvl = str(level or "ERROR").upper().strip()
    box = (
        f"\n" + "=" * 75 + "\n"
        f"🚨 [{lvl} ALERT] {f'({company_name}): ' if company_name else ''}{message}\n"
        + "=" * 75 + "\n"
    )
    print(box, flush=True)
    if company_name and lvl in ("ERROR", "CRITICAL", "WARNING", "WARN"):
        log_txn(company_name, lvl, message)

_session_last_req_time = {}
_session_delay_lock = threading.Lock()

def get_min_scraper_delay() -> float:
    """ดึงค่าหน่วงเวลาขั้นต่ำต่อคำขอ (ค่าเริ่มต้น 15.0 วินาที ตามนโยบายป้องกันการตรวจจับ)"""
    try:
        return float(os.environ.get("SCRAPER_MIN_DELAY", "15.0"))
    except Exception:
        return 15.0

class AuditedSession(requests.Session):
    """
    Standard requests.Session for scrapers with live request output to console for the Runner UI.
    Does NOT write request logs to disk files.
    Enforces minimum delay (default >= 15.0 seconds) per platform request.
    """
    def __init__(self, company_name: str = "SCRAPER"):
        super().__init__()
        self.company_name = company_name
        # If running standalone (not under run_parallel_monthly runner), auto-log start
        if os.environ.get("RUN_PARALLEL_MANAGED") != "1" and self.company_name not in ["SCRAPER", "TEST", "TEST_SEP"]:
            if self.company_name not in _started_companies:
                log_start(self.company_name)

    def request(self, method, url, *args, **kwargs):
        try:
            from time_window_util import wait_for_active_window
            wait_for_active_window(self.company_name)
        except Exception:
            pass

        # บังคับหน่วงเวลาอย่างน้อยต่อคำขอ สำหรับทุกตัว scrap
        min_delay = get_min_scraper_delay()
        if min_delay > 0:
            sleep_time = 0.0
            with _session_delay_lock:
                now = time.time()
                last_t = _session_last_req_time.get(self.company_name, 0.0)
                elapsed = now - last_t
                if last_t > 0 and elapsed < min_delay:
                    sleep_time = min_delay - elapsed
                    _session_last_req_time[self.company_name] = now + sleep_time
                else:
                    _session_last_req_time[self.company_name] = now
            if sleep_time > 0:
                time.sleep(sleep_time)

        t0 = time.time()
        try:
            resp = super().request(method, url, *args, **kwargs)
            with _session_delay_lock:
                _session_last_req_time[self.company_name] = max(_session_last_req_time.get(self.company_name, 0.0), time.time())
            elapsed_ms = int((time.time() - t0) * 1000)
            status_code = resp.status_code
            size_kb = len(resp.content) / 1024 if resp.content else 0.0
            
            # ส่งข้อมูล request ให้ตัวรัน (Runner) แสดงใน Live Dashboard
            req_msg = f"-> {method.upper()} {url} <- {status_code} ({elapsed_ms}ms | {size_kb:.1f} KB)"
            print(f"[HTTP-REQ ] [{self.company_name:<14s}] {req_msg}", flush=True)
            return resp
        except Exception as e:
            with _session_delay_lock:
                _session_last_req_time[self.company_name] = max(_session_last_req_time.get(self.company_name, 0.0), time.time())
            elapsed_ms = int((time.time() - t0) * 1000)
            print(f"[HTTP-REQ ] [{self.company_name:<14s}] -> {method.upper()} {url} <- ERR ({elapsed_ms}ms | {e})", flush=True)
            raise

if HAS_CURL_CFFI:
    class AuditedCurlSession(curl_requests.Session):
        """
        Chrome-impersonated HTTP session for scrapers with live request output to console for the Runner UI.
        Does NOT write request logs to disk files.
        Enforces minimum delay (default >= 15.0 seconds) per platform request.
        """
        def __init__(self, company_name: str = "SCRAPER", impersonate: str = "chrome120", *args, **kwargs):
            super().__init__(impersonate=impersonate, *args, **kwargs)
            self.company_name = company_name
            # If running standalone (not under run_parallel_monthly runner), auto-log start
            if os.environ.get("RUN_PARALLEL_MANAGED") != "1" and self.company_name not in ["SCRAPER", "TEST", "TEST_SEP"]:
                if self.company_name not in _started_companies:
                    log_start(self.company_name)

        def request(self, method, url, *args, **kwargs):
            try:
                from time_window_util import wait_for_active_window
                wait_for_active_window(self.company_name)
            except Exception:
                pass

            # บังคับหน่วงเวลาอย่างน้อยต่อคำขอ สำหรับทุกตัว scrap
            min_delay = get_min_scraper_delay()
            if min_delay > 0:
                sleep_time = 0.0
                with _session_delay_lock:
                    now = time.time()
                    last_t = _session_last_req_time.get(self.company_name, 0.0)
                    elapsed = now - last_t
                    if last_t > 0 and elapsed < min_delay:
                        sleep_time = min_delay - elapsed
                        _session_last_req_time[self.company_name] = now + sleep_time
                    else:
                        _session_last_req_time[self.company_name] = now
                if sleep_time > 0:
                    time.sleep(sleep_time)

            t0 = time.time()
            try:
                resp = super().request(method, url, *args, **kwargs)
                with _session_delay_lock:
                    _session_last_req_time[self.company_name] = max(_session_last_req_time.get(self.company_name, 0.0), time.time())
                elapsed_ms = int((time.time() - t0) * 1000)
                status_code = resp.status_code
                size_kb = len(resp.content) / 1024 if resp.content else 0.0
                
                # ส่งข้อมูล request ให้ตัวรัน (Runner) แสดงใน Live Dashboard
                req_msg = f"-> {method.upper()} {url} <- {status_code} ({elapsed_ms}ms | {size_kb:.1f} KB)"
                print(f"[HTTP-REQ ] [{self.company_name:<14s}] {req_msg}", flush=True)
                return resp
            except Exception as e:
                with _session_delay_lock:
                    _session_last_req_time[self.company_name] = max(_session_last_req_time.get(self.company_name, 0.0), time.time())
                elapsed_ms = int((time.time() - t0) * 1000)
                print(f"[HTTP-REQ ] [{self.company_name:<14s}] -> {method.upper()} {url} <- ERR ({elapsed_ms}ms | {e})", flush=True)
                raise
else:
    AuditedCurlSession = AuditedSession


# ==========================================
# Central Scraper State Management (JSON)
# ==========================================

def get_state_file_path(company_name: str, month_str: str = None) -> str:
    m_str = month_str or MONTH_STR
    out_dir = os.path.join(ROOT_DIR, "CSV_Output", m_str)
    os.makedirs(out_dir, exist_ok=True)
    c_key = re.sub(r'[^a-zA-Z0-9_]', '', company_name.lower())
    return os.path.join(out_dir, f".{c_key}_state_{m_str}.json")

def save_scraper_state(company_name: str, completed_pages: int, total_pages: int = 0, total_records: int = 0, status: str = "RUNNING", month_str: str = None, extra: dict = None):
    """
    บันทึกสถานะ Checkpoint การสแครปลงไฟล์ JSON ใน CSV_Output/YYYY_MM/.{company}_state_{month}.json
    """
    try:
        m_str = month_str or MONTH_STR
        filepath = get_state_file_path(company_name, m_str)
        payload = {
            "company": company_name,
            "month": m_str,
            "completed_pages": int(completed_pages),
            "total_pages": int(total_pages),
            "total_records": int(total_records),
            "status": status,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        if extra and isinstance(extra, dict):
            payload.update(extra)
        tmp_path = f"{filepath}.{os.getpid()}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        if os.path.exists(tmp_path):
            for _ in range(3):
                try:
                    os.replace(tmp_path, filepath)
                    break
                except Exception:
                    time.sleep(0.1)
    except Exception:
        pass

def load_scraper_state(company_name: str, month_str: str = None) -> dict:
    """
    โหลดสถานะ Checkpoint จากไฟล์ JSON ของบริษัทนั้นๆ
    """
    try:
        filepath = get_state_file_path(company_name, month_str)
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def reset_scraper_state(company_name: str, month_str: str = None):
    """
    ลบไฟล์สถานะ Checkpoint เมื่อต้องการรันใหม่ทั้งหมด (--fresh)
    """
    try:
        filepath = get_state_file_path(company_name, month_str)
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass


# ==========================================
# Shared Security, HTTP TLS, API Key & Safe CSV Helpers
# ==========================================

_SSL_WARNED_HOSTS = set()
_NAYOO_API_KEY_CACHE = None
_NAYOO_KEY_LOCK = threading.Lock()

def safe_ssl_request(session, method: str, url: str, ssl_fallback_on_gov: bool = True, **kwargs):
    """
    Execute HTTP request with TLS verification enabled by default.
    Only falls back to verify=False on .go.th domains if certificate verification fails,
    logging a clear warning once per host instead of blindly disabling SSL globally.
    """
    from urllib.parse import urlparse
    req_kwargs = dict(kwargs)
    req_kwargs.setdefault("verify", True)
    try:
        return session.request(method, url, **req_kwargs)
    except Exception as exc:
        msg = str(exc).lower()
        is_ssl_err = isinstance(exc, requests.exceptions.SSLError) or "ssl" in msg or "certificate" in msg
        host = urlparse(url).netloc.lower()
        if is_ssl_err and ssl_fallback_on_gov and host.endswith(".go.th"):
            if host not in _SSL_WARNED_HOSTS:
                _SSL_WARNED_HOSTS.add(host)
                comp = getattr(session, "company_name", "HTTP")
                msg_warn = f"TLS certificate verification failed for {host} ({exc}); falling back to verify=False for .go.th"
                print(f"[{comp}] ⚠️ {msg_warn}", flush=True)
                log_warning(comp, msg_warn)
            req_kwargs["verify"] = False
            return session.request(method, url, **req_kwargs)
        raise

def safe_ssl_get(session, url: str, **kwargs):
    return safe_ssl_request(session, "GET", url, **kwargs)

def safe_ssl_post(session, url: str, **kwargs):
    return safe_ssl_request(session, "POST", url, **kwargs)

def get_nayoo_api_key(session=None, timeout: int = 10) -> str:
    """
    Resolve NaYoo public API gateway key without hardcoding credentials in source/EXE:
    1. Environment variable NAYOO_API_KEY
    2. Optional external scraper_config.json (key: 'nayoo_api_key') next to ROOT_DIR / BASE_DIR
    3. Cached value discovered in-process
    4. Auto-discover from https://nayoo.co/ frontend Next.js chunks
    """
    global _NAYOO_API_KEY_CACHE
    env_k = os.environ.get("NAYOO_API_KEY", "").strip()
    if env_k:
        return env_k

    with _NAYOO_KEY_LOCK:
        if _NAYOO_API_KEY_CACHE:
            return _NAYOO_API_KEY_CACHE

        for cfg_dir in (BASE_DIR, ROOT_DIR):
            cfg_path = cfg_dir / "scraper_config.json"
            if cfg_path.exists():
                try:
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                    k = str(cfg.get("nayoo_api_key") or "").strip()
                    if k:
                        _NAYOO_API_KEY_CACHE = k
                        return k
                except Exception:
                    pass

        own_sess = session is None
        sess = session or requests.Session()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            r = safe_ssl_get(sess, "https://nayoo.co/", headers=headers, timeout=timeout, ssl_fallback_on_gov=False)
            if r.status_code == 200:
                m_inline = re.search(r'apikey\s*[:=]\s*["\']([a-f0-9]{32,})["\']', r.text, re.I)
                if m_inline:
                    _NAYOO_API_KEY_CACHE = m_inline.group(1)
                    return _NAYOO_API_KEY_CACHE
                scripts = re.findall(r'src="(https://static\.nayoo\.co/[^"]+\.js[^"]*)"', r.text)
                for chunk_url in scripts:
                    try:
                        rc = safe_ssl_get(sess, chunk_url, headers=headers, timeout=timeout, ssl_fallback_on_gov=False)
                        if rc.status_code == 200:
                            m_key = re.search(r'apikey\s*:\s*["\']([a-f0-9]{32,})["\']', rc.text, re.I)
                            if m_key:
                                _NAYOO_API_KEY_CACHE = m_key.group(1)
                                return _NAYOO_API_KEY_CACHE
                    except Exception:
                        continue
        except Exception:
            pass
        finally:
            if own_sess:
                try:
                    sess.close()
                except Exception:
                    pass
    return ""

def clean_resume_id(val) -> str:
    """Normalize ID/deed loaded from CSV without float '.0' artifacts or invalid placeholders."""
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("", "nan", "none", "null", "<na>", "undefined"):
        return ""
    if s.endswith(".0") and s[:-2].replace("-", "").isdigit():
        s = s[:-2]
    return s

def read_csv_resume(filename: str, columns: list, id_col: str = "ID", company_name: str = ""):
    """Load existing scraper CSV safely with dtype=str to prevent float '.0' ID/deed corruption."""
    import pandas as pd
    records = []
    seen_ids = set()
    if os.path.exists(filename):
        try:
            df = pd.read_csv(filename, encoding="utf-8-sig", dtype=str, keep_default_na=False).fillna("")
            for col in columns:
                if col not in df.columns:
                    df[col] = ""
            raw_records = df[columns].to_dict(orient="records")
            for r in raw_records:
                iid = clean_resume_id(r.get(id_col))
                if iid:
                    r[id_col] = iid
                    seen_ids.add(iid)
                records.append(r)
        except Exception as e:
            if company_name:
                print_alert(f"ไม่สามารถอ่านไฟล์สะสมเดิม {filename}: {e}", level="WARNING", company_name=company_name)
    return records, seen_ids

def atomic_write_csv(records: list, filename: str, columns: list, company_name: str = "") -> bool:
    """Write scraper records atomically via .tmp -> os.replace with Excel-lock backup fallback & .tmp cleanup."""
    import pandas as pd
    tmp_filename = f"{filename}.{os.getpid()}.tmp"
    try:
        df = pd.DataFrame(records)
        for col in columns:
            if col not in df.columns:
                df[col] = ""
        df = df[columns]
        os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)
        df.to_csv(tmp_filename, index=False, encoding="utf-8-sig")
        for attempt in range(5):
            try:
                os.replace(tmp_filename, filename)
                return True
            except PermissionError:
                if attempt < 4:
                    time.sleep(1)
                else:
                    alt_file = filename.replace(".csv", "_BACKUP.csv")
                    df.to_csv(alt_file, index=False, encoding="utf-8-sig")
                    print(f"\n⚠️ [FILE LOCKED] ไฟล์ {os.path.basename(filename)} ถูกเปิดล็อกไว้ใน Excel -> บันทึกข้อมูลสำรองไว้ที่ {os.path.basename(alt_file)} แทน", flush=True)
                    return True
        return True
    except Exception as e:
        print_alert(f"เกิดข้อผิดพลาดในการเซฟไฟล์ CSV '{filename}': {e}", level="CRITICAL", company_name=company_name)
        return False
    finally:
        if os.path.exists(tmp_filename):
            try:
                os.remove(tmp_filename)
            except Exception:
                pass
