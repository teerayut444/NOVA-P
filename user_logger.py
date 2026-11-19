"""
User Access Logger Module
=========================
Logs visitor IP address, Windows domain username, session ID, user agent,
and timestamps to SQLite database.
Designed for Streamlit-based NOVA NPA Dashboard.
"""

import os
import re
import socket
import sqlite3
import hashlib
import ipaddress
import getpass
import threading
import subprocess
from collections import OrderedDict
from datetime import datetime, timezone, timedelta

# Thailand timezone (GMT+7)
TH_TZ = timezone(timedelta(hours=7))
_TS_FORMAT = "%Y-%m-%d %H:%M:%S"
# Maximum gap between heartbeats/interactions counted as active time (excludes sleep/hibernation gaps)
HEARTBEAT_MAX_GAP_SECONDS = 180

# Database path - stored in 'logs' directory relative to the app
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
DB_PATH = os.path.join(DB_DIR, "user_access.db")
_DB_INITIALIZED = False
_DB_LOCK = threading.Lock()

# Bounded memory cache for IP to resolved username/hostname mapping
_USER_CACHE_MAX = 5000
_USER_CACHE = OrderedDict()
_RESOLVING_IPS = set()
_LOCK = threading.Lock()

_SAFE_HOSTNAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,62}$')


def _cache_get(key):
    with _LOCK:
        if key not in _USER_CACHE:
            return None
        _USER_CACHE.move_to_end(key)
        return _USER_CACHE[key]


def _cache_set(key, val):
    if not key or not val:
        return
    with _LOCK:
        _USER_CACHE[key] = val
        _USER_CACHE.move_to_end(key)
        while len(_USER_CACHE) > _USER_CACHE_MAX:
            _USER_CACHE.popitem(last=False)


def _sanitize_username(raw_name):
    """Sanitize display/identity username from external inputs (URL params, headers)."""
    if raw_name is None:
        return ""
    cleaned = re.sub(r'[\x00-\x1f\x7f<>"\'`$;|&]', '', str(raw_name)).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned[:80]


