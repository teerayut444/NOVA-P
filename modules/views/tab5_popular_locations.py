import os
import json
import statistics
import pandas as pd
import streamlit as st
import streamlit.components.v1 as stc

from modules.config.constants import REGION_PROVINCES, PROVINCE_TO_REGION
from modules.services.data_cleaner import get_dataset_month_year
from modules.services.data_loader import get_data_mtime
from modules.services.livinginsider_service import get_livinginsider_project_metrics

fragment_decorator = getattr(st, "fragment", lambda f: f)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@st.cache_data(show_spinner=False)
def _load_provinces_outer_geojson():
    """Loads pre-dissolved 77-province outer boundary GeoJSON string for Tab 5 map hover borders."""
    outer_path = os.path.join(_BASE_DIR, "static", "provinces_outer_geojson.json")
    if os.path.exists(outer_path):
        try:
            with open(outer_path, "r", encoding="utf-8") as f:
                return f.read().replace("</script>", "<\\/script>")
        except Exception:
            pass

    raw_path = os.path.join(_BASE_DIR, "static", "provinces_geojson.json")
    if os.path.exists(raw_path):
        try:
            from shapely import make_valid, set_precision
            from shapely.geometry import shape, mapping
            from shapely.ops import unary_union

            with open(raw_path, "r", encoding="utf-8") as f:
                raw_dict = json.load(f)
            features = []
            for prov, fc in raw_dict.items():
                geoms = [make_valid(shape(feat["geometry"])) for feat in fc.get("features", []) if feat.get("geometry")]
                if not geoms:
                    continue
                merged = unary_union(geoms).simplify(0.003, preserve_topology=True)
                merged = set_precision(merged, 0.0001)
                features.append({"type": "Feature", "properties": {"prov": prov}, "geometry": mapping(merged)})
            return json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":")).replace("</script>", "<\\/script>")
        except Exception:
            pass

    return '{"type":"FeatureCollection","features":[]}'


