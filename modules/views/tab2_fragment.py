import hashlib
import html
import json
import re
import numpy as np
import pandas as pd
import streamlit as st

from modules.services.geo_service import find_nearby_properties
from modules.services.export_service import render_import_export_section
from modules.services.data_cleaner import (
    to_float_sqwah,
    to_float_sqm,
    format_to_rai_ngan_wah,
    normalize_project_name,
    format_announcement_age,
    format_coord_vectorized,
    parse_listing_age_days,
)
from modules.services.data_loader import _parse_sold_date_value
from modules.config.constants import is_true_centroid
from modules.ui.kpi_header import format_price_kpi

def _sqw_from_df(df_obj):
    """Return numeric Sq.Wah series, parsing Rai-Ngan-Wah strings via unique-mapped to_float_sqwah when needed."""
    if df_obj is None or df_obj.empty:
        return pd.Series(dtype=float)
    if 'พื้นที่_ตารางวา' in df_obj.columns:
        sqw_num = pd.to_numeric(df_obj['พื้นที่_ตารางวา'], errors='coerce')
        if 'เนื้อที่ (ตร.ว.)' in df_obj.columns and sqw_num.isna().any():
            raw_obj = df_obj['เนื้อที่ (ตร.ว.)'].astype(object)
            na_mask = sqw_num.isna()
            u_raw = raw_obj.loc[na_mask].dropna().unique()
            if len(u_raw) > 0:
                u_map = {v: to_float_sqwah(v) for v in u_raw}
                sqw_num = sqw_num.fillna(pd.to_numeric(raw_obj.map(u_map), errors='coerce'))
        return sqw_num
    if 'เนื้อที่ (ตร.ว.)' in df_obj.columns:
        raw_obj = df_obj['เนื้อที่ (ตร.ว.)'].astype(object)
        u_raw = raw_obj.dropna().unique()
        u_map = {v: to_float_sqwah(v) for v in u_raw}
        return pd.to_numeric(raw_obj.map(u_map), errors='coerce')
    return pd.Series(np.nan, index=df_obj.index, dtype=float)

def _safe_float(val, default=0.0):
    """Safely parse any value to float without throwing exceptions on None/corrupt data."""
    try:
        if val is None:
            return default
        f = float(val)
        return default if np.isnan(f) else f
    except (ValueError, TypeError):
        return default

def _fmt_coord_val(row, coord_col):
    val = row.get(coord_col)
    try:
        if val is None or pd.isna(val):
            return '-'
        f = float(val)
        if f == 0:
            return '-'
        is_cen = is_true_centroid(row.get('is_centroid'), row.get('บริษัท'))
        return f"⚠️ {f:.6f}" if is_cen else f"{f:.6f}"
    except (ValueError, TypeError):
        return '-'


def _check_pure_land_mask_global(s_types):
    p = s_types.astype(str)
    return p.str.contains('ที่ดินเปล่า|ที่ดิน', regex=True, na=False) & \
           ~p.str.contains('บ้าน|อาคาร|ทาวน์|คอนโด|ตึก|โรงงาน|พาณิชย์|หอพัก|สิ่งปลูกสร้าง|พร้อมสิ่งปลูกสร้าง', regex=True, na=False)


def _extract_pure_land_pool_global(df_cand):
    if df_cand is None or df_cand.empty:
        return pd.DataFrame(), pd.Series(dtype=float)
    is_pure = _check_pure_land_mask_global(df_cand['ประเภททรัพย์'])
    p_num = pd.to_numeric(df_cand['ราคา'], errors='coerce')
    pure_df = df_cand[is_pure & (p_num > 0)].copy()
    if pure_df.empty:
        return pure_df, pd.Series(dtype=float)

    sqw_num = _sqw_from_df(pure_df)
    p_vals = pd.to_numeric(pure_df['ราคา'], errors='coerce')

    puw_vals = pd.to_numeric(pure_df.get('ราคาต่อตารางวา', np.nan), errors='coerce')
    if 'ราคาต่อหน่วย' in pure_df.columns:
        puw_vals = puw_vals.combine_first(pd.to_numeric(pure_df['ราคาต่อหน่วย'], errors='coerce'))

    fallback_sqw = np.where((sqw_num > 0) & (p_vals > 0), p_vals / sqw_num, np.nan)
    rates = np.where((puw_vals > 0), puw_vals, fallback_sqw)
    pure_df['rate_per_sqw'] = rates
    pure_df['ราคาต่อหน่วย'] = rates
    valid_mask = pure_df['rate_per_sqw'].notna() & (pure_df['rate_per_sqw'] > 0)
    valid_rates = pure_df.loc[valid_mask, 'rate_per_sqw']
    return pure_df.loc[valid_mask], valid_rates


@st.cache_data(show_spinner=False, max_entries=2)
def _get_cached_nationwide_pure_land(_df_raw, cache_key=None):
    return _extract_pure_land_pool_global(_df_raw)


@st.cache_data(show_spinner=False, max_entries=6)
def _compute_vectorized_unit_info_cached(_df_target, cache_key=None):
    if _df_target is None or _df_target.empty:
        return _df_target
    df_res = _df_target.copy()
    p_num = pd.to_numeric(df_res['ราคา'], errors='coerce')
    sqm_num = pd.to_numeric(df_res.get('พื้นที่ใช้สอย (ตร.ม.)', np.nan), errors='coerce')
    sqw_num = _sqw_from_df(df_res)

    p_type = df_res['ประเภททรัพย์'].astype(str).str.lower()
    is_condo = p_type.str.contains('คอนโด|ห้องชุด', regex=True, na=False)

    condo_rate = np.where(is_condo & (sqm_num > 0) & (p_num > 0), p_num / sqm_num, np.nan)
    land_rate = np.where((~is_condo) & (sqw_num > 0) & (p_num > 0), p_num / sqw_num, np.nan)
    unit_price = np.where(pd.notna(condo_rate), condo_rate, land_rate)

    df_res['ราคาต่อหน่วย'] = unit_price
    df_res['หน่วยวัด'] = np.where(is_condo, 'ตร.ม.', 'ตร.ว.')
    df_res['ประเภทพื้นที่'] = np.where(is_condo, 'พื้นที่ใช้สอย', 'เนื้อที่')
    return df_res.reset_index(drop=True)


def _clean_str_series(s, default='-'):
    """Fast vectorized string cleaner that leverages Categorical/unique values when possible."""
    if isinstance(s.dtype, pd.CategoricalDtype):
        cats = [str(c).strip() for c in s.cat.categories]
        cat_map = {
            orig: (default if cln in ('', '-', 'nan', 'None', 'null', '<NA>') else cln)
            for orig, cln in zip(s.cat.categories, cats)
        }
        return s.astype(object).map(cat_map).fillna(default)
    uniq = s.dropna().unique()
    if len(uniq) < len(s) * 0.4:
        u_map = {}
        for v in uniq:
            cln = str(v).strip()
            u_map[v] = default if cln in ('', '-', 'nan', 'None', 'null', '<NA>') else cln
        return s.map(u_map).fillna(default)
    return (
        s.fillna(default)
        .astype(str)
        .str.strip()
        .replace({'': default, 'nan': default, 'None': default, 'null': default, '<NA>': default})
    )


@st.cache_data(show_spinner=False, max_entries=6)
def _build_tab2_show_df_cached(
    _filtered_nearby,
    _is_fn_pure_land,
    median_raw_land,
    median_sqw_val,
    median_u_sel,
    median_sqm_val,
    price_ref_sqw=0.0,
    price_ref_sqm=0.0,
    price_ref_id="",
    cache_key=None
):
    """Builds and caches the detailed comparison table (show_df, df_to_export, has_valid_proj) using vectorized/unique-mapped operations."""
    filtered_nearby = _filtered_nearby
    is_fn_pure_land = _is_fn_pure_land
    show_df = pd.DataFrame(index=filtered_nearby.index)

    # 1. บริษัท, รหัสทรัพย์, ชื่อโครงการ, ประเภททรัพย์
    for col in ['บริษัท', 'รหัสทรัพย์', 'ชื่อโครงการ', 'ประเภททรัพย์']:
        if col in filtered_nearby.columns:
            if col == 'ชื่อโครงการ':
                proj_clean = _clean_str_series(filtered_nearby[col], '-')
                show_df[col] = np.where(proj_clean.str.len() > 35, proj_clean.str.slice(0, 35) + '...', proj_clean)
                show_df['_export_proj_full'] = proj_clean
            else:
                show_df[col] = _clean_str_series(filtered_nearby[col], '-')
        elif col == 'ชื่อโครงการ':
            show_df[col] = '-'
            show_df['_export_proj_full'] = '-'

    # 2. ราคา (บาท)
    price_num = pd.to_numeric(filtered_nearby['ราคา'], errors='coerce') if 'ราคา' in filtered_nearby.columns else pd.Series(np.nan, index=filtered_nearby.index)
    show_df['ราคา (บาท)'] = price_num

    # 3. เนื้อที่ (ไร่-งาน-ตร.ว.) - รูปแบบ 0-0-0 (map unique values for 80x speedup)
    if 'พื้นที่_ตารางวา' in filtered_nearby.columns:
        sqw_vals = pd.to_numeric(filtered_nearby['พื้นที่_ตารางวา'], errors='coerce')
        if 'เนื้อที่ (ตร.ว.)' in filtered_nearby.columns and sqw_vals.isna().any():
            raw_sqw_obj = filtered_nearby['เนื้อที่ (ตร.ว.)'].astype(object)
            u_raw_sqw = raw_sqw_obj.loc[sqw_vals.isna()].dropna().unique()
            u_sqw_map = {v: to_float_sqwah(v) for v in u_raw_sqw}
            sqw_vals = sqw_vals.fillna(pd.to_numeric(raw_sqw_obj.map(u_sqw_map), errors='coerce'))
    elif 'เนื้อที่ (ตร.ว.)' in filtered_nearby.columns:
        raw_sqw_obj = filtered_nearby['เนื้อที่ (ตร.ว.)'].astype(object)
        u_raw_sqw = raw_sqw_obj.dropna().unique()
        u_sqw_map = {v: to_float_sqwah(v) for v in u_raw_sqw}
        sqw_vals = pd.to_numeric(raw_sqw_obj.map(u_sqw_map), errors='coerce')
    else:
        sqw_vals = pd.Series(np.nan, index=filtered_nearby.index)

    if 'เนื้อที่ (ตร.ว.)' in filtered_nearby.columns:
        raw_sqw_obj = filtered_nearby['เนื้อที่ (ตร.ว.)'].astype(object)
        u_str_sqw = raw_sqw_obj.dropna().unique()
        u_fmt_str_map = {v: format_to_rai_ngan_wah(v) for v in u_str_sqw}
        formatted_sqw = raw_sqw_obj.map(u_fmt_str_map).astype(object).fillna("-")
        need_num_fmt = (formatted_sqw == "-") & sqw_vals.notna()
        if need_num_fmt.any():
            u_num_sqw = sqw_vals.loc[need_num_fmt].dropna().unique()
            u_fmt_num_map = {v: format_to_rai_ngan_wah(v) for v in u_num_sqw}
            formatted_sqw.loc[need_num_fmt] = sqw_vals.loc[need_num_fmt].astype(object).map(u_fmt_num_map).astype(object).fillna("-")
    else:
        u_num_sqw = sqw_vals.dropna().unique()
        u_fmt_num_map = {v: format_to_rai_ngan_wah(v) for v in u_num_sqw}
        formatted_sqw = sqw_vals.astype(object).map(u_fmt_num_map).astype(object).fillna("-")

    # 4. ราคาต่อตร.ว. (บาท)
    if 'ราคาต่อตารางวา' in filtered_nearby.columns:
        calc_p_sqw = pd.to_numeric(filtered_nearby['ราคาต่อตารางวา'], errors='coerce')
        fallback_sqw = np.where((price_num > 0) & (sqw_vals > 0), price_num / sqw_vals, np.nan)
        calc_p_sqw = np.where(calc_p_sqw > 0, calc_p_sqw, fallback_sqw)
    else:
        calc_p_sqw = np.where((price_num > 0) & (sqw_vals > 0), price_num / sqw_vals, np.nan)

    is_condo_row = filtered_nearby['ประเภททรัพย์'].astype(str).str.contains('คอนโด|ห้องชุด|อาคารชุด', na=False)
    calc_p_sqw = np.where(is_condo_row, np.nan, calc_p_sqw)
    formatted_sqw = formatted_sqw.astype(object).mask(is_condo_row, "-")

    def _fmt_diff_pct(val, med):
        if pd.isna(val) or val <= 0 or pd.isna(med) or med <= 0:
            return "-"
        diff = ((val - med) / med) * 100.0
        if diff > 0:
            return f"↑ +{diff:.1f}%"
        elif diff < 0:
            return f"↓ {diff:.1f}%"
        else:
            return "0.0%"

    def _fmt_diff_sub(val, med):
        if pd.isna(val) or val <= 0 or pd.isna(med) or med <= 0:
            return "-"
        diff = val - med
        if diff > 0:
            return f"↑ +{diff:,.0f} ฿"
        elif diff < 0:
            return f"↓ -{abs(diff):,.0f} ฿"
        else:
            return "0 ฿"

    # Calculate sqm and per-sqm rates
    if 'พื้นที่ใช้สอย (ตร.ม.)' in filtered_nearby.columns:
        if pd.api.types.is_numeric_dtype(filtered_nearby['พื้นที่ใช้สอย (ตร.ม.)']):
            sqm_vals = pd.to_numeric(filtered_nearby['พื้นที่ใช้สอย (ตร.ม.)'], errors='coerce')
            sqm_vals = sqm_vals.where(sqm_vals > 0, np.nan)
        else:
            raw_sqm_obj = filtered_nearby['พื้นที่ใช้สอย (ตร.ม.)'].astype(object)
            u_sqm = raw_sqm_obj.dropna().unique()
            u_sqm_map = {v: to_float_sqm(v) for v in u_sqm}
            sqm_vals = pd.to_numeric(raw_sqm_obj.map(u_sqm_map), errors='coerce')
    else:
        sqm_vals = pd.Series(np.nan, index=filtered_nearby.index)

    if 'ราคาต่อตารางเมตร' in filtered_nearby.columns:
        calc_p_sqm = pd.to_numeric(filtered_nearby['ราคาต่อตารางเมตร'], errors='coerce')
        fallback_sqm = np.where((price_num > 0) & (sqm_vals > 0), price_num / sqm_vals, np.nan)
        calc_p_sqm = np.where(calc_p_sqm > 0, calc_p_sqm, fallback_sqm)
    else:
        calc_p_sqm = np.where((price_num > 0) & (sqm_vals > 0), price_num / sqm_vals, np.nan)

    type_sqw_medians = {}
    type_sqm_medians = {}
    p_types_series = show_df['ประเภททรัพย์'] if 'ประเภททรัพย์' in show_df.columns else pd.Series([], dtype=str)
    if not filtered_nearby.empty and not p_types_series.empty:
        sqw_calc_rates = pd.Series(calc_p_sqw, index=filtered_nearby.index)
        for pt, sub_idx in filtered_nearby.groupby(p_types_series, observed=False).groups.items():
            sub_rates = sqw_calc_rates.loc[sub_idx].dropna()
            sub_rates = sub_rates[sub_rates > 0]
            if not sub_rates.empty:
                type_sqw_medians[pt] = float(sub_rates.median())

        sqm_calc_rates = pd.Series(calc_p_sqm, index=filtered_nearby.index)
        for pt, sub_idx in filtered_nearby.groupby(p_types_series, observed=False).groups.items():
            sub_rates = sqm_calc_rates.loc[sub_idx].dropna()
            sub_rates = sub_rates[sub_rates > 0]
            if not sub_rates.empty:
                type_sqm_medians[pt] = float(sub_rates.median())

    uniq_pts = p_types_series.unique() if not p_types_series.empty else []
    fallback_med_sqw = median_sqw_val if median_sqw_val > 0 else (median_u_sel if median_u_sel > 0 else (median_raw_land if median_raw_land > 0 else np.nan))
    pt_med_sqw_map = {}
    pt_med_sqm_map = {}
    for pt in uniq_pts:
        pt_clean = str(pt).strip()
        if any(k in pt_clean for k in ['คอนโด', 'ห้องชุด', 'อาคารชุด']):
            pt_med_sqw_map[pt] = np.nan
        elif pt_clean in type_sqw_medians:
            pt_med_sqw_map[pt] = type_sqw_medians[pt_clean]
        else:
            pt_med_sqw_map[pt] = fallback_med_sqw
        pt_med_sqm_map[pt] = type_sqm_medians.get(pt_clean, median_sqm_val if median_sqm_val > 0 else np.nan)

    if price_ref_id:
        # Comparison directly with Price Center Property
        if price_ref_sqw > 0:
            target_med_sqw_s = pd.Series(price_ref_sqw, index=filtered_nearby.index)
            target_med_sqw_s = target_med_sqw_s.mask(is_condo_row, np.nan)
        else:
            target_med_sqw_s = pd.Series(np.nan, index=filtered_nearby.index)

        if price_ref_sqm > 0:
            target_med_sqm_s = pd.Series(price_ref_sqm, index=filtered_nearby.index)
        else:
            target_med_sqm_s = pd.Series(np.nan, index=filtered_nearby.index)
    else:
        target_med_sqw_s = p_types_series.map(pt_med_sqw_map)
        if median_raw_land > 0 and isinstance(is_fn_pure_land, pd.Series) and len(is_fn_pure_land) == len(target_med_sqw_s):
            need_land_fb = target_med_sqw_s.isna() & is_fn_pure_land & (~is_condo_row)
            if need_land_fb.any():
                target_med_sqw_s = target_med_sqw_s.mask(need_land_fb, median_raw_land)
        target_med_sqm_s = p_types_series.map(pt_med_sqm_map)

    calc_p_sqw_s = pd.Series(calc_p_sqw, index=filtered_nearby.index)
    valid_sqw_diff = calc_p_sqw_s.notna() & (calc_p_sqw_s > 0) & target_med_sqw_s.notna() & (target_med_sqw_s > 0)
    diff_sqw_col = pd.Series("-", index=filtered_nearby.index, dtype=object)
    if valid_sqw_diff.any():
        diff_sqw_col.loc[valid_sqw_diff] = [
            _fmt_diff_pct(v, m)
            for v, m in zip(calc_p_sqw_s.loc[valid_sqw_diff], target_med_sqw_s.loc[valid_sqw_diff])
        ]

    sub_land_col = pd.Series("-", index=filtered_nearby.index, dtype=object)
    if median_raw_land > 0:
        valid_sub_land = calc_p_sqw_s.notna() & (calc_p_sqw_s > 0) & (~is_condo_row)
        if valid_sub_land.any():
            sub_land_col.loc[valid_sub_land] = [
                _fmt_diff_sub(v, median_raw_land)
                for v in calc_p_sqw_s.loc[valid_sub_land]
            ]

    calc_p_sqm_s = pd.Series(calc_p_sqm, index=filtered_nearby.index)
    valid_sqm_diff = calc_p_sqm_s.notna() & (calc_p_sqm_s > 0) & target_med_sqm_s.notna() & (target_med_sqm_s > 0)
    diff_sqm_col = pd.Series("-", index=filtered_nearby.index, dtype=object)
    if valid_sqm_diff.any():
        diff_sqm_col.loc[valid_sqm_diff] = [
            _fmt_diff_pct(v, m)
            for v, m in zip(calc_p_sqm_s.loc[valid_sqm_diff], target_med_sqm_s.loc[valid_sqm_diff])
        ]

    # Land Sq.Wah columns (Grouped together: เนื้อที่ -> ราคาต่อตร.ว. -> เทียบราคาต่อตร.ว. -> หักลบราคากลางที่ดินเปล่า)
    show_df['เนื้อที่ (ไร่-งาน-ตร.ว.)'] = formatted_sqw
    show_df['ราคาต่อตร.ว. (บาท)'] = calc_p_sqw
    if price_ref_id:
        show_df['เทียบราคา ตร.ว. (ทรัพย์อ้างอิง)'] = diff_sqw_col
    else:
        show_df['เทียบราคากลางต่อ ตร.ว.'] = diff_sqw_col
    show_df['หักลบราคากลาง ตร.ว. ที่ดินเปล่า'] = sub_land_col

    # Usable Area Sq.Metre columns (Grouped together: พื้นที่ใช้สอย -> ราคาต่อตร.ม. -> เทียบราคาต่อตร.ม.)
    show_df['พื้นที่ใช้สอย (ตร.ม.)'] = sqm_vals
    show_df['ราคาต่อตร.ม. (บาท)'] = calc_p_sqm
    if price_ref_id:
        show_df['เทียบราคา ตร.ม. (ทรัพย์อ้างอิง)'] = diff_sqm_col
    else:
        show_df['เทียบราคากลางต่อ ตร.ม.'] = diff_sqm_col

    if 'ระยะทาง (กม.)' in filtered_nearby.columns:
        show_df['ระยะทาง (กม.)'] = pd.to_numeric(filtered_nearby['ระยะทาง (กม.)'], errors='coerce')

    if 'ชั้น' in filtered_nearby.columns:
        show_df['ชั้น'] = _clean_str_series(filtered_nearby['ชั้น'], '-')
    else:
        show_df['ชั้น'] = '-'

    if 'ลิงก์' in filtered_nearby.columns:
        links_s = filtered_nearby['ลิงก์'].astype(object).copy()
        if 'บริษัท' in filtered_nearby.columns:
            is_legal = filtered_nearby['บริษัท'].astype(str).str.strip().str.upper().isin(['LED LEGAL', 'LED_LEGAL', 'LED_SOLD'])
            if is_legal.any():
                links_s.loc[is_legal] = links_s.loc[is_legal].astype(str).str.replace('led_bridge.html', 'led_legal_bridge.html', regex=False)
        show_df['เปิดลิงก์'] = links_s

    if 'วันประกาศ' in filtered_nearby.columns:
        ann_res = pd.Series("-", index=filtered_nearby.index, dtype=object)
        ann_col_obj = filtered_nearby['วันประกาศ'].astype(object)
        ann_mask = ann_col_obj.notna()
        if ann_mask.any():
            is_legal = (
                filtered_nearby['บริษัท'].astype(str).str.strip().str.upper().isin(['LED LEGAL', 'LED_LEGAL', 'LED_SOLD'])
                if 'บริษัท' in filtered_nearby.columns else pd.Series(False, index=filtered_nearby.index)
            )
            has_sold = (
                filtered_nearby['วันที่ขาย'].notna()
                & (filtered_nearby['วันที่ขาย'].astype(str).str.strip() != '')
                & (filtered_nearby['วันที่ขาย'].astype(str).str.strip() != '-')
                if 'วันที่ขาย' in filtered_nearby.columns else pd.Series(False, index=filtered_nearby.index)
            )
            legal_sold_mask = is_legal & has_sold & ann_mask
            reg_mask = ann_mask & ~legal_sold_mask
            if reg_mask.any():
                u_ann_dates = ann_col_obj.loc[reg_mask].dropna().unique()
                u_ann_map = {d: format_announcement_age(d) for d in u_ann_dates}
                ann_res.loc[reg_mask] = ann_col_obj.loc[reg_mask].map(u_ann_map).astype(object).fillna("-")

            if legal_sold_mask.any():
                sub_pairs = filtered_nearby.loc[legal_sold_mask, ['วันประกาศ', 'วันที่ขาย']].astype(object).drop_duplicates()
                pair_map = {}
                for _, r_dt in sub_pairs.iterrows():
                    ann_v = r_dt['วันประกาศ']
                    sold_v = r_dt['วันที่ขาย']
                    val_str = None
                    try:
                        s_dt = pd.to_datetime(sold_v, errors='coerce')
                        if pd.notna(s_dt):
                            diff = parse_listing_age_days(ann_v, ref_date=s_dt.date())
                            if diff >= 0:
                                val_str = f"ขายได้ใน {diff:,} วัน"
                    except Exception:
                        pass
                    if not val_str:
                        val_str = format_announcement_age(ann_v)
                    pair_map[(ann_v, sold_v)] = val_str
                ann_res.loc[legal_sold_mask] = [
                    pair_map.get((a, s), "-")
                    for a, s in zip(ann_col_obj.loc[legal_sold_mask], filtered_nearby.loc[legal_sold_mask, 'วันที่ขาย'].astype(object))
                ]
        show_df['อายุวันประกาศ'] = ann_res
    else:
        show_df['อายุวันประกาศ'] = '-'

    if 'เลขโฉนด' in filtered_nearby.columns:
        show_df['เลขโฉนด'] = _clean_str_series(filtered_nearby['เลขโฉนด'], '-')
    else:
        show_df['เลขโฉนด'] = '-'

    def _fmt_spec_count(val):
        if pd.isna(val) or val is None:
            return "-"
        s = str(val).strip()
        if s in ["", "-", "nan", "None", "<NA>", "null"]:
            return "-"
        try:
            f = float(s)
            if pd.isna(f) or f <= 0:
                return "-"
            return str(int(round(f)))
        except (ValueError, TypeError):
            return "-"

    for room_col in ['ห้องนอน', 'ห้องน้ำ', 'ที่จอดรถ']:
        if room_col in filtered_nearby.columns:
            rm_obj = filtered_nearby[room_col].astype(object)
            u_rm = rm_obj.dropna().unique()
            u_rm_map = {v: _fmt_spec_count(v) for v in u_rm}
            show_df[room_col] = rm_obj.map(u_rm_map).astype(object).fillna("-")
        else:
            show_df[room_col] = '-'

    for loc_col in ['ตำบล', 'อำเภอ', 'จังหวัด']:
        if loc_col in filtered_nearby.columns:
            show_df[loc_col] = _clean_str_series(filtered_nearby[loc_col], '-')
        else:
            show_df[loc_col] = '-'

    if 'ละติจูด' in filtered_nearby.columns:
        show_df['ละติจูด'] = format_coord_vectorized(filtered_nearby, 'ละติจูด')
    else:
        show_df['ละติจูด'] = '-'

    if 'ลองจิจูด' in filtered_nearby.columns:
        show_df['ลองจิจูด'] = format_coord_vectorized(filtered_nearby, 'ลองจิจูด')
    else:
        show_df['ลองจิจูด'] = '-'

    if 'โจทก์' in filtered_nearby.columns:
        show_df['โจทก์'] = _clean_str_series(filtered_nearby['โจทก์'], '-')
    else:
        show_df['โจทก์'] = '-'

    if 'ระยะทาง (กม.)' in show_df.columns:
        show_df = show_df.sort_values(by='ระยะทาง (กม.)', ascending=True).reset_index(drop=True)

    if price_ref_id and not show_df.empty and 'รหัสทรัพย์' in show_df.columns:
        clean_p_ref = str(price_ref_id).strip().lower()
        is_ref_row = show_df['รหัสทรัพย์'].astype(str).str.strip().str.lower() == clean_p_ref
        if is_ref_row.any():
            show_df = pd.concat([show_df[is_ref_row], show_df[~is_ref_row]], ignore_index=True)
            show_df.loc[0, 'รหัสทรัพย์'] = f"[อ้างอิง] {show_df.loc[0, 'รหัสทรัพย์']}"
            if 'ระยะทาง (กม.)' in show_df.columns:
                show_df.loc[0, 'ระยะทาง (กม.)'] = 0.0

    has_valid_proj = False
    if 'ชื่อโครงการ' in show_df.columns:
        has_valid_proj = bool((show_df['ชื่อโครงการ'].astype(str).str.strip().replace({'': '-', 'nan': '-', 'None': '-', 'null': '-', '<NA>': '-'}) != '-').any())

    df_to_export = show_df.copy()
    if '_export_proj_full' in df_to_export.columns:
        df_to_export['ชื่อโครงการ'] = df_to_export.pop('_export_proj_full')
    if '_export_proj_full' in show_df.columns:
        show_df = show_df.drop(columns=['_export_proj_full'])
    if 'รหัสทรัพย์' in df_to_export.columns:
        df_to_export['รหัสทรัพย์'] = df_to_export['รหัสทรัพย์'].astype(str).str.replace('[อ้างอิง] ', '', regex=False)
    return show_df, df_to_export, has_valid_proj


