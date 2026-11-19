import os
import time
import json
import base64
import pandas as pd
import streamlit as st
import streamlit.components.v1 as stc

import user_logger
from modules.services.auth_service import (
    MAX_FAILED_ATTEMPTS,
    authenticate_user,
    check_lockout,
    load_users,
    record_failed_attempt,
    reset_attempts,
)

from modules.services.data_loader import (
    load_properties_data,
    get_data_mtime,
    get_data_mtime_token,
    get_cache_builder_version,
    get_precomputed_map_payload,
    precompute_full_map_html,
    get_sam_project_options,
    STATIC_MAP_PAYLOAD_PATH,
)
from modules.services.geo_service import (
    load_raw_districts_geojson,
    load_raw_subdistricts_geojson,
    get_map_icon_atlas_and_mapping,
    get_leaflet_logo_dict
)
from bubble_chart import generate_3d_glossy_bubble_chart_html

def update_welcome_progress(placeholder, pct, status_text):
    """Renders a sleek luxury tech progress bar with live percentage on the welcome screen."""
    placeholder.html(f"""
    <div style="width: 350px; margin: 10px auto 6px auto; text-align: center; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans Thai', 'Outfit', sans-serif;">
        <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 0.76rem; font-weight: 700; color: #064e3b; margin-bottom: 6px; letter-spacing: 0.2px; white-space: nowrap;">
            <span id="welcome-status-text" style="color: {'#059669' if pct >= 100 else '#475569'}; font-weight: {'700' if pct >= 100 else '600'}; overflow: hidden; text-overflow: ellipsis;">{status_text}</span>
            <span id="welcome-pct-text" style="color: #059669; font-weight: 800; flex-shrink: 0;">{pct}%</span>
        </div>
        <div style="width: 100%; height: 6px; background: rgba(16, 185, 129, 0.14); border-radius: 9999px; overflow: hidden; box-shadow: inset 0 1px 2px rgba(0,0,0,0.06);">
            <div id="welcome-progress-bar" style="width: {pct}%; height: 100%; background: linear-gradient(90deg, #10b981 0%, #059669 100%); border-radius: 9999px; transition: width 0.3s ease;"></div>
        </div>
    </div>
    """)


def _render_browser_map_prewarmer(data_mtime, builder_ver):
    """Renders a hidden 0px runner that warms window.parent.__NOVA_MAP_CACHE__ before entering the dashboard."""
    mtime_token = get_data_mtime_token(data_mtime)
    prewarm_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body>
