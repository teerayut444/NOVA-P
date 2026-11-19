import html
import os
import re
import json
import gzip
import base64
import threading
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st

_ROOT_DIR = Path(__file__).resolve().parents[2]

from modules.services.data_cleaner import (
    ensure_derived_cols,
    parse_listing_age_days
)
from modules.services.geo_service import (
    get_map_icon_atlas_and_mapping,
    get_leaflet_logo_dict
)

def _resolve_root_file(rel_path):
    p_root = _ROOT_DIR / rel_path
    if p_root.exists():
        return p_root
    return Path(rel_path)

def _parse_sold_date_value(val):
    """Parse Thai Buddhist Era (DD/MM/2569) or Gregorian date string into Timestamp safely."""
    if val is None or pd.isna(val):
        return pd.NaT
    s = str(val).strip()
    if not s or s.lower() in ('nan', 'none', 'null', '-', '<na>'):
        return pd.NaT
    m_ymd = re.match(r'^(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?:\s.*)?$', s)
    if m_ymd:
        y, m, d = int(m_ymd.group(1)), int(m_ymd.group(2)), int(m_ymd.group(3))
        if y > 2400:
            y -= 543
        try:
            return pd.Timestamp(year=y, month=m, day=d)
        except Exception:
            return pd.NaT
    m_dmy = re.match(r'^(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?:\s.*)?$', s)
    if m_dmy:
        d, m, y = int(m_dmy.group(1)), int(m_dmy.group(2)), int(m_dmy.group(3))
        if y > 2400:
            y -= 543
        try:
            return pd.Timestamp(year=y, month=m, day=d)
        except Exception:
            return pd.NaT
    return pd.to_datetime(s, dayfirst=False, errors='coerce')

def get_latest_parquet_path():
    """Returns the primary dashboard dataset path strictly: all_assets.parquet or all_asset.parquet."""
    for name in ("all_assets.parquet", "all_asset.parquet"):
        p_root = _ROOT_DIR / name
        if p_root.exists():
            return p_root
        p_cwd = Path(name)
        if p_cwd.exists():
            return p_cwd
    return _ROOT_DIR / "all_assets.parquet"

def get_data_mtime():
    """Get modification timestamp of the primary dataset."""
    p = get_latest_parquet_path()
    if p.exists():
        return p.stat().st_mtime
    return 0


def get_data_mtime_token(data_mtime=None):
    """Canonical string representation of data_mtime shared between Python cache writers and JS readers."""
    m = get_data_mtime() if data_mtime is None else data_mtime
    try:
        return f"{float(m):.6f}"
    except Exception:
        return str(m or "0")


def get_cache_builder_version():
    """Cache-busting version string derived from static/map_cache_builder.js mtime."""
    p = str(_resolve_root_file("static/map_cache_builder.js"))
    try:
        return f"{os.path.getmtime(p):.0f}" if os.path.exists(p) else "1"
    except Exception:
        return "1"


STATIC_MAP_PAYLOAD_PATH = str(_ROOT_DIR / "static" / "map_payload_cache.js")


