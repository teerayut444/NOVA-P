"""
Standalone LandsMaps Real Coordinates Enricher strictly for LED_Legal_merge (LED Legal) assets.
Finds missing coordinates specifically for LED_Legal_merge_*.csv rows that failed matching
with LED_NPA_New (e.g. legacy properties only found in court auction reports).
Shares session rotation, locked Parquet RMW cache, master code resolution, and bounds/centroid
validation directly with `enrich_led_landsmaps.py` to avoid duplicated logic.
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

import time
import argparse
from datetime import datetime
import pandas as pd

from time_window_util import wait_for_active_window, get_scraper_delay_range
from enrich_led_landsmaps import (
    CACHE_PATH,
    DolSessionRotator,
    load_cache,
    save_cache,
    merge_and_save_cache,
    find_latest_led_merge_csv,
    clean_deed_number,
    clean_district_name,
    clean_province_name,
    load_master_codes,
    resolve_pv_am_codes,
    sync_cache_to_csv,
    trigger_dashboard_merge,
    query_single_deed_api,
    is_valid_thailand_real_coord,
    make_progress_bar,
    format_eta,
    _get_centroids,
)

# Backwards-compatible alias for any external caller importing sync_cache_to_merge_csv
sync_cache_to_merge_csv = sync_cache_to_csv


def run_merge_enrichment(
    merge_csv_path=None,
    cache_file=CACHE_PATH,
    province_filter=None,
    limit=None,
    delay=None,
    auto_merge=False,
    retry_not_found=False,
):
    if any(a.lower() in ["--now", "-now", "now", "--ignore-window", "--force-now", "--no-window"] for a in sys.argv):
        os.environ["SCRAPER_IGNORE_WINDOW"] = "1"
    wait_for_active_window("LandsMaps")

    if delay is not None:
        req_delay = max(0.5, float(delay))
        delay_display = f"{req_delay:.1f} วินาที"
    else:
        req_delay = None
        d_min, d_max = get_scraper_delay_range()
        delay_display = f"{d_min:.0f}-{d_max:.0f} วินาที"

    if not merge_csv_path:
        merge_csv_path = find_latest_led_merge_csv()
        if not merge_csv_path or not os.path.exists(merge_csv_path):
            print("[ERROR] ไม่พบไฟล์ LED_Legal_merge_*.csv ในโฟลเดอร์ CSV_Output/")
            return

    print("=" * 80)
    print("📍 [LandsMaps Merge Enricher] ระบบค้นหาพิกัดแปลงที่ดินจริงสำหรับไฟล์ merge.csv")
    print(f"เป้าหมายไฟล์ : {merge_csv_path}")
    print(f"แคชพิกัดจริง : {cache_file}")
    if province_filter:
        print(f"จังหวัดเป้าหมาย : {province_filter}")
    else:
        print(f"จังหวัดเป้าหมาย : ทุกจังหวัด (กระจายงานแบบ Round-Robin Interleaved)")
    print(f"ความเร็ว     : 1 Thread | หน่วงเวลา >= {delay_display} (อิงมาตรฐาน Scraper) | Auto Token Rotation (LoginSocial)")
    print("=" * 80)

    try:
        df = pd.read_csv(merge_csv_path, dtype=str, low_memory=False).fillna('')
    except Exception as e:
        print(f"[ERROR] ไม่สามารถอ่านไฟล์ {merge_csv_path}: {e}")
        return

    if 'ละติจูด' not in df.columns:
        df['ละติจูด'] = ""
    if 'ลองจิจูด' not in df.columns:
        df['ลองจิจูด'] = ""

    cset = _get_centroids()
    valid_mask = [is_valid_thailand_real_coord(lat, lon, cset) for lat, lon in zip(df['ละติจูด'], df['ลองจิจูด'])]
    df_missing = df[~pd.Series(valid_mask, index=df.index)].copy()

    total_in_merge = len(df)
    total_missing_coords = len(df_missing)
    print(f"[STATUS] จำนวนทรัพย์ใน merge.csv ทั้งหมด : {total_in_merge:,d} รายการ")
    print(f"[STATUS] รายการที่ยังไม่มีพิกัดแปลงจริง    : {total_missing_coords:,d} รายการ ({total_in_merge - total_missing_coords:,d} มีพิกัดแล้ว)")

    if total_missing_coords == 0:
        print("🎉 ทุกรายการใน merge.csv มีพิกัดจริงครบถ้วนแล้ว!")
        return

    df_missing['deed_clean'] = df_missing['เลขโฉนด'].apply(clean_deed_number)
    df_missing = df_missing[df_missing['deed_clean'].notna()]
    df_missing['prov_clean'] = df_missing['จังหวัด'].apply(clean_province_name)
    df_missing['dist_clean'] = df_missing['อำเภอ'].apply(clean_district_name)

    if province_filter:
        target_pv = clean_province_name(province_filter)
        df_missing = df_missing[df_missing['prov_clean'].str.contains(target_pv, na=False, regex=False)]

    if df_missing.empty:
        print("[INFO] ไม่พบรายการที่ขาดพิกัดและมีเลขโฉนดให้ค้นหา")
        return

    cache_df = load_cache(cache_file)
    if retry_not_found and not cache_df.empty:
        before_cnt = len(cache_df)
        cache_df = cache_df[cache_df['สถานะ'] == 'FOUND'].copy()
        save_cache(cache_df, cache_file)
        print(f"[CACHE] ล้างประวัติที่ไม่พบออก {before_cnt - len(cache_df):,d} รายการ (คงเหลือ FOUND: {len(cache_df):,d})")

    sync_cnt = sync_cache_to_csv(merge_csv_path, cache_df)
    if sync_cnt > 0:
        print(f"[CSV SYNC] ซิงค์พิกัดจากแคชเดิมลง merge.csv ล่วงหน้า {sync_cnt:,d} รายการ")
        df = pd.read_csv(merge_csv_path, dtype=str, low_memory=False).fillna('')
        valid_mask = [is_valid_thailand_real_coord(lat, lon, cset) for lat, lon in zip(df['ละติจูด'], df['ลองจิจูด'])]
        df_missing = df[~pd.Series(valid_mask, index=df.index)].copy()
        df_missing['deed_clean'] = df_missing['เลขโฉนด'].apply(clean_deed_number)
        df_missing = df_missing[df_missing['deed_clean'].notna()]
        df_missing['prov_clean'] = df_missing['จังหวัด'].apply(clean_province_name)
        df_missing['dist_clean'] = df_missing['อำเภอ'].apply(clean_district_name)
        if province_filter:
            df_missing = df_missing[df_missing['prov_clean'].str.contains(clean_province_name(province_filter), na=False, regex=False)]

    cached_keys = set()
    if not cache_df.empty:
        for pv_r, dt_r, dd_r in zip(cache_df['จังหวัด'].fillna(''), cache_df['อำเภอ'].fillna(''), cache_df['เลขโฉนด'].fillna('')):
            pv = clean_province_name(pv_r)
            dt = clean_district_name(dt_r)
            dd = clean_deed_number(dd_r)
            if pv and dd:
                cached_keys.add((pv, dt, dd))

    pending_records_raw = []
    seen = set()
    for row in df_missing[['จังหวัด', 'อำเภอ', 'เลขโฉนด', 'prov_clean', 'dist_clean', 'deed_clean']].to_dict('records'):
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

    print(f"[STATUS] โฉนดที่ยังต้องค้นหาในรอบนี้ : {len(pending_records):,d} แปลง")
    if not pending_records:
        print("✅ รายการที่มีเลขโฉนดใน merge.csv ถูกตรวจสอบกับแคชครบถ้วนแล้ว!")
        if auto_merge:
            trigger_dashboard_merge()
        return

    if limit and limit > 0:
        pending_records = pending_records[:limit]
        print(f"[STATUS] จำกัดรอบทดสอบที่ : {len(pending_records):,d} แปลง")

    rotator = DolSessionRotator(max_uses_per_token=20)
    prov_map, amp_map = load_master_codes(rotator)
    print(f"[MASTER] โหลดรหัสจังหวัด {len(prov_map)} จังหวัด และอำเภอ {len(amp_map)} รายการ สำเร็จ")

    new_results = []
    processed_count = 0
    found_in_session = 0
    not_found_in_session = 0
    total_pending = len(pending_records)
    start_all_time = time.time()

    print("\n" + "=" * 80, flush=True)
    print(f"🚀 เริ่มค้นหาพิกัดจริง LandsMaps สำหรับ {total_pending:,d} แปลง (1-Thread Safe Mode)", flush=True)
    print("=" * 80, flush=True)

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

            pct = int((processed_count / total_pending) * 100)
            pbar = make_progress_bar(pct, length=18)
            elapsed = time.time() - start_all_time
            eta_str = format_eta(elapsed, processed_count, total_pending, 1)

            print(f"[{'LandsMaps-Merge':<15s}] {pbar} | ({processed_count:5d}/{total_pending:5d} โฉนด) | พบจริง: {found_in_session:,d} | {eta_str}", flush=True)
            print(f"[{'LandsMaps-Merge':<15s}] ➔ {item['จังหวัด']} > {item['อำเภอ']} > โฉนด {item['เลขโฉนด']}: {res_desc}", flush=True)

            if len(new_results) >= 15:
                cache_df = merge_and_save_cache(new_results, cache_df, cache_file=cache_file)
                sync_cache_to_csv(merge_csv_path, cache_df)
                new_results.clear()
                print(f"[{'LandsMaps-Merge':<15s}] 💾 [SAVED] อัปเดตแคชและ merge.csv เรียบร้อย (สะสม {len(cache_df):,d} แปลง)", flush=True)

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] หยุดทำงานตามคำสั่งผู้ใช้ กำลังบันทึกความคืบหน้า...")
    finally:
        if new_results:
            cache_df = merge_and_save_cache(new_results, cache_df, cache_file=cache_file)
        sync_cache_to_csv(merge_csv_path, cache_df)

    elapsed = time.time() - start_all_time
    print("\n" + "=" * 80, flush=True)
    print(f"[{'LandsMaps-Merge':<15s}] ✅ ค้นหาเสร็จสิ้น ({processed_count:,d}/{total_pending:,d} โฉนด) ในเวลา {elapsed:.1f} วินาที", flush=True)
    print(f" - พบพิกัดแปลงจริงรอบนี้ : {found_in_session:,d} แปลง")
    print(f" - ไม่พบข้อมูล           : {not_found_in_session:,d} แปลง")
    print(f" - ซิงค์ลงไฟล์           : {os.path.basename(merge_csv_path)}")
    print("=" * 80)

    if auto_merge:
        trigger_dashboard_merge()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Find real GPS coordinates for LED_Legal_merge (LED Legal) assets from LandsMaps")
    parser.add_argument('--input', type=str, help="Path to LED_Legal_merge_*.csv (default: auto-detect latest in CSV_Output/)")
    parser.add_argument('--cache', type=str, default=CACHE_PATH, help="Cache Parquet file path")
    parser.add_argument('--province', type=str, help="Filter search to specific province")
    parser.add_argument('--limit', type=int, default=0, help="Limit number of deeds to search (0 = all, e.g. 10 for test)")
    parser.add_argument('--delay', type=float, default=None, help="Delay between requests in seconds (default: follow scraper delay 15-16s)")
    parser.add_argument('--no-merge', action='store_true', help="Do not auto-merge into all_assets.parquet after completion")
    parser.add_argument('--retry-not-found', action='store_true', help="Clear NOT_FOUND entries from cache before running")
    parser.add_argument('--now', '-now', '--ignore-window', action='store_true', help="Ignore active window and run immediately")

    args, _unknown = parser.parse_known_args()
    if args.now:
        os.environ["SCRAPER_IGNORE_WINDOW"] = "1"
    run_merge_enrichment(
        merge_csv_path=args.input,
        cache_file=args.cache,
        province_filter=args.province,
        limit=args.limit,
        delay=args.delay,
        auto_merge=not args.no_merge,
        retry_not_found=args.retry_not_found,
    )
