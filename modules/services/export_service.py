import html
import io
import re
import pandas as pd
import streamlit as st

from modules.config.constants import COMPANY_COLORS
from modules.services.data_cleaner import format_coord_vectorized

_SAFE_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
_RAI_NGAN_WAH_RE = re.compile(r'^\d+-\d+-\d+(?:\.\d+)?$')


def _safe_hex_color(val, default="#6366f1"):
    s = str(val or "").strip()
    return s if _SAFE_HEX_COLOR_RE.match(s) else default


def _sanitize_csv_text(val):
    if not isinstance(val, str):
        return val
    stripped = val.lstrip()
    if not stripped:
        return val
    # Preserve intentional Excel text formatting for Thai Rai-Ngan-Wah notation e.g. ="1-2-30"
    if re.match(r'^="\d+-\d+-\d+(?:\.\d+)?"$', stripped):
        return val
    if stripped[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + val
    return val


def _invalidate_imported_view_caches():
    st.session_state.pop("_merged_df_cache_key", None)
    st.session_state.pop("_merged_df_cache", None)
    st.session_state.pop("cached_map_html_base", None)
    st.session_state["_custom_import_ver"] = int(st.session_state.get("_custom_import_ver", 0)) + 1


def _sync_legacy_custom_keys():
    """Keep legacy single-company session keys aligned after add/delete."""
    all_saved_cos = st.session_state.get("imported_custom_companies")
    if isinstance(all_saved_cos, dict) and all_saved_cos:
        first_co_name = next(iter(all_saved_cos))
        first_co_conf = all_saved_cos[first_co_name] or {}
        st.session_state["imported_custom_company"] = first_co_name
        st.session_state["imported_custom_company_label"] = first_co_name
        st.session_state["imported_custom_symbol"] = first_co_conf.get("symbol", "IMP")
        st.session_state["imported_custom_color"] = first_co_conf.get("color", "#6366f1")
    else:
        for k in ("imported_custom_companies", "imported_custom_company", "imported_custom_company_label", "imported_custom_symbol", "imported_custom_color"):
            st.session_state.pop(k, None)

DEFAULT_NEW_CO_PALETTE = [
    "#6366f1", "#ec4899", "#14b8a6", "#f59e0b", "#8b5cf6",
    "#06b6d4", "#10b981", "#f43f5e", "#84cc16", "#3b82f6",
    "#e11d48", "#d97706", "#a855f7", "#0284c7", "#f97316"
]

KNOWN_SYSTEM_SYMBOLS = {
    "LED", "SAM", "BAM", "CHY", "GHB", "KBK", "KTB", "SCB", "GSB",
    "DDP", "LVI", "NYO", "ZMY", "BAA", "IMP"
}

def generate_default_symbol(company_name):
    """Generates default 3-character uppercase symbol for a company name."""
    clean = re.sub(r'^(บจก\.|บมจ\.|บริษัท|หจก\.)\s*', '', str(company_name).strip(), flags=re.I)
    clean = re.sub(r'\s*(จำกัด|มหาชน)$', '', clean, flags=re.I)
    clean = re.sub(r'[^a-zA-Z0-9\u0E00-\u0E7F]', '', clean).strip()
    if not clean:
        clean = "IMP"
    return clean[:3].upper()

_CSV_AREA_TEXT_COLS = ('เนื้อที่ (ตร.ว.)', 'เนื้อที่ (ไร่-งาน-ตร.ว.)', 'เนื้อที่')


def _prepare_export_df(df, for_csv=False):
    """Formats coordinates with centroid indicators and strips internal '_' columns only at export time."""
    if df is None or df.empty:
        return df
    export_cols = [c for c in df.columns if not c.startswith('_')]
    out = df[export_cols].copy()
    for coord_col in ('ละติจูด', 'ลองจิจูด'):
        if coord_col in out.columns and not pd.api.types.is_string_dtype(out[coord_col]):
            out[coord_col] = format_coord_vectorized(df, coord_col)
    if for_csv:
        for area_col in _CSV_AREA_TEXT_COLS:
            if area_col in out.columns:
                out[area_col] = (
                    out[area_col]
                    .fillna('')
                    .astype(str)
                    .str.strip()
                    .replace({'nan': '', 'None': '', '<NA>': ''})
                    .str.replace(r'^(\d+-\d+-\d+(?:\.\d+)?)$', r'="\1"', regex=True)
                )
        # Neutralize CSV formula injection across all text/categorical columns
        for col in out.columns:
            dt = out[col].dtype
            if pd.api.types.is_string_dtype(dt) or pd.api.types.is_object_dtype(dt) or isinstance(dt, pd.CategoricalDtype):
                out[col] = out[col].map(_sanitize_csv_text)
    return out

def convert_df_to_csv(df):
    """Direct CSV generator returning UTF-8 with BOM bytes."""
    if df is None or df.empty:
        return b""
    df_out = _prepare_export_df(df, for_csv=True)
    return df_out.to_csv(index=False).encode('utf-8-sig')

def convert_df_to_excel(df):
    """High-performance Excel generator using xlsxwriter with constant_memory."""
    if df is None or df.empty:
        return b""
    df_out = _prepare_export_df(df)
    excel_buffer = io.BytesIO()
    try:
        with pd.ExcelWriter(excel_buffer, engine='xlsxwriter', engine_kwargs={'options': {'constant_memory': True}}) as writer:
            df_out.to_excel(writer, index=False, sheet_name='Assets')
    except Exception:
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df_out.to_excel(writer, index=False, sheet_name='Assets')
    return excel_buffer.getvalue()

def render_import_export_section(df_to_export, filename_prefix="npa_data", key_suffix=""):
    """Renders side-by-side Import (Excel/CSV with multi-company support) and Export (Excel/CSV) UI."""
    st.markdown("<br/>", unsafe_allow_html=True)
    st.markdown("##### <i class='fa-solid fa-arrow-right-arrow-left' style='color:#059669; margin-right:6px;'></i>นำเข้าและส่งออกข้อมูล (Import & Export Data)", unsafe_allow_html=True)
    col_imp, col_exp = st.columns(2)
    
    # Left: Import File
    with col_imp:
        st.markdown("###### <i class='fa-solid fa-file-import' style='color:#64748b; margin-right:6px;'></i>นำเข้าข้อมูลเพิ่มเติม (Import File)", unsafe_allow_html=True)
        uploaded_file = st.file_uploader(
            "เลือกไฟล์ Excel หรือ CSV เพื่อเพิ่มข้อมูล", 
            type=["xlsx", "xls", "csv"], 
            key=f"custom_file_uploader_{key_suffix}",
            help="รองรับไฟล์ที่มีคอลัมน์: บริษัท, ประเภททรัพย์, ราคา, ละติจูด, ลองจิจูด, จังหวัด ฯลฯ"
        )
        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    u_df = None
                    for enc in ['utf-8-sig', 'utf-8', 'cp874', 'tis-620']:
                        try:
                            uploaded_file.seek(0)
                            u_df = pd.read_csv(uploaded_file, encoding=enc)
                            break
                        except Exception:
                            continue
                    if u_df is None:
                        uploaded_file.seek(0)
                        u_df = pd.read_csv(uploaded_file, encoding='utf-8', encoding_errors='replace')
                else:
                    u_df = pd.read_excel(uploaded_file)
                
                if not u_df.empty:
                    # Clean and inspect companies
                    has_company_col = 'บริษัท' in u_df.columns
                    u_work_df = u_df.copy()
                    
                    if not has_company_col:
                        u_work_df['บริษัท'] = "ไฟล์นำเข้า"
                    else:
                        blank_mask = (
                            u_work_df['บริษัท'].isna() | 
                            u_work_df['บริษัท'].astype(str).str.strip().isin(['', 'nan', 'None', 'null', '<NA>', 'NaN', '-'])
                        )
                        if blank_mask.any():
                            u_work_df.loc[blank_mask, 'บริษัท'] = "ไฟล์นำเข้า"
                        u_work_df['บริษัท'] = u_work_df['บริษัท'].astype(str).str.strip()
                    
                    co_counts = u_work_df['บริษัท'].value_counts()
                    total_detected_cos = len(co_counts)
                    
                    st.success(f"อ่านไฟล์สำเร็จ ({len(u_work_df):,} รายการ จาก {total_detected_cos:,} บริษัท)")
                    
                    # Separate known vs new companies
                    known_keys_upper = {k.upper(): k for k in COMPANY_COLORS.keys()}
                    known_cos = []
                    new_cos = []
                    
                    for co_name, cnt in co_counts.items():
                        co_upper = str(co_name).strip().upper()
                        if co_upper in known_keys_upper:
                            known_cos.append((known_keys_upper[co_upper], cnt))
                        else:
                            new_cos.append((str(co_name), cnt))
                    
                    # 1. Inform if known system companies are found
                    if known_cos:
                        known_desc = ", ".join([f"**{c}** ({cnt:,})" for c, cnt in known_cos])
                        st.info(
                            f"**ตรวจพบ {len(known_cos)} บริษัทมาตรฐานในระบบ:** {known_desc}<br/>"
                            f"<span style='font-size:12px; color:#475569;'>ระบบจะใช้สีองค์กรและโลโก้มาตรฐานเดิมอัตโนมัติ ไม่ต้องตั้งค่าซ้ำ</span>",
                            icon=":material/verified:"
                        )
                    
                    # 2. Accordions for new companies
                    configured_new_cos = {}
                    entered_symbols = {}
                    
                    if new_cos:
                        st.markdown(
                            "<div style='margin-top:10px; margin-bottom:6px;'>"
                            "<span style='font-size:13px; font-weight:700; color:#1e293b;'>"
                            "<i class='fa-solid fa-sliders' style='color:#6366f1; margin-right:6px;'></i>"
                            f"ตั้งค่าตัวย่อและสีหมุดสำหรับบริษัทใหม่ ({len(new_cos)} บริษัท):"
                            "</span>"
                            "</div>",
                            unsafe_allow_html=True
                        )
                        
                        existing_cos_state = st.session_state.get("imported_custom_companies", {})
                        
                        for idx, (co_name, cnt) in enumerate(new_cos):
                            default_sym = generate_default_symbol(co_name)
                            default_col = DEFAULT_NEW_CO_PALETTE[idx % len(DEFAULT_NEW_CO_PALETTE)]
                            
                            saved_conf = existing_cos_state.get(co_name, {}) if isinstance(existing_cos_state, dict) else {}
                            init_sym = saved_conf.get("symbol", default_sym)
                            init_col = saved_conf.get("color", default_col)
                            
                            with st.expander(f"{co_name} ({cnt:,} รายการ)", expanded=(len(new_cos) <= 3 or idx == 0), icon=":material/business:"):
                                c_sym_col, c_color_col = st.columns([1, 1])
                                with c_sym_col:
                                    sym_val = st.text_input(
                                        "ตัวย่อบนหมุด",
                                        value=init_sym,
                                        max_chars=4,
                                        key=f"custom_sym_input_{key_suffix}_{idx}_{co_name}",
                                        help=f"ตัวอักษร 1-4 ตัวบนหมุดแผนที่ (เริ่มต้นจาก 3 ตัวแรกของ '{co_name}')"
                                    ).strip().upper()
                                with c_color_col:
                                    color_val = st.color_picker(
                                        "เลือกสีหมุด",
                                        value=init_col,
                                        key=f"custom_color_picker_{key_suffix}_{idx}_{co_name}",
                                        help="สีนี้จะใช้แสดงเป็นขอบหมุดและจุดสีใน Legend"
                                    )
                                configured_new_cos[co_name] = {"symbol": sym_val, "color": color_val}
                                entered_symbols[co_name] = sym_val
                    
                    # 3. Validation
                    is_valid = True
                    validation_errors = []
                    
                    # Check empty symbols
                    empty_sym_cos = [html.escape(str(co), quote=True) for co, sym in entered_symbols.items() if not sym]
                    if empty_sym_cos:
                        is_valid = False
                        validation_errors.append(f"กรุณาระบุตัวย่อบนหมุดให้ครบถ้วน (ว่าง: {', '.join(empty_sym_cos)})")
                    
                    # Check duplicates among entered symbols
                    sym_groups = {}
                    for co, sym in entered_symbols.items():
                        if sym:
                            sym_groups.setdefault(sym, []).append(co)
                    
                    for sym, cos in sym_groups.items():
                        if len(cos) > 1:
                            is_valid = False
                            safe_sym = html.escape(str(sym), quote=True)
                            safe_cos = ", ".join(html.escape(str(c), quote=True) for c in cos)
                            validation_errors.append(f"ตัวย่อ <b>'{safe_sym}'</b> ซ้ำกันระหว่างบริษัท: {safe_cos}")
                    
                    # Check duplicates against standard system symbols or company names
                    known_upper_names = {k.upper() for k in COMPANY_COLORS.keys()}
                    for co, sym in entered_symbols.items():
                        if sym in KNOWN_SYSTEM_SYMBOLS or sym in known_upper_names:
                            is_valid = False
                            safe_sym = html.escape(str(sym), quote=True)
                            safe_co = html.escape(str(co), quote=True)
                            validation_errors.append(f"ตัวย่อ <b>'{safe_sym}'</b> ของ <i>'{safe_co}'</i> ซ้ำกับบริษัทมาตรฐานในระบบ ({safe_sym})")
                    
                    # Check duplicates against previously imported custom companies
                    existing_saved_cos = st.session_state.get("imported_custom_companies", {})
                    if isinstance(existing_saved_cos, dict):
                        for co, sym in entered_symbols.items():
                            for ex_co, ex_conf in existing_saved_cos.items():
                                if ex_co != co and isinstance(ex_conf, dict) and ex_conf.get("symbol") == sym:
                                    is_valid = False
                                    validation_errors.append(f"ตัวย่อ <b>'{sym}'</b> ของ <i>'{co}'</i> ซ้ำกับบริษัทที่เคยนำเข้าไว้: <i>'{ex_co}'</i>")
                    
                    # Show errors or success message
                    if not is_valid:
                        err_html = "<br/>".join([f"• {e}" for e in validation_errors])
                        st.markdown(
                            f'''<div style="background:rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.3); border-radius:8px; padding:10px 14px; margin:10px 0;">
                                <div style="color:#b91c1c; font-size:12.5px; font-weight:700; margin-bottom:4px;">
                                    <i class="fa-solid fa-triangle-exclamation" style="margin-right:6px;"></i>ตรวจพบข้อผิดพลาด กรุณาแก้ไขตัวย่อไม่ให้ซ้ำกัน:
                                </div>
                                <div style="color:#dc2626; font-size:12px; line-height:1.5;">{err_html}</div>
                            </div>''',
                            unsafe_allow_html=True
                        )
                    elif new_cos:
                        st.markdown(
                            '''<div style="background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.3); border-radius:8px; padding:8px 12px; margin:10px 0;">
                                <div style="color:#047857; font-size:12px; font-weight:600;">
                                    <i class="fa-solid fa-circle-check" style="margin-right:6px;"></i>ตัวย่อและสีหมุดถูกต้องครบถ้วน ไม่พบการซ้ำซ้อน พร้อมรวมข้อมูล
                                </div>
                            </div>''',
                            unsafe_allow_html=True
                        )
                    
                    # 4. Merge Button
                    if st.button("รวมเข้ากับฐานข้อมูลหลัก", icon=":material/merge:", key=f"btn_apply_import_{key_suffix}", disabled=not is_valid, use_container_width=True):
                        from modules.services.data_cleaner import ensure_derived_cols
                        
                        # Prepare data
                        u_clean = u_work_df.copy()
                        
                        # Standardize known company names in u_clean if casing differs
                        if known_keys_upper:
                            u_clean['บริษัท'] = u_clean['บริษัท'].apply(
                                lambda c: known_keys_upper.get(str(c).strip().upper(), str(c).strip())
                            )
                        
                        # Update session state metadata
                        if "imported_custom_companies" not in st.session_state or not isinstance(st.session_state["imported_custom_companies"], dict):
                            st.session_state["imported_custom_companies"] = {}
                        
                        for co_name, conf in configured_new_cos.items():
                            st.session_state["imported_custom_companies"][co_name] = conf
                        
                        # Update legacy single-company keys for backwards compatibility
                        all_saved_cos = st.session_state["imported_custom_companies"]
                        if all_saved_cos:
                            first_co_name = list(all_saved_cos.keys())[0]
                            first_co_conf = all_saved_cos[first_co_name]
                            st.session_state["imported_custom_company"] = first_co_name
                            st.session_state["imported_custom_company_label"] = first_co_name
                            st.session_state["imported_custom_symbol"] = first_co_conf.get("symbol", "IMP")
                            st.session_state["imported_custom_color"] = first_co_conf.get("color", "#6366f1")
                        
                        # Enrich derived cols
                        u_clean_derived = ensure_derived_cols(u_clean)
                        
                        # Append mode
                        if "imported_custom_df" in st.session_state and st.session_state["imported_custom_df"] is not None and not st.session_state["imported_custom_df"].empty:
                            prev_df = st.session_state["imported_custom_df"].copy()
                            for col in ['บริษัท', 'ประเภททรัพย์', 'จังหวัด', 'ภาค', 'ประเภทการขาย']:
                                if col in prev_df.columns and isinstance(prev_df[col].dtype, pd.CategoricalDtype):
                                    prev_df[col] = prev_df[col].astype(str)
                                if col in u_clean_derived.columns and isinstance(u_clean_derived[col].dtype, pd.CategoricalDtype):
                                    u_clean_derived[col] = u_clean_derived[col].astype(str)
                            combined_imp = pd.concat([prev_df, u_clean_derived], ignore_index=True)
                            st.session_state["imported_custom_df"] = combined_imp
                        else:
                            st.session_state["imported_custom_df"] = u_clean_derived
                        
                        # Clear caches
                        _invalidate_imported_view_caches()
                        st.success("นำเข้าข้อมูลสำเร็จแล้ว!")
                        st.rerun()
            except Exception as ex:
                st.error(f"อ่านไฟล์ไม่สำเร็จ: {ex}")
                
        # Status Card and Management (Clear All & Selective Delete)
        if "imported_custom_df" in st.session_state and st.session_state["imported_custom_df"] is not None and not st.session_state["imported_custom_df"].empty:
            imp_df_current = st.session_state["imported_custom_df"]
            imp_companies_dict = st.session_state.get("imported_custom_companies", {})
            total_imp_count = len(imp_df_current)
            co_counts = imp_df_current['บริษัท'].value_counts()
            
            badges_html = []
            for co_name, cnt in co_counts.items():
                co_str = str(co_name)
                if isinstance(imp_companies_dict, dict) and co_str in imp_companies_dict:
                    sym_show = imp_companies_dict[co_str].get("symbol", "IMP")
                    col_show = imp_companies_dict[co_str].get("color", "#6366f1")
                elif co_str in COMPANY_COLORS:
                    sym_show = co_str[:3].upper()
                    col_show = COMPANY_COLORS[co_str]
                else:
                    sym_show = st.session_state.get("imported_custom_symbol", "IMP")
                    col_show = st.session_state.get("imported_custom_color", "#6366f1")
                
                co_esc = html.escape(co_str, quote=True)
                sym_esc = html.escape(str(sym_show), quote=True)
                col_safe = _safe_hex_color(col_show)
                badge_item = (
                    f'<div style="display:inline-flex; align-items:center; background:#ffffff; border:1px solid #cbd5e1; '
                    f'border-radius:6px; padding:2px 8px; margin:3px 5px 3px 0; box-shadow:0 1px 2px rgba(0,0,0,0.04);">'
                    f'<span style="display:inline-block; border:1.5px solid {col_safe}; color:{col_safe}; background:#ffffff; '
                    f'font-size:10.5px; font-weight:800; border-radius:4px; padding:0px 5px; margin-right:6px;">{sym_esc}</span>'
                    f'<span style="color:#1e293b; font-size:12.5px; font-weight:600; margin-right:5px;">{co_esc}</span>'
                    f'<span style="color:#64748b; font-size:11.5px; font-weight:500;">({cnt:,})</span>'
                    f'</div>'
                )
                badges_html.append(badge_item)
            
            badges_container_html = "".join(badges_html)
            st.markdown(
                f'''<div style="background:rgba(99,102,241,0.06); border:1px solid rgba(99,102,241,0.22); border-radius:10px; padding:12px 14px; margin:12px 0 10px 0;">
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
                        <span style="color:#1e293b; font-weight:700; font-size:13.5px;">
                            <i class="fa-solid fa-layer-group" style="color:#6366f1; margin-right:6px;"></i>ข้อมูลนำเข้าสะสมทั้งหมด: <b style="color:#4f46e5;">{total_imp_count:,}</b> รายการ ({len(co_counts):,} บริษัท)
                        </span>
                    </div>
                    <div style="display:flex; flex-wrap:wrap; align-items:center;">
                        {badges_container_html}
                    </div>
                </div>''',
                unsafe_allow_html=True
            )
            
            col_del_all, col_del_sel = st.columns([1, 1])
            with col_del_all:
                if st.button("ล้างข้อมูลนำเข้าทั้งหมด", icon=":material/delete_forever:", key=f"btn_clear_all_{key_suffix}", use_container_width=True):
                    st.session_state.pop("imported_custom_df", None)
                    _sync_legacy_custom_keys()
                    st.session_state.pop("imported_custom_companies", None)
                    st.session_state.pop("imported_custom_company", None)
                    st.session_state.pop("imported_custom_company_label", None)
                    st.session_state.pop("imported_custom_symbol", None)
                    st.session_state.pop("imported_custom_color", None)
                    _invalidate_imported_view_caches()
                    st.rerun()
            
            with col_del_sel:
                with st.popover("ลบเฉพาะบางบริษัท", icon=":material/delete_sweep:", use_container_width=True):
                    st.markdown("<p style='font-size:12.5px; font-weight:600; color:#334155; margin-bottom:4px;'>เลือกบริษัทที่ต้องการลบออกจากระบบ:</p>", unsafe_allow_html=True)
                    avail_cos = sorted([str(c) for c in co_counts.keys()])
                    cos_to_remove = st.multiselect("บริษัท:", options=avail_cos, key=f"sel_cos_to_remove_{key_suffix}", label_visibility="collapsed")
                    if st.button("ยืนยันลบบริษัทที่เลือก", type="primary", key=f"btn_confirm_del_sel_{key_suffix}", use_container_width=True):
                        if cos_to_remove:
                            remaining_df = imp_df_current[~imp_df_current['บริษัท'].astype(str).isin(cos_to_remove)].copy()
                            if remaining_df.empty:
                                st.session_state.pop("imported_custom_df", None)
                                st.session_state.pop("imported_custom_companies", None)
                            else:
                                st.session_state["imported_custom_df"] = remaining_df
                                if "imported_custom_companies" in st.session_state and isinstance(st.session_state["imported_custom_companies"], dict):
                                    for rm_co in cos_to_remove:
                                        st.session_state["imported_custom_companies"].pop(rm_co, None)
                            _sync_legacy_custom_keys()
                            _invalidate_imported_view_caches()
                            st.rerun()

    # Right: Export File
    with col_exp:
        st.markdown("###### <i class='fa-solid fa-file-export' style='color:#64748b; margin-right:6px;'></i>ส่งออกข้อมูลในตาราง (Export Data)", unsafe_allow_html=True)
        if df_to_export is not None and not df_to_export.empty:
            n_rows = len(df_to_export)
            # Fingerprint = row count + hash of index -> different filters never reuse a stale file
            try:
                data_fp = (n_rows, int(pd.util.hash_pandas_object(df_to_export.index, index=False).sum()))
            except Exception:
                data_fp = (n_rows, tuple(df_to_export.columns))
            st.caption(f"ข้อมูลพร้อมส่งออกทั้งหมด **{n_rows:,}** รายการ")
            
            c_exp1, c_exp2 = st.columns(2)
            with c_exp1:
                csv_key = f"csv_data_{key_suffix}"
                csv_rows_key = f"csv_rows_{key_suffix}"
                
                if csv_key in st.session_state and st.session_state.get(csv_rows_key) != data_fp:
                    st.session_state.pop(csv_key, None)
                    st.session_state.pop(csv_rows_key, None)

                has_cached_csv = (
                    st.session_state.get(csv_rows_key) == data_fp and
                    csv_key in st.session_state and
                    isinstance(st.session_state[csv_key], bytes) and
                    len(st.session_state[csv_key]) > 0
                )

                if n_rows <= 10000:
                    st.download_button(
                        label="ส่งออก CSV (.csv)",
                        data=convert_df_to_csv(df_to_export),
                        file_name=f"{filename_prefix}.csv",
                        mime="text/csv",
                        icon=":material/download:",
                        use_container_width=True,
                        key=f"btn_export_csv_{key_suffix}",
                        help="ดาวน์โหลดทันที รองรับภาษาไทย UTF-8"
                    )
                else:
                    if has_cached_csv:
                        csv_data = st.session_state[csv_key]
                        size_mb = len(csv_data) / (1024 * 1024)
                        st.success(f"✅ ไฟล์ CSV พร้อมแล้ว ({size_mb:.1f} MB)")
                        st.download_button(
                            label=f"ดาวน์โหลด CSV ({n_rows:,} รายการ)",
                            data=csv_data,
                            file_name=f"{filename_prefix}.csv",
                            mime="text/csv",
                            icon=":material/download:",
                            use_container_width=True,
                            key=f"btn_export_csv_{key_suffix}",
                            help="คลิกเพื่อบันทึกไฟล์ CSV ลงในโฟลเดอร์ Downloads บนคอมพิวเตอร์ของคุณ"
                        )
                        if st.button("แปลงไฟล์ใหม่อีกครั้ง", key=f"btn_reset_csv_{key_suffix}", icon=":material/refresh:", help="คลิกเพื่อล้างและสร้างไฟล์ใหม่"):
                            st.session_state.pop(csv_key, None)
                            st.session_state.pop(csv_rows_key, None)
                            st.rerun()
                    else:
                        st.caption(f"ชุดข้อมูลใหญ่ ({n_rows:,} แถว) กดเพื่อเตรียมไฟล์")
                        if st.button(f"สร้างไฟล์ CSV (.csv)", icon=":material/description:", key=f"btn_prep_csv_{key_suffix}", use_container_width=True, help="คลิกเพื่อเริ่มแปลงข้อมูลเป็นไฟล์ CSV"):
                            with st.spinner(f"กำลังแปลงข้อมูล {n_rows:,} รายการเป็นไฟล์ CSV..."):
                                for _old_k in [k for k in st.session_state.keys() if str(k).startswith(("csv_data_", "csv_rows_"))]:
                                    st.session_state.pop(_old_k, None)
                                csv_bytes = convert_df_to_csv(df_to_export)
                                st.session_state[csv_key] = csv_bytes
                                st.session_state[csv_rows_key] = data_fp
                                st.rerun()

            with c_exp2:
                excel_key = f"excel_data_{key_suffix}"
                excel_rows_key = f"excel_rows_{key_suffix}"

                if excel_key in st.session_state and st.session_state.get(excel_rows_key) != data_fp:
                    st.session_state.pop(excel_key, None)
                    st.session_state.pop(excel_rows_key, None)

                has_cached_excel = (
                    st.session_state.get(excel_rows_key) == data_fp and
                    excel_key in st.session_state and
                    isinstance(st.session_state[excel_key], bytes) and
                    len(st.session_state[excel_key]) > 0
                )
                
                if n_rows <= 10000:
                    st.download_button(
                        label="ดาวน์โหลด Excel (.xlsx)",
                        data=convert_df_to_excel(df_to_export),
                        file_name=f"{filename_prefix}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        icon=":material/download:",
                        use_container_width=True,
                        key=f"btn_export_excel_{key_suffix}"
                    )
                else:
                    if has_cached_excel:
                        excel_data = st.session_state[excel_key]
                        size_mb = len(excel_data) / (1024 * 1024)
                        st.success(f"✅ ไฟล์ Excel พร้อมแล้ว ({size_mb:.1f} MB)")
                        st.download_button(
                            label=f"ดาวน์โหลด Excel (.xlsx) ({n_rows:,} รายการ)",
                            data=excel_data,
                            file_name=f"{filename_prefix}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            icon=":material/download:",
                            use_container_width=True,
                            key=f"btn_export_excel_{key_suffix}",
                            help="คลิกเพื่อบันทึกไฟล์ Excel ลงในโฟลเดอร์ Downloads บนคอมพิวเตอร์ของคุณ"
                        )
                        if st.button("แปลงไฟล์ Excel ใหม่อีกครั้ง", key=f"btn_reset_excel_{key_suffix}", icon=":material/refresh:", help="คลิกเพื่อล้างและสร้างไฟล์ใหม่"):
                            st.session_state.pop(excel_key, None)
                            st.session_state.pop(excel_rows_key, None)
                            st.rerun()
                    else:
                        st.caption(f"แนะนำ **CSV** สำหรับ {n_rows:,} แถว (เร็วและเบาที่สุด)")
                        if st.button(f"เตรียมไฟล์ Excel ({n_rows:,} รายการ)", icon=":material/table_view:", key=f"btn_prep_excel_{key_suffix}", use_container_width=True, help="คลิกเพื่อเริ่มแปลงข้อมูลเป็นไฟล์ Excel (.xlsx)"):
                            with st.spinner(f"กำลังแปลงข้อมูล {n_rows:,} รายการเป็น Excel ด้วย xlsxwriter (โปรดรอสักครู่)..."):
                                for _old_k in [k for k in st.session_state.keys() if str(k).startswith(("excel_data_", "excel_rows_"))]:
                                    st.session_state.pop(_old_k, None)
                                excel_bytes = convert_df_to_excel(df_to_export)
                                st.session_state[excel_key] = excel_bytes
                                st.session_state[excel_rows_key] = data_fp
                                st.rerun()
        else:
            st.info("ไม่มีข้อมูลสำหรับส่งออก")