<script>
(function () {{
  const MTIME_TOKEN = {json.dumps(mtime_token)};
  const BUILDER_VER = {json.dumps(str(builder_ver))};
  const TIMEOUT_MS = 25000;
  let entered = false;

  function updateParentProgress(pct, text) {{
    try {{
      const pdoc = window.parent && window.parent.document;
      if (!pdoc) return;
      const barEl = pdoc.getElementById('welcome-progress-bar');
      const pctEl = pdoc.getElementById('welcome-pct-text');
      const txtEl = pdoc.getElementById('welcome-status-text');
      if (barEl) barEl.style.width = pct + '%';
      if (pctEl) pctEl.textContent = pct + '%';
      if (txtEl) {{
        txtEl.textContent = text;
        if (pct >= 100) {{
          txtEl.style.color = '#059669';
          txtEl.style.fontWeight = '700';
        }}
      }}
    }} catch (_e) {{}}
  }}

  function triggerPortalEnter() {{
    if (entered) return;
    entered = true;
    const tryClick = () => {{
      try {{
        const pdoc = window.parent && window.parent.document;
        const btn = pdoc && pdoc.querySelector('.st-key-btn_welcome_enter_portal button');
        if (btn) {{
          btn.click();
          return true;
        }}
      }} catch (_e) {{}}
      return false;
    }};
    if (!tryClick()) {{
      let tries = 0;
      const timer = setInterval(() => {{
        tries += 1;
        if (tryClick() || tries >= 40) clearInterval(timer);
      }}, 150);
    }}
  }}

  function loadScript(src) {{
    return new Promise((resolve) => {{
      const s = document.createElement('script');
      s.src = src;
      s.async = true;
      s.onload = () => resolve(true);
      s.onerror = () => resolve(false);
      document.head.appendChild(s);
    }});
  }}

  function hasValidParentCacheFast() {{
    try {{
      const c = window.parent && window.parent.__NOVA_MAP_CACHE__;
      return !!(c && c.data && c.data.length > 0 && c.spatialGrid && c.projIndex && String(c.mtime || '') === MTIME_TOKEN);
    }} catch (_e) {{
      return false;
    }}
  }}

  const safetyTimer = setTimeout(() => {{
    updateParentProgress(100, '✓ กำลังเข้าสู่หน้าหลัก...');
    triggerPortalEnter();
  }}, TIMEOUT_MS);

  async function run() {{
    try {{
      if (hasValidParentCacheFast()) {{
        clearTimeout(safetyTimer);
        updateParentProgress(100, '✓ โหลดข้อมูลครบทั้ง 5 แท็บ และแผนที่พร้อมใช้งาน');
        setTimeout(triggerPortalEnter, 40);
        return;
      }}

      const boundaryPromise = Promise.all([
        loadScript('/app/static/provinces_geojson.js?v=20261001'),
        loadScript('/app/static/subdistricts_geojson.js?v=20261001')
      ]).catch(() => null);

      await Promise.all([
        loadScript('/app/static/d3.js'),
        loadScript('/app/static/map_cache_builder.js?v=' + encodeURIComponent(BUILDER_VER)),
        loadScript('/app/static/map_payload_cache.js?v=' + encodeURIComponent(MTIME_TOKEN))
      ]);

      if (window.NovaMapCache && window.__NOVA_RAW_MAP_PAYLOAD__ && window.__NOVA_RAW_MAP_PAYLOAD__.csv) {{
        await window.NovaMapCache.buildAndStoreParentCache(
          MTIME_TOKEN,
          window.__NOVA_RAW_MAP_PAYLOAD__,
          (pct, msg) => updateParentProgress(pct, msg)
        );
      }}

      await Promise.race([boundaryPromise, new Promise((r) => setTimeout(r, 250))]);
      if (window.NovaMapCache) {{
        if (window.ALL_PROVINCES_BOUNDARIES) {{
          window.NovaMapCache.storeParentBoundaryCache('provinces', window.ALL_PROVINCES_BOUNDARIES);
        }}
        if (window.ALL_SUBDISTRICTS_BOUNDARIES) {{
          window.NovaMapCache.storeParentBoundaryCache('subdistricts', window.ALL_SUBDISTRICTS_BOUNDARIES);
        }}
      }}

      clearTimeout(safetyTimer);
      updateParentProgress(100, '✓ โหลดข้อมูลครบทั้ง 5 แท็บ และแผนที่พร้อมใช้งาน');
      setTimeout(triggerPortalEnter, 80);
    }} catch (err) {{
      console.warn('Browser map prewarm fallback:', err);
      clearTimeout(safetyTimer);
      updateParentProgress(100, '✓ โหลดข้อมูลครบทั้ง 5 แท็บ พร้อมใช้งาน');
      triggerPortalEnter();
    }}
  }}

  run();
}})();
</script>
</body>
</html>"""
    stc.html(prewarm_html, height=0)

def _render_welcome_login_card():
    """Renders the Light Luxury glassmorphism login form and handles authentication + user_logger."""
    _, users_err = load_users()

    with st.container(key="welcome_login_card"):
        st.html("""
        <div style="text-align: center; margin-bottom: 10px;">
            <div style="display: inline-flex; align-items: center; gap: 7px; background: rgba(16, 185, 129, 0.10); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 9999px; padding: 4px 12px; font-family: 'Noto Sans Thai', 'Outfit', sans-serif; font-size: 0.74rem; font-weight: 700; color: #047857; margin-bottom: 6px;">
                <i class="fa-solid fa-shield-halved"></i> เข้าสู่ระบบเพื่อใช้งานแดชบอร์ด
            </div>
        </div>
        """)

        if users_err == "missing_file":
            st.warning(
                "ไม่พบไฟล์ `users.txt` สำหรับตรวจสอบสิทธิ์ กรุณาสร้างไฟล์ `users.txt` ที่โฟลเดอร์หลักของโปรเจกต์ (ดูรูปแบบจาก `users.example.txt`)",
                icon=":material/warning:",
            )
        elif users_err == "empty_users":
            st.warning(
                "ไฟล์ `users.txt` ยังไม่มีรายการผู้ใช้งานที่ถูกต้อง กรุณาเพิ่ม `username:password` อย่างน้อย 1 บัญชี",
                icon=":material/warning:",
            )
        elif users_err == "read_error":
            st.error("ไม่สามารถอ่านไฟล์ `users.txt` ได้ กรุณาตรวจสอบสิทธิ์การเข้าถึงไฟล์", icon=":material/error:")

        with st.form("welcome_login_form", clear_on_submit=False):
            username_input = st.text_input(
                "ชื่อผู้ใช้งาน",
                key="welcome_login_username",
                placeholder="Username...",
            )
            password_input = st.text_input(
                "รหัสผ่าน",
                type="password",
                key="welcome_login_password",
                placeholder="Password...",
            )
            submitted = st.form_submit_button(
                "เข้าสู่ระบบ",
                icon=":material/login:",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            attempt_state = st.session_state.get("_login_attempts")
            remaining_lock = check_lockout(attempt_state)
            clean_u = (username_input or "").strip()

            if remaining_lock > 0:
                try:
                    user_logger.log_auth_event(
                        "login_locked",
                        username=clean_u,
                        details=f"Blocked during {remaining_lock}s cooldown",
                    )
                except Exception:
                    pass
                st.error(
                    f"กรอกรหัสผ่านผิดเกินกำหนด กรุณารออีก {remaining_lock} วินาทีแล้วลองใหม่อีกครั้ง",
                    icon=":material/lock_clock:",
                )
                return

            auth_res = authenticate_user(clean_u, password_input or "")
            if auth_res["ok"]:
                st.session_state["authenticated"] = True
                st.session_state["auth_username"] = auth_res["username"]
                st.session_state["auth_display_name"] = auth_res["display_name"]
                st.session_state["user_name"] = auth_res["logger_user_name"]
                st.session_state["_login_attempts"] = reset_attempts()
                st.session_state.pop("welcome_login_password", None)
                try:
                    user_logger.log_auth_event(
                        "login_success",
                        username=auth_res["username"],
                        user_name=auth_res["logger_user_name"],
                        details="Login via welcome screen",
                    )
                    user_logger.log_visit(user_name=auth_res["logger_user_name"])
                    st.session_state["_visitor_logged"] = True
                except Exception:
                    pass
                st.rerun()

            reason = auth_res.get("reason")
            if reason == "empty_input":
                st.warning("กรุณากรอกชื่อผู้ใช้งานและรหัสผ่านให้ครบถ้วน", icon=":material/info:")
                return
            if reason in ("missing_file", "empty_users", "read_error"):
                try:
                    user_logger.log_auth_event(
                        "login_failed",
                        username=clean_u,
                        details=f"Auth config error: {reason}",
                    )
                except Exception:
                    pass
                st.error("ไม่สามารถเข้าสู่ระบบได้เนื่องจากยังไม่ได้ตั้งค่าไฟล์ `users.txt`", icon=":material/error:")
                return

            new_state, locked_for = record_failed_attempt(attempt_state)
            st.session_state["_login_attempts"] = new_state
            if locked_for > 0:
                try:
                    user_logger.log_auth_event(
                        "login_locked",
                        username=auth_res.get("username") or clean_u,
                        user_name=auth_res.get("logger_user_name", ""),
                        details=f"Locked {locked_for}s after {MAX_FAILED_ATTEMPTS} failed attempts",
                    )
                except Exception:
                    pass
                st.error(
                    f"ชื่อผู้ใช้งานหรือรหัสผ่านไม่ถูกต้อง — ระบบล็อคชั่วคราว {locked_for} วินาที",
                    icon=":material/gpp_bad:",
                )
            else:
                attempts_used = int(new_state.get("count", 0))
                attempts_left = max(0, MAX_FAILED_ATTEMPTS - attempts_used)
                try:
                    user_logger.log_auth_event(
                        "login_failed",
                        username=auth_res.get("username") or clean_u,
                        user_name=auth_res.get("logger_user_name", ""),
                        details=f"Invalid credentials ({attempts_used}/{MAX_FAILED_ATTEMPTS})",
                    )
                except Exception:
                    pass
                st.error(
                    f"ชื่อผู้ใช้งานหรือรหัสผ่านไม่ถูกต้อง (เหลือโอกาสอีก {attempts_left} ครั้ง)",
                    icon=":material/gpp_bad:",
                )


def render_welcome_screen():
    """Renders elegant light luxury Welcome Portal with login gate before data preload, 3D levitating icon, live loading progress %, and auto-enter."""
    is_authenticated = bool(st.session_state.get("authenticated", False))
    app_icon_b64 = ""
    icon_paths = [
        os.path.join("logo", "app_icon.png"),
        os.path.join("logo", "logo.png"),
        os.path.join("assets", "logo.png")
    ]
    for p in icon_paths:
        if os.path.exists(p):
            try:
                with open(p, "rb") as f_icon:
                    app_icon_b64 = base64.b64encode(f_icon.read()).decode("utf-8")
                if app_icon_b64:
                    break
            except Exception:
                pass

    sam_logo_b64 = ""
    sam_paths = [
        os.path.join("logo", "logo-main.webp"),
        os.path.join("assets", "logo-main.webp")
    ]
    for p in sam_paths:
        if os.path.exists(p):
            try:
                with open(p, "rb") as f_sam:
                    sam_logo_b64 = base64.b64encode(f_sam.read()).decode("utf-8")
                if sam_logo_b64:
                    break
            except Exception:
                pass

    sam_badge_html = ""
    if sam_logo_b64:
        sam_badge_html = f'''
        <div style="position: fixed; top: 22px; left: 32px; display: flex; align-items: center; gap: 14px; z-index: 999; background: transparent;">
            <img src="data:image/webp;base64,{sam_logo_b64}" style="height: 48px; width: auto; object-fit: contain; border-radius: 6px; filter: drop-shadow(0 2px 8px rgba(6, 78, 59, 0.12));" alt="SAM Logo" />
            <div style="display: flex; flex-direction: column; text-align: left; justify-content: center;">
                <span style="font-family: 'Noto Sans Thai', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 1.18rem; font-weight: 800; color: #064e3b; letter-spacing: 0.2px; line-height: 1.25;">บริษัท บริหารสินทรัพย์สุขุมวิท จำกัด</span>
                <span style="font-family: 'Outfit', sans-serif; font-size: 0.70rem; font-weight: 700; color: #059669; letter-spacing: 1.2px;">SUKHUMVIT ASSET MANAGEMENT</span>
            </div>
        </div>
        '''

    preload_links_html = ""
    cur_mtime = None
    cur_mtime_token = ""
    builder_ver = ""
    if is_authenticated:
        cur_mtime = get_data_mtime()
        cur_mtime_token = get_data_mtime_token(cur_mtime)
        builder_ver = get_cache_builder_version()
        payload_preload_tag = (
            f'<link rel="preload" href="/app/static/map_payload_cache.js?v={cur_mtime_token}" as="script">'
            if os.path.exists(STATIC_MAP_PAYLOAD_PATH)
            else ""
        )
        preload_links_html = f"""
