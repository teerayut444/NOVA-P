import os
import sys
import time
import random
import threading
import requests
from datetime import datetime
from logger_util import log_timeout, log_info, log_txn

DEFAULT_TIMEOUT = 100  # ช่วง 90 - 120 วินาที
DEFAULT_MAX_RETRIES = 4  # ช่วง 3 - 6 ครั้ง
_last_1hr_wait_finish = {}
_wait_lock = threading.Lock()

# Specific network/HTTP exceptions eligible for timeout backoff & 1hr cooldown (never swallow NameError/TypeError/bugs)
RETRYABLE_EXCEPTIONS = (
    requests.exceptions.RequestException,
    TimeoutError,
    ConnectionError,
    OSError,
)

def get_timeout_seconds():
    """สุ่ม timeout ในช่วง 90 - 120 วินาที เพื่อให้เวลารอนานพอและหลบเลี่ยงการตรวจจับ"""
    return random.randint(90, 120)

def get_timeout_sleep_seconds():
    """ระยะเวลาพักรอระหว่าง retry เมื่อเกิด Timeout (90 - 120 วินาที)"""
    return random.randint(90, 120)

def sleep_with_countdown(seconds, company_name="SCRAPER", reason="HTTP Retry"):
    """
    พักรอนับถอยหลังเป็นวินาที พร้อมส่งสัญญาณ [COUNTDOWN:X] ให้ตัวรันแสดงผลเรียลไทม์
    """
    total_sec = max(1, int(seconds))
    print(f"[COUNTDOWN:{total_sec}] [{company_name}] ⏳ พักรอนับถอยหลัง {total_sec} วินาที ({reason})", flush=True)
    start_t = time.time()
    end_t = start_t + total_sec
    while time.time() < end_t:
        rem = int(end_t - time.time())
        if rem <= 0:
            break
        time.sleep(min(1.0, max(0.1, rem)))
    print(f"[COUNTDOWN:0] [{company_name}] 🚀 ครบกำหนดพัก {total_sec} วินาทีแล้ว -> เริ่มทำงานต่อ ({reason})", flush=True)