def precompute_tab2_default_analytics(df_raw, data_mtime=0):
    """Pre-warms the Tab 2 nationwide analytics fragment and comparison table during the Welcome Screen."""
    if df_raw is None or df_raw.empty:
        return
    if 'ละติจูด' in df_raw.columns and 'ลองจิจูด' in df_raw.columns:
        valid_coords_mask = (
            df_raw['ละติจูด'].notna() & df_raw['ลองจิจูด'].notna() &
            df_raw['ละติจูด'].between(5, 21) & df_raw['ลองจิจูด'].between(97, 106)
        )
        df_raw = df_raw[valid_coords_mask]
    if df_raw.empty:
        return

    base_key = (data_mtime, len(df_raw))
    pure_df, pure_rates = _get_cached_nationwide_pure_land(df_raw, cache_key=base_key)
    median_raw_land = float(pure_rates.median()) if not pure_rates.empty else 0.0

    filtered_nearby = _compute_vectorized_unit_info_cached(df_raw, cache_key=base_key)
    is_fn_pure_land = _check_pure_land_mask_global(filtered_nearby['ประเภททรัพย์'])

    calc_type_df = filtered_nearby[~is_fn_pure_land & ~filtered_nearby['ประเภททรัพย์'].astype(str).str.contains('คอนโด|ห้องชุด', na=False)]
    s_vals = _sqw_from_df(calc_type_df)
    p_vals = pd.to_numeric(calc_type_df.get('ราคา', np.nan), errors='coerce')
    v_mask = (s_vals > 0) & (p_vals > 0)
    sqw_rates = (p_vals[v_mask] / s_vals[v_mask]).dropna()
    sqw_rates = sqw_rates[sqw_rates > 0]
    median_u_sel = float(sqw_rates.median()) if not sqw_rates.empty else 0.0
    median_sqw_val = median_u_sel

    median_sqm_val = 0.0
    if 'พื้นที่ใช้สอย (ตร.ม.)' in filtered_nearby.columns:
        sqm_vals = pd.to_numeric(filtered_nearby['พื้นที่ใช้สอย (ตร.ม.)'], errors='coerce')
        price_vals = pd.to_numeric(filtered_nearby['ราคา'], errors='coerce')
        valid_mask_sqm = (sqm_vals > 0) & (price_vals > 0)
        sqm_rates = (price_vals[valid_mask_sqm] / sqm_vals[valid_mask_sqm]).dropna()
        sqm_rates = sqm_rates[sqm_rates > 0]
        if not sqm_rates.empty:
            median_sqm_val = float(sqm_rates.median())

    idx_fp = int(pd.util.hash_pandas_object(filtered_nearby.index, index=False).sum()) if not filtered_nearby.empty else 0
    tbl_key = (
        data_mtime,
        0,
        len(filtered_nearby),
        idx_fp,
        0.0,
        0.0,
        0.0,
        round(median_raw_land, 2),
        round(median_sqw_val, 2),
        round(median_u_sel, 2),
        round(median_sqm_val, 2),
        0.0,
        0.0,
        "",
        False,
        False,
    )
    _build_tab2_show_df_cached(
        filtered_nearby,
        is_fn_pure_land,
        median_raw_land,
        median_sqw_val,
        median_u_sel,
        median_sqm_val,
        cache_key=tbl_key
    )


def _match_project_mask(df, p_list):
    """
    Robust matching of project names across all companies in the dataset:
    - Raw exact match on ชื่อโครงการ
    - Normalized project keyword match (handles English vs Thai, spaces, tones, abbreviations)
    - Core substring match (handles prefixes like คอนโด, โครงการ, อาคารชุด, etc.)
    """
    if df is None or df.empty or not p_list:
        return pd.Series(False, index=df.index if df is not None else [])

    clean_p_list = [p.strip() for p in p_list if p.strip()]
    if not clean_p_list:
        return pd.Series(False, index=df.index)

    selected_raw_names = set(clean_p_list)
    selected_norm_keys = {normalize_project_name(p) for p in clean_p_list if normalize_project_name(p)}

    mask = pd.Series(False, index=df.index)
    if 'ชื่อโครงการ' in df.columns:
        proj_col = df['ชื่อโครงการ'].astype(object).fillna('').astype(str).str.strip()
        mask = mask | proj_col.isin(selected_raw_names)

        if selected_norm_keys:
            if 'norm_project_name' in df.columns:
                mask = mask | df['norm_project_name'].isin(selected_norm_keys)
            else:
                norm_col = proj_col.apply(normalize_project_name)
                mask = mask | norm_col.isin(selected_norm_keys)

        for raw_p in clean_p_list:
            clean_core = re.sub(
                r'^(คอนโด\s*โครงการ|โครงการ\s*คอนโด|โครงการ\s*หมู่บ้าน|อาคารชุด|คอนโดมิเนียม|มีเนียม|โครงการ|หมู่บ้าน|คอนโด|บ้านเดี่ยว|บ้านแฝด|บ้าน|ทาวน์โฮม|ทาวน์เฮ้าส์|ขายคอนโด)\s*',
                '', raw_p, flags=re.IGNORECASE
            ).strip()
            clean_core = re.sub(r'(\[.*?\]|\(.*?\)).*$', '', clean_core).strip()
            if len(clean_core) >= 4:
                mask = mask | proj_col.str.contains(re.escape(clean_core), case=False, na=False)

    return mask

def _extract_asset_unit_rates(p_dict):
    """Extracts price, sqw_num, sqw_rate, sqm_rate, is_condo from a property dict."""
    if not p_dict or not isinstance(p_dict, dict):
        return 0.0, 0.0, 0.0, 0.0, False

    price = _safe_float(p_dict.get('ราคา'), 0.0)

    # Check if condo
    p_type = str(p_dict.get('ประเภททรัพย์', '')).lower()
    is_condo = bool(re.search(r'คอนโด|ห้องชุด|อาคารชุด', p_type))

    # Sq.wah
    sqw = _safe_float(p_dict.get('พื้นที่_ตารางวา'), 0.0)
    if sqw <= 0 and 'เนื้อที่ (ตร.ว.)' in p_dict:
        sqw = to_float_sqwah(p_dict.get('เนื้อที่ (ตร.ว.)'))

    sqw_rate = 0.0
    if not is_condo:
        raw_puw = _safe_float(p_dict.get('ราคาต่อตารางวา'), 0.0)
        if raw_puw > 0:
            sqw_rate = raw_puw
        elif sqw > 0 and price > 0:
            sqw_rate = price / sqw

    # Sq.metre
    sqm = _safe_float(p_dict.get('พื้นที่ใช้สอย (ตร.ม.)'), 0.0)
    sqm_rate = 0.0
    raw_pum = _safe_float(p_dict.get('ราคาต่อตารางเมตร'), 0.0)
    if raw_pum > 0:
        sqm_rate = raw_pum
    elif sqm > 0 and price > 0:
        sqm_rate = price / sqm

    return price, sqw, sqw_rate, sqm_rate, is_condo


fragment_decorator = getattr(st, "fragment", lambda f: f)

