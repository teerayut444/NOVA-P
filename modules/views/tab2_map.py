# Tab 2 Interactive Map View - Updated centroid popup logic
import os
import json
import re
import pandas as pd
import streamlit as st
import streamlit.components.v1 as stc

from modules.services.geo_service import (
    get_boundary_geojson_features,
    get_map_icon_atlas_and_mapping,
    get_leaflet_logo_dict
)
from modules.services.data_loader import (
    precompute_full_map_html,
    get_data_mtime,
    get_data_mtime_token,
    get_cache_builder_version,
    get_precomputed_map_payload,
    build_map_payload_from_df,
    get_base_map_html,
    STATIC_MAP_PAYLOAD_PATH,
)
from modules.views.tab2_fragment import render_tab2_reference_analytics_fragment


def _build_custom_company_colors_str():
    """Serializes user-imported custom company colors into JS object properties for the map template."""
    imported_cos = st.session_state.get("imported_custom_companies", {})
    default_imp_color = json.dumps(str(st.session_state.get("imported_custom_color", "#6366f1")), ensure_ascii=False)
    custom_color_entries = [f'"ไฟล์นำเข้า": {default_imp_color}']
    if isinstance(imported_cos, dict):
        for co_n, co_inf in imported_cos.items():
            if isinstance(co_inf, dict) and "color" in co_inf:
                custom_color_entries.append(
                    f'{json.dumps(str(co_n), ensure_ascii=False)}: {json.dumps(str(co_inf["color"]), ensure_ascii=False)}'
                )
    custom_co = st.session_state.get("imported_custom_company")
    custom_color = st.session_state.get("imported_custom_color", "#6366f1")
    if (
        custom_co
        and custom_co != "ไฟล์นำเข้า"
        and custom_co != "(ตามข้อมูลในไฟล์)"
        and (not isinstance(imported_cos, dict) or custom_co not in imported_cos)
    ):
        custom_color_entries.append(
            f'{json.dumps(str(custom_co), ensure_ascii=False)}: {json.dumps(str(custom_color), ensure_ascii=False)}'
        )
    return ",\n        ".join(custom_color_entries)


def _safe_js_inner_str(val):
    """Safely encode arbitrary strings for embedding inside a JS double-quoted string literal."""
    encoded = json.dumps(str(val or ""), ensure_ascii=False)[1:-1]
    return encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("/", "\\/")


def _safe_json_inline(obj):
    """Safely serialize Python data for inline JS assignment inside <script>."""
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("</", "<\\/")


def _safe_float_str(val, default=""):
    if val is None or val == "":
        return default
    try:
        f = float(val)
        if pd.isna(f):
            return default
        return f"{f:.6f}".rstrip("0").rstrip(".") or "0"
    except (ValueError, TypeError):
        return default


def _inject_dynamic_map_placeholders(
    html_str,
    *,
    is_dark_mode,
    active_ref_lat,
    active_ref_lon,
    active_ref_radius,
    search_prop_id,
    effective_provs,
    effective_dists,
    effective_subdists,
    current_prov_str,
):
    """Injects runtime session/filter placeholders shared by both Instant and Fallback map paths."""
    body_cls = "dark-theme" if is_dark_mode else ""
    html_str = html_str.replace("BODY_CLASS_PLACEHOLDER", body_cls)
    html_str = html_str.replace("INIT_REF_LAT_PLACEHOLDER", _safe_float_str(active_ref_lat, ""))
    html_str = html_str.replace("INIT_REF_LON_PLACEHOLDER", _safe_float_str(active_ref_lon, ""))
    html_str = html_str.replace("INIT_RADIUS_PLACEHOLDER", _safe_float_str(active_ref_radius, "5.0"))
    init_ref_id = str(
        st.session_state.get("tab2_search_prop_id") or st.query_params.get("map_ref_id") or search_prop_id or ""
    ).strip()
    html_str = html_str.replace("INIT_REF_ID_PLACEHOLDER", _safe_js_inner_str(init_ref_id))
    init_price_ref_id = str(
        st.session_state.get("tab2_price_center_id") or st.query_params.get("map_price_ref_id") or ""
    ).strip()
    html_str = html_str.replace("INIT_PRICE_REF_ID_PLACEHOLDER", _safe_js_inner_str(init_price_ref_id))
    active_comp_ids = st.session_state.get("tab2_compare_ids", [])
    comp_ids_json = _safe_json_inline(active_comp_ids)
    html_str = html_str.replace("INIT_COMPARE_IDS_PLACEHOLDER", comp_ids_json)

    boundary_obj = (
        get_boundary_geojson_features(effective_provs, effective_dists, effective_subdists)
        if effective_provs
        else None
    )
    boundary_json = _safe_json_inline(boundary_obj) if boundary_obj else "null"
    html_str = html_str.replace("BOUNDARY_GEOJSON_PLACEHOLDER", boundary_json)
    html_str = html_str.replace("CURRENT_PROV_PLACEHOLDER", _safe_js_inner_str(current_prov_str))
    html_str = html_str.replace("CUSTOM_COMPANY_COLORS_PLACEHOLDER", _build_custom_company_colors_str())
    html_str = html_str.replace("DATA_MTIME_PLACEHOLDER", get_data_mtime_token(get_data_mtime()))
    html_str = html_str.replace("CACHE_BUILDER_VER_PLACEHOLDER", get_cache_builder_version())
    return html_str