<!-- Preload heavy map & chart JS libraries into browser HTTP cache during Welcome Screen -->
<link rel="preload" href="/app/static/d3.js" as="script">
<link rel="preload" href="/app/static/map_cache_builder.js?v={builder_ver}" as="script">
{payload_preload_tag}
<link rel="preload" href="/app/static/deck.gl.js" as="script">
<link rel="preload" href="/app/static/provinces_geojson.js?v=20261001" as="script">
<link rel="preload" href="/app/static/subdistricts_geojson.js?v=20261001" as="script">
<link rel="preload" href="/app/static/vendor/leaflet/leaflet.css" as="style">
<link rel="preload" href="/app/static/vendor/leaflet/leaflet.js" as="script">
<link rel="preload" href="/app/static/leaflet-heat.js" as="script">
"""

    stage_w, stage_h, img_size, title_size, title_margin = (
        ("320px", "310px", "300px", "5.2rem", "18px 0 4px 16px")
        if is_authenticated
        else ("220px", "205px", "190px", "4.0rem", "10px 0 2px 14px")
    )
    overflow_css = "hidden" if is_authenticated else "auto"
    container_height_css = "height: 100vh !important;" if is_authenticated else "min-height: 100vh !important; height: auto !important; padding: 24px 12px !important;"

    st.html(f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@800;900&family=Outfit:wght@600;700;800;900&family=Noto+Sans+Thai:wght@500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
header[data-testid="stHeader"] {{
    background: transparent !important;
}}
section[data-testid="stSidebar"] {{
    display: none !important;
}}

html, body {{
    min-height: 100vh !important;
    overflow-x: hidden !important;
    overflow-y: {overflow_css} !important;
}}

div[data-testid="stAppViewBlockContainer"],
.main .block-container,
.block-container {{
    padding: 0 !important;
    max-width: 100% !important;
    {container_height_css}
    min-height: 100vh !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    overflow-x: hidden !important;
    overflow-y: {overflow_css} !important;
    margin: 0 auto !important;
}}

div[data-testid="stVerticalBlock"] {{
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    width: 100% !important;
    gap: 0 !important;
}}

body, .stApp {{
    background: radial-gradient(circle at 50% 40%, #ffffff 0%, #f4fbf7 38%, #e8f7f0 70%, #dcf3e9 100%) !important;
    min-height: 100vh !important;
}}

.portal-stage-light {{
    position: relative;
    width: {stage_w};
    height: {stage_h};
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
}}

.portal-house-img {{
    width: {img_size};
    height: {img_size};
    object-fit: contain;
    filter: drop-shadow(0 24px 40px rgba(6, 78, 59, 0.18));
    animation: floatLevitate 7s ease-in-out infinite;
    user-select: none;
    -webkit-user-drag: none;
}}

.portal-ground-shadow {{
    width: 180px;
    height: 20px;
    background: radial-gradient(ellipse at center, rgba(16, 185, 129, 0.42) 0%, rgba(5, 150, 105, 0.14) 50%, transparent 75%);
    border-radius: 50%;
    margin-top: 10px;
    animation: shadowPulse 7s ease-in-out infinite;
}}

@keyframes floatLevitate {{
    0%, 100% {{ transform: translateY(0px); }}
    50% {{ transform: translateY(-22px); }}
}}

@keyframes shadowPulse {{
    0%, 100% {{
        transform: scale(1.12);
        opacity: 0.9;
        filter: blur(5px);
    }}
    50% {{
        transform: scale(0.62);
        opacity: 0.22;
        filter: blur(9px);
    }}
}}

.nova-light-title {{
    font-family: 'Montserrat', 'Outfit', sans-serif;
    font-size: {title_size};
    font-weight: 900;
    letter-spacing: 16px;
    background: linear-gradient(180deg, #022c22 0%, #064e3b 38%, #047857 70%, #059669 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: {title_margin};
    line-height: 1.05;
    text-align: center;
    filter: drop-shadow(0 6px 18px rgba(5, 150, 105, 0.3));
}}

.nova-light-sub {{
    font-family: 'Outfit', sans-serif;
    font-size: 0.90rem;
    font-weight: 700;
    color: #475569;
    letter-spacing: 6px;
    text-transform: uppercase;
    text-align: center;
    margin: 6px 0 10px 6px;
}}

.st-key-welcome_login_card {{
    width: min(390px, 92vw) !important;
    max-width: 390px !important;
    margin: 10px auto 0 auto !important;
    padding: 18px 22px 20px 22px !important;
    background: rgba(255, 255, 255, 0.78) !important;
    backdrop-filter: blur(18px) !important;
    -webkit-backdrop-filter: blur(18px) !important;
    border: 1px solid rgba(16, 185, 129, 0.28) !important;
    border-radius: 18px !important;
    box-shadow: 0 18px 44px rgba(6, 78, 59, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.9) !important;
}}

.st-key-welcome_login_card [data-testid="stForm"] {{
    border: none !important;
    padding: 0 !important;
    background: transparent !important;
}}

.st-key-welcome_login_card label p {{
    font-family: 'Noto Sans Thai', 'Outfit', sans-serif !important;
    font-weight: 700 !important;
    font-size: 0.84rem !important;
    color: #064e3b !important;
}}

.st-key-welcome_login_card input {{
    background: rgba(255, 255, 255, 0.94) !important;
    border-radius: 10px !important;
    color: #0f172a !important;
}}

.st-key-welcome_login_card button[kind="primaryFormSubmit"],
.st-key-welcome_login_card [data-testid="stFormSubmitButton"] button {{
    background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
    border: none !important;
    border-radius: 10px !important;
    color: #ffffff !important;
    font-family: 'Noto Sans Thai', 'Outfit', sans-serif !important;
    font-weight: 700 !important;
    font-size: 0.94rem !important;
    padding: 0.55rem 1rem !important;
    box-shadow: 0 6px 18px rgba(5, 150, 105, 0.28) !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease !important;
}}

.st-key-welcome_login_card [data-testid="stFormSubmitButton"] button:hover {{
    transform: translateY(-1px) !important;
    box-shadow: 0 10px 22px rgba(5, 150, 105, 0.36) !important;
}}

.st-key-btn_welcome_enter_portal,
div[data-testid="stElementContainer"]:has(.st-key-btn_welcome_enter_portal),
div[data-testid="stButton"]:has(.st-key-btn_welcome_enter_portal),
.st-key-welcome_prewarm_host,
div[data-testid="stElementContainer"]:has(.st-key-welcome_prewarm_host) {{
    position: fixed !important;
    bottom: -9999px !important;
    right: -9999px !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    opacity: 0 !important;
    z-index: -9999 !important;
}}
</style>

{preload_links_html}

{sam_badge_html}
<div style="display: flex; flex-direction: column; align-items: center; justify-content: center; width: 100%; text-align: center;">
    <div class="portal-stage-light">
        <img class="portal-house-img" src="data:image/png;base64,{app_icon_b64}" alt="NOVA House Icon" />
        <div class="portal-ground-shadow"></div>
    </div>
    <div class="nova-light-title">NOVA</div>
    <div class="nova-light-sub">NPA ASSET INTELLIGENCE</div>
</div>
""")

    if not is_authenticated:
        _render_welcome_login_card()
        return

    progress_slot = st.empty()
    prewarm_slot = st.empty()
    enter_clicked = st.button("enter_portal", key="btn_welcome_enter_portal")
    if enter_clicked:
        prewarm_slot.empty()
        progress_slot.empty()
        st.session_state["portal_entered"] = True
        st.rerun()

    pts_label = ""
    if not st.session_state.get("preload_done", False):
        from modules.ui.kpi_header import precompute_kpi_header
        from modules.views.tab2_fragment import precompute_tab2_default_analytics
        from modules.views.tab3_analytics import precompute_tab3_analytics
        from modules.views.tab4_inventory import precompute_tab4_inventory
        from modules.views.tab5_popular_locations import precompute_tab5_popular_locations

        cur_dark_mode = bool(st.session_state.get("app_theme_mode", st.session_state.get("dark_mode", False)))

        # 1. Database & Global KPI Header
        update_welcome_progress(progress_slot, 14, "กำลังโหลดฐานข้อมูลทรัพย์สิน และการ์ดสรุป KPI...")
        df_p = load_properties_data(cur_mtime)
        if df_p is not None and not df_p.empty:
            precompute_kpi_header(df_p, data_mtime=cur_mtime)

        # 2. Tab 1: 3D Glossy Bubble Chart
        update_welcome_progress(progress_slot, 28, "กำลังเตรียม Tab 1: กราฟภาพรวม 3D Bubble Chart...")
        bubble_cache_key = "cached_bubble_html_v6_dark" if cur_dark_mode else "cached_bubble_html_v6"
        bubble_sig_key = f"{bubble_cache_key}_sig"
        bubble_sig = (cur_mtime, len(df_p) if df_p is not None else 0, int(st.session_state.get("_custom_import_ver", 0)), bool(cur_dark_mode))
        if df_p is not None and not df_p.empty and (bubble_cache_key not in st.session_state or st.session_state.get(bubble_sig_key) != bubble_sig):
            try:
                st.session_state[bubble_cache_key] = generate_3d_glossy_bubble_chart_html(df_p, is_dark_mode=cur_dark_mode)
                st.session_state[bubble_sig_key] = bubble_sig
            except Exception:
                pass

        # 3. Tab 2: Interactive Map & GeoJSON Boundaries
        pts_label = ""
        if df_p is not None and not df_p.empty:
            try:
                if 'ละติจูด' in df_p.columns and 'ลองจิจูด' in df_p.columns:
                    lat_s = pd.to_numeric(df_p['ละติจูด'], errors='coerce')
                    lon_s = pd.to_numeric(df_p['ลองจิจูด'], errors='coerce')
                    valid_cnt = int((lat_s.notna() & lon_s.notna() & lat_s.between(5, 21) & lon_s.between(97, 106)).sum())
                    pts_label = f" {valid_cnt:,} จุด"
                else:
                    pts_label = f" {len(df_p):,} จุด"
            except Exception:
                pts_label = f" {len(df_p):,} จุด"

        update_welcome_progress(progress_slot, 46, f"กำลังเตรียม Tab 2: พิกัดแผนที่{pts_label}...")
        load_raw_districts_geojson()
        load_raw_subdistricts_geojson()
        get_precomputed_map_payload(cur_mtime)
        precompute_full_map_html(cur_mtime)
        get_map_icon_atlas_and_mapping()
        get_leaflet_logo_dict()
        if df_p is not None and not df_p.empty:
            get_sam_project_options(df_p, cache_key=(cur_mtime, len(df_p)))

        # 4. Tab 2: Nationwide Median Analytics & Property Table
        update_welcome_progress(progress_slot, 60, "กำลังเตรียม Tab 2: ตารางวิเคราะห์ราคากลาง (Median)...")
        if df_p is not None and not df_p.empty:
            precompute_tab2_default_analytics(df_p, data_mtime=cur_mtime)

        # 5. Tab 3: Competitor & Market Analytics (Sub-tabs 1, 2, 3)
        update_welcome_progress(progress_slot, 72, "กำลังเตรียม Tab 3: กราฟสถิติและวิเคราะห์คู่แข่ง...")
        if df_p is not None and not df_p.empty:
            precompute_tab3_analytics(df_p, is_dark_mode=cur_dark_mode, data_mtime=cur_mtime)

        # 6. Tab 4: Property Inventory Table Structure
        update_welcome_progress(progress_slot, 80, "กำลังเตรียม Tab 4: โครงสร้างตารางรายการทรัพย์สิน...")
        if df_p is not None and not df_p.empty:
            precompute_tab4_inventory(df_p, data_mtime=cur_mtime)

        # 7. Tab 5: Popular Locations (Livinginsider Heatmap & Leaderboard)
        update_welcome_progress(progress_slot, 88, "กำลังเตรียม Tab 5: แผนที่ทำเลยอดนิยม (Livinginsider)...")
        if df_p is not None and not df_p.empty:
            precompute_tab5_popular_locations(df_p, is_dark_mode=cur_dark_mode, data_mtime=cur_mtime)

        st.session_state["preload_done"] = True

    if st.session_state.get("cached_map_data_len", 0) > 0 and os.path.exists(STATIC_MAP_PAYLOAD_PATH):
        update_welcome_progress(progress_slot, 90, f"กำลังเตรียมข้อมูลแผนที่บนเบราว์เซอร์{pts_label}...")
        with prewarm_slot.container(key="welcome_prewarm_host"):
            _render_browser_map_prewarmer(cur_mtime, builder_ver)
    else:
        update_welcome_progress(progress_slot, 100, "✓ โหลดข้อมูลครบทั้ง 5 แท็บ พร้อมใช้งาน")
        prewarm_slot.empty()
        st.session_state["portal_entered"] = True
        st.rerun()
