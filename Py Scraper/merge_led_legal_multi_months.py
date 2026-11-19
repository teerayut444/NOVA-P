# -*- coding: utf-8 -*-
"""
merge_led_legal_multi_months.py
สคริปต์สำหรับรวมไฟล์ผลการขายทอดตลาดหลายเดือน (LED_Legal_merge) เข้าด้วยกัน
พร้อมคัดกรองทรัพย์ที่ถูกประมูลซ้ำในนัดถัดไป โดยคงไว้เฉพาะ "นัดแรกที่ขายได้" (วันที่ขายแรกสุด)

คุณสมบัติ:
1. รองรับการรันแบบอัตโนมัติ (Auto-detect): ค้นหาไฟล์ LED_Legal_merge_YYYY_MM.csv ทุกเดือนใน CSV_Output
2. รองรับการระบุเดือนที่ต้องการรวมผ่าน Argument เช่น --months 2026_09 2026_10 หรือ --months 2026_09 2026_10 2026_11
3. รองรับการต่อยอดจากไฟล์รวมเดิม (Cumulative merge) เช่น นำ LED_Legal_merge_2026_9-10.csv ไปรวมกับเดือน 11 ได้ทันที
4. ตรวจจับและตัดรายการขายซ้ำ (Deduplication):
   - ตรวจจับตาม ID เดียวกัน -> คัดเก็บเฉพาะแถวที่มีวันที่ขายแรกสุด
   - ตรวจจับการประมูลซ้ำข้ามวัน/ข้ามเดือน (เลขคดีแดง + เลขโฉนด + จังหวัด + ราคาประเมิน) -> คัดเก็บเฉพาะนัดแรกที่ขายได้
   - รักษาห้องชุด/แปลงแยกที่ขายในวันเดียวกัน (ต่างห้อง/ต่างแปลง) ไว้อย่างครบถ้วน 100%
5. บันทึกผลลัพธ์เป็น CSV (utf-8-sig) โดยไม่แปลงเป็น Parquet ตามความต้องการของผู้ใช้
"""

import os
import sys
import glob
import re
import argparse
import pandas as pd
import numpy as np
from datetime import datetime

# บังคับใช้ UTF-8 Console บน Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR) if os.path.basename(_BASE_DIR).lower() in ["py scraper", "csv_output"] else _BASE_DIR
CSV_OUTPUT_DIR = os.path.join(_ROOT_DIR, "CSV_Output")

COLUMNS = [
    'บริษัท', 'ID', 'รหัสทรัพย์', 'ชื่อโครงการ', 'ประเภททรัพย์', 'ประเภทการขาย', 
    'ราคา', 'ตำบล', 'อำเภอ', 'จังหวัด', 'ละติจูด', 'ลองจิจูด', 'ชื่อประกาศ', 
    'ลิงก์', 'เนื้อที่ (ตร.ว.)', 'พื้นที่ใช้สอย (ตร.ม.)', 'วันที่ดึงข้อมูล', 
    'ห้องนอน', 'ห้องน้ำ', 'ที่จอดรถ', 'ชั้น', 'วันประกาศ', 'เลขโฉนด', 
    'โจทก์', 'ศาล', 'ยอดเข้าชม', 'ยอดคลิก', 'ราคาขายได้', 'วันที่ขาย'
]

def find_available_monthly_files():
    """
    ค้นหาไฟล์ LED_Legal_merge_*.csv ทุกเดือนที่มีใน CSV_Output
    ส่งคืนเป็น dict: { 'YYYY_MM': file_path } เรียงตามลำดับเวลา
    """
    found = {}
    pattern = os.path.join(CSV_OUTPUT_DIR, "**", "LED_Legal_merge_*.csv")
    for p in glob.glob(pattern, recursive=True):
        fname = os.path.basename(p)
        # ตรวจว่าเป็นไฟล์ประจำเดือนเดี่ยว เช่น LED_Legal_merge_2026_09.csv หรือ LED_Legal_merge_2026_10.csv
        m = re.match(r"^LED_Legal_merge_(\d{4}_\d{2})\.csv$", fname, re.IGNORECASE)
        if m:
            ym = m.group(1)
            # ถ้าเจอหลายที่ ให้เลือกไฟล์ที่มีขนาดใหญ่กว่าหรืออยู่ในโฟลเดอร์ของเดือนนั้น
            if ym not in found or os.path.getsize(p) > os.path.getsize(found[ym]):
                found[ym] = os.path.abspath(p)
    return dict(sorted(found.items()))

