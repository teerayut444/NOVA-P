import pandas as pd
import streamlit as st

from modules.services.data_loader import get_data_mtime
from modules.services.export_service import render_import_export_section

fragment_decorator = getattr(st, "fragment", lambda f: f)


@st.cache_data(show_spinner=False, max_entries=6)
def _build_tab4_header_bundle(_df_filtered, cache_key=None):
    # Prepare empty dataframe (0 rows) showing all relevant column headers for maximum speed
    df_table_show = _df_filtered.head(0).copy()

    # Ensure all formatted/display columns exist in empty DataFrame
    if 'ราคา' in _df_filtered.columns and 'ราคาขาย (บาท)' not in df_table_show.columns:
        df_table_show['ราคาขาย (บาท)'] = pd.Series(dtype='float64')
    if 'รูปแปลงที่ดิน' not in df_table_show.columns:
        df_table_show['รูปแปลงที่ดิน'] = pd.Series(dtype='object')
    if 'ความแม่นยำพิกัด' not in df_table_show.columns:
        df_table_show['ความแม่นยำพิกัด'] = pd.Series(dtype='object')
    if ('เนื้อที่ (ตร.ว.)' in _df_filtered.columns or 'พื้นที่_ตารางวา' in _df_filtered.columns) and 'เนื้อที่ (ไร่-งาน-ตร.ว.)' not in df_table_show.columns:
        df_table_show['เนื้อที่ (ไร่-งาน-ตร.ว.)'] = pd.Series(dtype='object')
    if 'พื้นที่ใช้สอย (ตร.ม.)' in _df_filtered.columns and 'พื้นที่ใช้สอย (ตร.ม.)' not in df_table_show.columns:
        df_table_show['พื้นที่ใช้สอย (ตร.ม.)'] = pd.Series(dtype='float64')

    cols_table_raw = [
        "บริษัท", "ID", "รหัสทรัพย์", "ชื่อโครงการ", "ประเภททรัพย์", "ประเภทการขาย", "ราคาขาย (บาท)",
        "ตำบล", "อำเภอ", "จังหวัด", "ละติจูด", "ลองจิจูด", "ความแม่นยำพิกัด", "ชื่อประกาศ", "ลิงก์", "รูปแปลงที่ดิน",
        "เนื้อที่ (ไร่-งาน-ตร.ว.)", "พื้นที่ใช้สอย (ตร.ม.)", "วันที่ดึงข้อมูล",
        "ห้องนอน", "ห้องน้ำ", "ที่จอดรถ", "ชั้น", "วันประกาศ", "เลขโฉนด", "โจทก์", "ศาล", "ยอดเข้าชม", "ยอดคลิก", "ราคาขายได้", "วันที่ขาย"
    ]
    cols_present = [c for c in cols_table_raw if c in df_table_show.columns]
    df_table_show = df_table_show[cols_present]

    has_proj_t4 = False
    proj_col_key = 'ชื่อโครงการ' if 'ชื่อโครงการ' in _df_filtered.columns else ('โครงการ' if 'โครงการ' in _df_filtered.columns else None)
    if proj_col_key:
        uniq_projs = [str(v).strip() for v in _df_filtered[proj_col_key].dropna().unique()]
        has_proj_t4 = any(v not in ('', '-', 'nan', 'None', 'null', '<NA>') for v in uniq_projs)
    proj_t4_width = "medium" if has_proj_t4 else "small"
    return df_table_show, proj_t4_width


def precompute_tab4_inventory(df_raw, data_mtime=0):
    """Pre-warms Tab 4 table header structure and project column width check during the Welcome Screen."""
    if df_raw is None or df_raw.empty:
        return
    cache_key = (
        data_mtime or get_data_mtime(),
        len(df_raw),
        0,
    )
    _build_tab4_header_bundle(df_raw, cache_key=cache_key)