@st.cache_data(show_spinner=False, max_entries=4)
def _build_tab5_popular_locations_bundle(_df_raw, is_dark_mode=False, cache_key=None):
    # 1. Fetch Aggregated Metrics
    projects = get_livinginsider_project_metrics(_df_raw)

    if not projects:
        return None

    # 2. KPI Summary Cards (Using Median)
    total_projects = len(projects)
    total_units = sum(p.get("units", 1) for p in projects)
    vds = [p.get("vd", 0) for p in projects if p.get("vd") is not None]
    cds = [p.get("cd", 0) for p in projects if p.get("cd") is not None]
    med_vd = statistics.median(vds) if vds else 0
    med_cd = statistics.median(cds) if cds else 0

    # Dataset month info for attribution banner
    month_th, _ = get_dataset_month_year(_df_raw)
    th_abbr = {
        'มกราคม': 'ม.ค.', 'กุมภาพันธ์': 'ก.พ.', 'มีนาคม': 'มี.ค.', 'เมษายน': 'เม.ย.',
        'พฤษภาคม': 'พ.ค.', 'มิถุนายน': 'มิ.ย.', 'กรกฎาคม': 'ก.ค.', 'สิงหาคม': 'ส.ค.',
        'กันยายน': 'ก.ย.', 'ตุลาคม': 'ต.ค.', 'พฤศจิกายน': 'พ.ย.', 'ธันวาคม': 'ธ.ค.'
    }
    month_short = str(month_th) if month_th else "ล่าสุด"
    for full_m, abbr_m in th_abbr.items():
        if full_m in month_short:
            month_short = month_short.replace(full_m, abbr_m)
            break

    # 3. Extract unique provinces, regions, and property types for select options
    provinces = sorted(list(set(p["prov"] for p in projects if p["prov"] and p["prov"] not in ['-', 'nan', 'None'])))
    # Sort so Bangkok and major metros come first, then alphabetical
    priority_provs = ["กรุงเทพมหานคร", "นนทบุรี", "สมุทรปราการ", "ปทุมธานี", "ชลบุรี", "เชียงใหม่", "ภูเก็ต", "ระยอง"]
    sorted_provs = [p for p in priority_provs if p in provinces] + [p for p in provinces if p not in priority_provs]

    region_names = list(REGION_PROVINCES.keys())
    if any(p not in PROVINCE_TO_REGION for p in sorted_provs):
        region_names.append("อื่นๆ / ไม่ระบุ")

    prop_types = sorted(list(set(p["prop_type"] for p in projects if p["prop_type"] and p["prop_type"] not in ['-', 'nan', 'None'])))

    # 4. Generate Interactive 70:30 HTML/JS App
    projects_json = json.dumps(projects, ensure_ascii=False).replace("</script>", "<\\/script>")
    provinces_json = json.dumps(sorted_provs, ensure_ascii=False).replace("</script>", "<\\/script>")
    regions_json = json.dumps(region_names, ensure_ascii=False).replace("</script>", "<\\/script>")
    prov_to_region_json = json.dumps(PROVINCE_TO_REGION, ensure_ascii=False).replace("</script>", "<\\/script>")
    prop_types_json = json.dumps(prop_types, ensure_ascii=False).replace("</script>", "<\\/script>")
    prov_outer_geojson_json = _load_provinces_outer_geojson()
    theme_class = "" if is_dark_mode else "light-theme"

    html_app = f"""<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Livinginsider Popular Locations</title>
    <!-- Leaflet CSS with local fallback -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" onerror="this.onerror=null;this.href='/app/static/vendor/leaflet/leaflet.css';" />
    <!-- FontAwesome -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <!-- Google Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Prompt:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    
    <style>
        :root {{
            --bg-body: #0b1120;
            --bg-card: #131d33;
            --bg-card-hover: #1e293b;
            --border-color: rgba(255, 255, 255, 0.1);
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --accent: #38bdf8;
            --accent-glow: rgba(56, 189, 248, 0.25);
            --badge-bg: rgba(56, 189, 248, 0.12);
            --badge-text: #38bdf8;
            --glass-bg: rgba(15, 23, 42, 0.88);
            --shadow-elevation: 0 10px 30px rgba(0,0,0,0.35);
        }}

        body.light-theme {{
            --bg-body: #f8fafc;
            --bg-card: #ffffff;
            --bg-card-hover: #f1f5f9;
            --border-color: rgba(0, 0, 0, 0.08);
            --text-main: #0f172a;
            --text-muted: #64748b;
            --accent: #0284c7;
            --accent-glow: rgba(2, 132, 199, 0.18);
            --badge-bg: rgba(2, 132, 199, 0.1);
            --badge-text: #0284c7;
            --glass-bg: rgba(255, 255, 255, 0.92);
            --shadow-elevation: 0 10px 30px rgba(0,0,0,0.08);
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Prompt', -apple-system, BlinkMacSystemFont, sans-serif;
        }}

        body {{
            background: var(--bg-body);
            color: var(--text-main);
            overflow: hidden;
            width: 100vw;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }}

        /* REALTIME KPI BAR */
        #kpi-bar {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            padding: 2px 2px 10px 2px;
            flex-shrink: 0;
        }}

        .kpi-card {{
            background: rgba(30, 41, 59, 0.72);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 11px 16px;
            display: flex;
            align-items: center;
            gap: 13px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.06);
        }}

        body.light-theme .kpi-card {{
            background: #ffffff;
            border: 1px solid rgba(0, 0, 0, 0.08);
        }}

        .kpi-icon {{
            width: 42px;
            height: 42px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.15rem;
            flex-shrink: 0;
        }}

        .kpi-val {{
            font-size: 1.3rem;
            font-weight: 700;
            line-height: 1.2;
        }}

        .kpi-label {{
            font-size: 0.75rem;
            color: var(--text-muted);
            letter-spacing: 0.2px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        #app-layout {{
            display: flex;
            width: 100%;
            flex: 1;
            min-height: 0;
            border-radius: 14px;
            overflow: hidden;
            border: 1px solid var(--border-color);
        }}

        /* LEFT PANE: 70% MAP */
        #map-container {{
            flex: 0 0 70%;
            height: 100%;
            position: relative;
            background: #111;
        }}

        #map {{
            width: 100%;
            height: 100%;
            z-index: 1;
        }}

        /* IN-MAP FLOATING CONTROLS */
        #in-map-panel {{
            position: absolute;
            top: 14px;
            left: 14px;
            z-index: 1000;
            background: var(--glass-bg);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 13px 16px;
            box-shadow: var(--shadow-elevation);
            width: calc(100% - 28px);
            max-width: 760px;
            transition: all 0.25s ease;
        }}

        /* HEATMAP LEGEND */
        #heat-legend {{
            position: absolute;
            bottom: 16px;
            left: 16px;
            z-index: 1000;
            background: var(--glass-bg);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 10px 14px;
            box-shadow: var(--shadow-elevation);
            min-width: 220px;
            pointer-events: none;
        }}

        .heat-legend-title {{
            font-size: 0.74rem;
            font-weight: 600;
            color: var(--text-main);
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .heat-legend-bar {{
            height: 9px;
            border-radius: 999px;
            background: linear-gradient(90deg, #38bdf8 0%, #10b981 28%, #fbbf24 55%, #f97316 80%, #ef4444 100%);
            margin-bottom: 5px;
        }}

        .heat-legend-labels {{
            display: flex;
            justify-content: space-between;
            font-size: 0.68rem;
            color: var(--text-muted);
        }}

        .control-row {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
            flex-wrap: wrap;
        }}

        .control-row:last-child {{
            margin-bottom: 0;
        }}

        .pill-group {{
            display: inline-flex;
            background: rgba(0,0,0,0.15);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 3px;
            gap: 3px;
        }}

        body.light-theme .pill-group {{
            background: rgba(0,0,0,0.04);
        }}

        .pill-btn {{
            border: none;
            background: transparent;
            color: var(--text-muted);
            font-size: 0.8rem;
            font-weight: 500;
            padding: 5px 12px;
            border-radius: 7px;
            cursor: pointer;
            transition: all 0.18s ease;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}

        .pill-btn:hover {{
            color: var(--text-main);
            background: rgba(255, 255, 255, 0.08);
        }}

        .pill-btn.active {{
            background: var(--accent);
            color: #ffffff;
            font-weight: 600;
            box-shadow: 0 2px 8px var(--accent-glow);
        }}

        .filter-select {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            border-radius: 8px;
            padding: 5px 10px;
            font-size: 0.8rem;
            outline: none;
            cursor: pointer;
            flex: 1;
            min-width: 120px;
        }}

        .filter-select:focus {{
            border-color: var(--accent);
        }}

        /* RIGHT PANE: 30% LEADERBOARD */
        #leaderboard-container {{
            flex: 0 0 30%;
            height: 100%;
            background: var(--bg-card);
            border-left: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            z-index: 2;
            box-shadow: -4px 0 20px rgba(0,0,0,0.15);
        }}

        #leaderboard-header {{
            padding: 16px 20px 12px 20px;
            border-bottom: 1px solid var(--border-color);
            background: var(--bg-card);
            flex-shrink: 0;
        }}

        .lb-title {{
            font-size: 1.1rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 4px;
        }}

        .lb-subtitle {{
            font-size: 0.78rem;
            color: var(--text-muted);
            margin-bottom: 12px;
        }}

        .search-box {{
            position: relative;
            width: 100%;
        }}

        .search-box i {{
            position: absolute;
            left: 12px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            font-size: 0.85rem;
        }}

        .search-input {{
            width: 100%;
            background: rgba(0, 0, 0, 0.12);
            border: 1px solid var(--border-color);
            border-radius: 9px;
            padding: 7px 12px 7px 34px;
            font-size: 0.85rem;
            color: var(--text-main);
            outline: none;
            transition: border-color 0.2s;
        }}

        body.light-theme .search-input {{
            background: rgba(0,0,0,0.03);
        }}

        .search-input:focus {{
            border-color: var(--accent);
        }}

        #leaderboard-list {{
            flex: 1;
            overflow-y: auto;
            padding: 12px 16px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}

        #leaderboard-list::-webkit-scrollbar {{
            width: 6px;
        }}
        #leaderboard-list::-webkit-scrollbar-track {{
            background: transparent;
        }}
        #leaderboard-list::-webkit-scrollbar-thumb {{
            background: rgba(255, 255, 255, 0.15);
            border-radius: 4px;
        }}

        /* LEADERBOARD CARD */
        .lb-card {{
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 12px 14px;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            gap: 12px;
            align-items: flex-start;
            position: relative;
        }}

        body.light-theme .lb-card {{
            background: #ffffff;
            box-shadow: 0 2px 8px rgba(0,0,0,0.03);
        }}

        .lb-card:hover {{
            background: var(--bg-card-hover);
            transform: translateY(-2px);
            border-color: var(--accent);
            box-shadow: 0 6px 16px var(--accent-glow);
        }}

        .rank-badge {{
            width: 32px;
            height: 32px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 0.85rem;
            flex-shrink: 0;
            background: rgba(255, 255, 255, 0.08);
            color: var(--text-muted);
        }}

        .rank-1 {{
            background: linear-gradient(135deg, #fbbf24, #d97706);
            color: #ffffff;
            box-shadow: 0 2px 10px rgba(245, 158, 11, 0.35);
        }}

        .rank-2 {{
            background: linear-gradient(135deg, #cbd5e1, #94a3b8);
            color: #ffffff;
        }}

        .rank-3 {{
            background: linear-gradient(135deg, #fdba74, #c2410c);
            color: #ffffff;
        }}

        .lb-card-body {{
            flex: 1;
            min-width: 0;
        }}

        .lb-card-title {{
            font-weight: 600;
            font-size: 0.9rem;
            color: var(--text-main);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-bottom: 3px;
        }}

        .lb-card-loc {{
            font-size: 0.75rem;
            color: var(--text-muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-bottom: 6px;
        }}

        .lb-card-footer {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 0.75rem;
        }}

        .metric-pill {{
            font-weight: 700;
            color: var(--accent);
            background: var(--badge-bg);
            padding: 3px 8px;
            border-radius: 6px;
        }}

        .units-pill {{
            color: var(--text-muted);
        }}

        /* LEADERBOARD ACTION BUTTONS & PROVINCE ACCORDION */
        .lb-title-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            margin-bottom: 4px;
        }}

        .lb-title-row .lb-title {{
            margin-bottom: 0;
            min-width: 0;
        }}

        .lb-action-btn {{
            border: 1px solid var(--border-color);
            background: var(--badge-bg);
            color: var(--accent);
            font-size: 0.72rem;
            font-weight: 600;
            padding: 4px 9px;
            border-radius: 7px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 5px;
            white-space: nowrap;
            transition: all 0.15s ease;
        }}

        .lb-action-btn:hover {{
            background: var(--accent);
            color: #ffffff;
            border-color: var(--accent);
        }}

        .lb-sort-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            margin-bottom: 10px;
            flex-wrap: wrap;
        }}

        .lb-sort-row .lb-subtitle {{
            margin-bottom: 0;
        }}

        .lb-sort-select {{
            background: rgba(0, 0, 0, 0.14);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            border-radius: 7px;
            padding: 3px 8px;
            font-size: 0.72rem;
            outline: none;
            cursor: pointer;
        }}

        body.light-theme .lb-sort-select {{
            background: #f8fafc;
        }}

        .prov-acc {{
            border: 1px solid var(--border-color);
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.02);
            overflow: hidden;
            flex-shrink: 0;
        }}

        body.light-theme .prov-acc {{
            background: #f8fafc;
        }}

        .prov-acc-header {{
            padding: 10px 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            cursor: pointer;
            transition: background 0.15s ease;
            user-select: none;
        }}

        .prov-acc-header:hover {{
            background: var(--bg-card-hover);
        }}

        .prov-acc-left {{
            display: flex;
            align-items: center;
            gap: 9px;
            min-width: 0;
            flex: 1;
        }}

        .prov-rank-pill {{
            min-width: 28px;
            height: 26px;
            padding: 0 6px;
            border-radius: 7px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 0.76rem;
            background: rgba(255, 255, 255, 0.08);
            color: var(--text-muted);
            flex-shrink: 0;
        }}

        body.light-theme .prov-rank-pill {{
            background: rgba(15, 23, 42, 0.07);
        }}

        .prov-rank-pill.rank-1,
        .prov-rank-pill.rank-2,
        .prov-rank-pill.rank-3 {{
            color: #ffffff;
        }}

        .prov-acc-info {{
            min-width: 0;
            flex: 1;
        }}

        .prov-acc-name {{
            font-weight: 700;
            font-size: 0.88rem;
            color: var(--text-main);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .prov-acc-meta {{
            font-size: 0.72rem;
            color: var(--text-muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .prov-acc-right {{
            display: flex;
            align-items: center;
            gap: 6px;
            flex-shrink: 0;
        }}

        .prov-drill-btn {{
            border: 1px solid var(--border-color);
            background: transparent;
            color: var(--accent);
            font-size: 0.7rem;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.15s ease;
        }}

        .prov-drill-btn:hover {{
            background: var(--accent);
            color: #ffffff;
            border-color: var(--accent);
        }}

        .prov-chevron {{
            font-size: 0.75rem;
            color: var(--text-muted);
            transition: transform 0.2s ease;
            width: 14px;
            text-align: center;
        }}

        .prov-acc.open .prov-chevron {{
            transform: rotate(180deg);
        }}

        .prov-acc-body {{
            display: none;
            padding: 8px 10px 10px 10px;
            border-top: 1px solid var(--border-color);
            flex-direction: column;
            gap: 8px;
            background: var(--bg-card);
        }}

        .prov-acc.open .prov-acc-body {{
            display: flex;
        }}

        .prov-more-btn {{
            border: 1px dashed var(--border-color);
            background: transparent;
            color: var(--accent);
            font-size: 0.74rem;
            font-weight: 600;
            padding: 6px 10px;
            border-radius: 8px;
            cursor: pointer;
            text-align: center;
            transition: all 0.15s ease;
        }}

        .prov-more-btn:hover {{
            background: var(--badge-bg);
            border-color: var(--accent);
        }}

        /* POPUP STYLING */
        .leaflet-popup-content-wrapper {{
            background: var(--bg-card) !important;
            color: var(--text-main) !important;
            border: 1px solid var(--border-color) !important;
            border-radius: 14px !important;
            box-shadow: var(--shadow-elevation) !important;
            padding: 0 !important;
            overflow: hidden !important;
        }}

        .leaflet-popup-tip {{
            background: var(--bg-card) !important;
        }}

        .popup-header {{
            background: linear-gradient(135deg, rgba(56, 189, 248, 0.15), rgba(99, 102, 241, 0.15));
            border-bottom: 1px solid var(--border-color);
            padding: 12px 16px;
        }}

        .popup-title {{
            font-weight: 700;
            font-size: 1rem;
            color: var(--text-main);
            margin-bottom: 2px;
        }}

        .popup-loc {{
            font-size: 0.75rem;
            color: var(--text-muted);
        }}

        .popup-body {{
            padding: 14px 16px;
        }}

        .stat-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-bottom: 12px;
        }}

        .stat-box {{
            background: rgba(0, 0, 0, 0.12);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 8px;
            text-align: center;
        }}

        body.light-theme .stat-box {{
            background: rgba(0,0,0,0.03);
        }}

        .stat-box-val {{
            font-size: 1rem;
            font-weight: 700;
            color: var(--accent);
        }}

        .stat-box-lbl {{
            font-size: 0.7rem;
            color: var(--text-muted);
        }}

        .popup-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.75rem;
            margin-bottom: 12px;
        }}

        .popup-table th, .popup-table td {{
            padding: 5px 8px;
            text-align: right;
            border-bottom: 1px solid var(--border-color);
        }}

        .popup-table th:first-child, .popup-table td:first-child {{
            text-align: left;
        }}

        a.popup-btn,
        .leaflet-popup-content a.popup-btn,
        .popup-btn {{
            display: block !important;
            width: 100% !important;
            text-align: center !important;
            background: var(--accent) !important;
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            font-weight: 600 !important;
            font-size: 0.82rem !important;
            padding: 8px 12px !important;
            border-radius: 8px !important;
            text-decoration: none !important;
            box-shadow: 0 2px 8px var(--accent-glow) !important;
            transition: all 0.2s ease !important;
        }}

        a.popup-btn:hover,
        .leaflet-popup-content a.popup-btn:hover,
        .popup-btn:hover {{
            opacity: 0.92 !important;
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
        }}

        a.popup-btn i,
        .leaflet-popup-content a.popup-btn i,
        .popup-btn i {{
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            margin-right: 5px !important;
        }}

        /* Leaflet Layer Switcher Control */
        .leaflet-control-layers {{
            background: var(--glass-bg) !important;
            backdrop-filter: blur(14px) !important;
            -webkit-backdrop-filter: blur(14px) !important;
            border: 1px solid var(--border-color) !important;
            border-radius: 12px !important;
            color: var(--text-main) !important;
            box-shadow: var(--shadow-elevation) !important;
            font-size: 0.8rem !important;
            padding: 8px 12px !important;
        }}

        .leaflet-control-layers-toggle {{
            filter: invert(1);
        }}

        body.light-theme .leaflet-control-layers-toggle {{
            filter: none;
        }}

        .leaflet-control-layers-base label {{
            display: flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
            margin-bottom: 4px;
        }}

        .leaflet-control-layers-base label:last-child {{
            margin-bottom: 0;
        }}

        path.leaflet-interactive:focus {{
            outline: none !important;
        }}

        /* PROVINCE HOVER TOOLTIP */
        .prov-hover-tooltip {{
            background: var(--glass-bg) !important;
            backdrop-filter: blur(12px) !important;
            -webkit-backdrop-filter: blur(12px) !important;
            border: 1px solid var(--border-color) !important;
            border-radius: 10px !important;
            color: var(--text-main) !important;
            box-shadow: var(--shadow-elevation) !important;
            padding: 7px 11px !important;
        }}

        .prov-hover-tooltip::before {{
            border-top-color: var(--border-color) !important;
        }}

        .prov-tt-name {{
            font-weight: 700;
            font-size: 0.85rem;
            color: var(--accent);
            line-height: 1.25;
        }}

        .prov-tt-meta {{
            font-size: 0.72rem;
            color: var(--text-muted);
            margin-top: 2px;
        }}
    </style>
</head>
<body class="{theme_class}">

<!-- REALTIME KPI BAR -->
<div id="kpi-bar">
    <div class="kpi-card">
        <div class="kpi-icon" style="background: rgba(59, 130, 246, 0.15); color: #3b82f6;">
            <i class="fa-solid fa-building"></i>
        </div>
        <div style="min-width: 0;">
            <div class="kpi-val" id="kpi-projects" style="color: #3b82f6;">{total_projects:,.0f}</div>
            <div class="kpi-label" id="kpi-projects-lbl">โครงการ / โซนทำเล</div>
        </div>
    </div>
    <div class="kpi-card">
        <div class="kpi-icon" style="background: rgba(16, 185, 129, 0.15); color: #10b981;">
            <i class="fa-solid fa-list-check"></i>
        </div>
        <div style="min-width: 0;">
            <div class="kpi-val" id="kpi-units" style="color: #10b981;">{total_units:,.0f}</div>
            <div class="kpi-label">จำนวนประกาศรวม (Livinginsider)</div>
        </div>
    </div>
    <div class="kpi-card">
        <div class="kpi-icon" style="background: rgba(245, 158, 11, 0.15); color: #f59e0b;">
            <i class="fa-solid fa-eye"></i>
        </div>
        <div style="min-width: 0;">
            <div class="kpi-val" id="kpi-med-vd" style="color: #f59e0b;">{med_vd:,.1f}</div>
            <div class="kpi-label" id="kpi-med-vd-lbl">ยอดเข้าชมมัธยฐาน (Median วิว/วัน)</div>
        </div>
    </div>
    <div class="kpi-card">
        <div class="kpi-icon" style="background: rgba(239, 68, 68, 0.15); color: #ef4444;">
            <i class="fa-solid fa-arrow-pointer"></i>
        </div>
        <div style="min-width: 0;">
            <div class="kpi-val" id="kpi-med-cd" style="color: #ef4444;">{med_cd:,.2f}</div>
            <div class="kpi-label" id="kpi-med-cd-lbl">ยอดคลิกมัธยฐาน (Median คลิก/วัน)</div>
        </div>
    </div>
</div>

<div id="app-layout">
    <!-- LEFT: 70% MAP -->
    <div id="map-container">
        <!-- FLOATING IN-MAP CONTROLS -->
        <div id="in-map-panel">
            <!-- Row 1: Metrics & Intervals -->
            <div class="control-row" style="justify-content: space-between;">
                <!-- Metric Selector -->
                <div class="pill-group" id="metric-group">
                    <button class="pill-btn active" data-metric="vd">
                        <i class="fa-solid fa-eye"></i> ยอดเข้าชม (Views)
                    </button>
                    <button class="pill-btn" data-metric="cd">
                        <i class="fa-solid fa-arrow-pointer"></i> ยอดคลิก (Clicks)
                    </button>
                </div>

                <!-- Time Interval Selector -->
                <div class="pill-group" id="interval-group">
                    <button class="pill-btn active" data-mult="1">ต่อวัน</button>
                    <button class="pill-btn" data-mult="7">ต่อสัปดาห์</button>
                    <button class="pill-btn" data-mult="30">ต่อเดือน</button>
                    <button class="pill-btn" data-mult="365">ต่อปี</button>
                </div>

                <!-- Toggle Markers Switch (Off by default for pure Heatmap) -->
                <div class="pill-group">
                    <button class="pill-btn" id="toggle-markers-btn" title="เปิด/ปิดจุดหมุดโครงการบนแผนที่">
                        <i class="fa-solid fa-location-dot"></i> แสดงหมุด
                    </button>
                </div>
            </div>

            <!-- Row 2: Filters -->
            <div class="control-row">
                <!-- Region Filter -->
                <select id="filter-region" class="filter-select">
                    <option value="">ทุกภาค (ทั่วประเทศ)</option>
                </select>

                <!-- Province Filter -->
                <select id="filter-prov" class="filter-select">
                    <option value="">ทุกจังหวัด (แบ่งรายจังหวัด)</option>
                </select>

                <!-- Property Type Filter -->
                <select id="filter-type" class="filter-select">
                    <option value="">ทุกประเภททรัพย์</option>
                </select>

                <!-- Price Range Filter -->
                <select id="filter-price" class="filter-select">
                    <option value="">ทุกช่วงราคา</option>
                    <option value="under2m">&lt; 2 ล้านบาท</option>
                    <option value="2to5m">2 - 5 ล้านบาท</option>
                    <option value="5to10m">5 - 10 ล้านบาท</option>
                    <option value="over10m">&gt; 10 ล้านบาท</option>
                </select>

                <!-- Min Units Filter -->
                <select id="filter-units" class="filter-select" style="max-width: 130px;">
                    <option value="1">1+ ยูนิต</option>
                    <option value="2" selected>2+ ยูนิต (แนะนำ)</option>
                    <option value="5">5+ ยูนิต</option>
                    <option value="10">10+ ยูนิต</option>
                </select>
            </div>
        </div>

        <!-- The Map Div -->
        <div id="map"></div>

        <!-- Floating Heatmap Legend -->
        <div id="heat-legend">
            <div class="heat-legend-title" id="heat-legend-title">
                <i class="fa-solid fa-fire" style="color: #ef4444;"></i> ความร้อน: ยอดเข้าชม (ต่อวัน)
            </div>
            <div class="heat-legend-bar"></div>
            <div class="heat-legend-labels">
                <span>น้อย</span>
                <span>ปานกลาง</span>
                <span id="heat-legend-max-lbl">สูงมาก (เทียบรายจังหวัด)</span>
            </div>
        </div>
    </div>

    <!-- RIGHT: 30% LEADERBOARD -->
    <div id="leaderboard-container">
        <div id="leaderboard-header">
            <div class="lb-title-row">
                <div class="lb-title" id="lb-title-text">
                    <i class="fa-solid fa-trophy" style="color: #fbbf24;"></i> ทำเลยอดนิยม (รายจังหวัด)
                </div>
                <div id="lb-header-actions"></div>
            </div>
            <div class="lb-sort-row">
                <div class="lb-subtitle" id="lb-sort-label">
                    Top 5 ต่อจังหวัด • เรียงตาม Median Top 5
                </div>
                <select id="prov-sort-mode" class="lb-sort-select" title="วิธีเรียงลำดับจังหวัด">
                    <option value="top5_median" selected>เรียง: Median Top 5</option>
                    <option value="all_median">เรียง: Median ทั้งจังหวัด</option>
                    <option value="total_sum">เรียง: ยอดรวมทั้งจังหวัด</option>
                    <option value="count">เรียง: จำนวนโครงการ</option>
                </select>
            </div>
            <div class="search-box">
                <i class="fa-solid fa-magnifying-glass"></i>
                <input type="text" id="lb-search" class="search-input" placeholder="ค้นหาชื่อโครงการ ทำเล หรือจังหวัด..." />
            </div>
        </div>

        <div id="leaderboard-list">
            <!-- Cards / Province Accordions populated dynamically via JS -->
        </div>
    </div>
</div>

<!-- Leaflet JS with synchronous local fallback -->
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
    if (typeof L === 'undefined') {{
        document.write('<link rel="stylesheet" href="/app/static/vendor/leaflet/leaflet.css" />');
        document.write('<script src="/app/static/vendor/leaflet/leaflet.js"><\\/script>');
    }}
</script>
<!-- Leaflet Heat plugin with fallback -->
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<script>
    if (typeof L !== 'undefined' && typeof L.heatLayer === 'undefined') {{
        document.write('<script src="/app/static/leaflet-heat.js"><\\/script>');
    }}
</script>

<script>
(function() {{
    // 1. Data Inject
    const ALL_PROJECTS = {projects_json};
    const PROVINCES = {provinces_json};
    const REGIONS = {regions_json};
    const PROVINCE_TO_REGION = {prov_to_region_json};
    const PROP_TYPES = {prop_types_json};
    const PROV_OUTER_GEOJSON = {prov_outer_geojson_json};
    const IS_DARK = {'true' if is_dark_mode else 'false'};

    const TOP_N_PER_PROV = 5;

    ALL_PROJECTS.forEach(p => {{
        p._region = PROVINCE_TO_REGION[p.prov] || 'อื่นๆ / ไม่ระบุ';
    }});

    // 2. State
    let activeMetric = 'vd';       // 'vd' (views/day) or 'cd' (clicks/day)
    let activeMultiplier = 1;     // 1, 7, 30, 365
    let activeRegion = '';
    let activeProv = '';
    let activeType = '';
    let activePriceRange = '';
    let activeMinUnits = 2;
    let searchQuery = '';
    let showMarkers = false;       // Pure Heatmap mode by default
    let provSortMode = 'top5_median';

    // Track accordion open/close overrides per province
    const userExpandedProvs = new Set();
    const userCollapsedProvs = new Set();
    let expandAllMode = false;

    // 3. Populate Filter Dropdowns
    const regionSelect = document.getElementById('filter-region');
    REGIONS.forEach(r => {{
        const opt = document.createElement('option');
        opt.value = r;
        opt.textContent = r;
        regionSelect.appendChild(opt);
    }});

    const provSelect = document.getElementById('filter-prov');
    function populateProvinceOptions(regionFilter) {{
        const prevVal = provSelect.value;
        provSelect.innerHTML = '';
        const defaultOpt = document.createElement('option');
        defaultOpt.value = '';
        defaultOpt.textContent = regionFilter ? `ทุกจังหวัดใน${{regionFilter}}` : 'ทุกจังหวัด (แบ่งรายจังหวัด)';
        provSelect.appendChild(defaultOpt);

        const list = regionFilter
            ? PROVINCES.filter(p => (PROVINCE_TO_REGION[p] || 'อื่นๆ / ไม่ระบุ') === regionFilter)
            : PROVINCES;

        list.forEach(p => {{
            const opt = document.createElement('option');
            opt.value = p;
            opt.textContent = p;
            provSelect.appendChild(opt);
        }});

        if (prevVal && list.includes(prevVal)) {{
            provSelect.value = prevVal;
        }} else {{
            provSelect.value = '';
            activeProv = '';
        }}
    }}
    populateProvinceOptions('');

    const typeSelect = document.getElementById('filter-type');
    PROP_TYPES.forEach(t => {{
        const opt = document.createElement('option');
        opt.value = t;
        opt.textContent = t;
        typeSelect.appendChild(opt);
    }});

    // 4. Initialize Leaflet Map (Free layers - No API key required)
    if (typeof L === 'undefined') {{
        const mapEl = document.getElementById('map');
        if (mapEl) {{
            mapEl.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#94a3b8;font-size:14px;">ไม่สามารถโหลดไลบรารีแผนที่ Leaflet ได้ กรุณาตรวจสอบเครือข่าย</div>';
        }}
        return;
    }}

    const streetLayer = L.tileLayer('https://mt{{s}}.google.com/vt?lyrs=m&hl=th&x={{x}}&y={{y}}&z={{z}}', {{
        subdomains: ['0', '1', '2', '3'],
        maxZoom: 20
    }});

    const esriStreetLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
        maxZoom: 19
    }});

    const darkLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
        maxZoom: 16
    }});

    const satLayer = L.tileLayer('https://mt{{s}}.google.com/vt?lyrs=y&hl=th&x={{x}}&y={{y}}&z={{z}}', {{
        subdomains: ['0', '1', '2', '3'],
        maxZoom: 20
    }});

    const osmLayer = L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
        maxZoom: 19
    }});

    const map = L.map('map', {{
        zoomControl: false,
        attributionControl: false
    }}).setView([13.2, 101.2], 6);

    const initialLayer = IS_DARK ? darkLayer : streetLayer;
    initialLayer.addTo(map);

    if (typeof ResizeObserver !== 'undefined') {{
        const mapElForResize = document.getElementById('map');
        if (mapElForResize) {{
            new ResizeObserver(() => map.invalidateSize()).observe(mapElForResize);
        }}
    }}

    L.control.zoom({{ position: 'bottomright' }}).addTo(map);

    L.control.layers({{
        "🗺️ Google Maps": streetLayer,
        "🌙 Dark Canvas (โหมดมืด)": darkLayer,
        "🛰️ ภาพถ่ายดาวเทียม (Satellite)": satLayer,
        "🏛️ Esri Street Map": esriStreetLayer,
        "🌐 OpenStreetMap": osmLayer
    }}, null, {{ position: 'bottomright' }}).addTo(map);

    let heatLayer = null;
    let markerLayerGroup = L.layerGroup().addTo(map);
    let focusMarkerLayerGroup = L.layerGroup().addTo(map);
    let markersMap = {{}};
    let provStatsMap = new Map();
    let hoveredProv = '';
    const provLayersMap = new Map();
    const provFeaturesMap = new Map();

    if (typeof map.createPane === 'function') {{
        map.createPane('provMaskPane');
        map.getPane('provMaskPane').style.zIndex = 445;
        map.getPane('provMaskPane').style.pointerEvents = 'none';

        map.createPane('provBoundaryPane');
        map.getPane('provBoundaryPane').style.zIndex = 450;

        map.createPane('provHighlightPane');
        map.getPane('provHighlightPane').style.zIndex = 455;
        map.getPane('provHighlightPane').style.pointerEvents = 'none';
    }}

    const provMaskLayerGroup = L.layerGroup().addTo(map);
    const provSelectedLayerGroup = L.layerGroup().addTo(map);
    const provHoverLayerGroup = L.layerGroup().addTo(map);
    const hoverTooltip = (typeof L.tooltip === 'function')
        ? L.tooltip({{
            direction: 'top',
            offset: [0, -14],
            className: 'prov-hover-tooltip',
            interactive: false
        }})
        : null;

    // Helper: Escape HTML & Validate URL
    function escHtml(s) {{
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }}

    function safeUrl(u) {{
        if (!u) return '';
        const s = String(u).trim();
        if (/^https?:\\/\\//i.test(s)) return escHtml(s);
        return '';
    }}

    // Helper: Format Numbers
    function fmtNum(n, decimals = 1) {{
        if (n === null || n === undefined || isNaN(n)) return '0';
        if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
        if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
        return Number(n).toLocaleString('th-TH', {{ maximumFractionDigits: decimals }});
    }}

    function fmtBaht(n) {{
        if (!n || n <= 0) return 'ไม่ระบุ';
        if (n >= 1000000) return '฿' + (n / 1000000).toFixed(2) + ' ล้าน';
        return '฿' + Number(n).toLocaleString('th-TH');
    }}

    function calcMedian(arr) {{
        if (!arr || arr.length === 0) return 0;
        const sorted = arr.slice().sort((a, b) => a - b);
        const mid = Math.floor(sorted.length / 2);
        return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
    }}

    function formatAgeTh(days) {{
        days = Math.max(1, Math.round(days || 1));
        const y = Math.floor(days / 365);
        const rem = days % 365;
        const m = Math.floor(rem / 30);
        const d = rem % 30;

        let res = "";
        if (y > 0) {{
            res += `${{y}} ปี `;
            if (m > 0) res += `${{m}} เดือน `;
            res += `(${{days.toLocaleString()}} วัน)`;
        }} else if (m > 0) {{
            res += `${{m}} เดือน `;
            if (d > 0) res += `${{d}} วัน `;
            res += `(${{days}} วัน)`;
        }} else {{
            res += `${{days}} วัน`;
        }}
        return res.trim();
    }}

    function formatUnitPrices(p_sqm, p_sqw) {{
        const parts = [];
        if (p_sqm && p_sqm > 0) {{
            parts.push(`฿${{Math.round(p_sqm).toLocaleString('th-TH')}}/ตร.ม.`);
        }}
        if (p_sqw && p_sqw > 0) {{
            parts.push(`฿${{Math.round(p_sqw).toLocaleString('th-TH')}}/ตร.ว.`);
        }}
        return parts.length > 0 ? parts.join(' • ') : 'ไม่ระบุ';
    }}

    function formatUnitPricesShort(p_sqm, p_sqw) {{
        if (p_sqm && p_sqm > 0) {{
            const val = p_sqm >= 1000 ? (p_sqm / 1000).toFixed(1) + 'k' : Math.round(p_sqm);
            return ` • ฿${{val}}/ตร.ม.`;
        }}
        if (p_sqw && p_sqw > 0) {{
            const val = p_sqw >= 1000 ? (p_sqw / 1000).toFixed(1) + 'k' : Math.round(p_sqw);
            return ` • ฿${{val}}/ตร.ว.`;
        }}
        return '';
    }}

    function getIntervalText() {{
        if (activeMultiplier === 7) return 'ต่อสัปดาห์';
        if (activeMultiplier === 30) return 'ต่อเดือน';
        if (activeMultiplier === 365) return 'ต่อปี';
        return 'ต่อวัน';
    }}

    function getMetricLabel() {{
        const mText = activeMetric === 'vd' ? 'ยอดเข้าชม' : 'ยอดคลิก';
        return `${{mText}} (${{getIntervalText()}})`;
    }}

    function markerKey(p) {{
        return `${{p.prov}}:::${{p.name}}`;
    }}

    function syncMarkersToggleBtn() {{
        const btn = document.getElementById('toggle-markers-btn');
        if (btn) {{
            btn.classList.toggle('active', Boolean(showMarkers));
        }}
    }}

    function fitMapForSelection() {{
        if (!activeProv && !activeRegion) {{
            map.flyTo([13.2, 101.2], 6, {{ duration: 0.7 }});
            return;
        }}
        if (activeProv && provLayersMap.has(activeProv)) {{
            const pLayer = provLayersMap.get(activeProv);
            if (pLayer && typeof pLayer.getBounds === 'function') {{
                const pBounds = pLayer.getBounds();
                if (pBounds && pBounds.isValid && pBounds.isValid()) {{
                    map.fitBounds(pBounds, {{
                        paddingTopLeft: [30, 115],
                        paddingBottomRight: [30, 30],
                        maxZoom: 13,
                        animate: true
                    }});
                    return;
                }}
            }}
        }}
        let targetList = getFilteredProjects();
        if (targetList.length === 0) {{
            targetList = ALL_PROJECTS.filter(p => {{
                if (activeRegion && p._region !== activeRegion) return false;
                if (activeProv && p.prov !== activeProv) return false;
                return true;
            }});
        }}
        if (targetList.length > 0) {{
            const bounds = L.latLngBounds(targetList.map(p => [p.lat, p.lon]));
            if (bounds.isValid()) {{
                map.fitBounds(bounds, {{
                    paddingTopLeft: [30, 115],
                    paddingBottomRight: [30, 30],
                    maxZoom: activeProv ? 13 : 9,
                    animate: true
                }});
            }}
        }}
    }}

    function selectProvinceDrilldown(provName) {{
        activeProv = provName;
        provSelect.value = provName;
        showMarkers = true;
        syncMarkersToggleBtn();
        clearHoverState();
        renderView();
        fitMapForSelection();
    }}

    function resetToAllProvinces() {{
        activeProv = '';
        provSelect.value = '';
        showMarkers = false;
        syncMarkersToggleBtn();
        clearHoverState();
        renderView();
        fitMapForSelection();
    }}

    // Filter Logic
    function getFilteredProjects() {{
        return ALL_PROJECTS.filter(p => {{
            if (activeRegion && p._region !== activeRegion) return false;
            if (activeProv && p.prov !== activeProv) return false;
            if (activeType && p.prop_type !== activeType) return false;
            if (p.units < activeMinUnits) return false;

            if (activePriceRange) {{
                const price = p.price || 0;
                if (activePriceRange === 'under2m' && price >= 2000000) return false;
                if (activePriceRange === '2to5m' && (price < 2000000 || price > 5000000)) return false;
                if (activePriceRange === '5to10m' && (price < 5000000 || price > 10000000)) return false;
                if (activePriceRange === 'over10m' && price <= 10000000) return false;
            }}

            if (searchQuery) {{
                const q = searchQuery.toLowerCase();
                const matchName = (p.name || '').toLowerCase().includes(q);
                const matchDist = (p.dist || '').toLowerCase().includes(q);
                const matchProv = (p.prov || '').toLowerCase().includes(q);
                if (!matchName && !matchDist && !matchProv) return false;
            }}

            return true;
        }});
    }}

    function updateRealtimeKpis(filtered, provCount) {{
        const totalProj = filtered.length;
        let sumUnits = 0;
        const vdList = [];
        const cdList = [];

        for (let i = 0; i < filtered.length; i++) {{
            const p = filtered[i];
            sumUnits += (p.units || 0);
            if (p.vd !== null && p.vd !== undefined) vdList.push(p.vd * activeMultiplier);
            if (p.cd !== null && p.cd !== undefined) cdList.push(p.cd * activeMultiplier);
        }}

        const medVd = calcMedian(vdList);
        const medCd = calcMedian(cdList);
        const tShort = getIntervalText().replace('ต่อ', '');

        document.getElementById('kpi-projects').textContent = totalProj.toLocaleString('th-TH');
        let scopeText = `${{provCount}} จังหวัด`;
        if (activeProv) scopeText = activeProv;
        else if (activeRegion) scopeText = `${{activeRegion}} • ${{provCount}} จ.`;
        document.getElementById('kpi-projects-lbl').textContent = `โครงการ / โซนทำเล (${{scopeText}})`;

        document.getElementById('kpi-units').textContent = sumUnits.toLocaleString('th-TH');

        document.getElementById('kpi-med-vd').textContent = medVd.toLocaleString('th-TH', {{
            minimumFractionDigits: activeMultiplier === 1 ? 1 : 0,
            maximumFractionDigits: activeMultiplier >= 30 ? 0 : 1
        }});
        document.getElementById('kpi-med-vd-lbl').textContent = `ยอดเข้าชมมัธยฐาน (Median วิว/${{tShort}})`;

        document.getElementById('kpi-med-cd').textContent = medCd.toLocaleString('th-TH', {{
            minimumFractionDigits: activeMultiplier === 1 ? 2 : 0,
            maximumFractionDigits: activeMultiplier === 1 ? 2 : 1
        }});
        document.getElementById('kpi-med-cd-lbl').textContent = `ยอดคลิกมัธยฐาน (Median คลิก/${{tShort}})`;
    }}

    function createMarker(p, normScore) {{
        const rad = activeProv
            ? Math.min(18, Math.max(6, Math.log10(Math.max(1, p._score)) * 4.5))
            : Math.round(6 + Math.min(1, Math.max(0, normScore)) * 9);
        const color = normScore >= 0.65 ? '#ef4444' : (normScore >= 0.35 ? '#fbbf24' : '#38bdf8');

        const marker = L.circleMarker([p.lat, p.lon], {{
            radius: rad,
            fillColor: color,
            color: '#ffffff',
            weight: 1.5,
            opacity: 0.9,
            fillOpacity: 0.78
        }});

        const safeName = escHtml(p.name);
        const safeSubdist = escHtml(p.subdist);
        const safeDist = escHtml(p.dist);
        const safeProv = escHtml(p.prov);
        const safeStartDt = escHtml(p.start_dt || '-');
        const safeEndDt = escHtml(p.end_dt || '-');
        const safeLink = safeUrl(p.link);

        marker.bindTooltip(`<strong>${{safeName}}</strong><br>${{safeProv}} • ${{fmtNum(p._score)}} ${{getMetricLabel()}} • ${{p.units}} ประกาศ`, {{
            direction: 'top',
            offset: [0, -rad]
        }});

        const vd = p.vd || 0;
        const cd = p.cd || 0;
        const popupHtml = `
            <div class="popup-header">
                <div class="popup-title">${{safeName}}</div>
                <div class="popup-loc"><i class="fa-solid fa-location-dot"></i> ${{safeSubdist}} ${{safeDist}} ${{safeProv}}</div>
            </div>
            <div class="popup-body">
                <div class="stat-grid">
                    <div class="stat-box">
                        <div class="stat-box-val">${{fmtNum(p._score)}}</div>
                        <div class="stat-box-lbl">${{getMetricLabel()}}</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-box-val">${{p.units}}</div>
                        <div class="stat-box-lbl">จำนวนยูนิตในโครงการ</div>
                    </div>
                </div>
                <table class="popup-table">
                    <thead>
                        <tr><th>สถิติมัธยฐาน (Median)</th><th>ยอดเข้าชม</th><th>ยอดคลิก</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>ต่อวัน</td><td><strong>${{fmtNum(vd)}}</strong></td><td>${{fmtNum(cd, 2)}}</td></tr>
                        <tr><td>ต่อสัปดาห์</td><td><strong>${{fmtNum(vd * 7)}}</strong></td><td>${{fmtNum(cd * 7, 1)}}</td></tr>
                        <tr><td>ต่อเดือน</td><td><strong>${{fmtNum(vd * 30)}}</strong></td><td>${{fmtNum(cd * 30, 1)}}</td></tr>
                        <tr><td>ต่อปี</td><td><strong>${{fmtNum(vd * 365, 0)}}</strong></td><td>${{fmtNum(cd * 365, 0)}}</td></tr>
                    </tbody>
                </table>
                <div style="background: rgba(0,0,0,0.12); border: 1px solid var(--border-color); border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; font-size: 0.75rem; line-height: 1.5;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                        <span style="color: var(--text-muted);"><i class="fa-regular fa-calendar-days" style="color: var(--accent); margin-right: 4px;"></i> วันประกาศ:</span>
                        <strong style="color: var(--text-main);">${{p.units > 1 && p.start_dt !== p.end_dt ? `${{safeStartDt}} - ${{safeEndDt}}` : safeStartDt}}</strong>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                        <span style="color: var(--text-muted);"><i class="fa-solid fa-hourglass-half" style="color: #f59e0b; margin-right: 4px;"></i> อายุประกาศ:</span>
                        <strong style="color: #f59e0b;">${{formatAgeTh(p.days)}}</strong>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                        <span style="color: var(--text-muted);"><i class="fa-solid fa-tag" style="color: #10b981; margin-right: 4px;"></i> ราคากลาง (Median):</span>
                        <strong style="color: var(--text-main);">${{fmtBaht(p.price)}}</strong>
                    </div>
                    <div style="display: flex; justify-content: space-between; border-top: 1px dashed var(--border-color); padding-top: 4px; margin-top: 4px;">
                        <span style="color: var(--text-muted);"><i class="fa-solid fa-ruler-combined" style="color: #38bdf8; margin-right: 4px;"></i> ราคาต่อหน่วย:</span>
                        <strong style="color: var(--accent);">${{formatUnitPrices(p.p_sqm, p.p_sqw)}}</strong>
                    </div>
                </div>
                ${{safeLink ? `<a href="${{safeLink}}" target="_blank" rel="noopener noreferrer" class="popup-btn" style="color: #ffffff !important; -webkit-text-fill-color: #ffffff !important;"><i class="fa-solid fa-arrow-up-right-from-square" style="color: #ffffff !important; -webkit-text-fill-color: #ffffff !important;"></i> ดูประกาศบน Livinginsider</a>` : ''}}
            </div>
        `;
        marker.bindPopup(popupHtml, {{ maxWidth: 320 }});
        return marker;
    }}

    function createProjectCard(p, rank, pName) {{
        const rankCls = rank === 1 ? 'rank-1' : (rank === 2 ? 'rank-2' : (rank === 3 ? 'rank-3' : ''));
        const metricUnit = activeMetric === 'vd' ? 'วิว' : 'คลิก';
        const safeName = escHtml(p.name);
        const safeDist = escHtml(p.dist);
        const safeProv = escHtml(p.prov);
        const safeStartDt = escHtml(p.start_dt || '-');

        const card = document.createElement('div');
        card.className = 'lb-card';
        card.innerHTML = `
            <div class="rank-badge ${{rankCls}}">#${{rank}}</div>
            <div class="lb-card-body">
                <div class="lb-card-title" title="${{safeName}}">${{safeName}}</div>
                <div class="lb-card-loc"><i class="fa-solid fa-location-dot"></i> ${{safeDist}}, ${{safeProv}}</div>
                <div style="font-size: 0.72rem; color: var(--text-muted); margin-bottom: 5px; display: flex; align-items: center; gap: 5px;">
                    <i class="fa-regular fa-clock" style="color: #f59e0b;"></i>
                    <span>ประกาศ: ${{safeStartDt}} (<strong>${{formatAgeTh(p.days)}}</strong>)</span>
                </div>
                <div class="lb-card-footer">
                    <span class="metric-pill">🔥 ${{fmtNum(p._score)}} ${{metricUnit}}/${{pName.replace('ต่อ', '')}}</span>
                    <span class="units-pill">${{p.units}} ยูนิต • ${{fmtBaht(p.price)}}${{formatUnitPricesShort(p.p_sqm, p.p_sqw)}}</span>
                </div>
            </div>
        `;

        card.addEventListener('click', () => {{
            focusMarkerLayerGroup.clearLayers();
            map.flyTo([p.lat, p.lon], 16, {{ duration: 1.2 }});
            let targetMarker = showMarkers ? markersMap[markerKey(p)] : null;
            if (!targetMarker) {{
                targetMarker = createMarker(p, 1.0);
                focusMarkerLayerGroup.addLayer(targetMarker);
            }}
            setTimeout(() => {{
                targetMarker.openPopup();
            }}, 1250);
        }});

        return card;
    }}

    // Province Outer Boundary Hover, Dim Mask & Selection Layer (Zero DOM reordering -> zero stuck tooltips)
    function extractProvHoleRings(feature) {{
        const geom = feature && feature.geometry;
        if (!geom || !geom.coordinates) return [];
        const rings = [];
        if (geom.type === 'Polygon' && Array.isArray(geom.coordinates[0])) {{
            rings.push(geom.coordinates[0].map(c => [c[1], c[0]]));
        }} else if (geom.type === 'MultiPolygon') {{
            geom.coordinates.forEach(poly => {{
                if (Array.isArray(poly) && Array.isArray(poly[0])) {{
                    rings.push(poly[0].map(c => [c[1], c[0]]));
                }}
            }});
        }}
        return rings;
    }}

    function clearHoverState() {{
        hoveredProv = '';
        provHoverLayerGroup.clearLayers();
        if (hoverTooltip && typeof map.removeLayer === 'function') {{
            try {{ map.removeLayer(hoverTooltip); }} catch(e) {{}}
        }}
    }}

    function updateHoverHighlight(provName, latlng) {{
        hoveredProv = provName;
        provHoverLayerGroup.clearLayers();
        const feat = provFeaturesMap.get(provName);
        if (feat && typeof L.geoJSON === 'function') {{
            const hoverColor = activeProv === provName ? '#fbbf24' : (IS_DARK ? '#38bdf8' : '#0284c7');
            L.geoJSON(feat, {{
                pane: typeof map.getPane === 'function' && map.getPane('provHighlightPane') ? 'provHighlightPane' : 'overlayPane',
                interactive: false,
                style: {{
                    color: hoverColor,
                    weight: activeProv === provName ? 3 : 2.5,
                    opacity: 0.98,
                    fillColor: hoverColor,
                    fillOpacity: 0.08,
                    interactive: false
                }}
            }}).addTo(provHoverLayerGroup);
        }}
        if (hoverTooltip && latlng) {{
            hoverTooltip.setLatLng(latlng).setContent(buildProvTooltipHtml(provName));
            if (typeof map.hasLayer !== 'function' || !map.hasLayer(hoverTooltip)) {{
                hoverTooltip.addTo(map);
            }}
        }}
    }}

    function refreshProvBoundaryStyles() {{
        provSelectedLayerGroup.clearLayers();
        provMaskLayerGroup.clearLayers();
        if (activeProv && provFeaturesMap.has(activeProv)) {{
            const feat = provFeaturesMap.get(activeProv);
            if (typeof L.polygon === 'function') {{
                const worldRing = [[-90, -180], [-90, 180], [90, 180], [90, -180]];
                const holeRings = extractProvHoleRings(feat);
                if (holeRings.length > 0) {{
                    L.polygon([worldRing, ...holeRings], {{
                        pane: typeof map.getPane === 'function' && map.getPane('provMaskPane') ? 'provMaskPane' : 'overlayPane',
                        stroke: false,
                        fillColor: IS_DARK ? '#020617' : '#e2e8f0',
                        fillOpacity: IS_DARK ? 0.52 : 0.48,
                        interactive: false
                    }}).addTo(provMaskLayerGroup);
                }}
            }}
            if (typeof L.geoJSON === 'function') {{
                L.geoJSON(feat, {{
                    pane: typeof map.getPane === 'function' && map.getPane('provHighlightPane') ? 'provHighlightPane' : 'overlayPane',
                    interactive: false,
                    style: {{
                        color: '#fbbf24',
                        weight: 2.8,
                        opacity: 0.95,
                        dashArray: '6, 4',
                        fillColor: '#fbbf24',
                        fillOpacity: 0.03,
                        interactive: false
                    }}
                }}).addTo(provSelectedLayerGroup);
            }}
        }}
    }}

    function formatProvStatText(g) {{
        const metricUnit = activeMetric === 'vd' ? 'วิว' : 'คลิก';
        const pNameShort = getIntervalText().replace('ต่อ', '');
        if (provSortMode === 'all_median') {{
            return `${{g.count.toLocaleString('th-TH')}} โครงการ • Median ทั้งจังหวัด ${{fmtNum(g.medianScore)}} ${{metricUnit}}/${{pNameShort}}`;
        }}
        if (provSortMode === 'total_sum') {{
            return `${{g.count.toLocaleString('th-TH')}} โครงการ • รวม ${{fmtNum(g.totalTraffic)}} ${{metricUnit}}/${{pNameShort}}`;
        }}
        if (provSortMode === 'count') {{
            return `${{g.count.toLocaleString('th-TH')}} โครงการ (${{g.totalUnits.toLocaleString('th-TH')}} ประกาศ) • Top 5: ${{fmtNum(g.top5MedianScore)}}`;
        }}
        return `${{g.count.toLocaleString('th-TH')}} โครงการ • Median Top 5: ${{fmtNum(g.top5MedianScore)}} ${{metricUnit}}/${{pNameShort}}`;
    }}

    function buildProvTooltipHtml(provName) {{
        const safeProv = escHtml(provName);
        const st = provStatsMap.get(provName);
        if (st && st.count > 0) {{
            return `<div class="prov-tt-name">${{safeProv}}</div><div class="prov-tt-meta">${{formatProvStatText(st)}}</div>`;
        }}
        if (activeProv && activeProv !== provName) {{
            return `<div class="prov-tt-name">${{safeProv}}</div><div class="prov-tt-meta">คลิกเพื่อสลับไปดูจังหวัดนี้</div>`;
        }}
        if (activeRegion && (PROVINCE_TO_REGION[provName] || 'อื่นๆ / ไม่ระบุ') !== activeRegion) {{
            return `<div class="prov-tt-name">${{safeProv}}</div><div class="prov-tt-meta">อยู่นอก${{escHtml(activeRegion)}} (คลิกเพื่อดูจังหวัดนี้)</div>`;
        }}
        return `<div class="prov-tt-name">${{safeProv}}</div><div class="prov-tt-meta">ไม่มีข้อมูลตามเงื่อนไขที่เลือก</div>`;
    }}

    if (typeof L.geoJSON === 'function' && PROV_OUTER_GEOJSON && Array.isArray(PROV_OUTER_GEOJSON.features)) {{
        L.geoJSON(PROV_OUTER_GEOJSON, {{
            pane: typeof map.getPane === 'function' && map.getPane('provBoundaryPane') ? 'provBoundaryPane' : 'overlayPane',
            style: () => ({{
                color: 'transparent',
                weight: 0,
                opacity: 0,
                fillColor: '#000000',
                fillOpacity: 0.001
            }}),
            onEachFeature: (feature, layer) => {{
                const provName = feature && feature.properties ? feature.properties.prov : '';
                if (!provName) return;
                provLayersMap.set(provName, layer);
                provFeaturesMap.set(provName, feature);
                layer.on({{
                    mouseover: (e) => {{
                        updateHoverHighlight(provName, e.latlng);
                    }},
                    mousemove: (e) => {{
                        if (hoveredProv !== provName) {{
                            updateHoverHighlight(provName, e.latlng);
                        }} else if (hoverTooltip && e.latlng) {{
                            hoverTooltip.setLatLng(e.latlng);
                        }}
                    }},
                    mouseout: () => {{
                        if (hoveredProv === provName) {{
                            clearHoverState();
                        }}
                    }},
                    click: () => {{
                        if (activeRegion && (PROVINCE_TO_REGION[provName] || 'อื่นๆ / ไม่ระบุ') !== activeRegion) {{
                            activeRegion = '';
                            regionSelect.value = '';
                            populateProvinceOptions('');
                        }}
                        selectProvinceDrilldown(provName);
                    }}
                }});
            }}
        }}).addTo(map);
    }}

    if (typeof map.on === 'function') {{
        map.on('mouseout dragstart zoomstart', clearHoverState);
    }}
    const mapDomEl = document.getElementById('map');
    if (mapDomEl) {{
        mapDomEl.addEventListener('mouseleave', clearHoverState);
    }}
    const inMapPanelEl = document.getElementById('in-map-panel');
    if (inMapPanelEl) {{
        inMapPanelEl.addEventListener('mouseenter', clearHoverState);
    }}

    // Render Function
    function renderView() {{
        const filtered = getFilteredProjects();

        // Calculate score per project
        filtered.forEach(p => {{
            p._score = (p[activeMetric] || 0) * activeMultiplier;
        }});

        // Sort globally by score descending
        filtered.sort((a, b) => (b._score - a._score) || ((b.units || 0) - (a.units || 0)));

        // Group by province
        const provMap = new Map();
        filtered.forEach(p => {{
            const pv = (p.prov && p.prov !== '-' && p.prov !== 'nan' && p.prov !== 'None') ? p.prov : 'ไม่ระบุจังหวัด';
            if (!provMap.has(pv)) provMap.set(pv, []);
            provMap.get(pv).push(p);
        }});

        const provGroups = Array.from(provMap.entries()).map(([prov, items]) => {{
            // items are already sorted descending by _score
            const medianScore = calcMedian(items.map(x => x._score));
            const top5MedianScore = calcMedian(items.slice(0, TOP_N_PER_PROV).map(x => x._score));
            const maxScore = items.length > 0 ? items[0]._score : 0;
            const totalUnits = items.reduce((acc, x) => acc + (x.units || 0), 0);
            const totalTraffic = items.reduce((acc, x) => acc + ((activeMetric === 'vd' ? (x.sum_vd || x.vd || 0) : (x.sum_cd || x.cd || 0)) * activeMultiplier), 0);
            return {{
                prov,
                items,
                count: items.length,
                totalUnits,
                medianScore,
                top5MedianScore,
                totalTraffic,
                maxScore
            }};
        }});

        // Sort provinces according to active sort mode (default: top5_median)
        provGroups.sort((a, b) => {{
            if (provSortMode === 'all_median') {{
                return (b.medianScore - a.medianScore) || (b.top5MedianScore - a.top5MedianScore) || (b.count - a.count);
            }}
            if (provSortMode === 'total_sum') {{
                return (b.totalTraffic - a.totalTraffic) || (b.top5MedianScore - a.top5MedianScore) || (b.count - a.count);
            }}
            if (provSortMode === 'count') {{
                return (b.count - a.count) || (b.top5MedianScore - a.top5MedianScore) || (b.maxScore - a.maxScore);
            }}
            return (b.top5MedianScore - a.top5MedianScore) || (b.maxScore - a.maxScore) || (b.count - a.count);
        }});

        // Sync province stats map & boundary styles
        provStatsMap = new Map();
        provGroups.forEach(g => provStatsMap.set(g.prov, g));
        refreshProvBoundaryStyles();
        if (hoveredProv && hoverTooltip) {{
            hoverTooltip.setContent(buildProvTooltipHtml(hoveredProv));
        }}

        // Update real-time KPI cards
        updateRealtimeKpis(filtered, provGroups.length);

        const mName = activeMetric === 'vd' ? 'ยอดเข้าชม' : 'ยอดคลิก';
        const pName = getIntervalText();
        const metricUnit = activeMetric === 'vd' ? 'วิว' : 'คลิก';
        const pNameShort = pName.replace('ต่อ', '');

        const lbTitleEl = document.getElementById('lb-title-text');
        const lbActionsEl = document.getElementById('lb-header-actions');
        const lbSortEl = document.getElementById('lb-sort-label');
        const provSortSelect = document.getElementById('prov-sort-mode');
        lbActionsEl.innerHTML = '';

        // Update Heatmap Legend
        const legendTitleEl = document.getElementById('heat-legend-title');
        const legendMaxEl = document.getElementById('heat-legend-max-lbl');
        if (legendTitleEl) {{
            legendTitleEl.innerHTML = `<i class="fa-solid fa-fire" style="color: #ef4444;"></i> ความร้อน: ${{mName}} (${{pName}})`;
        }}
        if (legendMaxEl) {{
            legendMaxEl.textContent = activeProv ? `สูงมาก (${{activeProv}})` : 'สูงมาก (เทียบรายจังหวัด)';
        }}

        // Prepare Map Heat Points (All filtered projects, per-province Log-scale) & Optional Markers
        const heatPoints = [];
        markerLayerGroup.clearLayers();
        focusMarkerLayerGroup.clearLayers();
        markersMap = {{}};

        if (activeProv) {{
            // SINGLE-PROVINCE DRILL-DOWN MODE (Top 50 Leaderboard, full province Heatmap)
            if (provSortSelect) provSortSelect.style.display = 'none';
            lbTitleEl.innerHTML = `<i class="fa-solid fa-trophy" style="color: #fbbf24;"></i> 50 ทำเลยอดนิยม — ${{escHtml(activeProv)}}`;
            lbSortEl.textContent = `จัดอันดับตาม: ${{mName}}เฉลี่ย${{pName}} • พบ ${{filtered.length.toLocaleString('th-TH')}} โครงการ`;

            const backBtn = document.createElement('button');
            backBtn.className = 'lb-action-btn';
            backBtn.innerHTML = `<i class="fa-solid fa-arrow-left"></i> ทุกจังหวัด`;
            backBtn.addEventListener('click', resetToAllProvinces);
            lbActionsEl.appendChild(backBtn);

            const provMax = filtered.length > 0 && filtered[0]._score > 0 ? filtered[0]._score : 0;
            const logDenom = Math.log1p(Math.max(0, provMax));
            filtered.forEach(p => {{
                const normLog = logDenom > 0 ? (Math.log1p(Math.max(0, p._score)) / logDenom) : 0;
                heatPoints.push([p.lat, p.lon, Math.min(1.0, Math.max(0.12, normLog))]);
            }});

            if (showMarkers) {{
                const mapMarkers = filtered.slice(0, 350);
                mapMarkers.forEach(p => {{
                    const normLog = logDenom > 0 ? (Math.log1p(Math.max(0, p._score)) / logDenom) : 0;
                    const marker = createMarker(p, normLog);
                    markerLayerGroup.addLayer(marker);
                    markersMap[markerKey(p)] = marker;
                }});
            }}
        }} else {{
            // GROUPED BY PROVINCE MODE (All filtered projects in per-province Log-scale Heatmap, Top N markers when toggled)
            if (provSortSelect) provSortSelect.style.display = '';
            const scopeTitle = activeRegion ? escHtml(activeRegion) : 'รายจังหวัด';
            lbTitleEl.innerHTML = `<i class="fa-solid fa-trophy" style="color: #fbbf24;"></i> ทำเลยอดนิยม (${{scopeTitle}})`;
            lbSortEl.textContent = `Top ${{TOP_N_PER_PROV}} ต่อจังหวัด • ${{mName}}${{pName}}`;

            if (provGroups.length > 0) {{
                const toggleAllBtn = document.createElement('button');
                toggleAllBtn.className = 'lb-action-btn';
                toggleAllBtn.innerHTML = expandAllMode
                    ? `<i class="fa-solid fa-compress"></i> พับทั้งหมด`
                    : `<i class="fa-solid fa-expand"></i> กางทั้งหมด`;
                toggleAllBtn.addEventListener('click', () => {{
                    expandAllMode = !expandAllMode;
                    userExpandedProvs.clear();
                    userCollapsedProvs.clear();
                    if (expandAllMode) {{
                        provGroups.forEach(g => userExpandedProvs.add(g.prov));
                    }} else {{
                        provGroups.forEach(g => userCollapsedProvs.add(g.prov));
                    }}
                    renderView();
                }});
                lbActionsEl.appendChild(toggleAllBtn);
            }}

            provGroups.forEach(g => {{
                const logDenom = Math.log1p(Math.max(0, g.maxScore));
                g.items.forEach(p => {{
                    const normLog = logDenom > 0 ? (Math.log1p(Math.max(0, p._score)) / logDenom) : 0;
                    heatPoints.push([p.lat, p.lon, Math.min(1.0, Math.max(0.12, normLog))]);
                }});

                if (showMarkers) {{
                    const topN = g.items.slice(0, TOP_N_PER_PROV);
                    topN.forEach(p => {{
                        const normLog = logDenom > 0 ? (Math.log1p(Math.max(0, p._score)) / logDenom) : 0;
                        const marker = createMarker(p, normLog);
                        markerLayerGroup.addLayer(marker);
                        markersMap[markerKey(p)] = marker;
                    }});
                }}
            }});
        }}

        // Update Heatmap Layer (guarantee old canvas is completely cleared)
        if (heatLayer) {{
            try {{ map.removeLayer(heatLayer); }} catch(e) {{}}
            if (heatLayer._canvas && heatLayer._canvas.parentNode) {{
                heatLayer._canvas.parentNode.removeChild(heatLayer._canvas);
            }}
            heatLayer = null;
        }}
        if (typeof L.heatLayer === 'function' && heatPoints.length > 0) {{
            heatLayer = L.heatLayer(heatPoints, {{
                radius: 26,
                blur: 20,
                minOpacity: 0.3,
                maxZoom: 14,
                gradient: {{
                    0.2: '#38bdf8',
                    0.4: '#10b981',
                    0.6: '#fbbf24',
                    0.8: '#f97316',
                    1.0: '#ef4444'
                }}
            }}).addTo(map);
        }}

        // Render Leaderboard
        const lbContainer = document.getElementById('leaderboard-list');
        lbContainer.innerHTML = '';

        if (filtered.length === 0) {{
            lbContainer.innerHTML = `
                <div style="text-align: center; padding: 40px 10px; color: var(--text-muted);">
                    <i class="fa-solid fa-filter-circle-xmark" style="font-size: 2.5rem; margin-bottom: 12px; opacity: 0.5;"></i>
                    <p style="font-size: 0.9rem;">ไม่พบข้อมูลตามเงื่อนไขที่เลือก</p>
                </div>
            `;
            return;
        }}

        if (activeProv) {{
            const top50 = filtered.slice(0, 50);
            top50.forEach((p, idx) => {{
                lbContainer.appendChild(createProjectCard(p, idx + 1, pName));
            }});
        }} else {{
            provGroups.forEach((g, idx) => {{
                const provRank = idx + 1;
                const rankCls = provRank === 1 ? 'rank-1' : (provRank === 2 ? 'rank-2' : (provRank === 3 ? 'rank-3' : ''));
                const isExpanded = Boolean(searchQuery)
                    || userExpandedProvs.has(g.prov)
                    || (idx < 3 && !userCollapsedProvs.has(g.prov));

                const acc = document.createElement('div');
                acc.className = 'prov-acc' + (isExpanded ? ' open' : '');

                const header = document.createElement('div');
                header.className = 'prov-acc-header';
                header.innerHTML = `
                    <div class="prov-acc-left">
                        <span class="prov-rank-pill ${{rankCls}}">#${{provRank}}</span>
                        <div class="prov-acc-info">
                            <div class="prov-acc-name">${{escHtml(g.prov)}}</div>
                            <div class="prov-acc-meta">${{formatProvStatText(g)}}</div>
                        </div>
                    </div>
                    <div class="prov-acc-right">
                        <button type="button" class="prov-drill-btn" title="เจาะลึก Top 50 ของ${{escHtml(g.prov)}}">ดูทั้งหมด</button>
                        <i class="fa-solid fa-chevron-down prov-chevron"></i>
                    </div>
                `;

                const drillBtn = header.querySelector('.prov-drill-btn');
                drillBtn.addEventListener('click', (e) => {{
                    e.stopPropagation();
                    selectProvinceDrilldown(g.prov);
                }});

                header.addEventListener('click', () => {{
                    const currentlyOpen = acc.classList.contains('open');
                    if (currentlyOpen) {{
                        acc.classList.remove('open');
                        userExpandedProvs.delete(g.prov);
                        userCollapsedProvs.add(g.prov);
                    }} else {{
                        acc.classList.add('open');
                        userCollapsedProvs.delete(g.prov);
                        userExpandedProvs.add(g.prov);
                    }}
                }});

                const body = document.createElement('div');
                body.className = 'prov-acc-body';
                const topItems = g.items.slice(0, TOP_N_PER_PROV);
                topItems.forEach((p, pIdx) => {{
                    body.appendChild(createProjectCard(p, pIdx + 1, pName));
                }});

                if (g.count > TOP_N_PER_PROV) {{
                    const moreBtn = document.createElement('button');
                    moreBtn.type = 'button';
                    moreBtn.className = 'prov-more-btn';
                    moreBtn.textContent = `ดูทั้งหมด ${{g.count}} โครงการใน${{g.prov}} →`;
                    moreBtn.addEventListener('click', () => selectProvinceDrilldown(g.prov));
                    body.appendChild(moreBtn);
                }}

                acc.appendChild(header);
                acc.appendChild(body);
                lbContainer.appendChild(acc);
            }});
        }}
    }}

    // Event Listeners: Metric Group
    document.querySelectorAll('#metric-group .pill-btn').forEach(btn => {{
        btn.addEventListener('click', () => {{
            document.querySelectorAll('#metric-group .pill-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeMetric = btn.dataset.metric;
            renderView();
        }});
    }});

    // Event Listeners: Interval Group
    document.querySelectorAll('#interval-group .pill-btn').forEach(btn => {{
        btn.addEventListener('click', () => {{
            document.querySelectorAll('#interval-group .pill-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeMultiplier = Number(btn.dataset.mult);
            renderView();
        }});
    }});

    // Event Listener: Toggle Markers Overlay
    const toggleMarkersBtn = document.getElementById('toggle-markers-btn');
    if (toggleMarkersBtn) {{
        toggleMarkersBtn.addEventListener('click', () => {{
            showMarkers = !showMarkers;
            toggleMarkersBtn.classList.toggle('active', showMarkers);
            renderView();
        }});
    }}

    // Event Listener: Province Sort Mode
    const provSortSelectEl = document.getElementById('prov-sort-mode');
    if (provSortSelectEl) {{
        provSortSelectEl.addEventListener('change', (e) => {{
            provSortMode = e.target.value || 'top5_median';
            renderView();
        }});
    }}

    // Event Listeners: Filters
    regionSelect.addEventListener('change', (e) => {{
        activeRegion = e.target.value;
        populateProvinceOptions(activeRegion);
        if (!activeProv) {{
            showMarkers = false;
            syncMarkersToggleBtn();
        }}
        renderView();
        fitMapForSelection();
    }});

    provSelect.addEventListener('change', (e) => {{
        activeProv = e.target.value;
        showMarkers = Boolean(activeProv);
        syncMarkersToggleBtn();
        clearHoverState();
        renderView();
        fitMapForSelection();
    }});

    typeSelect.addEventListener('change', (e) => {{
        activeType = e.target.value;
        renderView();
    }});

    document.getElementById('filter-price').addEventListener('change', (e) => {{
        activePriceRange = e.target.value;
        renderView();
    }});

    document.getElementById('filter-units').addEventListener('change', (e) => {{
        activeMinUnits = Number(e.target.value);
        renderView();
    }});

    // Search Input with Debounce
    let searchTimeout = null;
    document.getElementById('lb-search').addEventListener('input', (e) => {{
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {{
            searchQuery = e.target.value.trim();
            renderView();
        }}, 200);
    }});

    // Initial Render
    renderView();
}})();
</script>

</body>
</html>
"""
    return {
        "total_projects": total_projects,
        "total_units": total_units,
        "med_vd": med_vd,
        "med_cd": med_cd,
        "month_short": month_short,
        "html_app": html_app
    }