def _atomic_write_csv(df_obj, target_path):
    """Write CSV atomically using a unique temp file before os.replace."""
    target_dir = os.path.dirname(os.path.abspath(target_path)) or "."
    os.makedirs(target_dir, exist_ok=True)
    tmp_path = f"{target_path}.tmp.{os.getpid()}"
    try:
        df_obj.to_csv(tmp_path, index=False, encoding="utf-8-sig")
        os.replace(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise

def find_existing_multi_month_files():
    """
    ค้นหาไฟล์รวมหลายเดือนที่มีอยู่แล้ว เช่น LED_Legal_merge_2026_9-10.csv หรือ 2026_12-2027_1.csv
    """
    multi_files = {}
    pattern = os.path.join(CSV_OUTPUT_DIR, "**", "LED_Legal_merge_*.csv")
    for p in glob.glob(pattern, recursive=True):
        fname = os.path.basename(p)
        m = re.match(r"^LED_Legal_merge_(\d{4})_(\d{1,2})-(?:(\d{4})_)?(\d{1,2})\.csv$", fname, re.IGNORECASE)
        if m:
            multi_files[fname] = os.path.abspath(p)
    return multi_files

def deduplicate_first_sold(df_combined):
    """
    คัดกรองทรัพย์ที่ขายซ้ำ โดยเรียงตามวันที่ขายแรกสุด (นัดแรกที่ขายได้)
    """
    total_before = len(df_combined)
    
    # แปลงวันที่ขายเป็น datetime เพื่อจัดเรียงลำดับเวลาอย่างถูกต้อง
    df_combined['__sort_date'] = pd.to_datetime(df_combined['วันที่ขาย'], errors='coerce')
    # เรียงลำดับจากวันที่ขายแรกสุดไปหาวันที่ขายหลังสุด
    df_sorted = df_combined.sort_values(by=['__sort_date'], ascending=True, na_position='last').copy()
    
    # 1. กรองซ้ำตาม ID แท้จริง (หาก ID ไม่ว่างและไม่ใช่ nan)
    valid_id_mask = df_sorted['ID'].notna() & (df_sorted['ID'].astype(str).str.strip() != '') & (df_sorted['ID'].astype(str).str.strip().str.lower() != 'nan')
    dup_id_mask = valid_id_mask & df_sorted.duplicated(subset=['ID'], keep='first')
    dropped_by_id = int(dup_id_mask.sum())
    
    df_stage1 = df_sorted[~dup_id_mask].copy()
    
    # 2. กรองซ้ำกรณีเปิดประมูลซ้ำข้ามวัน/ข้ามเดือนจนได้ ID ใหม่:
    # จับคู่ (เลขคดีแดง, เลขโฉนด, จังหวัด, ราคาประเมิน)
    df_stage1['__norm_suit'] = df_stage1['รหัสทรัพย์'].astype(str).str.split('_').str[0].str.strip()
    df_stage1['__clean_deed'] = df_stage1['เลขโฉนด'].fillna('').astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
    df_stage1['__clean_prov'] = df_stage1['จังหวัด'].fillna('').astype(str).str.strip()
    df_stage1['__clean_price'] = df_stage1['ราคา'].fillna('').astype(str).str.strip()
    
    valid_deed_mask = (df_stage1['__clean_deed'] != '') & (df_stage1['__clean_deed'] != '-') & (df_stage1['__clean_deed'].str.lower() != 'nan')
    
    # ตรวจจับเฉพาะทรัพย์ที่มีการประมูลซ้ำในวันที่ต่างกัน (ข้ามวัน/ข้ามเดือน)
    # หากเป็นวันเดียวกันแต่มีหลาย ID (เช่น ห้องชุดคอนโดหลายห้องในอาคารเดียวกัน) จะไม่ถูกตัดทิ้ง
    to_drop_indices = []
    
    # กลุ่มที่มีเลขโฉนด
    for _, grp in df_stage1[valid_deed_mask].groupby(['__norm_suit', '__clean_deed', '__clean_prov', '__clean_price']):
        if len(grp) > 1 and grp['__sort_date'].nunique() > 1:
            earliest_date = grp['__sort_date'].min()
            later_rows = grp[grp['__sort_date'] > earliest_date]
            to_drop_indices.extend(later_rows.index.tolist())
            
    # กลุ่มที่ไม่มีเลขโฉนด (เช่น คอนโดที่โฉนดเป็น '-')
    for _, grp in df_stage1[~valid_deed_mask].groupby(['__norm_suit', '__clean_prov', '__clean_price']):
        if len(grp) > 1 and grp['__sort_date'].nunique() > 1:
            earliest_date = grp['__sort_date'].min()
            later_rows = grp[grp['__sort_date'] > earliest_date]
            to_drop_indices.extend(later_rows.index.tolist())
            
    dropped_cross_date = len(to_drop_indices)
    df_stage2 = df_stage1.drop(index=to_drop_indices).copy()
    
    # ลบคอลัมน์ช่วยเหลือออก
    drop_helper_cols = ['__sort_date', '__norm_suit', '__clean_deed', '__clean_prov', '__clean_price']
    for hc in drop_helper_cols:
        if hc in df_stage2.columns:
            df_stage2.drop(columns=[hc], inplace=True)
            
    total_after = len(df_stage2)
    total_dropped = total_before - total_after
    
    return df_stage2, dropped_by_id, dropped_cross_date, total_dropped

def format_span_name(month_keys):
    """
    สร้างชื่อช่วงเดือน เช่น ['2026_09', '2026_10'] -> 'LED_Legal_merge_2026_9-10.csv'
    ['2026_09', '2026_10', '2026_11'] -> 'LED_Legal_merge_2026_9-11.csv'
    """
    sorted_m = sorted(month_keys)
    start_ym = sorted_m[0]
    end_ym = sorted_m[-1]
    
    y_start, m_start = start_ym.split('_')
    y_end, m_end = end_ym.split('_')
    
    m_start_int = int(m_start)
    m_end_int = int(m_end)
    
    if y_start == y_end:
        return f"LED_Legal_merge_{y_start}_{m_start_int}-{m_end_int}.csv"
    else:
        return f"LED_Legal_merge_{y_start}_{m_start_int}-{y_end}_{m_end_int}.csv"

def merge_led_files(months=None, input_files=None, output_path=None):
    """
    ฟังก์ชันหลักในการรวมไฟล์ LED_Legal_merge และตัดรายการซ้ำ
    """
    print("=" * 65, flush=True)
    print("🔄 เริ่มต้นกระบวนการรวมไฟล์ผลการขายทอดตลาด (LED Legal Multi-Month Merge)", flush=True)
    print("=" * 65, flush=True)
    
    available_monthly = find_available_monthly_files()
    target_files = []
    month_keys = []
    
    if input_files:
        for f in input_files:
            if os.path.exists(f):
                target_files.append(os.path.abspath(f))
                # พยายามแกะเดือนจากชื่อไฟล์
                m = re.search(r"(\d{4}_\d{2})", os.path.basename(f))
                if m:
                    month_keys.append(m.group(1))
            else:
                print(f"⚠️ ไม่พบไฟล์อินพุต: {f}", flush=True)
    elif months:
        for ym in months:
            # แปลงรูปแบบเช่น 2026_9 เป็น 2026_09
            parts = ym.split('_')
            if len(parts) == 2:
                ym_norm = f"{parts[0]}_{int(parts[1]):02d}"
            else:
                ym_norm = ym
                
            if ym_norm in available_monthly:
                target_files.append(available_monthly[ym_norm])
                month_keys.append(ym_norm)
            else:
                # ลองค้นหาไฟล์โดยตรงในโฟลเดอร์ของเดือนนั้น
                direct_path = os.path.join(CSV_OUTPUT_DIR, ym_norm, f"LED_Legal_merge_{ym_norm}.csv")
                if os.path.exists(direct_path):
                    target_files.append(direct_path)
                    month_keys.append(ym_norm)
                else:
                    print(f"⚠️ ไม่พบไฟล์สำหรับเดือน {ym_norm}", flush=True)
    else:
        # Auto-detect โหมด: ใช้ทุกเดือนที่มีใน available_monthly
        print(f"🔍 ตรวจพบไฟล์รายเดือนอัตโนมัติ: {list(available_monthly.keys())}", flush=True)
        for ym, path in available_monthly.items():
            target_files.append(path)
            month_keys.append(ym)
            
    if not target_files:
        print("❌ ไม่พบไฟล์ที่สามารถนำมารวมได้ กรุณาตรวจสอบเส้นทางไฟล์หรือระบุ --months", flush=True)
        return False
        
    print(f"📂 ไฟล์ที่จะนำมารวม ({len(target_files)} ไฟล์):", flush=True)
    dfs = []
    for tf in target_files:
        size_mb = os.path.getsize(tf) / (1024 * 1024)
        print(f"  📄 {os.path.basename(tf)} ({size_mb:.2f} MB) -> {tf}", flush=True)
        try:
            df = pd.read_csv(tf, encoding="utf-8-sig", dtype=str)
            # ตรวจสอบคอลัมน์มาตรฐาน
            for c in COLUMNS:
                if c not in df.columns:
                    df[c] = ""
            df = df[COLUMNS]
            dfs.append(df)
            print(f"     └─ อ่านข้อมูลสำเร็จ: {len(df):,} รายการ", flush=True)
        except Exception as e:
            print(f"     ❌ เกิดข้อผิดพลาดในการอ่านไฟล์ {tf}: {e}", flush=True)
            
    if not dfs:
        print("❌ ไม่สามารถโหลดข้อมูลจากไฟล์ได้", flush=True)
        return False
        
    combined_df = pd.concat(dfs, ignore_index=True)
    total_raw = len(combined_df)
    print(f"\n📊 รวมข้อมูลทั้งหมดก่อนคัดกรอง: {total_raw:,} รายการ", flush=True)
    
    # ทำการ Deduplicate คงไว้เฉพาะนัดแรกที่ขายได้
    print("🧹 กำลังตรวจสอบและคัดกรองรายการที่ขายซ้ำ (คงไว้เฉพาะนัดแรกที่ขายได้)...", flush=True)
    clean_df, drop_id, drop_cross, total_dropped = deduplicate_first_sold(combined_df)
    
    print(f"  🛡️ คัดกรองรายการซ้ำตาม ID เดียวกันออก: {drop_id:,} รายการ", flush=True)
    print(f"  🛡️ คัดกรองรายการประมูลซ้ำข้ามวัน/ข้ามเดือน (เลขคดีแดง+โฉนด+ราคา): {drop_cross:,} รายการ", flush=True)
    print(f"  ✨ รวมรายการซ้ำที่คัดออกทั้งหมด: {total_dropped:,} รายการ", flush=True)
    print(f"  ✅ จำนวนข้อมูลสุทธิ (นัดแรกที่ขายได้จริง): {len(clean_df):,} รายการ", flush=True)
    
    # กำหนดชื่อไฟล์และเส้นทางบันทึก
    if not output_path:
        out_filename = format_span_name(month_keys) if month_keys else "LED_Legal_merge_combined.csv"
        main_out_path = os.path.join(CSV_OUTPUT_DIR, out_filename)
    else:
        main_out_path = os.path.abspath(output_path)
        out_filename = os.path.basename(main_out_path)
        
    # บันทึกไฟล์หลักที่ CSV_Output/ แบบ Atomic
    _atomic_write_csv(clean_df, main_out_path)
    main_size_mb = os.path.getsize(main_out_path) / (1024 * 1024)
    print(f"\n💾 บันทึกไฟล์ผลลัพธ์หลักสำเร็จ:", flush=True)
    print(f"   📍 {main_out_path} ({main_size_mb:.2f} MB | {len(clean_df):,} รายการ)", flush=True)
    
    # ทำสำเนาไปยังโฟลเดอร์เดือนเป้าหมาย (เช่น CSV_Output/2026_10/ หรือเดือนล่าสุด)
    if month_keys:
        latest_ym = sorted(month_keys)[-1]
        target_month_dir = os.path.join(CSV_OUTPUT_DIR, latest_ym)
        if os.path.exists(target_month_dir):
            copy_out_path = os.path.join(target_month_dir, out_filename)
            if os.path.abspath(copy_out_path) != os.path.abspath(main_out_path):
                _atomic_write_csv(clean_df, copy_out_path)
                print(f"💾 สำเนาไฟล์ไปยังโฟลเดอร์เดือนเป้าหมายสำเร็จ:", flush=True)
                print(f"   📍 {copy_out_path}", flush=True)
                
        # สำเนาไปยังโฟลเดอร์เดือนปัจจุบัน (เช่น 2026_11) หากมีโฟลเดอร์อยู่
        cur_ym = datetime.now().strftime("%Y_%m")
        cur_month_dir = os.path.join(CSV_OUTPUT_DIR, cur_ym)
        if os.path.exists(cur_month_dir) and os.path.abspath(cur_month_dir) != os.path.abspath(target_month_dir):
            cur_copy_path = os.path.join(cur_month_dir, out_filename)
            if os.path.abspath(cur_copy_path) != os.path.abspath(main_out_path):
                _atomic_write_csv(clean_df, cur_copy_path)
                print(f"💾 สำเนาไฟล์ไปยังโฟลเดอร์เดือนปัจจุบัน ({cur_ym}) สำเร็จ:", flush=True)
                print(f"   📍 {cur_copy_path}", flush=True)
                
    print("\n" + "=" * 65, flush=True)
    print(f"🎉 สำเร็จ! รวมไฟล์ผลการขายทอดตลาดเรียบร้อยแล้ว (ไม่มีการแปลงเป็น Parquet ตามคำขอ)", flush=True)
    print("=" * 65, flush=True)
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge LED Legal monthly CSVs and deduplicate repeat auctions")
    parser.add_argument("--months", nargs="+", help="ระบุเดือนที่ต้องการรวม เช่น --months 2026_09 2026_10 หรือ 2026_09 2026_10 2026_11")
    parser.add_argument("--input", nargs="+", help="ระบุไฟล์ CSV อินพุตโดยตรง")
    parser.add_argument("--output", help="ระบุเส้นทางไฟล์ CSV ผลลัพธ์")
    args = parser.parse_args()
    
    merge_led_files(months=args.months, input_files=args.input, output_path=args.output)
