# -*- coding: utf-8 -*-
"""
time_window_util.py
โมดูลควบคุมช่วงเวลาทำงานของ Scraper (Time Window Controller)
กำหนดให้ระบบทำงานเฉพาะช่วงค่ำถึงเช้า (ค่าเริ่มต้น 18:00 - 06:00 น.)
และพักรออัตโนมัตินอกช่วงเวลา พร้อมส่งสัญญาณนับถอยหลัง [COUNTDOWN:X] ให้ Dashboard
และรองรับโหมดรัน NOW ทันที (--now หรือ SCRAPER_IGNORE_WINDOW=1)
"""

import os
import sys
import time
from datetime import datetime, timedelta

COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_CYAN = "\033[96m"
COLOR_WHITE = "\033[97m"

DEFAULT_START_TIME = (18, 0) # 18:00 น.
DEFAULT_END_TIME = (6, 0)   # 06:00 น.

def parse_time_str(time_str: str):
    """แปลงสตริงเวลา 'HH:MM' หรือ 'HH' เป็น tuple (hour, minute)"""
    try:
        parts = time_str.strip().split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        return (h, m)
    except Exception:
        return None

def get_configured_window():
    """
    ดึงการตั้งค่าช่วงเวลาทำงาน:
    1. จาก env: SCRAPER_TIME_WINDOW (เช่น '18:00-06:00')
    2. หรือค่าเริ่มต้น (18:00 - 06:00 น.)
    """
    env_win = os.environ.get("SCRAPER_TIME_WINDOW", "").strip()
    if env_win and "-" in env_win:
        parts = env_win.split("-")
        s = parse_time_str(parts[0])
        e = parse_time_str(parts[1])
        if s and e:
            return s, e
    return DEFAULT_START_TIME, DEFAULT_END_TIME

def is_window_disabled():
    """ตรวจสอบว่ามีการสั่งปิดระบบจำกัดเวลาหรือไม่ (--now หรือ SCRAPER_IGNORE_WINDOW=1)"""
    if os.environ.get("SCRAPER_IGNORE_WINDOW", "0") in ["1", "true", "yes", "TRUE", "now", "NOW"]:
        return True
    if os.environ.get("SCRAPER_RUN_NOW", "0") in ["1", "true", "yes", "TRUE"]:
        return True
    for arg in sys.argv:
        if arg.lower() in ["--now", "-now", "now", "--ignore-window", "--no-window", "--force-now", "--test", "-test", "test"]:
            return True
    return False

def is_within_active_window(now_dt=None) -> bool:
    """
    ตรวจสอบว่าเวลาปัจจุบันอยู่ในช่วงเวลาที่อนุญาตให้ทำงานหรือไม่
    เช่น 18:00 - 06:00 น.
    """
    if is_window_disabled():
        return True

    now = now_dt or datetime.now()
    cur_m = now.hour * 60 + now.minute
    
    start_hm, end_hm = get_configured_window()
    s_m = start_hm[0] * 60 + start_hm[1]
    e_m = end_hm[0] * 60 + end_hm[1]
    
    if s_m > e_m:
        # ข้ามเที่ยงคืน เช่น 18:00 - 06:00 น.
        return cur_m >= s_m or cur_m < e_m
    else:
        # ภายในวันเดียวกัน เช่น 08:00 - 17:00 น.
        return s_m <= cur_m < e_m

def get_next_window_open_datetime(now_dt=None) -> datetime:
    """
    คำนวณเวลาที่ช่วงเวลาทำงานจะเปิดรอบถัดไป
    """
    now = now_dt or datetime.now()
    start_hm, end_hm = get_configured_window()
    s_h, s_m = start_hm
    
    today_start = now.replace(hour=s_h, minute=s_m, second=0, microsecond=0)
    
    if is_within_active_window(now):
        return now
        
    cur_m = now.hour * 60 + now.minute
    s_m_tot = s_h * 60 + s_m
    
    if cur_m < s_m_tot:
        return today_start
    else:
        return today_start + timedelta(days=1)

def get_seconds_until_window_opens(now_dt=None) -> int:
    """คำนวณจำนวนวินาทีที่ต้องรอนับถอยหลังจนกว่าจะถึงช่วงเวลาทำงาน"""
    if is_within_active_window(now_dt):
        return 0
    now = now_dt or datetime.now()
    target_dt = get_next_window_open_datetime(now)
    diff = int((target_dt - now).total_seconds())
    return max(0, diff)

