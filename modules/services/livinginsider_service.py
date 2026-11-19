from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import streamlit as st
from modules.services.data_loader import get_data_mtime

_TH_TZ = timezone(timedelta(hours=7))

@st.cache_data(show_spinner=False)
def _get_livinginsider_project_metrics_cached(_df_raw, cache_key=None):
    """
    Extracts Livinginsider data from _df_raw, parses Thai Buddhist Era dates,
    calculates days active and daily velocity (views/day, clicks/day),
    and aggregates metrics by project/location.
    """
    if _df_raw is None or _df_raw.empty:
        return []
    
    # Filter Livinginsider
    if 'บริษัท' in _df_raw.columns:
        li = _df_raw[_df_raw['บริษัท'] == 'Livinginsider'].copy()
    else:
        li = _df_raw.copy()
        
    if li.empty:
        return []
        
    # Ensure necessary columns exist
    for col in ['วันประกาศ', 'ยอดเข้าชม', 'ยอดคลิก', 'ละติจูด', 'ลองจิจูด', 'ชื่อโครงการ', 'ราคา', 'ประเภททรัพย์', 'ตำบล', 'อำเภอ', 'จังหวัด', 'ลิงก์']:
        if col not in li.columns:
            li[col] = None

    # Vectorized Thai Buddhist Era date parse
    s = li['วันประกาศ'].astype(str).str.strip()
    parts = s.str.split('/', expand=True)
    if parts.shape[1] < 3:
        return []
        
    valid_parts = parts[0].str.fullmatch(r'\d+') & parts[1].str.fullmatch(r'\d+') & parts[2].str.fullmatch(r'\d+')
    
    day = pd.to_numeric(parts.loc[valid_parts, 0], errors='coerce').astype('Int64')
    month = pd.to_numeric(parts.loc[valid_parts, 1], errors='coerce').astype('Int64')
    year = pd.to_numeric(parts.loc[valid_parts, 2], errors='coerce').astype('Int64')
    year = year.where(year <= 2400, year - 543)

    date_str = year.astype(str) + '-' + month.astype(str).str.zfill(2) + '-' + day.astype(str).str.zfill(2)
    post_dates = pd.to_datetime(date_str, errors='coerce')

    valid_mask = valid_parts & post_dates.notna() & li['ละติจูด'].notna() & li['ลองจิจูด'].notna()
    li = li[valid_mask].copy()
    if li.empty:
        return []

    li['post_date'] = post_dates[valid_mask]

    # Calculate active days using Thailand date (min 1 day to prevent div/0)
    today = pd.Timestamp(datetime.now(_TH_TZ).date())
    li['days_active'] = (today - post_dates[valid_mask]).dt.days.clip(lower=1)
    
    views = pd.to_numeric(li['ยอดเข้าชม'], errors='coerce').fillna(0)
    clicks = pd.to_numeric(li['ยอดคลิก'], errors='coerce').fillna(0)
    
    # Data Cleaning: Filter out scraper anomalies (e.g. phone numbers like 062-656-2896 in views column)
    clean_mask = (views < 1000000) & (clicks < 500000)
    li = li[clean_mask].copy()
    views = views[clean_mask]
    clicks = clicks[clean_mask]

    li['vd'] = (views / li['days_active']).round(2)
    li['cd'] = (clicks / li['days_active']).round(2)
    li['lat'] = pd.to_numeric(li['ละติจูด'], errors='coerce')
    li['lon'] = pd.to_numeric(li['ลองจิจูด'], errors='coerce')
    li['price'] = pd.to_numeric(li['ราคา'], errors='coerce')

    # Calculate price per sq.m. and price per sq.wah (guard optional area column)
    if 'พื้นที่ใช้สอย (ตร.ม.)' in li.columns:
        if pd.api.types.is_numeric_dtype(li['พื้นที่ใช้สอย (ตร.ม.)']):
            sqm = pd.to_numeric(li['พื้นที่ใช้สอย (ตร.ม.)'], errors='coerce')
        else:
            sqm = pd.to_numeric(li['พื้นที่ใช้สอย (ตร.ม.)'].astype(str).str.replace(',', '').str.strip(), errors='coerce')
    else:
        sqm = pd.Series(np.nan, index=li.index, dtype='float64')
    sqw = pd.to_numeric(li['พื้นที่_ตารางวา'], errors='coerce') if 'พื้นที่_ตารางวา' in li.columns else pd.Series(np.nan, index=li.index, dtype='float64')

    sqm = sqm.where((sqm >= 10) & (sqm <= 50000), pd.NA)
    sqw = sqw.where((sqw >= 1) & (sqw <= 500000), pd.NA)

    li['p_sqm'] = (li['price'] / sqm).where((li['price'] > 0) & sqm.notna(), pd.NA)
    li['p_sqw'] = (li['price'] / sqw).where((li['price'] > 0) & sqw.notna(), pd.NA)

    # Project clean name + province key (prevents merging same-named projects across provinces)
    li['proj_clean'] = li['ชื่อโครงการ'].fillna('').astype(str).str.strip()
    no_proj = li['proj_clean'].isin(['', '-', 'nan', 'None'])
    li.loc[no_proj, 'proj_clean'] = (
        li.loc[no_proj, 'ประเภททรัพย์'].fillna('ทรัพย์สิน').astype(str) + 
        ' (' + li.loc[no_proj, 'ตำบล'].fillna('').astype(str) + 
        ' ' + li.loc[no_proj, 'อำเภอ'].fillna('').astype(str) + ')'
    )
    li['prov_clean'] = li['จังหวัด'].fillna('-').astype(str).str.strip()

    # Group by (project clean name, province) using Median (มัธยฐาน)
    grp = li.groupby(['proj_clean', 'prov_clean'], dropna=False).agg(
        units=('ละติจูด', 'count'),
        prov=('prov_clean', 'first'),
        dist=('อำเภอ', 'first'),
        subdist=('ตำบล', 'first'),
        prop_type=('ประเภททรัพย์', lambda s: s.mode()[0] if not s.empty and not s.mode().empty else 'อื่นๆ'),
        lat=('lat', 'mean'),
        lon=('lon', 'mean'),
        price=('price', 'median'),
        min_p=('price', 'min'),
        max_p=('price', 'max'),
        p_sqm=('p_sqm', 'median'),
        p_sqw=('p_sqw', 'median'),
        vd=('vd', 'median'),
        cd=('cd', 'median'),
        sum_vd=('vd', 'sum'),
        sum_cd=('cd', 'sum'),
        days=('days_active', 'median'),
        start_date=('post_date', 'min'),
        end_date=('post_date', 'max'),
        link=('ลิงก์', 'first')
    ).reset_index()

    # Format Thai Buddhist dates
    th_months = ['', 'ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']
    def fmt_dt(dt):
        if pd.isna(dt): return '-'
        return f"{dt.day} {th_months[dt.month]} {dt.year + 543}"
    grp['start_dt'] = grp['start_date'].apply(fmt_dt)
    grp['end_dt'] = grp['end_date'].apply(fmt_dt)
    grp = grp.drop(columns=['start_date', 'end_date'])

    # Clean & format for JSON export
    grp['lat'] = grp['lat'].round(6)
    grp['lon'] = grp['lon'].round(6)
    grp['vd'] = grp['vd'].round(2)
    grp['cd'] = grp['cd'].round(2)
    grp['sum_vd'] = grp['sum_vd'].round(1)
    grp['sum_cd'] = grp['sum_cd'].round(1)
    grp['price'] = grp['price'].fillna(0).round(0)
    grp['min_p'] = grp['min_p'].fillna(0).round(0)
    grp['p_sqm'] = grp['p_sqm'].fillna(0).round(0)
    grp['p_sqw'] = grp['p_sqw'].fillna(0).round(0)
    grp['max_p'] = grp['max_p'].fillna(0).round(0)
    grp['days'] = grp['days'].round(0)
    grp['prov'] = grp['prov'].fillna('-').astype(str).str.strip()
    grp['dist'] = grp['dist'].fillna('-').astype(str).str.strip()
    grp['subdist'] = grp['subdist'].fillna('-').astype(str).str.strip()
    grp['prop_type'] = grp['prop_type'].fillna('อื่นๆ').astype(str).str.strip()
    grp['link'] = grp['link'].fillna('').astype(str)

    # Filter out invalid lat/lon outside Thailand bounding box (lat 5-21, lon 97-106)
    grp = grp[(grp['lat'] >= 5.0) & (grp['lat'] <= 21.0) & (grp['lon'] >= 97.0) & (grp['lon'] <= 106.0)]

    # Drop temporary grouping key & rename proj_clean to name
    if 'prov_clean' in grp.columns:
        grp = grp.drop(columns=['prov_clean'])
    grp = grp.rename(columns={'proj_clean': 'name'})

    return grp.to_dict(orient='records')


def get_livinginsider_project_metrics(df_raw, cache_key=None):
    """Public wrapper that caches Livinginsider metrics by (data_mtime, len(df_raw), th_date) without hashing 440k rows."""
    if df_raw is None or df_raw.empty:
        return []
    th_date = datetime.now(_TH_TZ).strftime("%Y-%m-%d")
    if cache_key is None:
        cache_key = (get_data_mtime(), len(df_raw), th_date)
    else:
        cache_key = (cache_key, th_date)
    return _get_livinginsider_project_metrics_cached(df_raw, cache_key=cache_key)