def _sanitize_csv_cell(val):
    """Neutralize spreadsheet formula injection when exporting CSV cells."""
    if not isinstance(val, str):
        return val
    stripped = val.lstrip()
    if stripped and stripped[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + val
    return val


def _get_db_connection(timeout=15):
    """Create a SQLite connection with WAL mode and busy timeout for high concurrency."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=timeout)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass
    return conn


def _get_local_domain_user():
    """Retrieve current Windows domain and username for local / host machine."""
    try:
        domain = os.environ.get("USERDOMAIN", "")
        username = os.environ.get("USERNAME", getpass.getuser())
        if domain and domain.upper() not in ("", "WORKGROUP"):
            return f"{domain}\\{username}"
        return username
    except Exception:
        return "SAM\\User"


def _ensure_db():
    """Create database directory and table once per process (or if DB file was deleted)."""
    global _DB_INITIALIZED
    with _DB_LOCK:
        if _DB_INITIALIZED and os.path.exists(DB_PATH):
            return
        conn = _get_db_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS access_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip TEXT NOT NULL,
                    user_name TEXT DEFAULT '',
                    machine_user TEXT DEFAULT '',
                    session_id TEXT NOT NULL,
                    first_seen TIMESTAMP NOT NULL,
                    last_seen TIMESTAMP NOT NULL,
                    visit_count INTEGER DEFAULT 1,
                    user_agent TEXT,
                    page_views INTEGER DEFAULT 1,
                    duration_seconds INTEGER DEFAULT 0
                )
            """)
            # Auto-migration: Check if user_name / machine_user / duration_seconds columns exist
            cursor = conn.execute("PRAGMA table_info(access_logs)")
            cols = [r[1] for r in cursor.fetchall()]
            if "user_name" not in cols:
                try:
                    conn.execute("ALTER TABLE access_logs ADD COLUMN user_name TEXT DEFAULT ''")
                except Exception:
                    pass
            if "machine_user" not in cols:
                try:
                    conn.execute("ALTER TABLE access_logs ADD COLUMN machine_user TEXT DEFAULT ''")
                except Exception:
                    pass
            if "duration_seconds" not in cols:
                try:
                    conn.execute("ALTER TABLE access_logs ADD COLUMN duration_seconds INTEGER DEFAULT 0")
                except Exception:
                    pass

            # Backfill existing local entries with current user if empty
            try:
                local_user = _get_local_domain_user()
                conn.execute(
                    "UPDATE access_logs SET user_name = ? WHERE (user_name IS NULL OR user_name = '') AND ip LIKE '127.0.0.1%'",
                    (local_user,)
                )
                conn.execute(
                    "UPDATE access_logs SET machine_user = ? WHERE (machine_user IS NULL OR machine_user = '') AND ip LIKE '127.0.0.1%'",
                    (local_user,)
                )
            except Exception:
                pass

            conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON access_logs (session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ip ON access_logs (ip)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user ON access_logs (user_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_machine_user ON access_logs (machine_user)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS auth_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_time TIMESTAMP NOT NULL,
                    event_type TEXT NOT NULL,
                    username TEXT DEFAULT '',
                    user_name TEXT DEFAULT '',
                    ip TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    user_agent TEXT,
                    details TEXT DEFAULT ''
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_time ON auth_logs (event_time)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_type ON auth_logs (event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_user ON auth_logs (username)")
            conn.commit()
            _DB_INITIALIZED = True
        finally:
            conn.close()


def _extract_clean_ip(ip_str):
    """Extract validated IPv4/IPv6 address from IP string, stripping annotations."""
    if not ip_str:
        return ""
    raw = str(ip_str).strip()
    if "::1" in raw or "localhost" in raw.lower():
        return "127.0.0.1"
    # Direct parse first (handles bare IPv4/IPv6)
    candidate = raw.split(" ")[0].strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        pass
    m = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', raw)
    if m:
        try:
            return str(ipaddress.ip_address(m.group(1)))
        except ValueError:
            return ""
    return ""


def _resolve_network_identity(clean_ip):
    """
    Resolve client IP to Windows domain user or computer name on corporate network.
    1. If 127.0.0.1 or local machine IP -> return local domain user.
    2. Try Reverse DNS (socket.gethostbyaddr) -> get computer hostname (e.g. COM-003204.SAM.LOCAL).
    3. Try WMI query via PowerShell to get logged-in Windows username (e.g. SAM\\Teerayut.N).
    4. Fallback to computer hostname or clean IP if WMI is firewalled.
    """
    if not clean_ip or clean_ip in ("Unknown", ""):
        return "ไม่ระบุตัวตน"

    # Local host check
    if clean_ip == "127.0.0.1":
        return _get_local_domain_user()

    try:
        local_host_ip = socket.gethostbyname(socket.gethostname())
        if clean_ip == local_host_ip:
            return _get_local_domain_user()
    except Exception:
        pass

    # Reverse DNS to find Computer Name on SAM.LOCAL
    hostname = None
    short_name = None
    try:
        host_info = socket.gethostbyaddr(clean_ip)
        if host_info and host_info[0]:
            hostname = host_info[0]
            cand_short = hostname.split('.')[0].strip()
            if _SAFE_HOSTNAME_RE.match(cand_short):
                short_name = cand_short
    except Exception:
        pass

    # Strictly validate target_machine (valid IP or RFC hostname label) before WMI lookup
    valid_ip = ""
    try:
        valid_ip = str(ipaddress.ip_address(clean_ip))
    except ValueError:
        valid_ip = ""

    target_machine = short_name or valid_ip
    if target_machine and (_SAFE_HOSTNAME_RE.match(target_machine) or target_machine == valid_ip):
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            ps_env = os.environ.copy()
            ps_env["NOVA_WMI_TARGET"] = target_machine
            cmd = [
                'powershell',
                '-NoProfile',
                '-NonInteractive',
                '-Command',
                '(Get-WmiObject -Class Win32_ComputerSystem -ComputerName $env:NOVA_WMI_TARGET -ErrorAction Stop).UserName'
            ]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=2.5,
                env=ps_env,
                creationflags=creation_flags
            )
            wmi_user = _sanitize_username(res.stdout)
            if wmi_user and not wmi_user.lower().startswith("error") and "\\" in wmi_user:
                return wmi_user
        except Exception:
            pass

    # Fallback to computer name (e.g. COM-003204)
    if short_name:
        return short_name
    if hostname:
        return _sanitize_username(hostname)

    return f"IP: {clean_ip}"


def _async_resolve_and_update(session_id, clean_ip, resolve_user_name=True, resolve_machine_user=True):
    """Background worker to resolve network identity without delaying page response."""
    with _LOCK:
        if clean_ip in _RESOLVING_IPS:
            return
        _RESOLVING_IPS.add(clean_ip)

    try:
        resolved = _resolve_network_identity(clean_ip)
        if resolved:
            if resolve_machine_user:
                _cache_set(f"machine:{clean_ip}", resolved)
            if resolve_user_name:
                _cache_set(clean_ip, resolved)
            conn = _get_db_connection()
            try:
                if resolve_machine_user:
                    conn.execute(
                        "UPDATE access_logs SET machine_user = ? WHERE session_id = ? AND (machine_user IS NULL OR machine_user = '' OR machine_user = 'กำลังตรวจสอบ...')",
                        (resolved, session_id)
                    )
                if resolve_user_name:
                    conn.execute(
                        "UPDATE access_logs SET user_name = ? WHERE session_id = ? AND (user_name IS NULL OR user_name = '' OR user_name = 'กำลังตรวจสอบ...')",
                        (resolved, session_id)
                    )
                conn.commit()
            except Exception:
                pass
            finally:
                conn.close()
    except Exception:
        pass
    finally:
        with _LOCK:
            _RESOLVING_IPS.discard(clean_ip)


def _get_trusted_proxies():
    raw = os.environ.get("NOVA_TRUSTED_PROXIES", "").strip()
    if not raw:
        return set()
    return {p.strip() for p in raw.split(",") if p.strip()}


def _is_trusted_proxy(direct_ip):
    if not direct_ip:
        return False
    norm = _extract_clean_ip(direct_ip)
    return norm in _get_trusted_proxies()


def get_client_ip():
    """
    Attempt to extract the client's real IP address from Streamlit request headers.
    Uses direct WebSocket peer IP by default (port 8501); only inspects forwarding
    headers when peer IP matches NOVA_TRUSTED_PROXIES.
    """
    try:
        import streamlit as st

        try:
            direct_ip = st.context.ip_address
        except Exception:
            direct_ip = None

        trusted_proxies = _get_trusted_proxies()
        norm_direct = _extract_clean_ip(direct_ip) if direct_ip else ""

        if direct_ip and not (trusted_proxies and norm_direct in trusted_proxies):
            return re.sub(r'[^a-zA-Z0-9_\-\.\:]', '_', str(direct_ip).strip())[:45]

        if trusted_proxies and norm_direct in trusted_proxies:
            headers = getattr(st.context, "headers", {})
            ip_headers = [
                "X-Forwarded-For",
                "X-Real-Ip",
                "Cf-Connecting-Ip",
                "X-Client-Ip",
                "Remote-Addr",
            ]

            for header in ip_headers:
                val = headers.get(header)
                if val:
                    ip = val.split(",")[0].strip()
                    if ip and ip not in ("", "unknown", "::1"):
                        try:
                            valid_ip = str(ipaddress.ip_address(ip))
                            return f"{valid_ip} (Proxy)"
                        except ValueError:
                            continue

        return "127.0.0.1 (Local)"
    except Exception:
        return "Unknown"


def get_client_username(clean_ip=None):
    """
    Detect user identity from available sources:
    1. st.session_state['user_name'] (if set by app / login)
    2. Sanitized URL query parameters (?user=... or ?name=...)
    3. Streamlit Native Auth (st.user.name)
    4. Trusted Reverse Proxy SSO Headers (X-Forwarded-User, etc.)
    5. Bounded in-memory cache for this IP
    6. Localhost domain user
    """
    try:
        import streamlit as st

        # 1. Session state (explicit login identity takes priority)
        if st.session_state.get("user_name"):
            u = _sanitize_username(st.session_state["user_name"])
            if u:
                return u
        if st.session_state.get("auth_username"):
            u = _sanitize_username(st.session_state["auth_username"])
            if u:
                return u

        # 2. URL query parameters (sanitized)
        qp = getattr(st, "query_params", {})
        if "user" in qp:
            u = _sanitize_username(qp["user"])
            if u:
                return u
        if "name" in qp:
            u = _sanitize_username(qp["name"])
            if u:
                return u

        # 3. Streamlit Auth
        if hasattr(st, "user") and st.user and getattr(st.user, "name", None):
            u = _sanitize_username(st.user.name)
            if u:
                return u

        # 4. Corporate SSO headers (only when connected through trusted reverse proxy)
        try:
            direct_ip = st.context.ip_address
        except Exception:
            direct_ip = None
        if _is_trusted_proxy(direct_ip):
            headers = getattr(st.context, "headers", {})
            sso_headers = [
                "X-Forwarded-User",
                "X-Remote-User",
                "Remote-User",
                "X-Ms-Client-Principal-Name",
                "X-Auth-Request-User"
            ]
            for h in sso_headers:
                val = headers.get(h)
                if val:
                    u = _sanitize_username(val)
                    if u:
                        return u
    except Exception:
        pass

    # 5. Check in-memory cache
    if clean_ip:
        cached_u = _cache_get(clean_ip)
        if cached_u:
            return cached_u

    # 6. Local machine fallback
    if clean_ip == "127.0.0.1":
        local_u = _get_local_domain_user()
        _cache_set("127.0.0.1", local_u)
        return local_u

    return None


def get_user_agent():
    """Extract and sanitize the User-Agent string from Streamlit request headers."""
    try:
        import streamlit as st
        ua = str(st.context.headers.get("User-Agent", "Unknown") or "Unknown")
        ua = re.sub(r'[\r\n\t\x00<>]', ' ', ua).strip()
        return ua[:500] or "Unknown"
    except Exception:
        return "Unknown"


def _get_session_id():
    """Get the current Streamlit session ID."""
    try:
        import streamlit as st
        ctx = st.runtime.scriptrunner.get_script_run_ctx()
        if ctx:
            return ctx.session_id
    except Exception:
        pass
    return hashlib.md5(str(datetime.now()).encode()).hexdigest()[:16]


def _parse_ts(ts_str):
    """Parse stored TH_TZ timestamp string into timezone-aware datetime."""
    if not ts_str:
        return None
    try:
        return datetime.strptime(str(ts_str).strip()[:19], _TS_FORMAT).replace(tzinfo=TH_TZ)
    except Exception:
        return None


def _compute_updated_duration(prev_last_str, prev_duration_sec, now_dt, max_gap_seconds=HEARTBEAT_MAX_GAP_SECONDS):
    """
    Compute updated active duration in seconds and elapsed delta from prev_last_seen.
    Gaps larger than max_gap_seconds (e.g. device sleep/hibernation) are excluded.
    """
    base_dur = max(0, int(prev_duration_sec or 0))
    prev_dt = _parse_ts(prev_last_str)
    if prev_dt is None:
        return base_dur, None
    delta = int((now_dt - prev_dt).total_seconds())
    if 0 < delta <= max_gap_seconds:
        return base_dur + delta, delta
    return base_dur, delta


def format_duration_thai(seconds):
    """Format session duration seconds into readable Thai label."""
    secs = max(0, int(seconds or 0))
    if secs < 45:
        return "< 1 นาที"
    total_mins = max(1, round(secs / 60))
    if total_mins < 60:
        return f"{total_mins:,} นาที"
    hours, rem_mins = divmod(total_mins, 60)
    if rem_mins == 0:
        return f"{hours:,} ชม."
    return f"{hours:,} ชม. {rem_mins} นาที"


def format_machine_user_label(machine_user, user_name="", ip=""):
    """
    Return clean machine/domain user label when informative and distinct from user_name/IP.
    Hides placeholders, raw 'IP: ...' fallbacks, and exact duplicates of user_name.
    """
    mu = str(machine_user or "").strip()
    if not mu or mu in ("ไม่ระบุตัวตน", "กำลังตรวจสอบ...") or mu.startswith("IP:"):
        return ""
    clean_ip = _extract_clean_ip(ip) if ip else ""
    if clean_ip and mu == clean_ip:
        return ""
    if user_name and mu.lower() == str(user_name).strip().lower():
        return ""
    return mu


def log_visit(ip=None, session_id=None, user_agent=None, user_name=None):
    """
    Log a visitor's access including login username and Windows domain/machine identity.
    Uses non-blocking background thread for domain network resolution
    to ensure 0ms page lag for visitors.
    """
    _ensure_db()

    if ip is None:
        ip = get_client_ip()
    if session_id is None:
        session_id = _get_session_id()
    if user_agent is None:
        user_agent = get_user_agent()

    clean_ip = _extract_clean_ip(ip)

    # Resolve login/display user_name if not explicitly passed
    need_async_user = False
    if not user_name:
        detected_user = get_client_username(clean_ip)
        if detected_user:
            user_name = detected_user
        else:
            user_name = _cache_get(clean_ip) or ""
            need_async_user = True

    # Resolve machine-level Windows domain/host identity (always tracked even after web login)
    machine_user = ""
    need_async_machine = False
    if clean_ip == "127.0.0.1":
        machine_user = _get_local_domain_user()
        _cache_set("machine:127.0.0.1", machine_user)
    elif clean_ip:
        machine_user = _cache_get(f"machine:{clean_ip}") or ""
        if not machine_user:
            need_async_machine = True

    now_dt = datetime.now(TH_TZ)
    now = now_dt.strftime(_TS_FORMAT)

    conn = _get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT id, visit_count, user_name, last_seen, COALESCE(duration_seconds, 0), COALESCE(machine_user, '') FROM access_logs WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()

        if row:
            # Update existing session
            current_user_name = row[2] or ""
            effective_user = user_name if user_name else current_user_name
            current_machine_user = row[5] or ""
            effective_machine = machine_user if machine_user else current_machine_user
            new_dur, _ = _compute_updated_duration(row[3], row[4], now_dt)
            conn.execute(
                "UPDATE access_logs SET last_seen = ?, visit_count = visit_count + 1, page_views = page_views + 1, user_name = ?, machine_user = ?, duration_seconds = ? WHERE id = ?",
                (now, effective_user, effective_machine, new_dur, row[0])
            )
        else:
            # New session
            conn.execute(
                "INSERT INTO access_logs (ip, user_name, machine_user, session_id, first_seen, last_seen, visit_count, user_agent, duration_seconds) VALUES (?, ?, ?, ?, ?, ?, 1, ?, 0)",
                (ip, user_name or "", machine_user or "", session_id, now, now, user_agent)
            )
        conn.commit()
    except Exception as e:
        print(f"[UserLogger] Error logging visit: {e}")
    finally:
        conn.close()

    # Launch background resolution if user_name or machine_user is not yet known
    if (need_async_user or need_async_machine) and clean_ip:
        bg_thread = threading.Thread(
            target=_async_resolve_and_update,
            args=(session_id, clean_ip, need_async_user, need_async_machine),
            daemon=True
        )
        bg_thread.start()


def touch_session(session_id=None, now_dt=None, max_gap_seconds=HEARTBEAT_MAX_GAP_SECONDS):
    """
    Update last_seen and accumulate active duration_seconds for an existing session
    without incrementing visit_count. Used for periodic heartbeats and UI interactions.
    """
    _ensure_db()
    if session_id is None:
        session_id = _get_session_id()
    if now_dt is None:
        now_dt = datetime.now(TH_TZ)
    now_str = now_dt.strftime(_TS_FORMAT)

    conn = _get_db_connection()
    missing_session = False
    try:
        cursor = conn.execute(
            "SELECT id, last_seen, COALESCE(duration_seconds, 0) FROM access_logs WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        if not row:
            missing_session = True
        else:
            row_id, prev_last_str, prev_dur = row[0], row[1], row[2]
            new_dur, delta = _compute_updated_duration(prev_last_str, prev_dur, now_dt, max_gap_seconds=max_gap_seconds)
            if delta == 0:
                return
            conn.execute(
                "UPDATE access_logs SET last_seen = ?, duration_seconds = ? WHERE id = ?",
                (now_str, new_dur, row_id)
            )
            conn.commit()
    except Exception as e:
        print(f"[UserLogger] Error touching session: {e}")
    finally:
        conn.close()

    if missing_session:
        log_visit(session_id=session_id)


def _build_search_condition(query):
    """Build SQL WHERE fragment and parameter list for log search queries."""
    if not query:
        return "1=1", []
    like_q = f"%{query}%"
    return "(ip LIKE ? OR user_name LIKE ? OR COALESCE(machine_user, '') LIKE ? OR user_agent LIKE ?)", [like_q, like_q, like_q, like_q]


def get_all_logs(limit=500):
    """
    Retrieve all access logs ordered by most recent first.
    Includes user_name, machine_user, and duration_seconds.
    """
    _ensure_db()
    conn = _get_db_connection()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT id, ip, user_name, COALESCE(machine_user, '') AS machine_user, session_id, first_seen, last_seen, visit_count, user_agent, COALESCE(duration_seconds, 0) AS duration_seconds FROM access_logs ORDER BY last_seen DESC LIMIT ?",
            (limit,)
        )
        return [dict(r) for r in cursor.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def get_stats(query="", date_filter=None, start_date=None):
    """
    Get summary statistics with optional query (IP, User Name, Machine User, User-Agent) and date filtering.
    """
    _ensure_db()
    conn = _get_db_connection()
    try:
        today_str = datetime.now(TH_TZ).strftime("%Y-%m-%d")

        query_cond, query_params = _build_search_condition(query)

        # 1. Total sessions
        total_sessions = conn.execute(
            f"SELECT COUNT(*) FROM access_logs WHERE {query_cond}",
            query_params
        ).fetchone()[0] or 0

        # 2. Total unique IPs
        total_unique_ips = conn.execute(
            f"SELECT COUNT(DISTINCT ip) FROM access_logs WHERE {query_cond}",
            query_params
        ).fetchone()[0] or 0

        # 3. Total unique Users
        total_unique_users = conn.execute(
            f"SELECT COUNT(DISTINCT user_name) FROM access_logs WHERE {query_cond} AND user_name != '' AND user_name IS NOT NULL",
            query_params
        ).fetchone()[0] or 0

        # 4. Today sessions
        today_sessions = conn.execute(
            f"SELECT COUNT(*) FROM access_logs WHERE {query_cond} AND (last_seen LIKE ?)",
            query_params + [f"{today_str}%"]
        ).fetchone()[0] or 0

        # 5. Today unique IPs
        today_unique_ips = conn.execute(
            f"SELECT COUNT(DISTINCT ip) FROM access_logs WHERE {query_cond} AND (last_seen LIKE ?)",
            query_params + [f"{today_str}%"]
        ).fetchone()[0] or 0

        # 6. Today unique Users
        today_unique_users = conn.execute(
            f"SELECT COUNT(DISTINCT user_name) FROM access_logs WHERE {query_cond} AND (last_seen LIKE ?) AND user_name != '' AND user_name IS NOT NULL",
            query_params + [f"{today_str}%"]
        ).fetchone()[0] or 0

        # 7. Period sessions and unique IPs
        if date_filter:
            period_cond = "(first_seen LIKE ? OR last_seen LIKE ?)"
            period_params = [f"{date_filter}%", f"{date_filter}%"]
        elif start_date:
            period_cond = "last_seen >= ?"
            period_params = [f"{start_date} 00:00:00"]
        else:
            period_cond = "last_seen LIKE ?"
            period_params = [f"{today_str}%"]

        period_sessions = conn.execute(
            f"SELECT COUNT(*) FROM access_logs WHERE {query_cond} AND {period_cond}",
            query_params + period_params
        ).fetchone()[0] or 0

        period_unique_ips = conn.execute(
            f"SELECT COUNT(DISTINCT ip) FROM access_logs WHERE {query_cond} AND {period_cond}",
            query_params + period_params
        ).fetchone()[0] or 0

        period_unique_users = conn.execute(
            f"SELECT COUNT(DISTINCT user_name) FROM access_logs WHERE {query_cond} AND {period_cond} AND user_name != '' AND user_name IS NOT NULL",
            query_params + period_params
        ).fetchone()[0] or 0

        return {
            "total_sessions": total_sessions,
            "unique_ips": total_unique_ips,
            "total_unique_ips": total_unique_ips,
            "total_unique_users": total_unique_users,
            "today_visitors": today_sessions,
            "today_sessions": today_sessions,
            "today_unique_ips": today_unique_ips,
            "today_unique_users": today_unique_users,
            "period_sessions": period_sessions,
            "period_unique_ips": period_unique_ips,
            "period_unique_users": period_unique_users,
        }
    except Exception as e:
        print(f"[UserLogger] Error calculating stats: {e}")
        return {
            "total_sessions": 0,
            "unique_ips": 0,
            "total_unique_ips": 0,
            "total_unique_users": 0,
            "today_visitors": 0,
            "today_sessions": 0,
            "today_unique_ips": 0,
            "today_unique_users": 0,
            "period_sessions": 0,
            "period_unique_ips": 0,
            "period_unique_users": 0,
        }
    finally:
        conn.close()


def search_logs(query="", date_filter=None, start_date=None, limit=500):
    """
    Search logs by IP, User Name, Machine User, or User Agent.
    """
    _ensure_db()
    conn = _get_db_connection()
    conn.row_factory = sqlite3.Row
    try:
        conditions = []
        params = []

        if query:
            q_cond, q_params = _build_search_condition(query)
            conditions.append(q_cond)
            params.extend(q_params)

        if date_filter:
            conditions.append("(first_seen LIKE ? OR last_seen LIKE ?)")
            params.extend([f"{date_filter}%", f"{date_filter}%"])
        elif start_date:
            conditions.append("last_seen >= ?")
            params.append(f"{start_date} 00:00:00")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        cursor = conn.execute(
            f"SELECT id, ip, user_name, COALESCE(machine_user, '') AS machine_user, session_id, first_seen, last_seen, visit_count, user_agent, COALESCE(duration_seconds, 0) AS duration_seconds FROM access_logs WHERE {where_clause} ORDER BY last_seen DESC LIMIT ?",
            params + [limit]
        )
        return [dict(r) for r in cursor.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def export_logs_csv():
    """
    Export all logs as CSV string including user_name, machine_user, and usage duration.
    """
    import csv
    import io

    logs = get_all_logs(limit=99999)
    if not logs:
        return ""

    output = io.StringIO()
    fieldnames = [
        "id",
        "user_name",
        "machine_user",
        "ip",
        "session_id",
        "first_seen",
        "last_seen",
        "duration_seconds",
        "duration_minutes",
        "visit_count",
        "user_agent",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    safe_logs = []
    for row in logs:
        dur_sec = max(0, int(row.get("duration_seconds") or 0))
        enriched = dict(row)
        enriched["duration_seconds"] = dur_sec
        enriched["duration_minutes"] = round(dur_sec / 60, 1)
        safe_logs.append({k: _sanitize_csv_cell(enriched.get(k, "")) for k in fieldnames})
    writer.writerows(safe_logs)
    return output.getvalue()


def clear_old_logs(days=90):
    """Delete logs older than specified days."""
    _ensure_db()
    conn = _get_db_connection()
    try:
        cutoff = (datetime.now(TH_TZ) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("DELETE FROM access_logs WHERE last_seen < ?", (cutoff,))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def log_auth_event(
    event_type,
    username="",
    user_name="",
    ip=None,
    session_id=None,
    user_agent=None,
    details="",
):
    """
    Record an authentication audit event (login_success, login_failed, login_locked, logout)
    into the auth_logs table in user_access.db.
    """
    _ensure_db()

    if ip is None:
        ip = get_client_ip()
    if session_id is None:
        session_id = _get_session_id()
    if user_agent is None:
        user_agent = get_user_agent()

    clean_event = re.sub(r'[^a-zA-Z0-9_\-]', '', str(event_type or "unknown"))[:32] or "unknown"
    clean_username = _sanitize_username(username)
    clean_user_name = _sanitize_username(user_name) or clean_username
    clean_details = _sanitize_username(details)[:200]
    now = datetime.now(TH_TZ).strftime("%Y-%m-%d %H:%M:%S")

    conn = _get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO auth_logs (event_time, event_type, username, user_name, ip, session_id, user_agent, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now, clean_event, clean_username, clean_user_name, ip, session_id, user_agent, clean_details),
        )
        conn.commit()
    except Exception as e:
        print(f"[UserLogger] Error logging auth event: {e}")
    finally:
        conn.close()


def get_auth_logs(query="", event_type="", date_filter=None, start_date=None, limit=300):
    """Retrieve authentication audit logs ordered by most recent first."""
    _ensure_db()
    conn = _get_db_connection()
    conn.row_factory = sqlite3.Row
    try:
        conditions = []
        params = []

        if query:
            conditions.append("(username LIKE ? OR user_name LIKE ? OR ip LIKE ? OR details LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"])

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        if date_filter:
            conditions.append("event_time LIKE ?")
            params.append(f"{date_filter}%")
        elif start_date:
            conditions.append("event_time >= ?")
            params.append(f"{start_date} 00:00:00")

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        cursor = conn.execute(
            f"""
            SELECT id, event_time, event_type, username, user_name, ip, session_id, user_agent, details
            FROM auth_logs
            WHERE {where_clause}
            ORDER BY event_time DESC, id DESC
            LIMIT ?
            """,
            params + [limit],
        )
        return [dict(r) for r in cursor.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def export_auth_logs_csv():
    """Export all authentication audit logs as CSV string."""
    import csv
    import io

    logs = get_auth_logs(limit=99999)
    if not logs:
        return ""

    output = io.StringIO()
    fieldnames = ["id", "event_time", "event_type", "username", "user_name", "ip", "session_id", "user_agent", "details"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    safe_logs = [
        {k: _sanitize_csv_cell(row.get(k, "")) for k in fieldnames}
        for row in logs
    ]
    writer.writerows(safe_logs)
    return output.getvalue()


# Alias for aggregated visitor logs
get_aggregated_visitor_logs = get_all_logs