def format_window_str() -> str:
    """ส่งคืนข้อความแสดงช่วงเวลาทำงาน เช่น '18:00 - 06:00 น.'"""
    start_hm, end_hm = get_configured_window()
    return f"{start_hm[0]:02d}:{start_hm[1]:02d} - {end_hm[0]:02d}:{end_hm[1]:02d} น."

def wait_for_active_window(company_name: str = "SCRAPER", check_interval: int = 5) -> bool:
    """
    ตรวจสอบเวลา หากอยู่นอกช่วงเวลาทำงาน จะหยุดรอ (Pause) ชั่วคราว
    พร้อมส่งสัญญาณ [COUNTDOWN:X] ให้ตัวรันแสดงผลเรียลไทม์
    เมื่อถึงเวลาทำงาน (18:00 น.) หรือมีคำสั่งรัน NOW จะเริ่มทำงานต่ออัตโนมัติ
    คืนค่า True หากมีการหยุดรอ, False หากอยู่ในช่วงเวลาทำงานอยู่แล้ว
    """
    if is_window_disabled():
        return False
        
    if is_within_active_window():
        return False
        
    win_str = format_window_str()
    target_dt = get_next_window_open_datetime()
    target_clock = target_dt.strftime("%H:%M:%S น.")
    
    initial_wait = get_seconds_until_window_opens()
    if initial_wait <= 0:
        return False
        
    h = initial_wait // 3600
    m = (initial_wait % 3600) // 60
    s = initial_wait % 60
    time_desc = f"{h} ชม. {m} นาที" if h > 0 else f"{m} นาที {s} วินาที"
    
    # ส่งสัญญาณนับถอยหลังให้ runner และ live dashboard รับรู้ทันที
    print(
        f"[COUNTDOWN:{initial_wait}] [{company_name}] {COLOR_YELLOW}{COLOR_BOLD}[TIME-WINDOW]{COLOR_RESET} นอกช่วงเวลาทำงาน ({COLOR_WHITE}{win_str}{COLOR_RESET}) "
        f"-> พักรอนับถอยหลัง {COLOR_WHITE}{COLOR_BOLD}{time_desc}{COLOR_RESET} (เริ่มทำงานเวลา {COLOR_YELLOW}{target_clock}{COLOR_RESET})",
        flush=True
    )
    
    while True:
        if is_window_disabled():
            print(f"[COUNTDOWN:0] [{company_name}] {COLOR_GREEN}{COLOR_BOLD}[RUN-NOW]{COLOR_RESET} สลับเข้าสู่โหมดรัน NOW -> เริ่มทำงานต่อทันที", flush=True)
            return True
            
        now = datetime.now()
        if is_within_active_window(now):
            break
            
        rem = get_seconds_until_window_opens(now)
        if rem <= 0:
            break
            
        sleep_dur = min(check_interval, max(1, rem))
        time.sleep(sleep_dur)
        
    print(f"[COUNTDOWN:0] [{company_name}] {COLOR_GREEN}{COLOR_BOLD}[RESUME]{COLOR_RESET} ถึงช่วงเวลาทำงานแล้ว ({COLOR_WHITE}{win_str}{COLOR_RESET}) -> เริ่มทำงานต่อทันที", flush=True)
    return True


NOW_MODE_DELAY = (15.0, 16.0)
WINDOW_MODE_DELAY = (15.0, 16.0)

def get_scraper_delay_range():
    """
    คืนค่าช่วงเวลาหน่วง (min_sec, max_sec) ตามโหมดการทำงาน:
    - ค่าหน่วงเวลามาตรฐาน 15.0 - 16.0 วินาที สำหรับทุกตัว scrap และตัวดึงพิกัด
    """
    if is_window_disabled():
        return NOW_MODE_DELAY
    return WINDOW_MODE_DELAY

def get_scraper_delay() -> float:
    """สุ่มค่าหน่วงเวลา 15.0 - 16.0 วินาที สำหรับทุกตัว scrap และตัวดึงพิกัด"""
    import random
    d_min, d_max = get_scraper_delay_range()
    return random.uniform(d_min, d_max)

