# -*- coding: utf-8 -*-
"""
export_projects_csv.py
ส่งออกไฟล์ CSV แยกสำหรับโครงการทั้งหมด
"""
import sys
import os
import pandas as pd
import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# 1. โหลดข้อมูล BAM ที่ผ่านการ Clean แล้ว
df_bam = pd.read_csv('โครงการ_BAM.csv', encoding='utf-8-sig', dtype=str)

# กรองเฉพาะแถวที่มีชื่อโครงการจริง (ไม่ว่าง)
df_bam_projects = df_bam[df_bam['ชื่อโครงการ'].fillna('').str.strip() != ''].copy()

# บันทึกเป็นไฟล์ CSV รายการทรัพย์ BAM ที่มีโครงการทั้งหมด
file_bam_projects = 'โครงการ_BAM_มีโครงการทั้งหมด.csv'
df_bam_projects.to_csv(file_bam_projects, index=False, encoding='utf-8-sig')
print(f"Created file: {file_bam_projects} with {len(df_bam_projects):,} rows")

# 2. สร้างไฟล์สรุปรายชื่อโครงการของ BAM แบบ Unique ไม่ซ้ำ
df_bam_projects['ราคา_num'] = pd.to_numeric(df_bam_projects['ราคา (บาท)'], errors='coerce')

def join_unique(series):
    vals = [str(x).strip() for x in series.dropna().unique() if str(x).strip()]
    return ', '.join(vals[:5]) if vals else ''

summary = df_bam_projects.groupby('ชื่อโครงการ').agg(
    asset_count=('รหัสทรัพย์', 'count'),
    property_types=('ประเภททรัพย์', join_unique),
    min_price=('ราคา_num', 'min'),
    max_price=('ราคา_num', 'max'),
    avg_price=('ราคา_num', 'mean'),
    amphoe=('อำเภอ', join_unique),
    province=('จังหวัด', join_unique)
).reset_index()

summary.columns = [
    'ชื่อโครงการ',
    'จำนวนทรัพย์ (รายการ)',
    'ประเภททรัพย์',
    'ราคาเริ่มต้น (บาท)',
    'ราคาสูงสุด (บาท)',
    'ราคาเฉลี่ย (บาท)',
    'อำเภอ',
    'จังหวัด'
]

summary = summary.sort_values(by='จำนวนทรัพย์ (รายการ)', ascending=False)
summary['ราคาเริ่มต้น (บาท)'] = summary['ราคาเริ่มต้น (บาท)'].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else '')
summary['ราคาสูงสุด (บาท)'] = summary['ราคาสูงสุด (บาท)'].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else '')
summary['ราคาเฉลี่ย (บาท)'] = summary['ราคาเฉลี่ย (บาท)'].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else '')

file_bam_summary = 'รายชื่อโครงการ_BAM_ทั้งหมด.csv'
summary.to_csv(file_bam_summary, index=False, encoding='utf-8-sig')
print(f"Created file: {file_bam_summary} with {len(summary):,} unique projects")