@fragment_decorator
def render_tab4_inventory_view(df_filtered, is_dark_mode):
    """
    Renders Tab 4: Property Listing / Inventory Explorer:
    - Previews column structure (header-only for maximum speed)
    - Full dataset CSV/Excel export section
    """
    if df_filtered is None or df_filtered.empty:
        st.warning("ไม่พบข้อมูลตามเงื่อนไข")
        return

    accent_c = "#34d399" if is_dark_mode else "#059669"
    sub_c = "#94a3b8" if is_dark_mode else "#475569"
    st.markdown(f"### <i class='fa-solid fa-table-list' style='color:{accent_c}; margin-right:8px;'></i>รายการทรัพย์สินทั้งหมด ({len(df_filtered):,} รายการ)", unsafe_allow_html=True)
    st.markdown(
        f"<div style='font-size:0.86rem; color:{sub_c}; margin:-6px 0 8px 0;'>"
        f"💡 แสดงเฉพาะหัวตาราง (Header Preview) เพื่อความรวดเร็วในการโหลดหน้า — "
        f"กรุณาใช้ปุ่ม <b>ส่งออก CSV / Excel</b> ด้านล่างเพื่อดาวน์โหลดข้อมูลครบทั้ง <b>{len(df_filtered):,}</b> รายการ"
        f"</div>",
        unsafe_allow_html=True,
    )

    cache_key = (
        get_data_mtime(),
        len(df_filtered),
        int(st.session_state.get("_custom_import_ver", 0)),
    )
    df_table_show, proj_t4_width = _build_tab4_header_bundle(df_filtered, cache_key=cache_key)

    st.dataframe(
        df_table_show,
        width="stretch",
        column_config={
            "ชื่อโครงการ": st.column_config.TextColumn("ชื่อโครงการ", width=proj_t4_width, help="ชื่อโครงการ / หมู่บ้าน / อาคารชุด"),
            "โครงการ": st.column_config.TextColumn("โครงการ", width=proj_t4_width, help="ชื่อโครงการ / หมู่บ้าน / อาคารชุด"),
            "ราคาขาย (บาท)": st.column_config.NumberColumn("ราคาขาย (บาท)", format="฿%,d"),
            "เนื้อที่ (ไร่-งาน-ตร.ว.)": st.column_config.TextColumn("เนื้อที่ (ไร่-งาน-ตร.ว.)"),
            "พื้นที่ใช้สอย (ตร.ม.)": st.column_config.NumberColumn("พื้นที่ใช้สอย (ตร.ม.)", format="%.1f"),
            "ยอดเข้าชม": st.column_config.NumberColumn("ยอดเข้าชม (วิว)", format="%,d"),
            "ยอดคลิก": st.column_config.NumberColumn("ยอดคลิก", format="%,d"),
            "ละติจูด": st.column_config.TextColumn("ละติจูด", help="พิกัดละติจูด (⚠️ = พิกัดกึ่งกลางตำบล/อำเภอโดยประมาณ ไม่ใช่ตำแหน่งจริง)"),
            "ลองจิจูด": st.column_config.TextColumn("ลองจิจูด", help="พิกัดลองจิจูด (⚠️ = พิกัดกึ่งกลางตำบล/อำเภอโดยประมาณ ไม่ใช่ตำแหน่งจริง)"),
            "ความแม่นยำพิกัด": st.column_config.TextColumn("ความแม่นยำพิกัด", help="ระบุว่าเป็นพิกัดแปลงจริงจากประกาศ หรือพิกัดจุดกึ่งกลางตำบล/อำเภอ"),
            "ชั้น": st.column_config.TextColumn("ชั้น", help="ชั้นที่ตั้งของทรัพย์สิน หรือจำนวนชั้นของอาคาร"),
            "เลขโฉนด": st.column_config.TextColumn("เลขโฉนด", help="เลขที่โฉนดที่ดิน หรือเอกสารสิทธิ์"),
            "โจทก์": st.column_config.TextColumn("โจทก์", help="โจทก์ผู้ฟ้องคดี (เฉพาะทรัพย์กรมบังคับคดี LED / LED Legal)"),
            "ศาล": st.column_config.TextColumn("ศาล", help="ศาลที่ออกหมายบังคับคดี (เฉพาะทรัพย์กรมบังคับคดี LED / LED Legal)"),
            "ราคาขายได้": st.column_config.NumberColumn("ราคาขายได้ (บาท)", format="฿%,d", help="ราคาที่ประมูลขายได้จริงจากรายงานผลขายทอดตลาด (LED Legal)"),
            "วันที่ขาย": st.column_config.TextColumn("วันที่ขาย", help="วันที่ประมูลขายทอดตลาดได้จริง (เฉพาะทรัพย์ขายได้ LED Legal)"),
            "ลิงก์": st.column_config.LinkColumn("ลิงก์ประกาศ", display_text="เปิดดูทรัพย์"),
            "รูปแปลงที่ดิน": st.column_config.LinkColumn("รูปแปลงที่ดิน (LED)", display_text="LandsMaps", help="คลิกเพื่อเปิดระบบค้นหารูปแปลงที่ดิน กรมที่ดิน (เฉพาะกรมบังคับคดี)")
        }
    )
    if df_filtered is not None and not df_filtered.empty:
        render_import_export_section(df_filtered, filename_prefix="npa_property_listing", key_suffix="tab4")