def ensure_static_map_payload_file(data_mtime, lookup_b64, csv_base64):
    """Writes the GZIP+Base64 nationwide map payload as a static JS file under /app/static/.

    Skips disk write when the file header already matches data_mtime, and uses
    temp-file + os.replace so concurrent readers never observe partial writes.
    """
    if not csv_base64:
        return False
    token = get_data_mtime_token(data_mtime)
    header_line = f"/* NOVA_MTIME:{token} */"
    target = STATIC_MAP_PAYLOAD_PATH
    try:
        if os.path.exists(target):
            with open(target, "r", encoding="utf-8", errors="ignore") as f_chk:
                if f_chk.readline().strip() == header_line:
                    return True
    except Exception:
        pass

    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp_path = f"{target}.tmp.{os.getpid()}.{threading.get_ident()}"
    try:
        payload_json = json.dumps(
            {"mtime": token, "lut": lookup_b64, "csv": csv_base64},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with open(tmp_path, "w", encoding="utf-8") as f_out:
            f_out.write(header_line)
            f_out.write("\nwindow.__NOVA_RAW_MAP_PAYLOAD__ = ")
            f_out.write(payload_json)
            f_out.write(";\n")
        os.replace(tmp_path, target)
        return True
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False

@st.cache_resource(ttl=3600, show_spinner="กำลังโหลดฐานข้อมูลทรัพย์สิน (all_assets.parquet)...")
def _load_properties_data_cached(data_version=0):
    """Load property dataset strictly from all_assets.parquet / all_asset.parquet and run initial derivation/enrichment.
    Cached across all user sessions as the single master in-memory resource.
    """
    parquet_file = get_latest_parquet_path()
    
    if not parquet_file.exists():
        st.error(f"ไม่พบไฟล์ข้อมูล '{parquet_file.name}' กรุณาตรวจสอบไฟล์ในโฟลเดอร์หลัก")
        return None

    try:
        df = pd.read_parquet(parquet_file)
        # Read-only: never write back to the shared parquet here. With many concurrent
        # LAN users this could corrupt the file, and changing its mtime would force a
        # second full reload. Derivation/persisting belongs in convert_csv_to_parquet.py.
        df = ensure_derived_cols(df)
        df.attrs['source'] = parquet_file.name
        return df
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการโหลดไฟล์ Parquet: {e}")
        return None

def load_properties_data(data_version=0):
    """Load property dataset strictly from all_assets.parquet / all_asset.parquet.
    
    [SEC-01] Returns df.copy(deep=False) so each session gets an independent DataFrame wrapper
    without duplicating the ~440k+ rows in RAM, preventing in-place mutations across users.
    """
    df = _load_properties_data_cached(data_version=data_version)
    if df is not None:
        df_copy = df.copy(deep=False)
        df_copy.attrs = getattr(df, 'attrs', {}).copy()
        return df_copy
    return None

load_properties_data.clear = _load_properties_data_cached.clear

@st.cache_data(show_spinner=False)
def get_sam_project_options(_df, cache_key=None, return_meta=False):
    """Pre-computes and caches list of all projects and their unit counts across all companies,
    prioritizing SAM projects at the top.

    `_df` is not hashed by Streamlit, so pass a hashable `cache_key` (e.g. len(df))
    whenever the dataframe content can change (imported data).
    """
    if _df is None or _df.empty or 'ชื่อโครงการ' not in _df.columns or 'บริษัท' not in _df.columns:
        if return_meta:
            return [], {}, [], [], {}
        return [], {}
    from modules.services.data_cleaner import (
        is_invalid_project_name,
        normalize_project_name,
        get_brand_search_tag,
        clean_display_project_name,
    )

    df_sub = _df[['ชื่อโครงการ', 'บริษัท']].dropna().copy()
    unique_projs = df_sub['ชื่อโครงการ'].dropna().astype(str).str.strip().unique()
    p_to_norm = {p: normalize_project_name(p) for p in unique_projs if not is_invalid_project_name(p)}
    df_sub['norm_k'] = df_sub['ชื่อโครงการ'].astype(str).str.strip().map(p_to_norm).fillna('')

    df_sub['p_clean'] = df_sub['ชื่อโครงการ'].astype(str).str.strip()
    df_sub = df_sub[~df_sub['p_clean'].map(is_invalid_project_name)]
    if df_sub.empty:
        if return_meta:
            return [], {}, [], [], {}
        return [], {}

    is_sam = df_sub['บริษัท'].astype(str).str.strip().str.upper() == 'SAM'
    sam_sub = df_sub[is_sam]
    comp_sub = df_sub[~is_sam]

    sam_counts = sam_sub.groupby('norm_k').size()
    comp_counts = comp_sub.groupby('norm_k').size()
    comp_companies = comp_sub.groupby('norm_k')['บริษัท'].nunique()

    # Group raw names by norm_k to eliminate duplicate/typo variations
    norm_groups = df_sub.groupby('norm_k')['p_clean'].unique().to_dict()
    raw_counts = df_sub['p_clean'].value_counts().to_dict()
    sam_raw_counts = sam_sub['p_clean'].value_counts().to_dict()

    canonical_to_norm = {}
    sam_projs = []
    other_projs = []

    for k, raws in norm_groups.items():
        if not k or len(k) <= 2:
            continue
        # Pick best canonical name: prefer SAM's most frequent name, else overall most frequent name
        sam_candidates = [r for r in raws if r in sam_raw_counts]
        if sam_candidates:
            sam_candidates.sort(key=lambda r: sam_raw_counts[r], reverse=True)
            best_raw = sam_candidates[0]
        else:
            candidates = sorted(raws, key=lambda r: raw_counts.get(r, 0), reverse=True)
            best_raw = candidates[0]

        can_p = clean_display_project_name(best_raw)
        if not can_p or can_p in canonical_to_norm:
            continue
        canonical_to_norm[can_p] = k

        s_cnt = int(sam_counts.get(k, 0))
        if s_cnt > 0:
            sam_projs.append(can_p)
        else:
            other_projs.append(can_p)

    def sam_sort_key(p):
        k = canonical_to_norm.get(p, '')
        o = int(comp_counts.get(k, 0)) if k else 0
        s = int(sam_counts.get(k, 0)) if k else 0
        return (1 if o > 0 else 0, o, s)

    def other_sort_key(p):
        k = canonical_to_norm.get(p, '')
        o = int(comp_counts.get(k, 0)) if k else 0
        return o

    sam_projs.sort(key=sam_sort_key, reverse=True)
    other_projs.sort(key=other_sort_key, reverse=True)

    sorted_projs = sam_projs + other_projs
    labels = {}
    proj_stats = {}
    for p in sorted_projs:
        k = canonical_to_norm.get(p, '')
        s = int(sam_counts.get(k, 0)) if k else 0
        o = int(comp_counts.get(k, 0)) if k else 0
        cj = int(comp_companies.get(k, 0)) if k else 0
        tag = get_brand_search_tag(p)
        tag_suffix = f"  [{tag}]" if tag else ""
        if s > 0:
            if o > 0:
                labels[p] = f"{p}  ➔  SAM: {s}  |  คู่แข่ง: {cj} เจ้า ({o} ทรัพย์){tag_suffix}"
            else:
                labels[p] = f"{p}  ➔  SAM: {s}  |  ไม่มีคู่แข่ง{tag_suffix}"
        else:
            labels[p] = f"{p}  ➔  {o} ทรัพย์ ({cj} เจ้า){tag_suffix}"
        proj_stats[p] = [s, o]

    if return_meta:
        return sorted_projs, labels, sam_projs, other_projs, proj_stats
    return sorted_projs, labels

@st.cache_data(show_spinner=False)
def get_base_map_html(mtime=None):
    """Load and cache the base HTML template for Leaflet/Deck.gl interactive map."""
    try:
        tmpl_path = _resolve_root_file("static/map_template.html")
        with open(tmpl_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def build_map_payload_from_df(
    df,
    df_project_source=None,
    data_mtime=0,
    progress_bar=None,
    custom_companies=None,
    custom_company=None,
    custom_color=None,
):
    """Builds GZIP+Base64 CSV payload, categorical lookup_b64, and legend HTML from a properties DataFrame."""
    if df is None or df.empty:
        return "", "", "", 0

    map_data = df[
        df['ละติจูด'].notna() & df['ลองจิจูด'].notna() &
        df['ละติจูด'].between(5, 21) & df['ลองจิจูด'].between(97, 106)
    ].copy()
    if map_data.empty:
        return "", "", "", 0

    if progress_bar is not None:
        progress_bar.progress(40, text="กำลังจัดเตรียมและคำนวณราคาต่อหน่วย (40%)...")

    map_data_full_len = len(map_data)
    _prices_num = pd.to_numeric(map_data['ราคา'], errors='coerce')

    _p_wah = pd.to_numeric(map_data['ราคาต่อตารางวา'], errors='coerce') if 'ราคาต่อตารางวา' in map_data.columns else pd.Series(np.nan, index=map_data.index)
    _p_sqm = pd.to_numeric(map_data['ราคาต่อตารางเมตร'], errors='coerce') if 'ราคาต่อตารางเมตร' in map_data.columns else pd.Series(np.nan, index=map_data.index)
    _sqw_calc = pd.to_numeric(map_data.get('พื้นที่_ตารางวา', np.nan), errors='coerce')
    _sqm_calc = pd.to_numeric(map_data.get('พื้นที่ใช้สอย (ตร.ม.)', np.nan), errors='coerce')
    _p_wah_calc = np.where((_p_wah > 0), _p_wah, np.where((_sqw_calc > 0) & (_prices_num > 0), _prices_num / _sqw_calc, np.nan))
    _p_sqm_calc = np.where((_p_sqm > 0), _p_sqm, np.where((_sqm_calc > 0) & (_prices_num > 0), _prices_num / _sqm_calc, np.nan))
    _ptype_str = map_data['ประเภททรัพย์'].astype(str) if 'ประเภททรัพย์' in map_data.columns else pd.Series('', index=map_data.index)
    _is_condo = _ptype_str.str.contains('ห้องชุด|คอนโด|อาคารชุด', na=False)
    _unit_prices = np.where(
        _is_condo,
        np.where(pd.notna(_p_sqm_calc) & (_p_sqm_calc > 0), _p_sqm_calc, np.where(pd.notna(_p_wah_calc) & (_p_wah_calc > 0), _p_wah_calc, 0.0)),
        np.where(pd.notna(_p_wah_calc) & (_p_wah_calc > 0), _p_wah_calc, np.where(pd.notna(_p_sqm_calc) & (_p_sqm_calc > 0), _p_sqm_calc, 0.0))
    )

    title_col = 'ชื่อประกาศ' if 'ชื่อประกาศ' in map_data.columns else ('ชื่อโครงการ' if 'ชื่อโครงการ' in map_data.columns else 'รหัสทรัพย์')
    titles = map_data[title_col].fillna('ไม่มีชื่อ').astype(str).str.strip().str[:80].tolist()
    ids = map_data['รหัสทรัพย์'].fillna('-').astype(str).str.strip().tolist()

    if 'is_centroid' in map_data.columns:
        centroid_mask = map_data['is_centroid'].apply(is_true_centroid).astype(bool) if not pd.api.types.is_bool_dtype(map_data['is_centroid'].dtype) else map_data['is_centroid'].fillna(False).astype(bool)
    else:
        centroid_mask = pd.Series(False, index=map_data.index)
    centroid_flags = centroid_mask.astype('uint8').tolist()

    centroid_per_company = (
        map_data.loc[centroid_mask, 'บริษัท'].fillna('-').value_counts().to_dict()
    )

    COMPANY_MAP_RGB = {
        "LED": [8, 145, 178], "LED Legal": [71, 85, 105], "LED_SOLD": [71, 85, 105], "SAM": [16, 185, 129], "BAM": [59, 130, 246],
        "Chayo555": [249, 115, 22], "GHB": [202, 138, 4], "KBANK": [5, 150, 105],
        "KTB": [2, 132, 199], "SCB": [126, 34, 206], "GSB": [235, 25, 133],
        "DDproperty": [168, 85, 247], "Livinginsider": [20, 184, 166],
        "NaYoo": [139, 92, 246], "ZmyHome": [236, 72, 153], "Baania": [245, 158, 11]
    }
    def _h2rgb_list(h):
        try:
            h = str(h).lstrip('#')
            if len(h) == 6:
                return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]
        except Exception:
            pass
        return [99, 102, 241]

    # Prefer explicit parameters so cached shared payloads never depend on per-user session_state
    imported_cos = custom_companies
    custom_co_val = custom_company
    custom_color_val = custom_color
    if imported_cos is None:
        try:
            import streamlit as st
            if hasattr(st, "session_state"):
                imported_cos = st.session_state.get("imported_custom_companies", {})
                if custom_co_val is None:
                    custom_co_val = st.session_state.get("imported_custom_company")
                if custom_color_val is None:
                    custom_color_val = st.session_state.get("imported_custom_color", "#6366f1")
        except Exception:
            imported_cos = {}

    if isinstance(imported_cos, dict):
        for co_n, co_inf in imported_cos.items():
            if isinstance(co_inf, dict) and "color" in co_inf:
                COMPANY_MAP_RGB[co_n] = _h2rgb_list(co_inf["color"])

    custom_rgb = _h2rgb_list(custom_color_val or "#6366f1")
    COMPANY_MAP_RGB["ไฟล์นำเข้า"] = custom_rgb
    if custom_co_val and custom_co_val != "ไฟล์นำเข้า" and custom_co_val != "(ตามข้อมูลในไฟล์)" and (not isinstance(imported_cos, dict) or custom_co_val not in imported_cos):
        COMPANY_MAP_RGB[custom_co_val] = custom_rgb
    DEFAULT_COLOR = [148, 163, 184]

    co_counts = map_data['บริษัท'].value_counts()
    legend_items_html = ['<div style="font-weight: 600; font-size: 11px; text-transform: uppercase; color: #64748b; margin-bottom: 4px; letter-spacing: 0.5px;">บริษัททรัพย์สิน</div>']
    for co_name, co_rgb in COMPANY_MAP_RGB.items():
        c_cnt = co_counts.get(co_name, 0)
        if c_cnt > 0:
            hex_c = f"rgb({int(co_rgb[0])},{int(co_rgb[1])},{int(co_rgb[2])})"
            c_centroid = centroid_per_company.get(co_name, 0)
            centroid_tag = f' <span class="legend-centroid-badge" style="background:#fef3c7; color:#92400e; font-size:9.5px; font-weight:800; padding:0px 4px; border-radius:4px; border:1px solid #fde68a;">&#9651; {c_centroid:,}</span>' if c_centroid > 0 else ''
            legend_items_html.append(f'<div class="legend-item"><span class="legend-color" style="background:{hex_c};"></span>{html.escape(str(co_name), quote=True)} ({c_cnt:,}){centroid_tag}</div>')
    other_co_cnt = sum(cnt for co, cnt in co_counts.items() if co not in COMPANY_MAP_RGB)
    if other_co_cnt > 0:
        other_co_names = [co for co in co_counts.index if co not in COMPANY_MAP_RGB]
        other_co_centroid = sum(centroid_per_company.get(co, 0) for co in other_co_names)
        other_centroid_tag = f' <span class="legend-centroid-badge" style="background:#fef3c7; color:#92400e; font-size:9.5px; font-weight:800; padding:0px 4px; border-radius:4px; border:1px solid #fde68a;">&#9651; {other_co_centroid:,}</span>' if other_co_centroid > 0 else ''
        legend_items_html.append(f'<div class="legend-item"><span class="legend-color" style="background:#94a3b8;"></span>อื่นๆ ({other_co_cnt:,}){other_centroid_tag}</div>')
    total_centroid_count = sum(centroid_per_company.values())
    if total_centroid_count > 0:
        legend_items_html.append(f'<div class="legend-centroid-summary" style="border-top:1px dashed #e2e8f0; margin-top:5px; padding-top:5px; font-size:10.5px; color:#92400e; font-weight:700;">&#9651; พิกัดกึ่งกลาง {total_centroid_count:,} จาก {len(map_data):,} จุด</div>')
    legend_content = "\n".join(legend_items_html)

    if 'ลิงก์' in map_data.columns:
        _lnk = map_data['ลิงก์'].fillna('').astype(str).str.strip()
        # Route LED Legal to dedicated led_legal_bridge.html
        if 'บริษัท' in map_data.columns:
            is_legal = map_data['บริษัท'].astype(str).str.strip().str.upper().isin(['LED LEGAL', 'LED_LEGAL', 'LED_SOLD'])
            if is_legal.any():
                _lnk = _lnk.copy()
                _lnk.loc[is_legal] = _lnk.loc[is_legal].str.replace('led_bridge.html', 'led_legal_bridge.html', regex=False)
        links = _lnk.where(~_lnk.isin(['', 'nan', 'None', '-']), '').tolist()
    else:
        links = [''] * len(map_data)

    if progress_bar is not None:
        progress_bar.progress(80, text="กำลังบีบอัด GZIP และแปลงเป็น Base64 (80%)...")

    _co_cat = pd.Categorical(map_data['บริษัท'].fillna('-').astype(str).str.strip())
    _ty_series = map_data['ประเภททรัพย์'].fillna('-').astype(str).str.strip()
    _ty_counts = _ty_series.value_counts()
    _ordered_types = [t for t in _ty_counts.index if t and t != '-'] + ['-']
    _ty_cat = pd.Categorical(_ty_series, categories=_ordered_types)
    _pv_cat = pd.Categorical(map_data['จังหวัด'].fillna('-').astype(str).str.strip())
    _st_col = map_data['ประเภทการขาย'].fillna('ไม่ระบุ').astype(str).str.strip() if 'ประเภทการขาย' in map_data.columns else pd.Series(['ไม่ระบุ'] * len(map_data), index=map_data.index)
    _st_cat = pd.Categorical(_st_col)
    _rg_col = map_data['ภาค'].fillna('ไม่ระบุ').astype(str).str.strip() if 'ภาค' in map_data.columns else pd.Series(['ไม่ระบุ'] * len(map_data), index=map_data.index)
    _rg_cat = pd.Categorical(_rg_col)
    _dt_col = map_data['อำเภอ'].fillna('ไม่ระบุ').astype(str).str.strip() if 'อำเภอ' in map_data.columns else pd.Series(['ไม่ระบุ'] * len(map_data), index=map_data.index)
    _dt_cat = pd.Categorical(_dt_col)
    _subdt_col = map_data['ตำบล'].fillna('ไม่ระบุ').astype(str).str.strip() if 'ตำบล' in map_data.columns else pd.Series(['ไม่ระบุ'] * len(map_data), index=map_data.index)
    _subdt_cat = pd.Categorical(_subdt_col)
    _prj_col = map_data['โครงการ'].fillna('-').astype(str).str.strip() if 'โครงการ' in map_data.columns else (
        map_data['ชื่อโครงการ'].fillna('-').astype(str).str.strip() if 'ชื่อโครงการ' in map_data.columns else pd.Series(['-'] * len(map_data), index=map_data.index)
    )
    _prj_col = _prj_col.replace({'': '-', 'nan': '-', 'None': '-', 'null': '-', 'undefined': '-'})
    _prj_cat = pd.Categorical(_prj_col)

    _plain_col = map_data['โจทก์'].fillna('').astype(str).str.strip() if 'โจทก์' in map_data.columns else pd.Series([''] * len(map_data), index=map_data.index)
    _plain_col = _plain_col.replace({'nan': '', 'None': '', 'null': '', '<NA>': '', '-': ''})
    _plain_cat = pd.Categorical(_plain_col)

    proj_src = df_project_source if df_project_source is not None else df
    if proj_src is not None and not proj_src.empty:
        sam_projs_list, _, sam_only, other_only, proj_stats = get_sam_project_options(
            proj_src, cache_key=(data_mtime, len(proj_src)), return_meta=True
        )
    else:
        sam_projs_list, sam_only, other_only, proj_stats = [], [], [], {}

    lookup_obj = {
        'co': _co_cat.categories.tolist(),
        'co_rgb': [COMPANY_MAP_RGB.get(c, DEFAULT_COLOR) for c in _co_cat.categories.tolist()],
        'ty': _ty_cat.categories.tolist(),
        'pv': _pv_cat.categories.tolist(),
        'st': _st_cat.categories.tolist(),
        'rg': _rg_cat.categories.tolist(),
        'dt': _dt_cat.categories.tolist(),
        'subdt': _subdt_cat.categories.tolist(),
        'prj': _prj_cat.categories.tolist(),
        'plaintiff': _plain_cat.categories.tolist(),
        'sam_prj': sam_only,
        'other_prj': other_only,
        'all_prj': sam_projs_list,
        'prj_stats': proj_stats,
    }
    lookup_b64 = base64.b64encode(
        gzip.compress(
            json.dumps(lookup_obj, ensure_ascii=False).encode('utf-8'),
            compresslevel=1
        )
    ).decode('utf-8')

    deeds = map_data['เลขโฉนด'].fillna('').astype(str).values if 'เลขโฉนด' in map_data.columns else [''] * len(map_data)

    # Floor numeric extraction
    if 'ชั้น' in map_data.columns:
        fl_raw = map_data['ชั้น']
        fl_num = pd.to_numeric(fl_raw, errors='coerce')
        fl_str = fl_raw.astype(str)
        needs_extract = fl_num.isna() & fl_str.str.contains(r'\d', na=False)
        extracted = pd.to_numeric(fl_str[needs_extract].str.extract(r'(\d+(?:\.\d+)?)', expand=False), errors='coerce')
        fl_final = np.where(fl_num.notna() & (fl_num >= 0), fl_num, -1.0).astype('float32')
        fl_final[needs_extract.values] = np.where(extracted.notna() & (extracted >= 0), extracted, -1.0)
        fl_final = fl_final.round(1).astype('float32')
    else:
        fl_final = np.full(len(map_data), -1.0, dtype='float32')

    # Bedrooms
    if 'ห้องนอน' in map_data.columns:
        bed_raw = map_data['ห้องนอน']
        bed_num = pd.to_numeric(bed_raw, errors='coerce')
        is_studio = bed_raw.astype(str).str.contains('สตูดิโอ|studio', case=False, na=False)
        bed_final = np.nan_to_num(
            np.where(is_studio, 0.0, np.where(bed_num.notna() & (bed_num >= 0), bed_num, -1.0)),
            nan=-1.0, posinf=-1.0, neginf=-1.0
        ).round(0).astype('int32')
    else:
        bed_final = np.full(len(map_data), -1, dtype='int32')

    # Bathrooms
    if 'ห้องน้ำ' in map_data.columns:
        bath_raw = map_data['ห้องน้ำ']
        bath_num = pd.to_numeric(bath_raw, errors='coerce')
        bath_final = np.nan_to_num(
            np.where(bath_num.notna() & (bath_num >= 0), bath_num, -1.0),
            nan=-1.0, posinf=-1.0, neginf=-1.0
        ).round(0).astype('int32')
    else:
        bath_final = np.full(len(map_data), -1, dtype='int32')

    # Parking
    if 'ที่จอดรถ' in map_data.columns:
        pkg_raw = map_data['ที่จอดรถ']
        pkg_num = pd.to_numeric(pkg_raw, errors='coerce')
        pkg_final = np.nan_to_num(
            np.where(pkg_num.notna() & (pkg_num >= 0), pkg_num, -1.0),
            nan=-1.0, posinf=-1.0, neginf=-1.0
        ).round(0).astype('int32')
    else:
        pkg_final = np.full(len(map_data), -1, dtype='int32')

    # Listing age in days
    if 'วันประกาศ' in map_data.columns:
        u_ann = map_data['วันประกาศ'].dropna().unique()
        age_map = {u: parse_listing_age_days(u) for u in u_ann}
        age_s = map_data['วันประกาศ'].map(age_map).fillna(-1.0).copy()

        # For LED Legal (sold properties): calculate (วันที่ขาย - วันประกาศ)
        if 'วันที่ขาย' in map_data.columns and 'บริษัท' in map_data.columns:
            legal_mask = (
                map_data['บริษัท'].astype(str).str.strip().str.upper().isin(['LED LEGAL', 'LED_LEGAL', 'LED_SOLD'])
                & map_data['วันประกาศ'].notna()
                & map_data['วันที่ขาย'].notna()
            )
            if legal_mask.any():
                sub_legal = map_data.loc[legal_mask, ['วันประกาศ', 'วันที่ขาย']].drop_duplicates()
                legal_age_map = {}
                for _, r_dt in sub_legal.iterrows():
                    ann_v, sold_v = r_dt['วันประกาศ'], r_dt['วันที่ขาย']
                    try:
                        s_dt = _parse_sold_date_value(sold_v)
                        if pd.notna(s_dt):
                            diff = parse_listing_age_days(ann_v, ref_date=s_dt.date())
                            if diff >= 0:
                                legal_age_map[(ann_v, sold_v)] = float(diff)
                    except Exception:
                        pass
                if legal_age_map:
                    legal_vals = [
                        legal_age_map.get((a, b))
                        for a, b in zip(map_data.loc[legal_mask, 'วันประกาศ'], map_data.loc[legal_mask, 'วันที่ขาย'])
                    ]
                    valid_legal = [v is not None for v in legal_vals]
                    if any(valid_legal):
                        target_l_idx = map_data.loc[legal_mask].index[valid_legal]
                        age_s.loc[target_l_idx] = [v for v in legal_vals if v is not None]

        age_final = np.nan_to_num(age_s.values, nan=-1.0, posinf=-1.0, neginf=-1.0).round(0).astype('int32')
    else:
        age_final = np.full(len(map_data), -1, dtype='int32')

    # Sold price & Sold date (for LED Legal)
    if 'ราคาขายได้' in map_data.columns:
        sold_p_raw = pd.to_numeric(map_data['ราคาขายได้'], errors='coerce').fillna(0).values
        sold_p_num = np.nan_to_num(sold_p_raw, nan=0.0, posinf=0.0, neginf=0.0).round(0).astype('int64')
    else:
        sold_p_num = np.zeros(len(map_data), dtype='int64')

    if 'วันที่ขาย' in map_data.columns:
        sold_date_list = map_data['วันที่ขาย'].fillna('').astype(str).str.strip().tolist()
    else:
        sold_date_list = [''] * len(map_data)

    # Color RGB and Thai baht _price_str are reconstructed on client from _lut.co_rgb[_ci] and _p
    csv_df = pd.DataFrame({
        'lon': np.round(map_data['ลองจิจูด'].values.astype('float64'), 6),
        'lat': np.round(map_data['ละติจูด'].values.astype('float64'), 6),
        '_title': titles,
        '_id':    ids,
        '_ci':    _co_cat.codes.astype('int16'),
        '_ti':    _ty_cat.codes.astype('int16'),
        '_pi':    _pv_cat.codes.astype('int16'),
        '_sti':   _st_cat.codes.astype('int16'),
        '_rgi':   _rg_cat.codes.astype('int16'),
        '_dti':   _dt_cat.codes.astype('int16'),
        '_subdti': _subdt_cat.codes.astype('int16'),
        '_prji':  _prj_cat.codes.astype('int32'),
        '_p':     np.nan_to_num(_prices_num.fillna(0).values, nan=0.0, posinf=0.0, neginf=0.0).round(0).astype('int64'),
        '_up':    np.nan_to_num(_unit_prices, nan=0.0, posinf=0.0, neginf=0.0).round(0).astype('int64'),
        '_sqw':   np.nan_to_num(_sqw_calc, nan=0.0).round(1).astype('float32'),
        '_sqm':   np.nan_to_num(_sqm_calc, nan=0.0).round(1).astype('float32'),
        '_puw':   np.nan_to_num(_p_wah_calc, nan=0.0, posinf=0.0, neginf=0.0).round(0).astype('int64'),
        '_pum':   np.nan_to_num(_p_sqm_calc, nan=0.0, posinf=0.0, neginf=0.0).round(0).astype('int64'),
        '_fl':    fl_final,
        '_bed':   bed_final,
        '_bath':  bath_final,
        '_pkg':   pkg_final,
        '_age':   age_final,
        '_link':     links,
        '_centroid': centroid_flags,
        '_deed':     deeds,
        '_pti':      _plain_cat.codes.astype('int32' if (_plain_cat.codes.max() > 32767 if len(_plain_cat.codes) > 0 else False) else 'int16'),
        '_sold_p':   sold_p_num,
        '_sold_date': sold_date_list,
    })

    csv_base64 = base64.b64encode(
        gzip.compress(
            csv_df.to_csv(index=False).encode('utf-8'),
            compresslevel=1
        )
    ).decode('utf-8')

    return csv_base64, lookup_b64, legend_content, map_data_full_len

@st.cache_data(show_spinner=False)
def get_precomputed_map_payload(data_mtime):
    """Precomputes and caches the entire 440k dataset map data, GZIP csv_base64, and lookup_b64."""
    df = load_properties_data(data_mtime)
    return build_map_payload_from_df(
        df,
        df_project_source=df,
        data_mtime=data_mtime,
        custom_companies={},
        custom_company="",
        custom_color="#6366f1",
    )

@st.cache_resource(show_spinner=False, max_entries=2)
def _build_full_map_html_v2(data_mtime, tmpl_mtime, cache_builder_ver="1"):
    """Builds the slimmed nationwide map HTML once per (data, template, builder) version.

    Writes the heavy map payload to static/map_payload_cache.js so the iframe HTML
    stays ~1.5 MB instead of 84 MB, while browser clients share the parsed dataset via
    window.parent.__NOVA_MAP_CACHE__. Falls back to inline injection if static write fails.
    """
    csv_base64, lookup_b64, legend_content, map_data_full_len = get_precomputed_map_payload(data_mtime)
    if map_data_full_len == 0:
        return None, 0

    static_ok = ensure_static_map_payload_file(data_mtime, lookup_b64, csv_base64)
    csv_inject = "" if static_ok else csv_base64
    lut_inject = "" if static_ok else lookup_b64

    base_tmpl = get_base_map_html(tmpl_mtime)
    if not base_tmpl:
        return None, 0

    atlas_uri, icon_mapping = get_map_icon_atlas_and_mapping(128)
    icon_mapping_json = json.dumps(icon_mapping, ensure_ascii=False)

    company_logos_dict = get_leaflet_logo_dict(72)
    company_logos_json = json.dumps(company_logos_dict, ensure_ascii=False)

    df = load_properties_data(data_mtime)
    all_provinces_list = sorted(list({
        str(p).strip().strip(" ,;.-'\"")
        for p in df['จังหวัด'].dropna().unique()
        if str(p).strip().strip(" ,;.-'\"") and str(p).strip().strip(" ,;.-'\"") not in ['-', 'ไม่มีข้อมูล', 'nan', 'None'] and not re.search(r'\d', str(p)) and re.search(r'^[ก-๙]', str(p).strip())
    })) if df is not None and not df.empty else []
    all_provinces_json = json.dumps(all_provinces_list, ensure_ascii=False)

    html = base_tmpl.replace("CSV_BASE64_PLACEHOLDER", csv_inject)
    html = html.replace("LOOKUP_BASE64_PLACEHOLDER", lut_inject)
    html = html.replace("DATA_MTIME_PLACEHOLDER", get_data_mtime_token(data_mtime))
    html = html.replace("CACHE_BUILDER_VER_PLACEHOLDER", str(cache_builder_ver))
    html = html.replace("LEGEND_ITEMS_PLACEHOLDER", legend_content)
    html = html.replace("ATLAS_BASE64_PLACEHOLDER", atlas_uri)
    html = html.replace("ICON_MAPPING_PLACEHOLDER", icon_mapping_json)
    html = html.replace("COMPANY_LOGOS_PLACEHOLDER", company_logos_json)
    html = html.replace("ALL_PROVINCES_PLACEHOLDER", all_provinces_json)
    html = html.replace("CUSTOM_COMPANY_COLORS_PLACEHOLDER", '"ไฟล์นำเข้า": "#6366f1"')
    return html, map_data_full_len

def precompute_full_map_html(data_mtime):
    """Pre-assembles the map HTML with all heavy data offloaded to static/map_payload_cache.js."""
    _tmpl_path = str(_resolve_root_file("static/map_template.html"))
    _tmpl_mtime = os.path.getmtime(_tmpl_path) if os.path.exists(_tmpl_path) else None
    _builder_ver = get_cache_builder_version()

    # Self-heal if static payload file is missing even though resource/session cache exists
    if not os.path.exists(STATIC_MAP_PAYLOAD_PATH):
        csv_b64, lut_b64, _, _cnt = get_precomputed_map_payload(data_mtime)
        if _cnt > 0:
            ensure_static_map_payload_file(data_mtime, lut_b64, csv_b64)

    if (
        "cached_map_html_base" in st.session_state
        and st.session_state.get("cached_map_tmpl_mtime") == _tmpl_mtime
        and st.session_state.get("cached_map_data_mtime") == data_mtime
        and st.session_state.get("cached_map_builder_ver") == _builder_ver
    ):
        return

    html, map_data_full_len = _build_full_map_html_v2(data_mtime, _tmpl_mtime, _builder_ver)
    if not html:
        return

    # Session only stores a reference to the shared string (no extra memory per user)
    st.session_state["cached_map_html_base"] = html
    st.session_state["cached_map_data_len"] = map_data_full_len
    st.session_state["cached_map_tmpl_mtime"] = _tmpl_mtime
    st.session_state["cached_map_data_mtime"] = data_mtime
    st.session_state["cached_map_builder_ver"] = _builder_ver