def precompute_tab5_popular_locations(df_raw, is_dark_mode=False, data_mtime=0):
    """Pre-warms Tab 5 Livinginsider metrics and 70/30 map HTML bundle during the Welcome Screen."""
    if df_raw is None or df_raw.empty:
        return
    cache_key = (
        data_mtime or get_data_mtime(),
        len(df_raw),
        bool(is_dark_mode),
        0,
    )
    _build_tab5_popular_locations_bundle(df_raw, is_dark_mode=is_dark_mode, cache_key=cache_key)


@fragment_decorator
def render_tab5_popular_locations_view(df_raw, is_dark_mode=False):
    """
    Renders Tab 5: Popular Locations (ทำเลยอดนิยม)
    Features:
      - Fast cached Livinginsider project aggregation
      - Real-time filtered KPI summary cards
      - 70/30 dual-pane interactive experience:
        * Left (70%): Leaflet Heatmap + Marker map with floating in-map controls (Glassmorphism)
        * Right (30%): Per-province Top 5 grouped accordion & single-province Top 50 drill-down Leaderboard
    """
    with st.container(key="tab_popular_locations"):
        st.markdown("""
        <style>
        .st-key-tab_popular_locations {
            margin-top: -12px !important;
        }
        .st-key-tab_popular_locations div[data-testid="stHorizontalBlock"] {
            margin-bottom: 8px !important;
        }
        .popular-source-banner {
            background: rgba(30, 41, 59, 0.45);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 9px;
            padding: 7px 14px;
            font-size: 0.8rem;
            color: #94a3b8;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 4px;
        }
        .popular-source-banner strong {
            color: #f1f5f9;
            font-weight: 600;
        }
        .popular-source-banner.light {
            background: #f8fafc;
            border: 1px solid rgba(0, 0, 0, 0.07);
            color: #64748b;
        }
        .popular-source-banner.light strong {
            color: #0f172a;
        }
        </style>
        """, unsafe_allow_html=True)

        cache_key = (
            get_data_mtime(),
            len(df_raw) if df_raw is not None else 0,
            bool(is_dark_mode),
            int(st.session_state.get("_custom_import_ver", 0)),
        )
        bundle = _build_tab5_popular_locations_bundle(df_raw, is_dark_mode=is_dark_mode, cache_key=cache_key)

        if not bundle:
            st.info("ไม่พบข้อมูลสถิติของ Livinginsider ในชุดข้อมูลปัจจุบัน")
            return

        month_short = bundle["month_short"]
        html_app = bundle["html_app"]

        theme_cls = "light" if not is_dark_mode else ""

        # Top Info Banner: Source Attribution
        st.markdown(f"""
        <div class="popular-source-banner {theme_cls}">
            <i class="fa-solid fa-satellite-dish" style="color: #38bdf8; margin-right: 6px;"></i>
            <span><strong>แหล่งข้อมูล:</strong> สถิติการเข้าชมและยอดคลิกอ้างอิงจาก <strong>Livinginsider</strong> (อัปเดตล่าสุด: {month_short})</span>
        </div>
        """, unsafe_allow_html=True)

        # Render HTML component (includes real-time KPI cards + 70/30 map & leaderboard)
        try:
            stc.html(html_app, height=960, scrolling=False)
        except Exception:
            st.html(html_app)