@fragment_decorator
def render_tab2_reference_analytics_fragment(
    df_raw,
    is_dark_mode,
    active_ref_lat,
    active_ref_lon,
    active_ref_prop,
    active_price_ref_prop=None,
    active_ref_radius=5.0,
    tab2_types=None
):
    """
    Renders the live reference analytics fragment below the Tab 2 Leaflet map:
    - Hidden sync bridge with Leaflet iframe (two-way state syncing)
    - Active filter status chip banner
    - Prominent comparison action button
    - Dynamic median price benchmark cards (Total assets, sqm median, target type median, pure land benchmark)
    - Detailed comparative dataframe with up/down delta badges
    - CSV/Excel export section
    """
    if active_ref_prop is not None and isinstance(active_ref_prop, pd.Series):
        active_ref_prop = active_ref_prop.to_dict()
    if active_price_ref_prop is not None and isinstance(active_price_ref_prop, pd.Series):
        active_price_ref_prop = active_price_ref_prop.to_dict()

    if st.session_state.pop("tab2_inject_clear_price_center_js", False):
        st.html("""
        <script>
        (function() {
            try {
                var u = new URL(window.parent.location.href);
                u.searchParams.delete('map_price_ref_id');
                window.parent.history.replaceState({}, '', u.toString());
                var iframes = window.parent.document.querySelectorAll('iframe');
                iframes.forEach(function(f) {
                    try {
                        if (f.contentWindow) {
                            if (typeof f.contentWindow.clearPriceCenter === 'function') {
                                f.contentWindow.clearPriceCenter();
                            } else {
                                f.contentWindow.postMessage({ action: 'clear_price_center' }, '*');
                            }
                        }
                    } catch(e) {}
                });
            } catch(e) {}
        })();
        </script>
        """)

    if st.session_state.get("tab2_just_reset_price_center"):
        active_price_ref_prop = None
        st.session_state["tab2_price_center_id"] = ""
        st.session_state.pop("tab2_price_ref_prop", None)
        try:
            st.query_params.pop("map_price_ref_id", None)
        except Exception:
            pass

    # Ensure Tab 2 reference analytics strictly operates on properties with valid coordinates (matching the 418,055 map pins)
    if df_raw is not None and not df_raw.empty and 'ละติจูด' in df_raw.columns and 'ลองจิจูด' in df_raw.columns:
        valid_coords_mask = (
            df_raw['ละติจูด'].notna() & df_raw['ลองจิจูด'].notna() &
            df_raw['ละติจูด'].between(5, 21) & df_raw['ลองจิจูด'].between(97, 106)
        )
        df_raw = df_raw[valid_coords_mask]

    # 0. Hidden synchronization bridge between map iframe and Streamlit
    st.markdown("""
    <style>
    /* Position sync button and bridge input offscreen while remaining active and clickable via JS */
    .st-key-btn_map_filter_sync,
    div[data-testid="stElementContainer"]:has(.st-key-btn_map_filter_sync),
    div[data-testid="stButton"]:has(.st-key-btn_map_filter_sync),
    .st-key-map_sync_bridge_payload,
    div[data-testid="stElementContainer"]:has(.st-key-map_sync_bridge_payload),
    div[data-testid="stTextInput"]:has(.st-key-map_sync_bridge_payload) {
        position: fixed !important;
        bottom: -9999px !important;
        right: -9999px !important;
        opacity: 0 !important;
        z-index: -9999 !important;
    }
    </style>
    <div id="map-sync-anchor" style="position:fixed; bottom:-9999px; right:-9999px;"></div>
    """, unsafe_allow_html=True)

    sync_bridge_val = st.text_input("map_sync_bridge", key="map_sync_bridge_payload", label_visibility="collapsed")
    sync_btn_clicked = st.button("sync_map_filter", key="btn_map_filter_sync")

    if sync_bridge_val or sync_btn_clicked:
        payload_obj = None
        if sync_bridge_val and str(sync_bridge_val).strip():
            try:
                payload_obj = json.loads(str(sync_bridge_val).strip())
            except Exception:
                pass

        if payload_obj and isinstance(payload_obj, dict):
            p_prov = str(payload_obj.get("prov", "")).strip()
            if p_prov and p_prov not in ["ALL", "__ALL__", "all", "-"]:
                st.session_state["tab2_filter_provinces"] = [p_prov]
                try:
                    st.query_params["map_prov"] = p_prov
                except Exception:
                    pass
            else:
                st.session_state["tab2_filter_provinces"] = []
                st.session_state["tab2_filter_districts"] = []
                st.session_state["tab2_filter_subdistricts"] = []
                st.session_state["tab2_search_prop_id"] = ""
                st.session_state.pop("tab2_ref_prop", None)
                for qk in ["map_prov", "map_dist", "map_subdist", "map_ref_id"]:
                    try:
                        st.query_params.pop(qk, None)
                    except Exception:
                        pass

            p_dist = str(payload_obj.get("dist", "")).strip()
            if st.session_state.get("tab2_filter_provinces") and p_dist and p_dist not in ["ALL", "__ALL__", "all", "-"]:
                st.session_state["tab2_filter_districts"] = [p_dist]
                try:
                    st.query_params["map_dist"] = p_dist
                except Exception:
                    pass
            else:
                st.session_state["tab2_filter_districts"] = []
                try:
                    st.query_params.pop("map_dist", None)
                except Exception:
                    pass

            p_subdist = str(payload_obj.get("subdist", "")).strip()
            if st.session_state.get("tab2_filter_provinces") and st.session_state.get("tab2_filter_districts") and p_subdist and p_subdist not in ["ALL", "__ALL__", "all", "-"]:
                st.session_state["tab2_filter_subdistricts"] = [p_subdist]
                try:
                    st.query_params["map_subdist"] = p_subdist
                except Exception:
                    pass
            else:
                st.session_state["tab2_filter_subdistricts"] = []
                try:
                    st.query_params.pop("map_subdist", None)
                except Exception:
                    pass

            p_proj = str(payload_obj.get("proj", "")).strip()
            if p_proj and p_proj not in ["ALL", "__ALL__", "all", "-"]:
                p_list = [x.strip() for x in p_proj.split(",") if x.strip()]
                st.session_state["tab2_filter_projects"] = p_list
                try:
                    st.query_params["map_proj"] = p_proj
                except Exception:
                    pass
            elif "proj" in payload_obj:
                st.session_state["tab2_filter_projects"] = []
                try:
                    st.query_params.pop("map_proj", None)
                except Exception:
                    pass

            if "compare_ids" in payload_obj:
                raw_cids = payload_obj.get("compare_ids", [])
                if isinstance(raw_cids, list):
                    st.session_state["tab2_compare_ids"] = [str(x).strip() for x in raw_cids if str(x).strip()]
                elif isinstance(raw_cids, str):
                    st.session_state["tab2_compare_ids"] = [x.strip() for x in raw_cids.split(",") if x.strip()]
                if st.session_state.get("tab2_compare_ids"):
                    st.query_params["map_compare_ids"] = ",".join(st.session_state["tab2_compare_ids"])
                else:
                    st.query_params.pop("map_compare_ids", None)

            p_id = str(payload_obj.get("id", "")).strip()
            if p_id:
                st.session_state["tab2_search_prop_id"] = p_id
                try:
                    st.query_params["map_ref_id"] = p_id
                except Exception:
                    pass
                if df_raw is not None and not df_raw.empty:
                    m = df_raw[df_raw['รหัสทรัพย์'].astype(str).str.strip().str.lower() == p_id.lower()]
                    if not m.empty:
                        active_ref_prop = m.iloc[0].to_dict()
                        st.session_state["tab2_ref_prop"] = active_ref_prop
                        prop_p = str(active_ref_prop.get('จังหวัด', '')).strip()
                        prop_d = str(active_ref_prop.get('อำเภอ', '')).strip()
                        prop_s = str(active_ref_prop.get('ตำบล', '')).strip()
                        if prop_p and prop_p not in ['-', 'ไม่มีข้อมูล', 'nan']:
                            st.session_state["tab2_filter_provinces"] = [prop_p]
                        if prop_d and prop_d not in ['-', 'ไม่มีข้อมูล', 'nan']:
                            st.session_state["tab2_filter_districts"] = [prop_d]
                        if prop_s and prop_s not in ['-', 'ไม่มีข้อมูล', 'nan']:
                            st.session_state["tab2_filter_subdistricts"] = [prop_s]
            elif "id" in payload_obj or not st.session_state.get("tab2_filter_provinces"):
                st.session_state["tab2_search_prop_id"] = ""
                st.session_state.pop("tab2_ref_prop", None)
                try:
                    st.query_params.pop("map_ref_id", None)
                except Exception:
                    pass

            if "price_center_id" in payload_obj:
                if st.session_state.get("tab2_just_reset_price_center"):
                    p_price_id = ""
                else:
                    p_price_id = str(payload_obj.get("price_center_id", "")).strip()
                if p_price_id:
                    st.session_state["tab2_price_center_id"] = p_price_id
                    try:
                        st.query_params["map_price_ref_id"] = p_price_id
                    except Exception:
                        pass
                    if df_raw is not None and not df_raw.empty:
                        m_pr = df_raw[df_raw['รหัสทรัพย์'].astype(str).str.strip().str.lower() == p_price_id.lower()]
                        if not m_pr.empty:
                            active_price_ref_prop = m_pr.iloc[0].to_dict()
                            st.session_state["tab2_price_ref_prop"] = active_price_ref_prop
                else:
                    st.session_state["tab2_price_center_id"] = ""
                    st.session_state.pop("tab2_price_ref_prop", None)
                    active_price_ref_prop = None
                    try:
                        st.query_params.pop("map_price_ref_id", None)
                    except Exception:
                        pass

            p_lat_f = _safe_float(payload_obj.get("lat"), 0.0)
            p_lon_f = _safe_float(payload_obj.get("lon"), 0.0)
            if p_lat_f > 0 and p_lon_f > 0:
                active_ref_lat = p_lat_f
                active_ref_lon = p_lon_f
                st.session_state["tab2_ref_lat"] = active_ref_lat
                st.session_state["tab2_ref_lon"] = active_ref_lon
                st.session_state["tab2_compared_lat"] = active_ref_lat
                st.session_state["tab2_compared_lon"] = active_ref_lon
                try:
                    st.query_params["map_ref_lat"] = f"{active_ref_lat:.6f}"
                    st.query_params["map_ref_lon"] = f"{active_ref_lon:.6f}"
                except Exception:
                    pass
            elif "lat" in payload_obj or "lon" in payload_obj:
                active_ref_lat = None
                active_ref_lon = None
                st.session_state.pop("tab2_ref_lat", None)
                st.session_state.pop("tab2_ref_lon", None)
                st.session_state.pop("tab2_compared_lat", None)
                st.session_state.pop("tab2_compared_lon", None)
                for qk in ["map_ref_lat", "map_ref_lon"]:
                    try:
                        st.query_params.pop(qk, None)
                    except Exception:
                        pass

            p_rad = payload_obj.get("radius")
            if p_rad:
                try:
                    active_ref_radius = float(p_rad)
                    st.session_state["tab2_ref_radius"] = active_ref_radius
                    try:
                        st.query_params["map_ref_radius"] = str(active_ref_radius)
                    except Exception:
                        pass
                except (ValueError, TypeError):
                    pass

            p_mode = payload_obj.get("mode")
            if p_mode:
                st.session_state["tab2_pin_mode"] = str(p_mode).strip()
                try:
                    st.query_params["map_pin_mode"] = str(p_mode).strip()
                except Exception:
                    pass

            if "cos" in payload_obj and isinstance(payload_obj["cos"], list):
                st.session_state["tab2_map_filter_cos"] = payload_obj["cos"]
                try:
                    if payload_obj["cos"]:
                        st.query_params["map_filter_cos"] = ",".join(payload_obj["cos"])
                    else:
                        st.query_params.pop("map_filter_cos", None)
                except Exception:
                    pass
            if "types" in payload_obj and isinstance(payload_obj["types"], list):
                st.session_state["tab2_map_filter_types"] = payload_obj["types"]
                try:
                    if payload_obj["types"]:
                        st.query_params["map_filter_types"] = ",".join(payload_obj["types"])
                    else:
                        st.query_params.pop("map_filter_types", None)
                except Exception:
                    pass
            if "min_p" in payload_obj:
                st.session_state["tab2_map_filter_min_p"] = _safe_float(payload_obj.get("min_p"), 0.0)
            if "max_p" in payload_obj:
                st.session_state["tab2_map_filter_max_p"] = _safe_float(payload_obj.get("max_p"), 0.0)
            if "min_sqw" in payload_obj:
                st.session_state["tab2_map_filter_min_sqw"] = _safe_float(payload_obj.get("min_sqw"), 0.0)
            if "max_sqw" in payload_obj:
                st.session_state["tab2_map_filter_max_sqw"] = _safe_float(payload_obj.get("max_sqw"), 0.0)
            if "min_sqm" in payload_obj:
                st.session_state["tab2_map_filter_min_sqm"] = _safe_float(payload_obj.get("min_sqm"), 0.0)
            if "max_sqm" in payload_obj:
                st.session_state["tab2_map_filter_max_sqm"] = _safe_float(payload_obj.get("max_sqm"), 0.0)
            if "only_with_proj" in payload_obj:
                st.session_state["tab2_map_filter_only_proj"] = bool(payload_obj["only_with_proj"])
                try:
                    if payload_obj["only_with_proj"]:
                        st.query_params["map_filter_only_proj"] = "1"
                    else:
                        st.query_params.pop("map_filter_only_proj", None)
                except Exception:
                    pass

            if "sales" in payload_obj and isinstance(payload_obj["sales"], list):
                st.session_state["tab2_map_filter_sales"] = payload_obj["sales"]
            if "min_puw" in payload_obj:
                st.session_state["tab2_map_filter_min_puw"] = _safe_float(payload_obj.get("min_puw"), 0.0)
            if "max_puw" in payload_obj:
                st.session_state["tab2_map_filter_max_puw"] = _safe_float(payload_obj.get("max_puw"), 0.0)
            if "min_pum" in payload_obj:
                st.session_state["tab2_map_filter_min_pum"] = _safe_float(payload_obj.get("min_pum"), 0.0)
            if "max_pum" in payload_obj:
                st.session_state["tab2_map_filter_max_pum"] = _safe_float(payload_obj.get("max_pum"), 0.0)

            if "floors" in payload_obj and isinstance(payload_obj["floors"], list):
                st.session_state["tab2_map_filter_floors"] = payload_obj["floors"]
            if "min_fl" in payload_obj:
                st.session_state["tab2_map_filter_min_fl"] = _safe_float(payload_obj.get("min_fl"), 0.0)
            if "max_fl" in payload_obj:
                st.session_state["tab2_map_filter_max_fl"] = _safe_float(payload_obj.get("max_fl"), 0.0)

            if "beds" in payload_obj and isinstance(payload_obj["beds"], list):
                st.session_state["tab2_map_filter_beds"] = payload_obj["beds"]
            if "baths" in payload_obj and isinstance(payload_obj["baths"], list):
                st.session_state["tab2_map_filter_baths"] = payload_obj["baths"]
            if "pkgs" in payload_obj and isinstance(payload_obj["pkgs"], list):
                st.session_state["tab2_map_filter_pkgs"] = payload_obj["pkgs"]
            if "max_age" in payload_obj:
                st.session_state["tab2_map_filter_max_age"] = _safe_float(payload_obj.get("max_age"), 0.0)

            if payload_obj.get("compare_active", True):
                st.session_state["tab2_compared_active"] = True

        else:
            q_prov = st.query_params.get("map_prov", None)
            if q_prov and str(q_prov).strip() not in ["ALL", "__ALL__", "all", "", "-"]:
                st.session_state["tab2_filter_provinces"] = [str(q_prov).strip()]
            elif q_prov in ["ALL", "__ALL__", "all", "-"]:
                st.session_state["tab2_filter_provinces"] = []
                st.session_state["tab2_filter_districts"] = []
                st.session_state["tab2_filter_subdistricts"] = []
                st.session_state["tab2_search_prop_id"] = ""
                st.session_state.pop("tab2_ref_prop", None)

            q_dist = st.query_params.get("map_dist", None)
            if st.session_state.get("tab2_filter_provinces") and q_dist and str(q_dist).strip() not in ["ALL", "__ALL__", "all", "", "-"]:
                st.session_state["tab2_filter_districts"] = [str(q_dist).strip()]
            elif q_dist in ["ALL", "__ALL__", "all", "-"]:
                st.session_state["tab2_filter_districts"] = []

            q_subdist = st.query_params.get("map_subdist", None)
            if st.session_state.get("tab2_filter_provinces") and st.session_state.get("tab2_filter_districts") and q_subdist and str(q_subdist).strip() not in ["ALL", "__ALL__", "all", "", "-"]:
                st.session_state["tab2_filter_subdistricts"] = [str(q_subdist).strip()]
            elif q_subdist in ["ALL", "__ALL__", "all", "-"]:
                st.session_state["tab2_filter_subdistricts"] = []

            q_lat = st.query_params.get("map_ref_lat")
            q_lon = st.query_params.get("map_ref_lon")
            if q_lat and q_lon:
                try:
                    active_ref_lat = float(q_lat)
                    active_ref_lon = float(q_lon)
                    st.session_state["tab2_ref_lat"] = active_ref_lat
                    st.session_state["tab2_ref_lon"] = active_ref_lon
                    st.session_state["tab2_compared_active"] = True
                except (ValueError, TypeError):
                    pass

            q_id = st.query_params.get("map_ref_id")
            if q_id and df_raw is not None and not df_raw.empty:
                clean_id = str(q_id).strip()
                st.session_state["tab2_search_prop_id"] = clean_id
                if "map_proj" not in st.query_params:
                    st.session_state["tab2_filter_projects"] = []
                f_prop = df_raw[df_raw['รหัสทรัพย์'].astype(str).str.strip().str.lower() == clean_id.lower()]
                if not f_prop.empty:
                    prop_row = f_prop.iloc[0]
                    active_ref_prop = prop_row.to_dict()
                    st.session_state["tab2_ref_prop"] = active_ref_prop
                    r_prov = str(prop_row.get('จังหวัด', '')).strip()
                    r_dist = str(prop_row.get('อำเภอ', '')).strip()
                    r_subdist = str(prop_row.get('ตำบล', '')).strip()
                    if r_prov and r_prov not in ['-', 'ไม่มีข้อมูล', 'nan']:
                        st.session_state["tab2_filter_provinces"] = [r_prov]
                    if r_dist and r_dist not in ['-', 'ไม่มีข้อมูล', 'nan']:
                        st.session_state["tab2_filter_districts"] = [r_dist]
                    if r_subdist and r_subdist not in ['-', 'ไม่มีข้อมูล', 'nan']:
                        st.session_state["tab2_filter_subdistricts"] = [r_subdist]

            has_loc_synced = (
                (q_prov is not None and str(q_prov).strip() not in ["", "ALL", "__ALL__", "all"]) or
                (q_dist is not None and str(q_dist).strip() not in ["", "ALL", "__ALL__", "all"]) or
                (q_subdist is not None and str(q_subdist).strip() not in ["", "ALL", "__ALL__", "all"]) or
                bool(q_id)
            )
            if has_loc_synced:
                st.session_state["tab2_compared_active"] = True

    # 1. Recovery of reference coordinates & radius from query_params or session_state
    q_lat_check = st.query_params.get("map_ref_lat")
    if q_lat_check:
        try:
            if float(q_lat_check) > 0 and "map_ref_cleared" in st.query_params:
                del st.query_params["map_ref_cleared"]
        except (ValueError, TypeError):
            pass

    if st.query_params.get("map_ref_cleared") == "1":
        active_ref_lat = 0.0
        active_ref_lon = 0.0
        active_ref_prop = None
        active_price_ref_prop = None
        st.session_state["tab2_ref_lat"] = 0.0
        st.session_state["tab2_ref_lon"] = 0.0
        st.session_state["tab2_ref_prop"] = None
        st.session_state["tab2_price_ref_prop"] = None
        st.session_state["tab2_price_center_id"] = ""
        st.session_state["tab2_compared_active"] = False
        try:
            del st.query_params["map_ref_cleared"]
        except Exception:
            pass
        try:
            del st.query_params["map_price_ref_id"]
        except Exception:
            pass
    else:
        try:
            q_lat = st.query_params.get("map_ref_lat")
            q_lon = st.query_params.get("map_ref_lon")
            if q_lat and q_lon and float(q_lat) > 0 and float(q_lon) > 0:
                active_ref_lat = float(q_lat)
                active_ref_lon = float(q_lon)
                st.session_state["tab2_ref_lat"] = active_ref_lat
                st.session_state["tab2_ref_lon"] = active_ref_lon
            q_rad = st.query_params.get("map_ref_radius")
            if q_rad and float(q_rad) > 0:
                active_ref_radius = float(q_rad)
                st.session_state["tab2_ref_radius"] = active_ref_radius
        except (ValueError, TypeError):
            pass

    if not active_ref_lat or not active_ref_lon or float(active_ref_lat) <= 0 or float(active_ref_lon) <= 0:
        s_lat = float(st.session_state.get("tab2_ref_lat") or 0.0)
        s_lon = float(st.session_state.get("tab2_ref_lon") or 0.0)
        if s_lat > 0 and s_lon > 0:
            active_ref_lat = s_lat
            active_ref_lon = s_lon

    if not active_ref_radius or float(active_ref_radius) <= 0:
        active_ref_radius = float(st.session_state.get("tab2_ref_radius") or 5.0)

    q_comp = st.query_params.get("map_compare_ids")
    if q_comp and str(q_comp).strip():
        st.session_state["tab2_compare_ids"] = [x.strip() for x in str(q_comp).split(",") if x.strip()]

    # Auto-resolve active_ref_prop if present in query params or session state
    q_id = st.query_params.get("map_ref_id") or st.session_state.get("tab2_search_prop_id")
    if q_id and df_raw is not None and not df_raw.empty:
        clean_id = str(q_id).strip()
        if active_ref_prop is None or str(active_ref_prop.get('รหัสทรัพย์', '')).strip().lower() != clean_id.lower():
            found = df_raw[df_raw['รหัสทรัพย์'].astype(str).str.strip().str.lower() == clean_id.lower()]
            if not found.empty:
                active_ref_prop = found.iloc[0].to_dict()
                st.session_state["tab2_ref_prop"] = active_ref_prop
                st.session_state["tab2_search_prop_id"] = clean_id
    elif not q_id and not st.session_state.get("tab2_search_prop_id"):
        active_ref_prop = None
        st.session_state["tab2_search_prop_id"] = ""
        st.session_state.pop("tab2_ref_prop", None)

    # Auto-resolve active_price_ref_prop if present in query params or session state
    if st.session_state.get("tab2_just_reset_price_center"):
        st.session_state["tab2_just_reset_price_center"] = False
        active_price_ref_prop = None
        st.session_state["tab2_price_center_id"] = ""
        st.session_state.pop("tab2_price_ref_prop", None)
        try:
            st.query_params.pop("map_price_ref_id", None)
        except Exception:
            pass
    else:
        q_price_id = st.query_params.get("map_price_ref_id") or st.session_state.get("tab2_price_center_id")
        if q_price_id and df_raw is not None and not df_raw.empty:
            clean_price_id = str(q_price_id).strip()
            if active_price_ref_prop is None or str(active_price_ref_prop.get('รหัสทรัพย์', '')).strip().lower() != clean_price_id.lower():
                found_p = df_raw[df_raw['รหัสทรัพย์'].astype(str).str.strip().str.lower() == clean_price_id.lower()]
                if not found_p.empty:
                    active_price_ref_prop = found_p.iloc[0].to_dict()
                    st.session_state["tab2_price_ref_prop"] = active_price_ref_prop
                    st.session_state["tab2_price_center_id"] = clean_price_id
        elif not q_price_id and not st.session_state.get("tab2_price_center_id"):
            active_price_ref_prop = None
            st.session_state["tab2_price_center_id"] = ""
            st.session_state.pop("tab2_price_ref_prop", None)

    # 2. Extract and resolve all current map filters
    q_prov = st.query_params.get("map_prov", None)
    if q_prov and str(q_prov).strip() not in ["ALL", "__ALL__", "all", "", "-"]:
        active_prov = [str(q_prov).strip()]
        st.session_state["tab2_filter_provinces"] = active_prov
    elif q_prov in ["ALL", "__ALL__", "all", "-"]:
        active_prov = []
        st.session_state["tab2_filter_provinces"] = []
    else:
        active_prov = st.session_state.get("tab2_filter_provinces", [])

    q_dist = st.query_params.get("map_dist", None)
    if active_prov and q_dist and str(q_dist).strip() not in ["ALL", "__ALL__", "all", "", "-"]:
        active_dist = [str(q_dist).strip()]
        st.session_state["tab2_filter_districts"] = active_dist
    elif q_dist in ["ALL", "__ALL__", "all", "-"]:
        active_dist = []
        st.session_state["tab2_filter_districts"] = []
    else:
        active_dist = st.session_state.get("tab2_filter_districts", []) if active_prov else []

    q_subdist = st.query_params.get("map_subdist", None)
    if active_prov and active_dist and q_subdist and str(q_subdist).strip() not in ["ALL", "__ALL__", "all", "", "-"]:
        active_subdist = [str(q_subdist).strip()]
        st.session_state["tab2_filter_subdistricts"] = active_subdist
    elif q_subdist in ["ALL", "__ALL__", "all", "-"]:
        active_subdist = []
        st.session_state["tab2_filter_subdistricts"] = []
    else:
        active_subdist = st.session_state.get("tab2_filter_subdistricts", []) if (active_prov and active_dist) else []

    q_proj = st.query_params.get("map_proj", None)
    if q_proj and str(q_proj).strip() not in ["ALL", "__ALL__", "all", ""]:
        active_proj = str(q_proj).strip()
    else:
        proj_list = st.session_state.get("tab2_filter_projects", [])
        active_proj = ",".join(proj_list) if proj_list else None

    if "tab2_map_filter_cos" in st.session_state:
        map_cos = st.session_state.get("tab2_map_filter_cos", [])
    else:
        raw_cos = st.query_params.get("map_filter_cos", "")
        map_cos = [c.strip() for c in raw_cos.split(",") if c.strip()] if raw_cos else []

    if "tab2_map_filter_only_proj" in st.session_state:
        q_only_proj = bool(st.session_state.get("tab2_map_filter_only_proj", False))
    else:
        q_only_proj = st.query_params.get("map_filter_only_proj", "0") in ["1", "true", "True"]

    if "tab2_map_filter_types" in st.session_state:
        map_types = st.session_state.get("tab2_map_filter_types", [])
    else:
        raw_types = st.query_params.get("map_filter_types", "")
        map_types = [t.strip() for t in raw_types.split(",") if t.strip()] if raw_types else []

    raw_sales = st.query_params.get("map_filter_sales", "")
    map_sales = [s.strip() for s in raw_sales.split(",") if s.strip()] if raw_sales else st.session_state.get("tab2_map_filter_sales", [])

    try:
        map_min_p = float(st.query_params.get("map_filter_min_p", 0)) or float(st.session_state.get("tab2_map_filter_min_p", 0.0))
    except (ValueError, TypeError):
        map_min_p = float(st.session_state.get("tab2_map_filter_min_p", 0.0))

    try:
        map_max_p = float(st.query_params.get("map_filter_max_p", 0)) or float(st.session_state.get("tab2_map_filter_max_p", 0.0))
    except (ValueError, TypeError):
        map_max_p = float(st.session_state.get("tab2_map_filter_max_p", 0.0))

    try:
        map_min_sqw = float(st.query_params.get("map_filter_min_sqw", 0)) or float(st.session_state.get("tab2_map_filter_min_sqw", 0.0))
    except (ValueError, TypeError):
        map_min_sqw = float(st.session_state.get("tab2_map_filter_min_sqw", 0.0))

    try:
        map_max_sqw = float(st.query_params.get("map_filter_max_sqw", 0)) or float(st.session_state.get("tab2_map_filter_max_sqw", 0.0))
    except (ValueError, TypeError):
        map_max_sqw = float(st.session_state.get("tab2_map_filter_max_sqw", 0.0))

    try:
        map_min_sqm = float(st.query_params.get("map_filter_min_sqm", 0)) or float(st.session_state.get("tab2_map_filter_min_sqm", 0.0))
    except (ValueError, TypeError):
        map_min_sqm = float(st.session_state.get("tab2_map_filter_min_sqm", 0.0))

    try:
        map_max_sqm = float(st.query_params.get("map_filter_max_sqm", 0)) or float(st.session_state.get("tab2_map_filter_max_sqm", 0.0))
    except (ValueError, TypeError):
        map_max_sqm = float(st.session_state.get("tab2_map_filter_max_sqm", 0.0))

    try:
        map_min_puw = float(st.query_params.get("map_filter_min_puw", 0)) or float(st.session_state.get("tab2_map_filter_min_puw", 0.0))
    except (ValueError, TypeError):
        map_min_puw = float(st.session_state.get("tab2_map_filter_min_puw", 0.0))

    try:
        map_max_puw = float(st.query_params.get("map_filter_max_puw", 0)) or float(st.session_state.get("tab2_map_filter_max_puw", 0.0))
    except (ValueError, TypeError):
        map_max_puw = float(st.session_state.get("tab2_map_filter_max_puw", 0.0))

    try:
        map_min_pum = float(st.query_params.get("map_filter_min_pum", 0)) or float(st.session_state.get("tab2_map_filter_min_pum", 0.0))
    except (ValueError, TypeError):
        map_min_pum = float(st.session_state.get("tab2_map_filter_min_pum", 0.0))

    try:
        map_max_pum = float(st.query_params.get("map_filter_max_pum", 0)) or float(st.session_state.get("tab2_map_filter_max_pum", 0.0))
    except (ValueError, TypeError):
        map_max_pum = float(st.session_state.get("tab2_map_filter_max_pum", 0.0))

    map_floors = st.session_state.get("tab2_map_filter_floors", [])
    map_min_fl = float(st.session_state.get("tab2_map_filter_min_fl", 0.0))
    map_max_fl = float(st.session_state.get("tab2_map_filter_max_fl", 0.0))
    map_beds = st.session_state.get("tab2_map_filter_beds", [])
    map_baths = st.session_state.get("tab2_map_filter_baths", [])
    map_pkgs = st.session_state.get("tab2_map_filter_pkgs", [])
    map_max_age = float(st.session_state.get("tab2_map_filter_max_age", 0.0))

    pin_mode = st.session_state.get("tab2_pin_mode") or st.query_params.get("map_pin_mode", "radius")
    has_ref_point = bool(active_ref_lat and active_ref_lon and float(active_ref_lat) > 0 and float(active_ref_lon) > 0)
    has_loc_filter = bool(active_prov or active_dist or active_subdist or active_proj)
    active_compare_ids = st.session_state.get("tab2_compare_ids", [])

    has_any_filter = bool(
        has_ref_point or
        has_loc_filter or
        map_cos or
        q_only_proj or
        map_types or
        map_sales or
        (map_min_p > 0) or
        (map_max_p > 0) or
        (map_min_sqw > 0) or
        (map_max_sqw > 0) or
        (map_min_sqm > 0) or
        (map_max_sqm > 0) or
        (map_min_puw > 0) or
        (map_max_puw > 0) or
        (map_min_pum > 0) or
        (map_max_pum > 0) or
        map_floors or
        (map_min_fl > 0) or
        (map_max_fl > 0) or
        map_beds or
        map_baths or
        map_pkgs or
        (map_max_age > 0) or
        bool(active_compare_ids) or
        (active_ref_prop is not None)
    )

    # 3. Compute matching count and summary labels for Filter Status Bar (aligned with Comparison Mode)
    status_df = df_raw if df_raw is not None else pd.DataFrame()
    is_comparison_active = False
    if active_compare_ids and df_raw is not None and not df_raw.empty and 'รหัสทรัพย์' in df_raw.columns:
        cids_set = {str(x).strip().lower() for x in active_compare_ids if str(x).strip()}
        if cids_set:
            comp_match = df_raw[df_raw['รหัสทรัพย์'].astype(str).str.strip().str.lower().isin(cids_set)]
            if not comp_match.empty:
                status_df = comp_match.copy().reset_index(drop=True)
                is_comparison_active = True

    if not is_comparison_active and has_any_filter and not status_df.empty:
        if active_proj:
            p_list = [p.strip() for p in active_proj.split(",") if p.strip()]
            status_df = status_df[_match_project_mask(status_df, p_list)]
            if active_prov and 'จังหวัด' in status_df.columns:
                status_df = status_df[status_df['จังหวัด'].astype(str).str.strip().isin(active_prov)]
            if active_dist and 'อำเภอ' in status_df.columns:
                clean_target_dists = [d.split(' (')[0].strip() for d in active_dist]
                status_df = status_df[status_df['อำเภอ'].astype(str).str.strip().isin(clean_target_dists)]
            if active_subdist and 'ตำบล' in status_df.columns:
                clean_target_subs = [s.split(' (')[0].strip() for s in active_subdist]
                status_df = status_df[status_df['ตำบล'].astype(str).str.strip().isin(clean_target_subs)]
        elif has_ref_point and (pin_mode == 'radius' or not has_loc_filter):
            status_df = find_nearby_properties(active_ref_lat, active_ref_lon, status_df, active_ref_radius)
        elif active_prov:
            if 'จังหวัด' in status_df.columns:
                status_df = status_df[status_df['จังหวัด'].astype(str).str.strip().isin(active_prov)]
            if active_dist and 'อำเภอ' in status_df.columns:
                clean_target_dists = [d.split(' (')[0].strip() for d in active_dist]
                status_df = status_df[status_df['อำเภอ'].astype(str).str.strip().isin(clean_target_dists)]
            if active_subdist and 'ตำบล' in status_df.columns:
                clean_target_subs = [s.split(' (')[0].strip() for s in active_subdist]
                status_df = status_df[status_df['ตำบล'].astype(str).str.strip().isin(clean_target_subs)]
        else:
            # Nationwide fallback: keep all properties matching active in-map filters
            pass

        if not status_df.empty:
            if map_cos and 'บริษัท' in status_df.columns:
                status_df = status_df[status_df['บริษัท'].isin(map_cos)]
            if map_types and 'ประเภททรัพย์' in status_df.columns:
                status_df = status_df[status_df['ประเภททรัพย์'].isin(map_types)]
            if map_sales:
                col_sale = 'ประเภทการขาย' if 'ประเภทการขาย' in status_df.columns else ('สถานะ' if 'สถานะ' in status_df.columns else None)
                if col_sale:
                    status_df = status_df[status_df[col_sale].isin(map_sales)]
            if map_min_p > 0 and 'ราคา' in status_df.columns:
                status_df = status_df[status_df['ราคา'] >= map_min_p]
            if map_max_p > 0 and 'ราคา' in status_df.columns:
                status_df = status_df[status_df['ราคา'] <= map_max_p]
            if map_min_sqw > 0 or map_max_sqw > 0:
                if 'พื้นที่_ตารางวา' in status_df.columns:
                    sqw_s = pd.to_numeric(status_df['พื้นที่_ตารางวา'], errors='coerce')
                    if 'เนื้อที่ (ตร.ว.)' in status_df.columns and sqw_s.isna().any():
                        na_idx = sqw_s[sqw_s.isna()].index
                        sqw_s.loc[na_idx] = status_df.loc[na_idx, 'เนื้อที่ (ตร.ว.)'].apply(to_float_sqwah)
                elif 'เนื้อที่ (ตร.ว.)' in status_df.columns:
                    sqw_s = status_df['เนื้อที่ (ตร.ว.)'].apply(to_float_sqwah)
                else:
                    sqw_s = None
                if sqw_s is not None:
                    sqw_mask = pd.Series(True, index=status_df.index)
                    if map_min_sqw > 0:
                        sqw_mask = sqw_mask & (sqw_s >= map_min_sqw)
                    if map_max_sqw > 0:
                        sqw_mask = sqw_mask & (sqw_s <= map_max_sqw)
                    status_df = status_df[sqw_mask]
            if (map_min_sqm > 0 or map_max_sqm > 0) and 'พื้นที่ใช้สอย (ตร.ม.)' in status_df.columns:
                sqm_s = pd.to_numeric(status_df['พื้นที่ใช้สอย (ตร.ม.)'], errors='coerce')
                if sqm_s.isna().any():
                    na_idx = sqm_s[sqm_s.isna()].index
                    sqm_s.loc[na_idx] = status_df.loc[na_idx, 'พื้นที่ใช้สอย (ตร.ม.)'].apply(to_float_sqm)
                sqm_mask = pd.Series(True, index=status_df.index)
                if map_min_sqm > 0:
                    sqm_mask = sqm_mask & (sqm_s >= map_min_sqm)
                if map_max_sqm > 0:
                    sqm_mask = sqm_mask & (sqm_s <= map_max_sqm)
                status_df = status_df[sqm_mask]

            if map_min_puw > 0 or map_max_puw > 0:
                col_puw = 'ราคาต่อตารางวา' if 'ราคาต่อตารางวา' in status_df.columns else None
                p_vals = pd.to_numeric(status_df['ราคา'], errors='coerce')
                if 'พื้นที่_ตารางวา' in status_df.columns:
                    sqw_vals = pd.to_numeric(status_df['พื้นที่_ตารางวา'], errors='coerce')
                elif 'เนื้อที่ (ตร.ว.)' in status_df.columns:
                    sqw_vals = status_df['เนื้อที่ (ตร.ว.)'].apply(to_float_sqwah)
                else:
                    sqw_vals = pd.Series(np.nan, index=status_df.index)
                puw_calc = pd.to_numeric(status_df[col_puw], errors='coerce') if col_puw else pd.Series(np.nan, index=status_df.index)
                fallback_puw = np.where((p_vals > 0) & (sqw_vals > 0), p_vals / sqw_vals, np.nan)
                puw_final = pd.Series(np.where(puw_calc > 0, puw_calc, fallback_puw), index=status_df.index)
                puw_mask = pd.Series(True, index=status_df.index)
                if map_min_puw > 0:
                    puw_mask = puw_mask & (puw_final >= map_min_puw)
                if map_max_puw > 0:
                    puw_mask = puw_mask & (puw_final <= map_max_puw)
                status_df = status_df[puw_mask]

            if map_min_pum > 0 or map_max_pum > 0:
                col_pum = 'ราคาต่อตารางเมตร' if 'ราคาต่อตารางเมตร' in status_df.columns else None
                p_vals = pd.to_numeric(status_df['ราคา'], errors='coerce')
                sqm_vals = pd.to_numeric(status_df['พื้นที่ใช้สอย (ตร.ม.)'], errors='coerce') if 'พื้นที่ใช้สอย (ตร.ม.)' in status_df.columns else pd.Series(np.nan, index=status_df.index)
                pum_calc = pd.to_numeric(status_df[col_pum], errors='coerce') if col_pum else pd.Series(np.nan, index=status_df.index)
                fallback_pum = np.where((p_vals > 0) & (sqm_vals > 0), p_vals / sqm_vals, np.nan)
                pum_final = pd.Series(np.where(pum_calc > 0, pum_calc, fallback_pum), index=status_df.index)
                pum_mask = pd.Series(True, index=status_df.index)
                if map_min_pum > 0:
                    pum_mask = pum_mask & (pum_final >= map_min_pum)
                if map_max_pum > 0:
                    pum_mask = pum_mask & (pum_final <= map_max_pum)
                status_df = status_df[pum_mask]

            if (map_floors or map_min_fl > 0 or map_max_fl > 0) and 'ชั้น' in status_df.columns and not status_df.empty:
                fl_s = status_df['ชั้น']
                fl_num = pd.to_numeric(fl_s, errors='coerce')
                fl_str = fl_s.astype(str)
                needs_ex = fl_num.isna() & fl_str.str.contains(r'\d', na=False)
                extracted_fl = pd.to_numeric(fl_str[needs_ex].str.extract(r'(\d+(?:\.\d+)?)', expand=False), errors='coerce')
                fl_val = np.where(fl_num.notna() & (fl_num >= 0), fl_num, -1.0)
                fl_val[needs_ex.values] = np.where(extracted_fl.notna() & (extracted_fl >= 0), extracted_fl, -1.0)
                fl_series = pd.Series(fl_val, index=status_df.index)

                fl_mask = pd.Series(False, index=status_df.index)
                if map_floors:
                    if 'none' in map_floors:
                        fl_mask = fl_mask | (fl_series < 0)
                    if '1' in map_floors:
                        fl_mask = fl_mask | ((fl_series >= 1) & (fl_series < 2))
                    if '2' in map_floors:
                        fl_mask = fl_mask | ((fl_series >= 2) & (fl_series < 3))
                    if '3' in map_floors:
                        fl_mask = fl_mask | ((fl_series >= 3) & (fl_series < 4))
                    if '4+' in map_floors:
                        fl_mask = fl_mask | (fl_series >= 4)
                else:
                    fl_mask = pd.Series(True, index=status_df.index)
                if map_min_fl > 0:
                    fl_mask = fl_mask & (fl_series >= map_min_fl)
                if map_max_fl > 0:
                    fl_mask = fl_mask & (fl_series >= 0) & (fl_series <= map_max_fl)
                status_df = status_df[fl_mask]

            if map_beds and 'ห้องนอน' in status_df.columns and not status_df.empty:
                bed_s = status_df['ห้องนอน']
                bed_num = pd.to_numeric(bed_s, errors='coerce')
                is_std = bed_s.astype(str).str.contains('สตูดิโอ|studio', case=False, na=False)
                bed_val = np.where(is_std, 0.0, np.where(bed_num.notna() & (bed_num >= 0), bed_num, -1.0))
                bed_series = pd.Series(bed_val, index=status_df.index)

                bed_mask = pd.Series(False, index=status_df.index)
                if 'none' in map_beds:
                    bed_mask = bed_mask | (bed_series < 0)
                if '0' in map_beds:
                    bed_mask = bed_mask | (bed_series == 0)
                for n in [1, 2, 3, 4]:
                    if str(n) in map_beds:
                        bed_mask = bed_mask | (bed_series.round() == n)
                if '5+' in map_beds:
                    bed_mask = bed_mask | (bed_series >= 5)
                status_df = status_df[bed_mask]

            if map_baths and 'ห้องน้ำ' in status_df.columns and not status_df.empty:
                bath_s = status_df['ห้องน้ำ']
                bath_num = pd.to_numeric(bath_s, errors='coerce')
                bath_val = np.where(bath_num.notna() & (bath_num >= 0), bath_num, -1.0)
                bath_series = pd.Series(bath_val, index=status_df.index)

                bath_mask = pd.Series(False, index=status_df.index)
                if 'none' in map_baths:
                    bath_mask = bath_mask | (bath_series < 0)
                for n in [1, 2, 3, 4]:
                    if str(n) in map_baths:
                        bath_mask = bath_mask | (bath_series.round() == n)
                if '5+' in map_baths:
                    bath_mask = bath_mask | (bath_series >= 5)
                status_df = status_df[bath_mask]

            if map_pkgs and 'ที่จอดรถ' in status_df.columns and not status_df.empty:
                pkg_s = status_df['ที่จอดรถ']
                pkg_num = pd.to_numeric(pkg_s, errors='coerce')
                pkg_val = np.where(pkg_num.notna() & (pkg_num >= 0), pkg_num, -1.0)
                pkg_series = pd.Series(pkg_val, index=status_df.index)

                pkg_mask = pd.Series(False, index=status_df.index)
                if 'none' in map_pkgs:
                    pkg_mask = pkg_mask | (pkg_series < 0)
                for n in [1, 2, 3]:
                    if str(n) in map_pkgs:
                        pkg_mask = pkg_mask | (pkg_series.round() == n)
                if '4+' in map_pkgs:
                    pkg_mask = pkg_mask | (pkg_series >= 4)
                status_df = status_df[pkg_mask]

            if map_max_age > 0 and 'วันประกาศ' in status_df.columns and not status_df.empty:
                u_ann = status_df['วันประกาศ'].dropna().unique()
                age_map = {u: parse_listing_age_days(u) for u in u_ann}
                age_series = status_df['วันประกาศ'].map(age_map).fillna(-1.0).copy()
                if 'วันที่ขาย' in status_df.columns and 'บริษัท' in status_df.columns:
                    is_legal = status_df['บริษัท'].astype(str).str.strip().str.upper().isin(['LED LEGAL', 'LED_LEGAL', 'LED_SOLD'])
                    has_sold = status_df['วันที่ขาย'].notna() & (status_df['วันที่ขาย'].astype(str).str.strip() != '') & (status_df['วันที่ขาย'].astype(str).str.strip() != '-')
                    l_mask = is_legal & has_sold & status_df['วันประกาศ'].notna()
                    if l_mask.any():
                        for idx_row, r_row in status_df.loc[l_mask, ['วันประกาศ', 'วันที่ขาย']].iterrows():
                            s_dt = _parse_sold_date_value(r_row['วันที่ขาย'])
                            if pd.notna(s_dt):
                                d_diff = parse_listing_age_days(r_row['วันประกาศ'], ref_date=s_dt.date())
                                if d_diff >= 0:
                                    age_series.at[idx_row] = d_diff
                status_df = status_df[(age_series >= 0) & (age_series <= map_max_age)]

            if q_only_proj:
                proj_col = 'ชื่อโครงการ' if 'ชื่อโครงการ' in status_df.columns else None
                if proj_col:
                    valid_proj_mask = (
                        status_df[proj_col].notna() &
                        (status_df[proj_col].astype(str).str.strip().str.len() > 1) &
                        (~status_df[proj_col].astype(str).str.strip().isin(['-', 'ไม่มีข้อมูล', 'ไม่ระบุ', 'ว่าง', 'โครงการ', 'ห้องชุด', 'อาคารชุด', 'บ้านพักอาศัย', 'null', 'None']))
                    )
                    status_df = status_df[valid_proj_mask]

                    if map_cos and len(map_cos) >= 2 and 'บริษัท' in status_df.columns:
                        df_cos_proj = status_df[status_df['บริษัท'].isin(map_cos)].copy()
                        if 'norm_project_name' in df_cos_proj.columns:
                            df_cos_proj['_norm_p'] = df_cos_proj['norm_project_name']
                        else:
                            df_cos_proj['_norm_p'] = df_cos_proj[proj_col].apply(normalize_project_name)
                        proj_company_counts = df_cos_proj.groupby('_norm_p', observed=False)['บริษัท'].nunique()

                        req_count = 2
                        shared_norms = set(proj_company_counts[proj_company_counts >= req_count].index)
                        norm_s = status_df['norm_project_name'] if 'norm_project_name' in status_df.columns else status_df[proj_col].apply(normalize_project_name)
                        status_df = status_df[norm_s.isin(shared_norms)]

        status_df = status_df.copy().reset_index(drop=True)

    matched_count = len(status_df)

    # Human-readable labels
    if active_proj:
        loc_str = f"โครงการ: {active_proj}"
        if active_prov:
            clean_d = active_dist[0].split(' (')[0].strip() if active_dist else ""
            clean_s = active_subdist[0].split(' (')[0].strip() if active_subdist else ""
            loc_parts = [f"จ.{active_prov[0]}"]
            if clean_d:
                loc_parts.append(f"อ.{clean_d}")
            if clean_s:
                loc_parts.append(f"ต.{clean_s}")
            loc_str += f" ({' > '.join(loc_parts)})"
    elif has_ref_point and (pin_mode == 'radius' or not has_loc_filter):
        if active_subdist:
            clean_s = active_subdist[0].split(' (')[0].strip()
            clean_d = active_dist[0].split(' (')[0].strip() if active_dist else "-"
            loc_str = f"จุดศูนย์กลาง: จ.{active_prov[0] if active_prov else '-'} > อ.{clean_d} > ต.{clean_s}"
        elif active_dist:
            clean_d = active_dist[0].split(' (')[0].strip()
            loc_str = f"จุดศูนย์กลาง: จ.{active_prov[0] if active_prov else '-'} > อ.{clean_d}"
        elif active_prov:
            loc_str = f"จุดศูนย์กลาง: จ.{active_prov[0]}"
        else:
            loc_str = "ตามพิกัดจุดอ้างอิง (ครอบคลุมตามรัศมี)"
    elif active_subdist:
        clean_s = active_subdist[0].split(' (')[0].strip()
        clean_d = active_dist[0].split(' (')[0].strip() if active_dist else "-"
        loc_str = f"จ.{active_prov[0] if active_prov else '-'} > อ.{clean_d} > ต.{clean_s}"
    elif active_dist:
        clean_d = active_dist[0].split(' (')[0].strip()
        loc_str = f"จ.{active_prov[0] if active_prov else '-'} > อ.{clean_d}"
    elif active_prov:
        loc_str = f"จ.{active_prov[0]}"
    elif q_only_proj and map_cos and len(map_cos) >= 2:
        loc_str = f"โครงการร่วมกัน ({' + '.join(map_cos)}) ทั่วประเทศ"
    else:
        loc_str = "ทุกทำเล (ทั่วประเทศ)"

    if has_ref_point:
        if active_ref_prop is not None:
            rad_str = f"{active_ref_radius:.1f} กม. รอบ [{active_ref_prop.get('บริษัท', '-')}] {active_ref_prop.get('รหัสทรัพย์', '')}"
        else:
            rad_str = f"{active_ref_radius:.1f} กม. ({active_ref_lat:.4f}, {active_ref_lon:.4f})"
    else:
        rad_str = f"รัศมี {active_ref_radius:.1f} กม. (ยังไม่ได้ปักหมุด)"

    if q_only_proj and map_cos and len(map_cos) >= 2:
        cos_str = f"{', '.join(map_cos)} (โครงการร่วมกัน)"
    elif q_only_proj:
        cos_str = f"{', '.join(map_cos)} (เฉพาะมีโครงการ)" if map_cos else "ทุกบริษัท (เฉพาะมีโครงการ)"
    else:
        cos_str = f"{', '.join(map_cos)} ({len(map_cos)} บริษัท)" if map_cos else "ทุกบริษัท"
    types_str = f"{', '.join(map_types)}" if map_types else "ทุกประเภททรัพย์"

    if map_min_p > 0 and map_max_p > 0:
        price_str = f"฿{format_price_kpi(map_min_p)} - ฿{format_price_kpi(map_max_p)}"
    elif map_min_p > 0:
        price_str = f">= ฿{format_price_kpi(map_min_p)}"
    elif map_max_p > 0:
        price_str = f"<= ฿{format_price_kpi(map_max_p)}"
    else:
        price_str = "ทุกช่วงราคา"

    area_parts = []
    if map_min_sqw > 0 or map_max_sqw > 0:
        area_parts.append(f"{map_min_sqw:,.0f}-{map_max_sqw:,.0f} ตร.ว." if map_max_sqw > 0 else f">= {map_min_sqw:,.0f} ตร.ว.")
    if map_min_sqm > 0 or map_max_sqm > 0:
        area_parts.append(f"{map_min_sqm:,.0f}-{map_max_sqm:,.0f} ตร.ม." if map_max_sqm > 0 else f">= {map_min_sqm:,.0f} ตร.ม.")
    area_str = " / ".join(area_parts) if area_parts else "ทุกขนาด (ทุก Plan)"

    floor_parts = []
    if map_floors:
        fl_map_lbl = {'1': '1 ชั้น', '2': '2 ชั้น', '3': '3 ชั้น', '4+': '4+ ชั้น', 'none': 'ไม่ระบุ'}
        floor_parts.append(", ".join(fl_map_lbl.get(c, c) for c in map_floors))
    if map_min_fl > 0 and map_max_fl > 0:
        floor_parts.append(f"ชั้น {map_min_fl:,.0f}-{map_max_fl:,.0f}")
    elif map_min_fl > 0:
        floor_parts.append(f">= ชั้น {map_min_fl:,.0f}")
    elif map_max_fl > 0:
        floor_parts.append(f"<= ชั้น {map_max_fl:,.0f}")
    floor_str = " / ".join(floor_parts) if floor_parts else "ทุกชั้น"

    spec_parts = []
    if map_beds:
        b_lbl = {'0': 'สตูดิโอ', '1': '1 นอน', '2': '2 นอน', '3': '3 นอน', '4': '4 นอน', '5+': '5+ นอน', 'none': 'นอน(ไม่ระบุ)'}
        spec_parts.append(", ".join(b_lbl.get(b, b) for b in map_beds))
    if map_baths:
        ba_lbl = {'1': '1 น้ำ', '2': '2 น้ำ', '3': '3 น้ำ', '4': '4 น้ำ', '5+': '5+ น้ำ', 'none': 'น้ำ(ไม่ระบุ)'}
        spec_parts.append(", ".join(ba_lbl.get(b, b) for b in map_baths))
    if map_pkgs:
        pk_lbl = {'1': '1 จอด', '2': '2 จอด', '3': '3 จอด', '4+': '4+ จอด', 'none': 'จอด(ไม่ระบุ)'}
        spec_parts.append(", ".join(pk_lbl.get(p, p) for p in map_pkgs))
    spec_str = " · ".join(spec_parts) if spec_parts else "ทุกสเปกห้อง/ที่จอด"

    if map_max_age > 0:
        if map_max_age >= 365:
            age_str = f"<= {map_max_age/365:,.1f} ปี" if map_max_age % 365 != 0 else f"<= {int(map_max_age/365)} ปี"
        else:
            age_str = f"<= {int(map_max_age)} วัน"
    else:
        age_str = "ทุกระยะเวลา"

    mode_badge_lbl = "ตามรัศมี (Radius)" if (has_ref_point and pin_mode == 'radius') else "ตามทำเล (Location)"

    # Theme colors for status card
    card_bg = "rgba(2, 44, 34, 0.45)" if is_dark_mode else "#f8fafc"
    card_border = "rgba(52, 211, 153, 0.35)" if is_dark_mode else "#e2e8f0"
    chip_bg = "rgba(2, 44, 34, 0.7)" if is_dark_mode else "#ffffff"
    chip_border = "rgba(52, 211, 153, 0.25)" if is_dark_mode else "#e2e8f0"
    text_c = "#f1f5f9" if is_dark_mode else "#1e293b"
    sub_c = "#94a3b8" if is_dark_mode else "#64748b"

    # --- RENDER FILTER STATUS BANNER (นอกแผนที่ ข้างใต้แผนที่) ---
    st.markdown(f"""
    <div id='ref-analytics-section' style='height: 0px; margin: 0px; padding: 0px; scroll-margin-top: 80px;'></div>
    <div id="map-active-filters-banner" style="background: {card_bg}; border: 1.5px solid {card_border}; border-radius: 14px; padding: 12px 16px; margin-top: -18px; margin-bottom: 12px; position: relative; z-index: 10; box-shadow: 0 4px 14px rgba(0,0,0,0.04);">
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid {chip_border};">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="background: linear-gradient(135deg, #059669, #10b981); color: #ffffff; padding: 3px 10px; border-radius: 6px; font-size: 0.78rem; font-weight: 800; display: inline-flex; align-items: center; gap: 5px;">
                    <i class="fa-solid fa-sliders"></i> สถานะตัวกรองแผนที่ (Active Map Filters)
                </span>
                <span style="font-size: 0.82rem; font-weight: 700; color: #10b981;" id="active-filter-mode-val">
                    โหมด: <b>{mode_badge_lbl}</b>
                </span>
            </div>
            <div style="font-size: 0.82rem; font-weight: 700; color: #059669; background: rgba(16, 185, 129, 0.12); padding: 3px 10px; border-radius: 20px; display: inline-flex; align-items: center; gap: 5px;" id="active-filter-count-val">
                <i class="fa-solid fa-layer-group"></i> ทรัพย์ที่ตรงเงื่อนไข: <b>{matched_count:,}</b> รายการ
            </div>
        </div>
        <div style="display: flex; flex-wrap: wrap; gap: 6px; align-items: center;">
            <div style="background: {chip_bg}; border: 1px solid {chip_border}; border-radius: 8px; padding: 5px 11px; display: inline-flex; align-items: center; gap: 6px; flex: 0 0 auto; max-width: 100%; box-sizing: border-box;" title="ทำเล (Location)">
                <i class="fa-solid fa-location-dot" style="color: #10b981; font-size: 0.86rem; flex-shrink: 0;"></i>
                <span id="active-filter-loc-val" style="font-size: 0.81rem; font-weight: 700; color: {text_c}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 320px;">
                    {html.escape(str(loc_str))}
                </span>
            </div>
            <div style="background: {chip_bg}; border: 1px solid {chip_border}; border-radius: 8px; padding: 5px 11px; display: inline-flex; align-items: center; gap: 6px; flex: 0 0 auto; box-sizing: border-box;" title="รัศมีตรวจ (Radius)">
                <i class="fa-solid fa-bullseye" style="color: #06b6d4; font-size: 0.86rem; flex-shrink: 0;"></i>
                <span id="active-filter-rad-val" style="font-size: 0.81rem; font-weight: 700; color: {text_c}; white-space: nowrap;">
                    {html.escape(str(rad_str))}
                </span>
            </div>
            <div style="background: {chip_bg}; border: 1px solid {chip_border}; border-radius: 8px; padding: 5px 11px; display: inline-flex; align-items: center; gap: 6px; flex: 0 0 auto; box-sizing: border-box;" title="บริษัท (Company)">
                <i class="fa-solid fa-building" style="color: #3b82f6; font-size: 0.86rem; flex-shrink: 0;"></i>
                <span id="active-filter-co-val" style="font-size: 0.81rem; font-weight: 700; color: {text_c}; white-space: nowrap;">
                    {html.escape(str(cos_str))}
                </span>
            </div>
            <div style="background: {chip_bg}; border: 1px solid {chip_border}; border-radius: 8px; padding: 5px 11px; display: inline-flex; align-items: center; gap: 6px; flex: 0 0 auto; box-sizing: border-box;" title="ประเภททรัพย์ (Type)">
                <i class="fa-solid fa-house" style="color: #f59e0b; font-size: 0.86rem; flex-shrink: 0;"></i>
                <span id="active-filter-type-val" style="font-size: 0.81rem; font-weight: 700; color: {text_c}; white-space: nowrap;">
                    {html.escape(str(types_str))}
                </span>
            </div>
            <div style="background: {chip_bg}; border: 1px solid {chip_border}; border-radius: 8px; padding: 5px 11px; display: inline-flex; align-items: center; gap: 6px; flex: 0 0 auto; box-sizing: border-box;" title="ราคา (Price)">
                <i class="fa-solid fa-tag" style="color: #10b981; font-size: 0.86rem; flex-shrink: 0;"></i>
                <span id="active-filter-price-val" style="font-size: 0.81rem; font-weight: 700; color: {text_c}; white-space: nowrap;">
                    {html.escape(str(price_str))}
                </span>
            </div>
            <div style="background: {chip_bg}; border: 1px solid {chip_border}; border-radius: 8px; padding: 5px 11px; display: inline-flex; align-items: center; gap: 6px; flex: 0 0 auto; box-sizing: border-box;" title="ขนาด/Plan (Area)">
                <i class="fa-solid fa-ruler-combined" style="color: #8b5cf6; font-size: 0.86rem; flex-shrink: 0;"></i>
                <span id="active-filter-area-val" style="font-size: 0.81rem; font-weight: 700; color: {text_c}; white-space: nowrap;">
                    {html.escape(str(area_str))}
                </span>
            </div>
            <div style="background: {chip_bg}; border: 1px solid {chip_border}; border-radius: 8px; padding: 5px 11px; display: inline-flex; align-items: center; gap: 6px; flex: 0 0 auto; box-sizing: border-box;" title="ชั้น (Floor)">
                <i class="fa-solid fa-stairs" style="color: #6366f1; font-size: 0.86rem; flex-shrink: 0;"></i>
                <span id="active-filter-floor-val" style="font-size: 0.81rem; font-weight: 700; color: {text_c}; white-space: nowrap;">
                    {html.escape(str(floor_str))}
                </span>
            </div>
            <div style="background: {chip_bg}; border: 1px solid {chip_border}; border-radius: 8px; padding: 5px 11px; display: inline-flex; align-items: center; gap: 6px; flex: 0 0 auto; box-sizing: border-box;" title="ห้อง/ที่จอด (Room/Parking)">
                <i class="fa-solid fa-bed" style="color: #ec4899; font-size: 0.86rem; flex-shrink: 0;"></i>
                <span id="active-filter-spec-val" style="font-size: 0.81rem; font-weight: 700; color: {text_c}; white-space: nowrap;">
                    {html.escape(str(spec_str))}
                </span>
            </div>
            <div style="background: {chip_bg}; border: 1px solid {chip_border}; border-radius: 8px; padding: 5px 11px; display: inline-flex; align-items: center; gap: 6px; flex: 0 0 auto; box-sizing: border-box;" title="อายุประกาศ (Age)">
                <i class="fa-solid fa-calendar-days" style="color: #0284c7; font-size: 0.86rem; flex-shrink: 0;"></i>
                <span id="active-filter-age-val" style="font-size: 0.81rem; font-weight: 700; color: {text_c}; white-space: nowrap;">
                    {html.escape(str(age_str))}
                </span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 4. Require at least one active location/pin, comparison selection, or in-map filter
    if not has_any_filter:
        st.info("กรุณาปักหมุดบนแผนที่ หรือเลือกตัวกรอง/ทำเล เพื่อเริ่มดูข้อมูล", icon=":material/location_on:")
        return

    # 5. Calculation results (Cards & Table) with Live Filters
    # Determine comparison data scope label
    if has_ref_point and (pin_mode == 'radius' or not has_loc_filter) and not active_proj:
        scope_header = f"ในรัศมี {active_ref_radius:.1f} กม. รอบจุดอ้างอิง"
    elif active_proj:
        prov_tag = f" จังหวัด{active_prov[0]}" if active_prov else ""
        scope_header = f"ในโครงการ {active_proj}{prov_tag}"
    else:
        if active_subdist:
            clean_s = active_subdist[0].split(' (')[0].strip()
            clean_d = active_dist[0].split(' (')[0].strip() if active_dist else ""
            scope_header = f"ในทำเล ตำบล{clean_s} อำเภอ{clean_d} จังหวัด{active_prov[0] if active_prov else ''}"
        elif active_dist:
            clean_d = active_dist[0].split(' (')[0].strip()
            scope_header = f"ในทำเล อำเภอ{clean_d} จังหวัด{active_prov[0] if active_prov else ''}"
        elif active_prov:
            scope_header = f"ในทำเล จังหวัด{active_prov[0]}"
        else:
            scope_parts = []
            if map_cos:
                scope_parts.append(f"บริษัท {', '.join(map_cos)}")
            if q_only_proj:
                scope_parts.append("เฉพาะมีโครงการ")
            if map_types:
                scope_parts.append(f"ประเภท {', '.join(map_types)}")
            if scope_parts:
                scope_header = f"({' · '.join(scope_parts)} ทั่วประเทศ)"
            else:
                scope_header = "(ภาพรวมทั่วประเทศ)"

    def compute_vectorized_unit_info(df_target):
        if df_target is None or df_target.empty:
            return df_target
        df_res = df_target.copy()
        p_num = pd.to_numeric(df_res['ราคา'], errors='coerce')
        sqm_num = pd.to_numeric(df_res.get('พื้นที่ใช้สอย (ตร.ม.)', np.nan), errors='coerce')
        sqw_num = _sqw_from_df(df_res)

        p_type = df_res['ประเภททรัพย์'].astype(str).str.lower()
        is_condo = p_type.str.contains('คอนโด|ห้องชุด', regex=True, na=False)

        condo_rate = np.where(is_condo & (sqm_num > 0) & (p_num > 0), p_num / sqm_num, np.nan)
        land_rate = np.where((~is_condo) & (sqw_num > 0) & (p_num > 0), p_num / sqw_num, np.nan)
        unit_price = np.where(pd.notna(condo_rate), condo_rate, land_rate)

        df_res['ราคาต่อหน่วย'] = unit_price
        df_res['หน่วยวัด'] = np.where(is_condo, 'ตร.ม.', 'ตร.ว.')
        df_res['ประเภทพื้นที่'] = np.where(is_condo, 'พื้นที่ใช้สอย', 'เนื้อที่')
        return df_res

    # Target type determination
    target_type = None
    if active_ref_prop is not None:
        target_type = active_ref_prop.get('ประเภททรัพย์')
    elif tab2_types and len(tab2_types) == 1:
        target_type = tab2_types[0]
    elif map_types and len(map_types) == 1:
        target_type = map_types[0]

    if is_comparison_active:
        scope_header = f"เปรียบเทียบทรัพย์ที่เลือก ({len(status_df)} รายการ)"

    # Header row with title
    if active_price_ref_prop is not None:
        st.markdown(
            """
            <style>
            .metric-card-pink,
            div.metric-card.metric-card-pink,
            #median-card-1.metric-card-pink,
            #median-card-2.metric-card-pink,
            #median-card-3.metric-card-pink {
                border-top: 3.5px solid #F6BAC0 !important;
                border-top-color: #F6BAC0 !important;
                border-color: rgba(246, 186, 192, 0.6) !important;
                background: rgba(246, 186, 192, 0.12) !important;
                box-shadow: 0 4px 14px rgba(246, 186, 192, 0.2) !important;
            }
            .metric-card-pink:hover,
            div.metric-card.metric-card-pink:hover,
            #median-card-1.metric-card-pink:hover,
            #median-card-2.metric-card-pink:hover,
            #median-card-3.metric-card-pink:hover {
                border-color: #F6BAC0 !important;
                border-top-color: #f43f5e !important;
                box-shadow: 0 10px 26px rgba(244, 63, 94, 0.25) !important;
            }
            .st-key-btn_reset_price_center button {
                border: 1.5px solid rgba(246, 186, 192, 0.7) !important;
                color: #be185d !important;
                font-weight: 600 !important;
            }
            .st-key-btn_reset_price_center button:hover {
                border-color: #F6BAC0 !important;
                background-color: rgba(246, 186, 192, 0.15) !important;
                color: #9f1239 !important;
            }
            </style>
            """,
            unsafe_allow_html=True
        )
        hdr_c1, hdr_c2 = st.columns([0.72, 0.28])
        with hdr_c1:
            ref_cid_disp = active_price_ref_prop.get('รหัสทรัพย์', '-')
            st.markdown(
                f"<div id='median-section-header' style='font-size: 1.25rem; font-weight: 700; margin-bottom: 12px;'><i class='fa-solid fa-scale-balanced' style='color:#e11d48; margin-right:6px;'></i>ผลการวิเคราะห์เทียบราคาทรัพย์อ้างอิงตรง <span style='font-size:0.95rem; color:#be185d; font-weight:800;'>[รหัส: {html.escape(str(ref_cid_disp))}]</span> <span id='median-scope-header-text' style='font-size:0.85rem; font-weight:500; color:#64748b;'>{html.escape(str(scope_header))}</span></div>",
                unsafe_allow_html=True
            )
        with hdr_c2:
            if st.button("รีเซ็ตกลับเป็นราคากลาง (Median)", icon=":material/restart_alt:", key="btn_reset_price_center", use_container_width=True, help="คลิกเพื่อยกเลิกการเทียบตรง และกลับไปใช้ราคากลาง (Median) ของพื้นที่"):
                st.session_state["tab2_just_reset_price_center"] = True
                st.session_state["tab2_inject_clear_price_center_js"] = True
                st.session_state["tab2_price_center_id"] = ""
                st.session_state.pop("tab2_price_ref_prop", None)
                active_price_ref_prop = None
                try:
                    st.query_params.pop("map_price_ref_id", None)
                except Exception:
                    pass
                if "map_sync_bridge_payload" in st.session_state:
                    try:
                        p_obj = json.loads(st.session_state["map_sync_bridge_payload"])
                        if isinstance(p_obj, dict):
                            p_obj["price_center_id"] = ""
                            st.session_state["map_sync_bridge_payload"] = json.dumps(p_obj)
                    except Exception:
                        pass
                st.rerun(scope="fragment")
    else:
        st.markdown(
            f"<div id='median-section-header' style='font-size: 1.25rem; font-weight: 700; margin-bottom: 12px;'><i class='fa-solid fa-chart-simple' style='color:#059669; margin-right:6px;'></i>ผลการวิเคราะห์ราคากลางต่อหน่วย (Median Analysis) <span id='median-scope-header-text'>{html.escape(str(scope_header))}</span></div>",
            unsafe_allow_html=True
        )

    # Synchronize comparison data directly with active status_df from Filter Status Banner
    from modules.services.data_loader import get_data_mtime as _get_mtime_t2
    _cur_mtime_t2 = _get_mtime_t2()
    if df_raw is not None and len(status_df) == len(df_raw):
        filtered_nearby = _compute_vectorized_unit_info_cached(status_df, cache_key=(_cur_mtime_t2, len(status_df)))
    else:
        filtered_nearby = compute_vectorized_unit_info(status_df).reset_index(drop=True)
    active_cos = map_cos
    active_types = map_types

    # 1. Dedicated Pure Land Calculation (Card 4 & Benchmark) - reuses global pure-land extractors
    _check_pure_land_mask = _check_pure_land_mask_global
    _extract_pure_land_pool = _extract_pure_land_pool_global

    is_radius_scope = bool(has_ref_point and (pin_mode == 'radius' or not has_loc_filter) and not active_proj)
    source_icon = "fa-circle-dot"
    land_source_desc = ""
    pure_df = pd.DataFrame()
    pure_rates = pd.Series(dtype=float)

    if is_radius_scope:
        land_radius = max(float(active_ref_radius), 1.0)
        source_icon = "fa-circle-dot"
        land_source_desc = f"ตามรัศมี {land_radius:.1f} กม. รอบจุดอ้างอิง"
        # Unfiltered query from df_raw for pure land around reference point
        cand_raw = find_nearby_properties(active_ref_lat, active_ref_lon, df_raw, land_radius)
        pure_df, pure_rates = _extract_pure_land_pool(cand_raw)

        # Progressive radius expansion if no pure land found in tight radius
        if pure_rates.empty:
            for exp_r in [10.0, 15.0, 20.0, 30.0, 50.0]:
                if exp_r <= land_radius:
                    continue
                exp_cand = find_nearby_properties(active_ref_lat, active_ref_lon, df_raw, exp_r)
                exp_pure, exp_rates = _extract_pure_land_pool(exp_cand)
                if not exp_rates.empty:
                    pure_df, pure_rates = exp_pure, exp_rates
                    land_source_desc = f"ที่ดินเปล่าในรัศมี {exp_r:.0f} กม. รอบจุดอ้างอิง"
                    source_icon = "fa-circle-dot"
                    break

        # Fallback to District / Province if still empty
        if pure_rates.empty:
            r_dist = ""
            r_prov = ""
            if active_ref_prop:
                r_dist = str(active_ref_prop.get('อำเภอ', '')).strip()
                r_prov = str(active_ref_prop.get('จังหวัด', '')).strip()
            if not r_dist or not r_prov or r_dist in ['-', 'ไม่มีข้อมูล', 'nan'] or r_prov in ['-', 'ไม่มีข้อมูล', 'nan']:
                cand_50 = find_nearby_properties(active_ref_lat, active_ref_lon, df_raw, 50.0)
                if not cand_50.empty:
                    d_vals = [d.strip() for d in cand_50['อำเภอ'].dropna().astype(str).unique() if d.strip() not in ['-', 'ไม่มีข้อมูล', 'nan']] if 'อำเภอ' in cand_50.columns else []
                    p_vals = [p.strip() for p in cand_50['จังหวัด'].dropna().astype(str).unique() if p.strip() not in ['-', 'ไม่มีข้อมูล', 'nan']] if 'จังหวัด' in cand_50.columns else []
                    if d_vals:
                        r_dist = d_vals[0]
                    if p_vals:
                        r_prov = p_vals[0]

            if r_dist and r_prov and r_dist not in ['-', 'ไม่มีข้อมูล', 'nan'] and r_prov not in ['-', 'ไม่มีข้อมูล', 'nan']:
                dist_cand = df_raw[
                    (df_raw['อำเภอ'].astype(str).str.strip() == r_dist) &
                    (df_raw['จังหวัด'].astype(str).str.strip() == r_prov)
                ] if ('อำเภอ' in df_raw.columns and 'จังหวัด' in df_raw.columns) else pd.DataFrame()
                dist_pure, dist_rates = _extract_pure_land_pool(dist_cand)
                if not dist_rates.empty:
                    pure_df, pure_rates = dist_pure, dist_rates
                    land_source_desc = f"ที่ดินเปล่าใน อ.{r_dist} จ.{r_prov}"
                    source_icon = "fa-location-dot"

            if pure_rates.empty and r_prov and r_prov not in ['-', 'ไม่มีข้อมูล', 'nan']:
                prov_cand = df_raw[df_raw['จังหวัด'].astype(str).str.strip() == r_prov] if 'จังหวัด' in df_raw.columns else pd.DataFrame()
                prov_pure, prov_rates = _extract_pure_land_pool(prov_cand)
                if not prov_rates.empty:
                    pure_df, pure_rates = prov_pure, prov_rates
                    land_source_desc = f"ที่ดินเปล่าใน จ.{r_prov}"
                    source_icon = "fa-location-dot"

    elif active_proj:
        source_icon = "fa-mountain-sun"
        p_list = [p.strip() for p in active_proj.split(",") if p.strip()]
        proj_df = df_raw[_match_project_mask(df_raw, p_list)].copy() if (df_raw is not None and not df_raw.empty) else pd.DataFrame()
        pure_df, pure_rates = _extract_pure_land_pool(proj_df)
        if not pure_rates.empty:
            land_source_desc = f"ในโครงการ: {active_proj}"
        else:
            # Project has no pure land -> search nearby coordinates
            proj_lats = pd.to_numeric(proj_df.get('ละติจูด', pd.Series(dtype=float)), errors='coerce').dropna()
            proj_lons = pd.to_numeric(proj_df.get('ลองจิจูด', pd.Series(dtype=float)), errors='coerce').dropna()
            valid_coord = not proj_lats.empty and not proj_lons.empty and (proj_lats.iloc[0] > 0) and (proj_lons.iloc[0] > 0)
            if valid_coord:
                c_lat = float(proj_lats.median())
                c_lon = float(proj_lons.median())
                for r_dist in [5.0, 10.0, 15.0, 20.0, 30.0]:
                    cand = find_nearby_properties(c_lat, c_lon, df_raw, r_dist)
                    cand_pure, cand_rates = _extract_pure_land_pool(cand)
                    if len(cand_rates) >= 2 or (r_dist == 30.0 and len(cand_rates) > 0):
                        pure_df, pure_rates = cand_pure, cand_rates
                        land_source_desc = f"ที่ดินเปล่ารอบโครงการ (รัศมี {r_dist:.0f} กม.)"
                        break

            p_dists = [d.split(' (')[0].strip() for d in proj_df['อำเภอ'].dropna().astype(str).unique() if d not in ['-', 'ไม่มีข้อมูล', 'ไม่ระบุ', 'nan']] if 'อำเภอ' in proj_df.columns else []
            p_provs = [p.strip() for p in proj_df['จังหวัด'].dropna().astype(str).unique() if p not in ['-', 'ไม่มีข้อมูล', 'ไม่ระบุ', 'nan']] if 'จังหวัด' in proj_df.columns else []
            if pure_rates.empty and p_dists and 'อำเภอ' in df_raw.columns:
                cand = df_raw[df_raw['อำเภอ'].astype(str).str.strip().isin(p_dists)].copy()
                if p_provs and 'จังหวัด' in cand.columns:
                    cand = cand[cand['จังหวัด'].astype(str).str.strip().isin(p_provs)]
                cand_pure, cand_rates = _extract_pure_land_pool(cand)
                if not cand_rates.empty:
                    pure_df, pure_rates = cand_pure, cand_rates
                    d_lbl = p_dists[0]
                    p_lbl = p_provs[0] if p_provs else ""
                    land_source_desc = f"ที่ดินเปล่ารอบโครงการ (อ.{d_lbl} จ.{p_lbl})"

            if pure_rates.empty and p_provs and 'จังหวัด' in df_raw.columns:
                cand = df_raw[df_raw['จังหวัด'].astype(str).str.strip().isin(p_provs)].copy()
                cand_pure, cand_rates = _extract_pure_land_pool(cand)
                if not cand_rates.empty:
                    pure_df, pure_rates = cand_pure, cand_rates
                    land_source_desc = f"ที่ดินเปล่ารอบโครงการ (จ.{p_provs[0]})"

    else:
        # Location mode or Nationwide
        source_icon = "fa-location-dot"
        if active_subdist and not df_raw.empty and 'ตำบล' in df_raw.columns:
            clean_target_subs = [s.split(' (')[0].strip() for s in active_subdist]
            clean_target_dists = [d.split(' (')[0].strip() for d in active_dist] if active_dist else []
            sub_cand = df_raw[df_raw['ตำบล'].astype(str).str.strip().isin(clean_target_subs)].copy()
            if clean_target_dists and 'อำเภอ' in sub_cand.columns:
                sub_cand = sub_cand[sub_cand['อำเภอ'].astype(str).str.strip().isin(clean_target_dists)]
            if active_prov and 'จังหวัด' in sub_cand.columns:
                sub_cand = sub_cand[sub_cand['จังหวัด'].astype(str).str.strip().isin(active_prov)]
            pure_sub, rates_sub = _extract_pure_land_pool(sub_cand)
            if not rates_sub.empty:
                pure_df, pure_rates = pure_sub, rates_sub
                clean_s_name = active_subdist[0].split(' (')[0].strip()
                clean_d_name = active_dist[0].split(' (')[0].strip() if active_dist else ""
                land_source_desc = f"ตามทำเล ต.{clean_s_name} อ.{clean_d_name}"

        if pure_rates.empty and active_dist and not df_raw.empty and 'อำเภอ' in df_raw.columns:
            clean_target_dists = [d.split(' (')[0].strip() for d in active_dist]
            dist_cand = df_raw[df_raw['อำเภอ'].astype(str).str.strip().isin(clean_target_dists)].copy()
            if active_prov and 'จังหวัด' in dist_cand.columns:
                dist_cand = dist_cand[dist_cand['จังหวัด'].astype(str).str.strip().isin(active_prov)]
            pure_dist, rates_dist = _extract_pure_land_pool(dist_cand)
            if not rates_dist.empty:
                pure_df, pure_rates = pure_dist, rates_dist
                clean_d_name = active_dist[0].split(' (')[0].strip()
                clean_p_name = active_prov[0] if active_prov else ""
                land_source_desc = f"ที่ดินเปล่าใน อ.{clean_d_name} จ.{clean_p_name}"

        if pure_rates.empty and active_prov and not df_raw.empty and 'จังหวัด' in df_raw.columns:
            prov_cand = df_raw[df_raw['จังหวัด'].astype(str).str.strip().isin(active_prov)].copy()
            pure_prov, rates_prov = _extract_pure_land_pool(prov_cand)
            if not rates_prov.empty:
                pure_df, pure_rates = pure_prov, rates_prov
                land_source_desc = f"ที่ดินเปล่าใน จ.{active_prov[0]}"

    # Final nationwide fallback if still empty
    if pure_rates.empty and df_raw is not None and not df_raw.empty:
        pure_all, rates_all = _get_cached_nationwide_pure_land(df_raw, cache_key=(_cur_mtime_t2, len(df_raw)))
        if not rates_all.empty:
            pure_df, pure_rates = pure_all, rates_all
            land_source_desc = "ที่ดินเปล่า ภาพรวมทั่วประเทศ"
            source_icon = "fa-globe"

    # Check company filter: prioritize company if matching pure land exists in this pool
    if active_cos and not active_proj and not pure_df.empty and 'บริษัท' in pure_df.columns:
        co_pure = pure_df[pure_df['บริษัท'].isin(active_cos)]
        co_rates = co_pure['rate_per_sqw'].dropna()
        co_rates = co_rates[co_rates > 0]
        if not co_rates.empty:
            pure_df = co_pure
            pure_rates = co_rates

    land_pool_df = pure_df
    has_raw_land = False
    median_raw_land = min_raw_land = max_raw_land = 0.0
    count_raw_land = 0
    if not pure_rates.empty:
        median_raw_land = float(pure_rates.median())
        min_raw_land = float(pure_rates.min())
        max_raw_land = float(pure_rates.max())
        count_raw_land = len(pure_rates)
        has_raw_land = True

    # Pure land mask for filtered_nearby
    is_fn_pure_land = _check_pure_land_mask(filtered_nearby['ประเภททรัพย์']) if not filtered_nearby.empty else pd.Series(False, index=filtered_nearby.index)

    # Check if the user explicitly selected pure land in the map filter
    user_filtered_pure_land = bool(active_types and all(('ที่ดิน' in t and not any(k in t for k in ['บ้าน', 'อาคาร', 'ทาวน์', 'คอนโด', 'ตึก', 'โรงงาน', 'พาณิชย์', 'หอพัก', 'สิ่งปลูกสร้าง'])) for t in active_types))

    # -------------------------------------------------------------
    # 2. Calculate Median for Sq. Wah (Card 2 - Strictly ตร.ว. only)
    # Title: ราคากลางตร.ว. {ประเภททรัพย์เป้าหมาย} แต่เป็นพวกที่มี ตร.ว. เท่านั้น
    # -------------------------------------------------------------
    has_sel_u_stats = False
    median_u_sel = min_u_sel = max_u_sel = 0.0
    median_sqw_val = 0.0
    unit_lbl_sel = "ตร.ว."
    count_u_sel = 0
    c2_source_desc = ""

    def _is_condo_type(val):
        return bool(re.search(r'คอนโด|ห้องชุด', str(val), re.IGNORECASE))

    def _extract_sqw_rates_from_df(calc_df):
        if calc_df is None or calc_df.empty:
            return pd.Series(dtype=float)
        s_vals = _sqw_from_df(calc_df)
        p_vals = pd.to_numeric(calc_df.get('ราคา', np.nan), errors='coerce')
        v_mask = (s_vals > 0) & (p_vals > 0)
        rates = (p_vals[v_mask] / s_vals[v_mask]).dropna()
        return rates[rates > 0]

    # Determine target landed type(s) strictly for properties with ตร.ว.
    target_is_condo = bool(target_type and _is_condo_type(target_type))
    target_is_pure_land = bool(target_type and _check_pure_land_mask(pd.Series([target_type])).iloc[0])

    if target_type and not target_is_condo and not target_is_pure_land:
        # Target property is a specific landed type (e.g. บ้านเดี่ยว, ทาวน์เฮ้าส์, อาคารพาณิชย์)
        t_lbl = target_type
        title_c2 = f"ราคากลางตร.ว. {t_lbl}"
        calc_type_df = filtered_nearby[filtered_nearby['ประเภททรัพย์'] == target_type].copy() if not filtered_nearby.empty else pd.DataFrame()
    elif active_types:
        landed_active = [t for t in active_types if not _check_pure_land_mask(pd.Series([t])).iloc[0] and not _is_condo_type(t)]
        if landed_active:
            t_lbl = ", ".join(landed_active)
            title_c2 = f"ราคากลางตร.ว. {t_lbl}"
            calc_type_df = filtered_nearby[filtered_nearby['ประเภททรัพย์'].isin(landed_active)].copy() if not filtered_nearby.empty else pd.DataFrame()
        elif user_filtered_pure_land:
            t_lbl = "ที่ดินเปล่า"
            title_c2 = "ราคากลางตร.ว. ที่ดินเปล่า"
            calc_type_df = filtered_nearby[is_fn_pure_land].copy() if not filtered_nearby.empty else pd.DataFrame()
        else:
            # Active types selected are condo / non-landed only -> No ตร.ว. in filter!
            title_c2 = "ราคากลางตร.ว. บ้านและสิ่งปลูกสร้าง"
            calc_type_df = pd.DataFrame()
    elif target_is_pure_land:
        title_c2 = "ราคากลางตร.ว. ที่ดินเปล่า"
        calc_type_df = filtered_nearby[is_fn_pure_land].copy() if not filtered_nearby.empty else pd.DataFrame()
    elif target_is_condo:
        # Target property is condo -> Condo has no ตร.ว.
        title_c2 = "ราคากลางตร.ว. บ้านและสิ่งปลูกสร้าง"
        calc_type_df = pd.DataFrame()
    else:
        # Default / no type filter: strictly landed houses/buildings (exclude pure land and condo)
        title_c2 = "ราคากลางตร.ว. บ้านและสิ่งปลูกสร้าง"
        calc_type_df = filtered_nearby[~is_fn_pure_land & ~filtered_nearby['ประเภททรัพย์'].astype(str).str.contains('คอนโด|ห้องชุด', na=False)].copy() if not filtered_nearby.empty else pd.DataFrame()

    # Calculate strictly from filtered data (no fallback to wider location scope)
    sqw_rates = _extract_sqw_rates_from_df(calc_type_df)

    if not sqw_rates.empty:
        median_u_sel = float(sqw_rates.median())
        median_sqw_val = median_u_sel
        min_u_sel = float(sqw_rates.min())
        max_u_sel = float(sqw_rates.max())
        count_u_sel = len(sqw_rates)
        has_sel_u_stats = True
    else:
        median_u_sel = 0.0
        median_sqw_val = 0.0
        min_u_sel = max_u_sel = 0.0
        count_u_sel = 0
        has_sel_u_stats = False

    # Calculate Median for All Sq. Metre (พื้นที่ใช้สอย) in filtered_nearby (Card 4)
    has_sqm_median = False
    median_sqm_val = 0.0
    count_sqm_val = 0
    min_sqm_val = max_sqm_val = 0.0
    if not filtered_nearby.empty and 'พื้นที่ใช้สอย (ตร.ม.)' in filtered_nearby.columns:
        sqm_vals = pd.to_numeric(filtered_nearby['พื้นที่ใช้สอย (ตร.ม.)'], errors='coerce')
        price_vals = pd.to_numeric(filtered_nearby['ราคา'], errors='coerce')
        valid_mask_sqm = (sqm_vals > 0) & (price_vals > 0)
        sqm_rates = (price_vals[valid_mask_sqm] / sqm_vals[valid_mask_sqm]).dropna()
        sqm_rates = sqm_rates[sqm_rates > 0]
        if not sqm_rates.empty:
            median_sqm_val = float(sqm_rates.median())
            min_sqm_val = float(sqm_rates.min())
            max_sqm_val = float(sqm_rates.max())
            count_sqm_val = len(sqm_rates)
            has_sqm_median = True

    # Render 4 Metric Cards (Total Count, Target Type, Pure Land, Sq. Metre)
    card_c1, card_c2, card_c3, card_c4 = st.columns(4)
    total_nearby_cnt = len(filtered_nearby)
    safe_scope_header = html.escape(str(scope_header))

    price_ref_price = price_ref_sqw_num = price_ref_sqw_rate = price_ref_sqm_rate = 0.0
    ref_is_condo = False
    ref_prop_code = ""
    if active_price_ref_prop is not None:
        ref_prop_code = str(active_price_ref_prop.get('รหัสทรัพย์', '-')).strip()
        ref_co = str(active_price_ref_prop.get('บริษัท', '-')).strip()
        ref_proj = str(active_price_ref_prop.get('ชื่อโครงการ', '')).strip()
        ref_type = str(active_price_ref_prop.get('ประเภททรัพย์', '-')).strip()
        price_ref_price, price_ref_sqw_num, price_ref_sqw_rate, price_ref_sqm_rate, ref_is_condo = _extract_asset_unit_rates(active_price_ref_prop)

        # Card 1 Override: Property Code
        ref_title_sub = f"[{html.escape(ref_co)}] {html.escape(ref_proj if ref_proj and ref_proj not in ['-', 'nan', 'ไม่มีข้อมูล'] else ref_type)}"
        card1_price_str = f"฿{price_ref_price:,.0f} บาท" if price_ref_price > 0 else "-"
        card1_html = (
            f"<div class='metric-card metric-card-pink' id='median-card-1' style='position: relative; overflow: hidden; background: rgba(246, 186, 192, 0.12) !important; border: 1.5px solid rgba(246, 186, 192, 0.6) !important; border-top: 3.5px solid #F6BAC0 !important; border-top-color: #F6BAC0 !important; border-radius: 12px; padding: 12px 14px; box-shadow: 0 4px 12px rgba(246, 186, 192, 0.15) !important; min-height: 140px; display: flex; flex-direction: column; justify-content: space-between;'>"
            f"<div class='metric-card-bg-icon' style='position: absolute; left: -24px; bottom: -20px; font-size: 7rem; line-height: 1; pointer-events: none; z-index: 0; color: #F6BAC0; opacity: 0.25;'><i class='fa-solid fa-scale-balanced'></i></div>"
            f"<div style='position: relative; z-index: 1;'>"
            f"<div style='font-size: 0.78rem; font-weight: 700; color: #be185d; text-transform: uppercase; letter-spacing: 0.4px;'><i class='fa-solid fa-hashtag' style='color: #e11d48; margin-right:4px;'></i> รหัสทรัพย์ศูนย์กลางราคา</div>"
            f"<div id='median-card1-val' style='font-size: 1.45rem; font-weight: 800; color: #be185d; margin: 3px 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;' title='{html.escape(ref_prop_code)}'>{html.escape(ref_prop_code)}</div>"
            f"</div>"
            f"<div style='position: relative; z-index: 1;'>"
            f"<div id='median-card1-loc' style='color: #e11d48; font-size: 0.76rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;'><i class='fa-solid fa-tag' style='color:#e11d48; font-size:0.72rem; margin-right:3px;'></i>{card1_price_str}</div>"
            f"<div id='median-card1-sub' style='color: #64748b; font-size: 0.74rem; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;'>{ref_title_sub}</div>"
            f"</div>"
            f"</div>"
        )

        # Card 2 Override: Price per sq.wah of selected asset
        if price_ref_sqw_rate > 0:
            c4_main = f"฿{price_ref_sqw_rate:,.0f}"
            c4_unit = "/ตร.ว."
            c4_sub = f"เนื้อที่: {price_ref_sqw_num:,.1f} ตร.ว."
        elif ref_is_condo:
            c4_main = "-"
            c4_unit = ""
            c4_sub = "คอนโดมิเนียม (ไม่มีเนื้อที่ดิน)"
        else:
            c4_main = "-"
            c4_unit = ""
            c4_sub = "ไม่มีข้อมูลเนื้อที่ดิน"

        card4_html = (
            f"<div class='metric-card metric-card-pink' id='median-card-3' style='position: relative; overflow: hidden; background: rgba(246, 186, 192, 0.12) !important; border: 1.5px solid rgba(246, 186, 192, 0.6) !important; border-top: 3.5px solid #F6BAC0 !important; border-top-color: #F6BAC0 !important; border-radius: 12px; padding: 12px 14px; box-shadow: 0 4px 12px rgba(246, 186, 192, 0.15) !important; min-height: 140px; display: flex; flex-direction: column; justify-content: space-between;'>"
            f"<div class='metric-card-bg-icon' style='position: absolute; left: -24px; bottom: -20px; font-size: 7rem; line-height: 1; pointer-events: none; z-index: 0; color: #F6BAC0; opacity: 0.25;'><i class='fa-solid fa-house-chimney'></i></div>"
            f"<div style='position: relative; z-index: 1;'>"
            f"<div id='median-card3-title' style='font-size: 0.78rem; font-weight: 700; color: #be185d; text-transform: uppercase; letter-spacing: 0.4px;'><i class='fa-solid fa-house' style='color: #e11d48; margin-right:4px;'></i> ราคา / ตร.ว. (ทรัพย์ที่เลือก)</div>"
            f"<div id='median-card3-val' style='font-size: 1.55rem; font-weight: 800; color: #be185d; margin: 3px 0;'>{c4_main} <span style='font-size:0.85rem; font-weight:600; color:#64748b;'>{c4_unit}</span></div>"
            f"</div>"
            f"<div style='position: relative; z-index: 1;'>"
            f"<div id='median-card3-sub' style='color: #64748b; font-size: 0.76rem;'>{c4_sub}</div>"
            f"</div>"
            f"</div>"
        )

        # Card 4 Override: Price per sq.metre of selected asset
        if price_ref_sqm_rate > 0:
            c3_main = f"฿{price_ref_sqm_rate:,.0f}"
            c3_unit = "/ตร.ม."
            raw_sqm = _safe_float(active_price_ref_prop.get('พื้นที่ใช้สอย (ตร.ม.)'), 0.0)
            c3_sub = f"พื้นที่ใช้สอย: {raw_sqm:,.1f} ตร.ม." if raw_sqm > 0 else "พื้นที่ใช้สอย (มีข้อมูล)"
        else:
            c3_main = "-"
            c3_unit = ""
            c3_sub = "ไม่มีข้อมูลพื้นที่ใช้สอย"

        card3_html = (
            f"<div class='metric-card metric-card-pink' id='median-card-2' style='position: relative; overflow: hidden; background: rgba(246, 186, 192, 0.12) !important; border: 1.5px solid rgba(246, 186, 192, 0.6) !important; border-top: 3.5px solid #F6BAC0 !important; border-top-color: #F6BAC0 !important; border-radius: 12px; padding: 12px 14px; box-shadow: 0 4px 12px rgba(246, 186, 192, 0.15) !important; min-height: 140px; display: flex; flex-direction: column; justify-content: space-between;'>"
            f"<div class='metric-card-bg-icon' style='position: absolute; left: -24px; bottom: -20px; font-size: 7rem; line-height: 1; pointer-events: none; z-index: 0; color: #F6BAC0; opacity: 0.25;'><i class='fa-solid fa-building'></i></div>"
            f"<div style='position: relative; z-index: 1;'>"
            f"<div id='median-card2-title' style='font-size: 0.78rem; font-weight: 700; color: #be185d; text-transform: uppercase; letter-spacing: 0.4px;'><i class='fa-solid fa-building' style='color: #e11d48; margin-right:4px;'></i> ราคา / ตร.ม. (ทรัพย์ที่เลือก)</div>"
            f"<div id='median-card2-val' style='font-size: 1.55rem; font-weight: 800; color: #be185d; margin: 3px 0;'>{c3_main} <span style='font-size:0.85rem; font-weight:600; color:#64748b;'>{c3_unit}</span></div>"
            f"</div>"
            f"<div style='position: relative; z-index: 1;'>"
            f"<div id='median-card2-sub' style='color: #64748b; font-size: 0.76rem;'>{c3_sub}</div>"
            f"</div>"
            f"</div>"
        )
    else:
        # Card 1: Reference Info (Total Count as Primary Metric)
        if active_ref_prop is not None:
            p_co = html.escape(str(active_ref_prop.get('บริษัท', '-')))
            p_code = html.escape(str(active_ref_prop.get('รหัสทรัพย์', '-')))
            p_type_str = html.escape(str(active_ref_prop.get('ประเภททรัพย์', '-')))
            sub_ref_info = f"<div id='median-card1-sub' style='color: #94a3b8; font-size: 0.74rem; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;'>[{p_co}] {p_code} &bull; {p_type_str}</div>"
        elif active_ref_lat and active_ref_lon:
            sub_ref_info = "<div id='median-card1-sub' style='color: #94a3b8; font-size: 0.74rem; margin-top: 2px;'>กำหนดจากพิกัดแผนที่</div>"
        else:
            sub_ref_info = f"<div id='median-card1-sub' style='color: #94a3b8; font-size: 0.74rem; margin-top: 2px;'>{safe_scope_header}</div>"

        card1_loc_detail = f"{active_ref_lat:.5f}, {active_ref_lon:.5f} (รัศมี {active_ref_radius:.1f} กม.)" if (active_ref_lat and active_ref_lon) else safe_scope_header
        card1_html = (
            f"<div class='metric-card' id='median-card-1' style='position: relative; overflow: hidden; background: rgba(16, 185, 129, 0.04); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 12px; padding: 12px 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); min-height: 140px; display: flex; flex-direction: column; justify-content: space-between;'>"
            f"<div class='metric-card-bg-icon' style='position: absolute; left: -24px; bottom: -20px; font-size: 7rem; line-height: 1; pointer-events: none; z-index: 0;'><i class='fa-solid fa-layer-group'></i></div>"
            f"<div style='position: relative; z-index: 1;'>"
            f"<div style='font-size: 0.78rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.4px;'><i class='fa-solid fa-layer-group' style='color: #10b981; margin-right:4px;'></i> จำนวนทรัพย์ทั้งหมด</div>"
            f"<div id='median-card1-val' style='font-size: 1.55rem; font-weight: 800; color: #059669; margin: 3px 0;'>{total_nearby_cnt:,} <span style='font-size:0.85rem; font-weight:600; color:#64748b;'>รายการ</span></div>"
            f"</div>"
            f"<div style='position: relative; z-index: 1;'>"
            f"<div id='median-card1-loc' style='color: #64748b; font-size: 0.76rem;'><i class='fa-solid fa-location-dot' style='color:#10b981; font-size:0.72rem; margin-right:3px;'></i>{card1_loc_detail}</div>"
            f"{sub_ref_info}"
            f"</div>"
            f"</div>"
        )

        # Card 4 (rendered in Column 4): Median Sq. Metre (All Properties)
        if has_sqm_median:
            c3_main = f"฿{median_sqm_val:,.0f}"
            c3_unit = "/ตร.ม."
            c3_sub = f"ต่ำสุด ฿{min_sqm_val:,.0f} &bull; สูงสุด ฿{max_sqm_val:,.0f}"
            c3_badge = f"<span style='font-size:0.74rem; font-weight:600; color:#10b981;'>({count_sqm_val:,} แปลง)</span>"
        else:
            c3_main = "-"
            c3_unit = ""
            c3_sub = "ไม่มีข้อมูลพื้นที่ใช้สอย"
            c3_badge = ""

        card3_html = (
            f"<div class='metric-card' id='median-card-2' style='position: relative; overflow: hidden; background: rgba(16, 185, 129, 0.04); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 12px; padding: 12px 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); min-height: 140px; display: flex; flex-direction: column; justify-content: space-between;'>"
            f"<div class='metric-card-bg-icon' style='position: absolute; left: -24px; bottom: -20px; font-size: 7rem; line-height: 1; pointer-events: none; z-index: 0;'><i class='fa-solid fa-building'></i></div>"
            f"<div style='position: relative; z-index: 1;'>"
            f"<div id='median-card2-title' style='font-size: 0.78rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.4px;'><i class='fa-solid fa-building' style='color: #10b981; margin-right:4px;'></i> ราคากลาง / ตร.ม. <span id='median-card2-badge'>{c3_badge}</span></div>"
            f"<div id='median-card2-val' style='font-size: 1.55rem; font-weight: 800; color: #059669; margin: 3px 0;'>{c3_main} <span style='font-size:0.85rem; font-weight:600; color:#64748b;'>{c3_unit}</span></div>"
            f"</div>"
            f"<div style='position: relative; z-index: 1;'>"
            f"<div id='median-card2-sub' style='color: #64748b; font-size: 0.76rem;'>{c3_sub}</div>"
            f"</div>"
            f"</div>"
        )

        # Card 2 (rendered in Column 2): Landed Sq. Wah (Strictly ตร.ว. only)
        if has_sel_u_stats:
            c4_main = f"฿{median_u_sel:,.0f}"
            c4_unit = "/ตร.ว."
            c4_sub = f"ต่ำสุด ฿{min_u_sel:,.0f} &bull; สูงสุด ฿{max_u_sel:,.0f}"
            if c2_source_desc:
                c4_sub = f"<div style='color: #059669; font-size: 0.74rem; font-weight: 600;'><i class='fa-solid fa-location-dot' style='font-size:0.72rem; margin-right:3px;'></i>{html.escape(str(c2_source_desc))}</div>" + c4_sub
            c4_badge = f"<span style='font-size:0.74rem; font-weight:600; color:#10b981;'>({count_u_sel:,} แปลง)</span>"
        else:
            c4_main = "-"
            c4_unit = ""
            c4_sub = "-"
            c4_badge = ""

        card4_html = (
            f"<div class='metric-card' id='median-card-3' style='position: relative; overflow: hidden; background: rgba(16, 185, 129, 0.04); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 12px; padding: 12px 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); min-height: 140px; display: flex; flex-direction: column; justify-content: space-between;'>"
            f"<div class='metric-card-bg-icon' style='position: absolute; left: -24px; bottom: -20px; font-size: 7rem; line-height: 1; pointer-events: none; z-index: 0;'><i class='fa-solid fa-house-chimney'></i></div>"
            f"<div style='position: relative; z-index: 1;'>"
            f"<div id='median-card3-title' style='font-size: 0.78rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.4px;'><i class='fa-solid fa-house' style='color: #10b981; margin-right:4px;'></i> {html.escape(str(title_c2))} <span id='median-card3-badge'>{c4_badge}</span></div>"
            f"<div id='median-card3-val' style='font-size: 1.55rem; font-weight: 800; color: #059669; margin: 3px 0;'>{c4_main} <span style='font-size:0.85rem; font-weight:600; color:#64748b;'>{c4_unit}</span></div>"
            f"</div>"
            f"<div style='position: relative; z-index: 1;'>"
            f"<div id='median-card3-sub' style='color: #64748b; font-size: 0.76rem;'>{c4_sub}</div>"
            f"</div>"
            f"</div>"
        )

    # Card 4 (rendered in Column 3): Pure Land (Earth-brown theme for land/soil)
    if has_raw_land:
        c5_main = f"฿{median_raw_land:,.0f}"
        c5_unit = "/ตร.ว."
        c5_sub = f"ต่ำสุด ฿{min_raw_land:,.0f} &bull; สูงสุด ฿{max_raw_land:,.0f}"
        c5_badge = f"<span style='font-size:0.74rem; font-weight:600; color:#92400e;'>({count_raw_land:,} แปลง)</span>"
        safe_land_desc = html.escape(str(land_source_desc))
        c5_source_html = f"<div id='median-card4-source' style='color: #92400e; font-size: 0.76rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;' title='{safe_land_desc}'><i class='fa-solid {source_icon}' style='font-size:0.72rem; margin-right:3px; color: #b45309;'></i>{safe_land_desc}</div>"
    else:
        c5_main = "-"
        c5_unit = ""
        c5_sub = "-"
        c5_badge = ""
        c5_source_html = ""

    card5_html = (
        f"<div class='metric-card metric-card-brown' id='median-card-4' style='position: relative; overflow: hidden; background: rgba(180, 83, 9, 0.04) !important; border: 1px solid rgba(180, 83, 9, 0.35) !important; border-top: 3.5px solid #92400e !important; border-radius: 12px; padding: 12px 14px; box-shadow: 0 4px 12px rgba(120, 53, 15, 0.06); min-height: 140px; display: flex; flex-direction: column; justify-content: space-between;'>"
        f"<div class='metric-card-bg-icon metric-card-bg-icon-brown' style='position: absolute; left: -24px; bottom: -20px; font-size: 7rem; line-height: 1; pointer-events: none; z-index: 0; color: #92400e;'><i class='fa-solid fa-mountain-sun'></i></div>"
        f"<div style='position: relative; z-index: 1;'>"
        f"<div id='median-card4-title' style='font-size: 0.78rem; font-weight: 700; color: #78716c; text-transform: uppercase; letter-spacing: 0.4px;'><i class='fa-solid fa-mountain-sun' style='color: #b45309; margin-right:4px;'></i> ราคากลางที่ดินเปล่า <span id='median-card4-badge'>{c5_badge}</span></div>"
        f"<div id='median-card4-val' style='font-size: 1.55rem; font-weight: 800; color: #92400e; margin: 3px 0;'>{c5_main} <span style='font-size:0.85rem; font-weight:600; color:#78716c;'>{c5_unit}</span></div>"
        f"</div>"
        f"<div style='position: relative; z-index: 1;'>"
        f"{c5_source_html}"
        f"<div id='median-card4-sub' style='color: #78716c; font-size: 0.74rem; margin-top: 1px;'>{c5_sub}</div>"
        f"</div>"
        f"</div>"
    )

    with card_c1:
        st.html(card1_html)
    with card_c2:
        st.html(card4_html)
    with card_c3:
        st.html(card5_html)
    with card_c4:
        st.html(card3_html)

    # Nearby Assets Table (Direct display with icon instead of expander)
    filter_summary_str = f" [กรอง: {', '.join(active_cos)}]" if (active_cos and not active_proj) else ""
    if not filtered_nearby.empty:
        # Prioritize the selected price center property at Row 1, or SAM assets if active_proj
        if active_price_ref_prop is not None and not filtered_nearby.empty and 'รหัสทรัพย์' in filtered_nearby.columns:
            ref_c_lower = str(active_price_ref_prop.get('รหัสทรัพย์', '')).strip().lower()
            is_ref_near = filtered_nearby['รหัสทรัพย์'].astype(str).str.strip().str.lower() == ref_c_lower
            if is_ref_near.any():
                filtered_nearby = pd.concat([filtered_nearby[is_ref_near], filtered_nearby[~is_ref_near]], ignore_index=True)
            else:
                ref_row_df = pd.DataFrame([active_price_ref_prop])
                filtered_nearby = pd.concat([ref_row_df, filtered_nearby], ignore_index=True)
            is_fn_pure_land = _check_pure_land_mask(filtered_nearby['ประเภททรัพย์'])
        elif active_proj and 'บริษัท' in filtered_nearby.columns:
            is_sam = (filtered_nearby['บริษัท'].astype(str) == 'SAM')
            filtered_nearby = pd.concat([filtered_nearby[is_sam], filtered_nearby[~is_sam]], ignore_index=True)
        else:
            filtered_nearby = filtered_nearby.reset_index(drop=True)

        legend_txt_color = "#94a3b8" if is_dark_mode else "#475569"
        legend_bg = "rgba(148, 163, 184, 0.12)" if is_dark_mode else "rgba(100, 116, 139, 0.08)"
        legend_border = "rgba(148, 163, 184, 0.22)" if is_dark_mode else "rgba(148, 163, 184, 0.3)"
        legend_green = "#34d399" if is_dark_mode else "#059669"
        legend_red = "#f87171" if is_dark_mode else "#dc2626"
        if active_price_ref_prop is not None:
            ref_c_id = active_price_ref_prop.get('รหัสทรัพย์', '')
            safe_ref_c_id = html.escape(str(ref_c_id))
            table_title_text = f"เปรียบเทียบราคาโดยตรงกับทรัพย์ {safe_ref_c_id} ({len(filtered_nearby):,} รายการ {safe_scope_header})"
            tbl_title_icon = "<i class='fa-solid fa-scale-balanced' style='color:#e11d48; margin-right:8px;'></i>"
            tbl_badge_html = (
                f"<span style='font-size: 0.8rem; font-weight: 600; color: #be185d; background: rgba(246, 186, 192, 0.2); padding: 4px 12px; border-radius: 20px; border: 1.2px solid rgba(246, 186, 192, 0.6);'>"
                f"<i class='fa-solid fa-scale-balanced' style='margin-right:5px;'></i>ศูนย์กลางราคา: {safe_ref_c_id}</span>"
            )
        elif is_comparison_active:
            table_title_text = f"รายการทรัพย์สินที่เลือกเปรียบเทียบ ({len(filtered_nearby):,} รายการ)"
            tbl_title_icon = "<i class='fa-solid fa-table-list' style='color:#059669; margin-right:8px;'></i>"
            tbl_badge_html = (
                f"<span style='font-size: 0.8rem; font-weight: 600; color: #059669; background: rgba(16, 185, 129, 0.1); padding: 4px 12px; border-radius: 20px; border: 1.2px solid rgba(16, 185, 129, 0.3);'>"
                f"<i class='fa-solid fa-layer-group' style='margin-right:5px;'></i>ตารางเปรียบเทียบข้อมูลทรัพย์</span>"
            )
        else:
            table_title_text = f"รายการทรัพย์สิน ({len(filtered_nearby):,} รายการ {safe_scope_header}{html.escape(str(filter_summary_str))})"
            tbl_title_icon = "<i class='fa-solid fa-table-list' style='color:#059669; margin-right:8px;'></i>"
            tbl_badge_html = (
                f"<span style='font-size: 0.8rem; font-weight: 600; color: #059669; background: rgba(16, 185, 129, 0.1); padding: 4px 12px; border-radius: 20px; border: 1.2px solid rgba(16, 185, 129, 0.3);'>"
                f"<i class='fa-solid fa-layer-group' style='margin-right:5px;'></i>ตารางเปรียบเทียบข้อมูลทรัพย์</span>"
            )

        st.markdown(
            f"<div style='margin-top: 22px; margin-bottom: 12px; font-weight: 700; font-size: 1.06rem; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;'>"
            f"<span>{tbl_title_icon}"
            f"<span id='median-table-title'>{table_title_text}</span></span>"
            f"<div style='display: flex; align-items: center; gap: 10px;'>"
            f"<span style='font-size: 0.8rem; font-weight: 500; color: {legend_txt_color}; background: {legend_bg}; padding: 4px 10px; border-radius: 8px; border: 1px solid {legend_border}; display: inline-flex; align-items: center; gap: 4px;'>"
            f"คำอธิบาย: <span style=\"color: {legend_green}; font-weight: 600;\">↓ สีเขียว (ถูกกว่า)</span> / <span style=\"color: {legend_red}; font-weight: 600;\">↑ สีแดง (แพงกว่า)</span>"
            f"</span>"
            f"{tbl_badge_html}"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True
        )
        # Build detailed analysis dataframe for display (cached & vectorized)
        _has_dist_k = bool('ระยะทาง (กม.)' in filtered_nearby.columns)
        _idx_fp = int(pd.util.hash_pandas_object(filtered_nearby.index, index=False).sum()) if not filtered_nearby.empty else 0
        _import_ver = int(st.session_state.get("_custom_import_ver", 0))
        _tbl_cache_key = (
            _cur_mtime_t2,
            _import_ver,
            len(filtered_nearby),
            _idx_fp,
            round(float(active_ref_lat or 0.0), 5),
            round(float(active_ref_lon or 0.0), 5),
            round(float(active_ref_radius or 0.0), 2),
            round(float(median_raw_land), 2),
            round(float(median_sqw_val), 2),
            round(float(median_u_sel), 2),
            round(float(median_sqm_val), 2),
            round(float(price_ref_sqw_rate), 2) if active_price_ref_prop else 0.0,
            round(float(price_ref_sqm_rate), 2) if active_price_ref_prop else 0.0,
            str(ref_prop_code or ""),
            _has_dist_k,
            bool(is_comparison_active),
        )
        show_df, df_to_export, has_valid_proj = _build_tab2_show_df_cached(
            filtered_nearby,
            is_fn_pure_land,
            median_raw_land,
            median_sqw_val,
            median_u_sel,
            median_sqm_val,
            price_ref_sqw=price_ref_sqw_rate if active_price_ref_prop else 0.0,
            price_ref_sqm=price_ref_sqm_rate if active_price_ref_prop else 0.0,
            price_ref_id=ref_prop_code if active_price_ref_prop else "",
            cache_key=_tbl_cache_key
        )
        proj_col_width = "medium" if has_valid_proj else "small"

        is_ref_mode = active_price_ref_prop is not None
        col_sqw_title = "เทียบราคา ตร.ว. (ทรัพย์อ้างอิง)" if is_ref_mode else "เทียบราคากลางต่อ ตร.ว."
        col_sqm_title = "เทียบราคา ตร.ม. (ทรัพย์อ้างอิง)" if is_ref_mode else "เทียบราคากลางต่อ ตร.ม."
        col_sqw_help = "เทียบกับราคาต่อ ตร.ว. ของทรัพย์อ้างอิงที่เลือก (↓ สีเขียว = ถูกกว่าทรัพย์อ้างอิง, ↑ สีแดง = แพงกว่าทรัพย์อ้างอิง)" if is_ref_mode else "เทียบกับราคากลางต่อ ตร.ว. ตามประเภททรัพย์นั้นๆ ในพื้นที่ (↓ สีเขียว = ถูกกว่าราคากลางประเภทนั้น, ↑ สีแดง = แพงกว่าราคากลางประเภทนั้น)"
        col_sqm_help = "เทียบกับราคาต่อ ตร.ม. ของทรัพย์อ้างอิงที่เลือก (↓ สีเขียว = ถูกกว่าทรัพย์อ้างอิง, ↑ สีแดง = แพงกว่าทรัพย์อ้างอิง)" if is_ref_mode else "เทียบกับราคากลางต่อ ตร.ม. ตามประเภททรัพย์นั้นๆ ในพื้นที่ (↓ สีเขียว = ถูกกว่าราคากลางประเภทนั้น, ↑ สีแดง = แพงกว่าราคากลางประเภทนั้น)"

        table_col_config = {
            "บริษัท": st.column_config.TextColumn("บริษัท", help="บริษัทบริหารสินทรัพย์", pinned=True),
            "ชื่อโครงการ": st.column_config.TextColumn("ชื่อโครงการ", help="ชื่อโครงการ / หมู่บ้าน / อาคารชุด", width=proj_col_width),
            "ชั้น": st.column_config.TextColumn("ชั้น", help="ชั้นที่ตั้งของทรัพย์สิน หรือจำนวนชั้นของอาคาร"),
            "ราคา (บาท)": st.column_config.NumberColumn("ราคา (บาท)", format="฿%,d"),
            "เนื้อที่ (ไร่-งาน-ตร.ว.)": st.column_config.TextColumn(
                "เนื้อที่ (ไร่-งาน-ตร.ว.)",
                help="ขนาดเนื้อที่ดินในรูปแบบ ไร่-งาน-ตารางวา (0-0-0)"
            ),
            "เนื้อที่ (ตร.ว.)": st.column_config.TextColumn(
                "เนื้อที่ (ไร่-งาน-ตร.ว.)",
                help="ขนาดเนื้อที่ดินในรูปแบบ ไร่-งาน-ตารางวา (0-0-0)"
            ),
            "ราคาต่อตร.ว. (บาท)": st.column_config.NumberColumn("ราคาต่อตร.ว. (บาท)", format="฿%,d"),
            col_sqw_title: st.column_config.TextColumn(
                col_sqw_title,
                help=col_sqw_help
            ),
            "หักลบราคากลาง ตร.ว. ที่ดินเปล่า": st.column_config.TextColumn(
                "หักลบราคากลาง ตร.ว. ที่ดินเปล่า",
                help=f"หักลบกับราคากลาง ตร.ว. ของที่ดินเปล่าแท้ๆ ในพื้นที่ (ราคาต่อ ตร.ว. - ฿{median_raw_land:,.0f}/ตร.ว.) | ↓ สีเขียว = ถูกกว่า, ↑ สีแดง = แพงกว่า" if median_raw_land > 0 else "หักลบราคากลาง ตร.ว. ที่ดินเปล่า"
            ),
            "พื้นที่ใช้สอย (ตร.ม.)": st.column_config.NumberColumn("พื้นที่ใช้สอย (ตร.ม.)", format="%,.1f"),
            "ราคาต่อตร.ม. (บาท)": st.column_config.NumberColumn("ราคาต่อตร.ม. (บาท)", format="฿%,d"),
            col_sqm_title: st.column_config.TextColumn(
                col_sqm_title,
                help=col_sqm_help
            ),
            "ระยะทาง (กม.)": st.column_config.NumberColumn("ระยะทาง (กม.)", format="%.2f กม."),
            "เปิดลิงก์": st.column_config.LinkColumn("เปิดลิงก์", display_text="เปิดดูทรัพย์"),
            "อายุวันประกาศ": st.column_config.TextColumn(
                "อายุวันประกาศ",
                help="ระยะเวลาตั้งแต่เริ่มลงประกาศจนถึงปัจจุบัน (คำนวณจากวันประกาศ)"
            ),
            "เลขโฉนด": st.column_config.TextColumn(
                "เลขโฉนด",
                help="เลขที่โฉนดที่ดิน หรือ เอกสารสิทธิ์"
            ),
            "ห้องนอน": st.column_config.TextColumn("ห้องนอน", help="จำนวนห้องนอน"),
            "ห้องน้ำ": st.column_config.TextColumn("ห้องน้ำ", help="จำนวนห้องน้ำ"),
            "ที่จอดรถ": st.column_config.TextColumn("ที่จอดรถ", help="จำนวนช่องจอดรถ"),
            "ตำบล": st.column_config.TextColumn("ตำบล", help="ตำบล/แขวง"),
            "อำเภอ": st.column_config.TextColumn("อำเภอ", help="อำเภอ/เขต"),
            "จังหวัด": st.column_config.TextColumn("จังหวัด", help="จังหวัด"),
            "ละติจูด": st.column_config.TextColumn(
                "ละติจูด",
                help="พิกัดละติจูด (⚠️ = พิกัดกึ่งกลางตำบล/อำเภอโดยประมาณ ไม่ใช่ตำแหน่งจริง)"
            ),
            "ลองจิจูด": st.column_config.TextColumn(
                "ลองจิจูด",
                help="พิกัดลองจิจูด (⚠️ = พิกัดกึ่งกลางตำบล/อำเภอโดยประมาณ ไม่ใช่ตำแหน่งจริง)"
            ),
            "โจทก์": st.column_config.TextColumn("โจทก์", help="โจทก์ผู้ฟ้องคดี (เฉพาะทรัพย์กรมบังคับคดี LED / LED Legal)"),
        }

        def highlight_diff_cells(val):
            s = str(val).strip()
            if s in ["-", "", "nan", "None", "0.0%", "0 ฿", "0"] or "(0.0%)" in s:
                return ""
            # Market median: ↓ (cheaper) = Green
            if s.startswith("↓") or s.startswith("▼"):
                return (
                    "color: #34d399; font-weight: 700; background-color: rgba(16, 185, 129, 0.15); border: 1.5px solid rgba(16, 185, 129, 0.45); border-radius: 6px;"
                    if is_dark_mode else
                    "color: #047857; font-weight: 700; background-color: rgba(16, 185, 129, 0.12); border: 1.5px solid rgba(16, 185, 129, 0.4); border-radius: 6px;"
                )
            # Market median: ↑ (more expensive) = Red
            elif s.startswith("↑") or s.startswith("▲"):
                return (
                    "color: #f87171; font-weight: 700; background-color: rgba(239, 68, 68, 0.15); border: 1.5px solid rgba(239, 68, 68, 0.45); border-radius: 6px;"
                    if is_dark_mode else
                    "color: #b91c1c; font-weight: 700; background-color: rgba(239, 68, 68, 0.12); border: 1.5px solid rgba(239, 68, 68, 0.4); border-radius: 6px;"
                )
            return ""

        diff_target_cols = [c for c in ['เทียบราคากลางต่อ ตร.ว.', 'หักลบราคากลาง ตร.ว. ที่ดินเปล่า', 'เทียบราคากลางต่อ ตร.ม.', 'เทียบราคา ตร.ว. (ทรัพย์อ้างอิง)', 'เทียบราคา ตร.ม. (ทรัพย์อ้างอิง)'] if c in show_df.columns]

        # Pandas Styler has a cell rendering cap (default 262,144 cells).
        # When viewing large datasets (e.g. nationwide or thousands of rows), render show_df
        # directly via Arrow to maintain ultra-fast virtualized scrolling and avoid Styler memory exceptions.
        df_to_render = show_df
        if diff_target_cols and show_df.size <= 200_000:
            try:
                df_to_render = show_df.style.map(highlight_diff_cells, subset=diff_target_cols)
            except Exception:
                df_to_render = show_df

        # Dynamic key forces Glide Data Grid to unmount and completely remount fresh canvas
        # whenever company filters, projects, or row counts change
        first_asset_id = str(show_df['รหัสทรัพย์'].iloc[0]) if not show_df.empty and 'รหัสทรัพย์' in show_df.columns else ""
        first_co = str(show_df['บริษัท'].iloc[0]) if not show_df.empty and 'บริษัท' in show_df.columns else ""
        co_part = ','.join(sorted(active_cos)) if active_cos else 'ALL'
        grid_sig = f"{co_part}_{active_proj or ''}_{len(show_df)}_{first_asset_id}_{first_co}"
        grid_key = f"tab2_table_grid_{hashlib.md5(grid_sig.encode('utf-8')).hexdigest()[:12]}"

        try:
            st.dataframe(df_to_render, use_container_width=True, height=420, column_config=table_col_config, hide_index=True, key=grid_key)
        except Exception:
            st.dataframe(show_df, use_container_width=True, height=420, column_config=table_col_config, hide_index=True, key=f"{grid_key}_fb")
        # ── Import / Export (same style as Tab 1) ──
        render_import_export_section(df_to_export, filename_prefix=f"comparison_{scope_header.replace(' ', '_')}", key_suffix="tab2_compare")
    else:
        st.info(f"ไม่พบรายการทรัพย์สินที่ตรงตามเงื่อนไขตัวกรอง {scope_header}")