def _render_map_html_component(html_str, height=870):
    """Renders map HTML via stc.html with fallback to st.html."""
    try:
        stc.html(html_str, height=height)
        return True
    except Exception:
        pass
    try:
        st.html(html_str, unsafe_allow_javascript=True)
        return True
    except Exception:
        pass
    st.error("ไม่สามารถแสดงแผนที่ได้ กรุณาลองรีเฟรชหน้าเว็บ")
    return False


def render_tab2_map_view(df_raw, df_filtered, is_dark_mode):
    """
    Renders Tab 2: Interactive Leaflet Map with Deck.gl point visualization,
    in-map controls, search sync, boundary layers, and reference analytics fragment.
    """
    with st.container(key="tab_map"):
        # TOP IN-PAGE FILTERS & REFERENCE POINT PICKER (FontAwesome Icons)
        st.markdown('<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">', unsafe_allow_html=True)

        tab2_regions = []
        tab2_provs = st.session_state.get("tab2_filter_provinces", [])
        tab2_dists = st.session_state.get("tab2_filter_districts", [])
        tab2_subdists = st.session_state.get("tab2_filter_subdistricts", [])
        tab2_types = []

        # Resolve active reference point
        active_ref_prop = st.session_state.get("tab2_ref_prop")
        active_ref_lat = None
        active_ref_lon = None
        try:
            active_ref_radius = float(st.query_params.get("map_ref_radius", 5.0))
        except (ValueError, TypeError):
            active_ref_radius = 5.0

        # Check if reference property ID came from map search, click, or query params
        q_comp = st.query_params.get("map_compare_ids")
        if q_comp and str(q_comp).strip():
            st.session_state["tab2_compare_ids"] = [x.strip() for x in str(q_comp).split(",") if x.strip()]
        q_id = st.query_params.get("map_ref_id")
        search_prop_id = q_id or st.session_state.get("tab2_search_prop_id", "")

        if search_prop_id and search_prop_id.strip():
            clean_id = search_prop_id.strip()
            if active_ref_prop is None or str(active_ref_prop.get('รหัสทรัพย์', '')).strip().lower() != clean_id.lower():
                if df_raw is not None and not df_raw.empty:
                    s_codes = df_raw['รหัสทรัพย์'].astype(str).str.strip().str.lower()
                    clean_id_lower = clean_id.lower()
                    match_df = df_raw[s_codes == clean_id_lower]
                    if match_df.empty:
                        match_df = df_raw[s_codes.str.startswith(clean_id_lower + '_')]
                    if not match_df.empty:
                        r0 = match_df.iloc[0]
                        try:
                            lat_f = float(r0.get('ละติจูด', 0))
                            lon_f = float(r0.get('ลองจิจูด', 0))
                            valid_coords = lat_f > 0 and lon_f > 0
                        except (ValueError, TypeError):
                            valid_coords = False
                        if valid_coords:
                            active_ref_prop = r0.to_dict()
                            active_ref_lat = lat_f
                            active_ref_lon = lon_f
                            st.session_state["tab2_ref_lat"] = active_ref_lat
                            st.session_state["tab2_ref_lon"] = active_ref_lon
                            st.session_state["tab2_ref_prop"] = active_ref_prop
                            st.session_state["tab2_search_prop_id"] = clean_id
                            st.session_state["tab2_filter_projects"] = []
                            try:
                                st.query_params.pop("map_proj", None)
                            except Exception:
                                pass
                            p_prov = str(r0.get('จังหวัด', '')).strip()
                            p_dist = str(r0.get('อำเภอ', '')).strip()
                            p_subdist = str(r0.get('ตำบล', '')).strip()
                            if p_prov and p_prov not in ['-', 'ไม่มีข้อมูล', 'nan']:
                                st.session_state["tab2_filter_provinces"] = [p_prov]
                                st.query_params["map_prov"] = p_prov
                            if p_dist and p_dist not in ['-', 'ไม่มีข้อมูล', 'nan']:
                                st.session_state["tab2_filter_districts"] = [p_dist]
                                st.query_params["map_dist"] = p_dist
                            if p_subdist and p_subdist not in ['-', 'ไม่มีข้อมูล', 'nan']:
                                st.session_state["tab2_filter_subdistricts"] = [p_subdist]
                                st.query_params["map_subdist"] = p_subdist
            else:
                active_ref_lat = float(active_ref_prop.get('ละติจูด', 0))
                active_ref_lon = float(active_ref_prop.get('ลองจิจูด', 0))

        if active_ref_lat is None:
            q_lat = st.query_params.get("map_ref_lat")
            q_lon = st.query_params.get("map_ref_lon")
            if q_lat and q_lon:
                try:
                    active_ref_lat = float(q_lat)
                    active_ref_lon = float(q_lon)
                    if active_ref_prop is not None:
                        p_lat = float(active_ref_prop.get('ละติจูด', 0))
                        p_lon = float(active_ref_prop.get('ลองจิจูด', 0))
                        if abs(p_lat - active_ref_lat) > 0.0005 or abs(p_lon - active_ref_lon) > 0.0005:
                            active_ref_prop = None
                            st.session_state["tab2_ref_prop"] = None
                            st.session_state["tab2_search_prop_id"] = ""
                            st.session_state["tab2_input_prop_id"] = ""
                except ValueError:
                    pass
            elif st.session_state.get("tab2_ref_lat") and st.session_state.get("tab2_ref_lon"):
                try:
                    active_ref_lat = float(st.session_state["tab2_ref_lat"])
                    active_ref_lon = float(st.session_state["tab2_ref_lon"])
                except (ValueError, TypeError):
                    active_ref_lat = None
                    active_ref_lon = None

        # Resolve active price center property
        if st.session_state.get("tab2_just_reset_price_center"):
            active_price_ref_prop = None
            st.session_state["tab2_price_ref_prop"] = None
            st.session_state["tab2_price_center_id"] = ""
            try:
                st.query_params.pop("map_price_ref_id", None)
            except Exception:
                pass
        else:
            active_price_ref_prop = st.session_state.get("tab2_price_ref_prop")
            price_prop_id = str(st.query_params.get("map_price_ref_id") or st.session_state.get("tab2_price_center_id", "")).strip()
            if price_prop_id:
                clean_price_id = price_prop_id.strip()
                if active_price_ref_prop is None or str(active_price_ref_prop.get('รหัสทรัพย์', '')).strip().lower() != clean_price_id.lower():
                    if df_raw is not None and not df_raw.empty:
                        s_codes = df_raw['รหัสทรัพย์'].astype(str).str.strip().str.lower()
                        m_p = df_raw[s_codes == clean_price_id.lower()]
                        if m_p.empty:
                            m_p = df_raw[s_codes.str.startswith(clean_price_id.lower() + '_')]
                        if not m_p.empty:
                            active_price_ref_prop = m_p.iloc[0].to_dict()
                            st.session_state["tab2_price_ref_prop"] = active_price_ref_prop
                            st.session_state["tab2_price_center_id"] = clean_price_id
                elif active_price_ref_prop is not None:
                    st.session_state["tab2_price_center_id"] = clean_price_id
            else:
                active_price_ref_prop = None
                st.session_state["tab2_price_ref_prop"] = None
                st.session_state["tab2_price_center_id"] = ""

        # 3. MAP DATA (Keep full dataset in map so client-side in-map filters and dropdowns work in real-time)
        if df_filtered is None:
            tab2_filtered = pd.DataFrame()
        elif tab2_regions and not df_filtered.empty and 'ภาค' in df_filtered.columns:
            tab2_filtered = df_filtered[df_filtered['ภาค'].isin(tab2_regions)]
        else:
            tab2_filtered = df_filtered

        effective_provs = tab2_provs or st.session_state.get("tab2_filter_provinces", []) or st.session_state.get("selected_provinces", [])
        effective_dists = tab2_dists or st.session_state.get("tab2_filter_districts", []) or st.session_state.get("selected_districts_formatted", [])
        effective_subdists = tab2_subdists or st.session_state.get("tab2_filter_subdistricts", []) or st.session_state.get("selected_subdistricts_formatted", [])
        current_prov_str = effective_provs[0] if (effective_provs and len(effective_provs) > 0) else ""

        # Map Rendering (Deck.gl OpenStreetMap Map with dynamic marker mode, compass, and slider)
        has_custom_import = (
            "imported_custom_df" in st.session_state
            and st.session_state["imported_custom_df"] is not None
            and not st.session_state["imported_custom_df"].empty
        )
        is_nationwide_default = (
            not tab2_regions
            and not has_custom_import
            and (len(tab2_filtered) == len(df_raw) if (df_raw is not None and not df_raw.empty) else True)
        )

        # INSTANT PATH: Use fully pre-assembled HTML from welcome screen preload (0ms data prep)
        _instant_rendered = False
        _tmpl_path = "static/map_template.html"
        _tmpl_mtime = os.path.getmtime(_tmpl_path) if os.path.exists(_tmpl_path) else None
        _cur_data_mtime = get_data_mtime()
        _cur_builder_ver = get_cache_builder_version()
        if is_nationwide_default and (
            "cached_map_html_base" not in st.session_state
            or st.session_state.get("cached_map_tmpl_mtime") != _tmpl_mtime
            or st.session_state.get("cached_map_data_mtime") != _cur_data_mtime
            or st.session_state.get("cached_map_builder_ver") != _cur_builder_ver
            or not os.path.exists(STATIC_MAP_PAYLOAD_PATH)
        ):
            precompute_full_map_html(_cur_data_mtime)

        if (is_nationwide_default and
            "cached_map_html_base" in st.session_state and
            st.session_state.get("cached_map_tmpl_mtime") == _tmpl_mtime and
            st.session_state.get("cached_map_data_mtime") == _cur_data_mtime and
            st.session_state.get("cached_map_data_len", 0) > 0):

            _instant_html = _inject_dynamic_map_placeholders(
                st.session_state["cached_map_html_base"],
                is_dark_mode=is_dark_mode,
                active_ref_lat=active_ref_lat,
                active_ref_lon=active_ref_lon,
                active_ref_radius=active_ref_radius,
                search_prop_id=search_prop_id,
                effective_provs=effective_provs,
                effective_dists=effective_dists,
                effective_subdists=effective_subdists,
                current_prov_str=current_prov_str,
            )
            _render_map_html_component(_instant_html, height=870)
            _instant_rendered = True

        # FALLBACK PATH: Full computation for filtered views or when cache is not ready
        if not _instant_rendered:
            progress_bar = None
            if is_nationwide_default:
                csv_base64, lookup_b64, legend_content, map_data_full_len = get_precomputed_map_payload(get_data_mtime())
                map_data_empty = (map_data_full_len == 0)
            else:
                progress_bar = st.progress(0, text="กำลังเตรียมข้อมูลแผนที่...")
                progress_bar.progress(20, text="กำลังกรองจุดพิกัดในประเทศไทย (20%)...")
                csv_base64, lookup_b64, legend_content, map_data_full_len = build_map_payload_from_df(
                    tab2_filtered,
                    df_project_source=df_raw,
                    data_mtime=get_data_mtime(),
                    progress_bar=progress_bar,
                    custom_companies=st.session_state.get("imported_custom_companies", {}),
                    custom_company=st.session_state.get("imported_custom_company"),
                    custom_color=st.session_state.get("imported_custom_color", "#6366f1"),
                )
                map_data_empty = (map_data_full_len == 0)

            if map_data_empty:
                if progress_bar:
                    progress_bar.empty()
                st.warning("ไม่พบพิกัดตำแหน่ง ละติจูด/ลองจิจูด ในรายการทรัพย์สินที่คุณเลือกค้นหา")
            else:
                _tmpl_path = "static/map_template.html"
                _tmpl_mtime = os.path.getmtime(_tmpl_path) if os.path.exists(_tmpl_path) else None
                base_tmpl = get_base_map_html(_tmpl_mtime)

                atlas_uri, icon_mapping = get_map_icon_atlas_and_mapping(128)
                icon_mapping_json = json.dumps(icon_mapping, ensure_ascii=False)

                html_content = base_tmpl.replace("CSV_BASE64_PLACEHOLDER", csv_base64)
                html_content = html_content.replace("LOOKUP_BASE64_PLACEHOLDER", lookup_b64)
                html_content = html_content.replace("LEGEND_ITEMS_PLACEHOLDER", legend_content)
                html_content = html_content.replace("ATLAS_BASE64_PLACEHOLDER", atlas_uri)
                html_content = html_content.replace("ICON_MAPPING_PLACEHOLDER", icon_mapping_json)

                all_provinces_list = sorted(list({
                    str(p).strip().strip(" ,;.-'\"")
                    for p in df_raw['จังหวัด'].dropna().unique()
                    if str(p).strip().strip(" ,;.-'\"") and str(p).strip().strip(" ,;.-'\"") not in ['-', 'ไม่มีข้อมูล', 'nan', 'None'] and not re.search(r'\d', str(p)) and re.search(r'^[ก-๙]', str(p).strip())
                })) if df_raw is not None and not df_raw.empty else []
                all_provinces_json = json.dumps(all_provinces_list, ensure_ascii=False)
                html_content = html_content.replace("ALL_PROVINCES_PLACEHOLDER", all_provinces_json)

                company_logos_dict = get_leaflet_logo_dict(72)
                company_logos_json = json.dumps(company_logos_dict, ensure_ascii=False)
                html_content = html_content.replace("COMPANY_LOGOS_PLACEHOLDER", company_logos_json)

                html_content = _inject_dynamic_map_placeholders(
                    html_content,
                    is_dark_mode=is_dark_mode,
                    active_ref_lat=active_ref_lat,
                    active_ref_lon=active_ref_lon,
                    active_ref_radius=active_ref_radius,
                    search_prop_id=search_prop_id,
                    effective_provs=effective_provs,
                    effective_dists=effective_dists,
                    effective_subdists=effective_subdists,
                    current_prov_str=current_prov_str,
                )

                if progress_bar:
                    progress_bar.progress(100, text="เรนเดอร์แผนที่สำเร็จแล้ว (100%)")
                    progress_bar.empty()

                _render_map_html_component(html_content, height=870)

        # ----------------- BELOW MAP: ANALYTICS CARDS & NEARBY ASSET LISTING -----------------
        # Filter for properties with valid map coordinates (pins) to keep counts 100% consistent
        df_map_valid = df_raw[
            df_raw['ละติจูด'].notna() & df_raw['ลองจิจูด'].notna() &
            df_raw['ละติจูด'].between(5, 21) & df_raw['ลองจิจูด'].between(97, 106)
        ] if df_raw is not None and not df_raw.empty else df_raw

        render_tab2_reference_analytics_fragment(
            df_raw=df_map_valid,
            is_dark_mode=is_dark_mode,
            active_ref_lat=active_ref_lat,
            active_ref_lon=active_ref_lon,
            active_ref_prop=active_ref_prop,
            active_price_ref_prop=active_price_ref_prop,
            active_ref_radius=active_ref_radius,
            tab2_types=tab2_types
        )