def wait_1hr_on_timeout(company_name="SCRAPER", context_msg="", wait_seconds=None):
    """
    พักรอเมื่อเกิด HTTP Error หรือหน้าเว็บ Timeout ไม่ตอบสนอง (ค่าเริ่มต้น 1 ชม. / 3,600 วินาที)
    พร้อมส่งสัญญาณ [COUNTDOWN:3600] ให้ Live Dashboard ของตัวรันนับถอยหลังวินาทีต่อวินาที
    """
    with _wait_lock:
        last_fin = _last_1hr_wait_finish.get(company_name, 0.0)
        if time.time() - last_fin < 30.0:
            return

    if wait_seconds is None:
        wait_seconds = float(os.environ.get("SCRAPER_TIMEOUT_WAIT_SEC", 3600))
        
    border = "=" * 80
    msg = f"🚨 หน้าเว็บไม่ตอบสนองเกินกำหนด ({context_msg}) -> กำลังพักรอ {int(wait_seconds):,} วินาที (1 ชั่วโมง) เพื่อให้เซิร์ฟเวอร์ปลายทางฟื้นตัว..."
    print(f"\n{border}\n[{company_name}] {msg}\n{border}", flush=True)
    log_timeout(company_name, msg)
    
    # ส่งสัญญาณเริ่มต้นการนับถอยหลังให้ runner ทราบทันที
    print(f"[COUNTDOWN:{int(wait_seconds)}] [{company_name}] ⏳ HTTP Error/Timeout: พักรอนับถอยหลัง {int(wait_seconds)} วินาที ({context_msg})", flush=True)
    
    start_time = time.time()
    end_time = start_time + wait_seconds
    next_status_elapsed = 30.0
    next_log_elapsed = 600.0
    
    while True:
        now = time.time()
        remaining = end_time - now
        if remaining <= 0:
            break
        elapsed = now - start_time

        # ใช้ timestamp-threshold ป้องกัน timer drift ข้ามจังหวะ % 30 / % 600
        if elapsed >= next_status_elapsed:
            rem_i = max(0, int(remaining))
            mins, secs = rem_i // 60, rem_i % 60
            time_display = f"{mins:02d}:{secs:02d} นาที" if mins > 0 else f"{secs} วินาที"
            print(f"[{company_name}] ⏳ เซิร์ฟเวอร์ Timeout: กำลังพักรอนับถอยหลัง... เหลืออีก {time_display} ก่อนเริ่มทำต่ออัตโนมัติ", flush=True)
            while next_status_elapsed <= elapsed:
                next_status_elapsed += 30.0

        if elapsed >= next_log_elapsed:
            rem_m = max(1, int(remaining // 60))
            log_txn(company_name, "TIMEOUT_WAIT", f"⏳ กำลังพักรอการฟื้นตัว... เหลือเวลาอีก {rem_m} นาที")
            while next_log_elapsed <= elapsed:
                next_log_elapsed += 600.0

        time.sleep(min(1.0, max(0.05, remaining)))
        
    with _wait_lock:
        _last_1hr_wait_finish[company_name] = time.time()
    # ส่งสัญญาณสิ้นสุดการนับถอยหลัง
    print(f"[COUNTDOWN:0] [{company_name}] 🚀 ครบกำหนดพัก {int(wait_seconds):,} วินาทีแล้ว -> กำลังเริ่มเชื่อมต่อและทำงานต่อทันที...", flush=True)
    resume_msg = f"🚀 ครบกำหนดพัก {int(wait_seconds):,} วินาทีแล้ว -> กำลังเริ่มเชื่อมต่อและทำงานต่อทันที..."
    print(f"\n[{company_name}] {resume_msg}\n{border}\n", flush=True)
    log_info(company_name, resume_msg)

def handle_timeout_retry(company_name="SCRAPER", attempt=0, max_retries=DEFAULT_MAX_RETRIES, context_msg=""):
    """
    จัดการเมื่อเกิด Timeout ตามนโยบาย:
    - ลองยิง request ทุก 90-120 วินาที จำนวน 3-6 ครั้ง (ค่าเริ่มต้น 4 ครั้ง)
    - ถ้าครบ 3-6 ครั้งแล้วยัง time out ให้พักรอ 1 ชั่วโมง
    """
    if attempt < max_retries - 1:
        sleep_sec = get_timeout_sleep_seconds()
        reason = f"Timeout retry {attempt + 1}/{max_retries}"
        time_str = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{time_str}] [{company_name}] ⚠️ รอนานเกินกำหนด/หลุดการเชื่อมต่อ ({reason}) -> พักรอ {sleep_sec} วินาที (ช่วง 90-120 วิ)...", flush=True)
        sleep_with_countdown(sleep_sec, company_name=company_name, reason=reason)
        return False
    else:
        # ครบตามกำหนด 3-6 ครั้งแล้วยัง Timeout -> พักรอ 1 ชั่วโมง
        wait_1hr_on_timeout(company_name=company_name, context_msg=f"{context_msg} (Timeout ต่อเนื่องครบ {max_retries} ครั้ง)")
        return True

def execute_with_retry(fn, company_name="SCRAPER", context_msg="", max_retries=DEFAULT_MAX_RETRIES, max_cooldown_cycles=1):
    """
    Run `fn()` with intra-cycle retries (90-120s backoff) and up to `max_cooldown_cycles`
    1-hour cooldowns, ALWAYS retrying `fn()` after each 1-hour sleep.
    `fn()` should raise RuntimeError/RequestException/Retryable error or return result on success.
    """
    last_exc = None
    for cycle in range(max_cooldown_cycles + 1):
        for attempt in range(max_retries):
            try:
                return fn()
            except RETRYABLE_EXCEPTIONS as e:
                last_exc = e
                if attempt < max_retries - 1:
                    sleep_sec = get_timeout_sleep_seconds()
                    sleep_with_countdown(sleep_sec, company_name=company_name, reason=f"{context_msg} retry {attempt + 1}/{max_retries}")
                elif cycle < max_cooldown_cycles:
                    wait_1hr_on_timeout(company_name=company_name, context_msg=f"{context_msg} (Cycle {cycle + 1}/{max_cooldown_cycles})")
                else:
                    raise
            except RuntimeError as e:
                # Allow explicit HTTP error wrappers raised as RuntimeError("HTTP ...") to retry
                if not any(tag in str(e) for tag in ("HTTP", "Timeout", "Challenge", "WAF", "Empty", "429", "403", "500", "502", "503", "504")):
                    raise
                last_exc = e
                if attempt < max_retries - 1:
                    sleep_sec = get_timeout_sleep_seconds()
                    sleep_with_countdown(sleep_sec, company_name=company_name, reason=f"{context_msg} retry {attempt + 1}/{max_retries}")
                elif cycle < max_cooldown_cycles:
                    wait_1hr_on_timeout(company_name=company_name, context_msg=f"{context_msg} ({e})")
                else:
                    raise
    if last_exc:
        raise last_exc

def safe_http_request(session, method, url, company_name="SCRAPER", timeout=None, max_retries=DEFAULT_MAX_RETRIES, max_cooldown_cycles=2, **kwargs):
    """
    HTTP request wrapper with timeout threshold (90-120s), backoff countdown (90-120s), and 1-hour wait if exhausted (up to max_cooldown_cycles).
    """
    if timeout is None:
        timeout = get_timeout_seconds()
    kwargs["timeout"] = timeout
    kwargs.setdefault("verify", True)
    
    cooldown_count = 0
    while cooldown_count <= max_cooldown_cycles:
        for attempt in range(max_retries):
            try:
                if method.upper() == "GET":
                    r = session.get(url, **kwargs)
                elif method.upper() == "POST":
                    r = session.post(url, **kwargs)
                else:
                    r = session.request(method, url, **kwargs)
                return r
            except RETRYABLE_EXCEPTIONS as e:
                time_str = datetime.now().strftime("%H:%M:%S")
                print(f"\n[{time_str}] [{company_name}] ⚠️ รอนานเกินกำหนด/หลุดการเชื่อมต่อ (ครั้งที่ {attempt+1}/{max_retries}): {e}", flush=True)
                sleep_sec = get_timeout_sleep_seconds()
                sleep_with_countdown(sleep_sec, company_name=company_name, reason=f"Timeout retry {attempt+1}/{max_retries}")
                
        # If all retries failed due to timeout / server down -> Wait 1 hour (up to max_cooldown_cycles)
        cooldown_count += 1
        if cooldown_count <= max_cooldown_cycles:
            wait_1hr_on_timeout(company_name=company_name, context_msg=f"{url} (Cooldown cycle {cooldown_count}/{max_cooldown_cycles})")
        else:
            time_str = datetime.now().strftime("%H:%M:%S")
            print(f"\n[{time_str}] [{company_name}] ❌ Exceeded max cooldown cycles ({max_cooldown_cycles}). Skipping URL: {url}", flush=True)
            return None
