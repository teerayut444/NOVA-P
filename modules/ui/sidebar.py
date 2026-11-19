import os
import hmac
import html
import base64
import datetime
import pandas as pd
import streamlit as st
import user_logger
from modules.services.auth_service import authenticate_user
from modules.services.data_cleaner import get_dataset_month_year


_fragment_decorator = getattr(st, "fragment", None)
if _fragment_decorator is not None:
    @_fragment_decorator(run_every=60)
    def _render_session_heartbeat_fragment():
        """Periodically update active session duration every 60s without full page rerun."""
        try:
            user_logger.touch_session()
        except Exception:
            pass
else:
    def _render_session_heartbeat_fragment():
        pass


def render_sidebar(df_raw):
    """Renders the top sidebar: Logo, Theme toggle, Data source summary, Reset filters, and Admin Panel (Visitor Logs & Server Cache)."""
    # ----------------- SIDEBAR HEADER LOGO (Aligned with collapse button) -----------------
    _base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidate_logo_paths = [
        os.path.join("logo", "logo-main.webp"),
        os.path.join(_base_dir, "logo", "logo-main.webp"),
        r"C:\Users\Teerayut.N\.vscode\extensions\NOVA\logo\logo-main.webp",
    ]
    logo_main_path = next((p for p in candidate_logo_paths if os.path.exists(p)), None)

    # Ensure collapsed icon has both SAM logo and House icon side-by-side (SAM first)
    collapsed_icon_path = os.path.join("logo", "collapsed_sam_house.png")
    if not os.path.exists(collapsed_icon_path):
        try:
            from PIL import Image
            sam_p = os.path.join("logo", "logo-main.webp")
            house_p = os.path.join("logo", "app_icon.png")
            if os.path.exists(sam_p) and os.path.exists(house_p):
                sam_im = Image.open(sam_p).convert("RGBA")
                house_im = Image.open(house_p).convert("RGBA")
                target_h = 120
                sam_w = int(target_h * (sam_im.width / sam_im.height))
                sam_res = sam_im.resize((sam_w, target_h), Image.Resampling.LANCZOS)
                house_res = house_im.resize((target_h, target_h), Image.Resampling.LANCZOS)
                gap = 24
                tot_w = sam_w + gap + target_h
                comb = Image.new("RGBA", (tot_w, target_h), (0, 0, 0, 0))
                comb.paste(sam_res, (0, 0), sam_res)
                comb.paste(house_res, (sam_w + gap, 0), house_res)
                comb.save(collapsed_icon_path, "PNG")
        except Exception:
            pass

    candidate_icon_paths = [
        os.path.join("logo", "collapsed_sam_house.png"),
        os.path.join(_base_dir, "logo", "collapsed_sam_house.png"),
        os.path.join("logo", "logo-main.webp"),
        os.path.join(_base_dir, "logo", "logo-main.webp"),
    ]
    icon_path = next((p for p in candidate_icon_paths if os.path.exists(p)), logo_main_path)

    if logo_main_path and hasattr(st, "logo"):
        try:
            st.logo(
                image=logo_main_path,
                icon_image=icon_path if icon_path else logo_main_path,
                size="large"
            )
        except Exception:
            pass

    with st.sidebar:
        st.html("""<style>
        [data-testid="stSidebarHeader"],
        section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
            width: 100% !important;
            visibility: visible !important;
            opacity: 1 !important;
            padding: 8px 0 4px 0 !important;
            margin-bottom: 6px !important;
            min-height: 48px !important;
            box-sizing: border-box !important;
        }
        [data-testid="stSidebarHeader"] [data-testid="stLogo"],
        [data-testid="stSidebarHeader"] a:has(img.stLogo),
        [data-testid="stSidebarHeader"] .stLogo {
            display: flex !important;
            align-items: center !important;
            justify-content: flex-start !important;
            visibility: visible !important;
            opacity: 1 !important;
            margin: 0 !important;
            padding: 0 !important;
            line-height: 1 !important;
            text-decoration: none !important;
        }
        [data-testid="stSidebarHeader"] [data-testid="stLogo"] img,
        [data-testid="stSidebarHeader"] img.stLogo {
            height: 36px !important;
            max-height: 40px !important;
            width: auto !important;
            max-width: 135px !important;
            object-fit: contain !important;
            border-radius: 6px !important;
            filter: drop-shadow(0 2px 5px rgba(0,0,0,0.25)) !important;
            transition: transform 0.2s ease, filter 0.2s ease !important;
        }
        [data-testid="stSidebarHeader"] [data-testid="stLogo"] img:hover,
        [data-testid="stSidebarHeader"] img.stLogo:hover {
            transform: scale(1.03) !important;
            filter: drop-shadow(0 4px 8px rgba(0,0,0,0.35)) !important;
        }
        [data-testid="stSidebarHeader"] a,
        [data-testid="stSidebarHeader"] a:hover,
        [data-testid="stSidebarHeader"] a:focus {
            text-decoration: none !important;
            outline: none !important;
            box-shadow: none !important;
        }
        [data-testid="stSidebarCollapsedControl"] {
            display: flex !important;
            align-items: center !important;
            gap: 8px !important;
            visibility: visible !important;
            opacity: 1 !important;
        }
        header[data-testid="stHeader"] [data-testid="stHeaderLogo"],
        header[data-testid="stHeader"] [data-testid="stLogo"],
        header[data-testid="stHeader"] img.stLogo {
            height: 32px !important;
            max-height: 36px !important;
            width: auto !important;
            max-width: 160px !important;
            object-fit: contain !important;
            border-radius: 5px !important;
            filter: drop-shadow(0 2px 4px rgba(0,0,0,0.18)) !important;
        }
        [data-testid="stSidebarCollapseButton"],
        [data-testid="stSidebarCollapseButton"] button,
        button[data-testid="stSidebarCollapseButton"],
        [data-testid="stSidebarNavCollapseButton"],
        [data-testid="stSidebarHeader"] button,
        section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] button,
        section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"],
        section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button,
        section[data-testid="stSidebar"] button[kind="headerNoPadding"],
        section[data-testid="stSidebar"] button[kind="header"] {
            display: inline-flex !important;
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
            margin-left: auto !important;
            margin-right: 0 !important;
            right: 0 !important;
            left: auto !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
        }
        [data-testid="stSidebarCollapseButton"] *,
        [data-testid="stSidebarCollapseButton"] svg,
        [data-testid="stSidebarCollapseButton"] svg *,
        [data-testid="stSidebarCollapseButton"] svg path,
        button[data-testid="stSidebarCollapseButton"] *,
        button[data-testid="stSidebarCollapseButton"] svg,
        button[data-testid="stSidebarCollapseButton"] svg path,
        [data-testid="stSidebarHeader"] button *,
        [data-testid="stSidebarHeader"] button svg,
        [data-testid="stSidebarHeader"] button svg path,
        section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] button *,
        section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] button svg,
        section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] button svg path,
        section[data-testid="stSidebar"] button[kind="headerNoPadding"] *,
        section[data-testid="stSidebar"] button[kind="headerNoPadding"] svg,
        section[data-testid="stSidebar"] button[kind="headerNoPadding"] svg path,
        section[data-testid="stSidebar"] button[kind="header"] *,
        section[data-testid="stSidebar"] button[kind="header"] svg,
        section[data-testid="stSidebar"] button[kind="header"] svg path {
            color: #ffffff !important;
            fill: #ffffff !important;
            stroke: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            opacity: 1 !important;
            filter: none !important;
            text-shadow: none !important;
            box-shadow: none !important;
        }
        [data-testid="stSidebarCollapseButton"]:hover *,
        [data-testid="stSidebarCollapseButton"] button:hover *,
        [data-testid="stSidebarHeader"] button:hover *,
        section[data-testid="stSidebar"] button[kind="headerNoPadding"]:hover * {
            color: #34d399 !important;
            fill: #34d399 !important;
            stroke: #34d399 !important;
            -webkit-text-fill-color: #34d399 !important;
            filter: none !important;
            text-shadow: none !important;
            box-shadow: none !important;
        }
        </style>""")
        col_side_title, col_side_theme = st.columns([0.72, 0.28])
        with col_side_title:
            st.markdown('''
            <div style="display: flex; flex-direction: column; justify-content: center; margin-bottom: 2px; padding-top: 2px;">
                <div style="font-size: 1.35rem; font-weight: 800; color: #ffffff; line-height: 1.1; letter-spacing: -0.5px;">NOVA <span style="font-size: 0.72rem; font-weight: 600; color: #a7f3d0; letter-spacing: 0.2px;">v1.2</span></div>
                <div style="font-size: 0.68rem; font-weight: 700; color: #a7f3d0; letter-spacing: 0.8px;">NPA DASHBOARD</div>
            </div>
            ''', unsafe_allow_html=True)
            
        with col_side_theme:
            col_t1, col_t2 = st.columns([0.65, 0.35])
            with col_t1:
                is_dark_mode = st.toggle("โหมดมืด", value=False, key="app_theme_mode", label_visibility="collapsed", help="สลับระหว่างโหมดมืดและโหมดสว่าง (Dark / Light Mode)")
            with col_t2:
                st.markdown(f'''<div style="padding-top: 6px; font-size: 1.15rem; color: {'#34d399' if is_dark_mode else '#6ee7b7'};"><i class="fa-solid fa-moon"></i></div>''', unsafe_allow_html=True)
        
        if st.session_state.get("authenticated"):
            cur_user_display = html.escape(str(st.session_state.get("user_name") or st.session_state.get("auth_username") or "User"))
            col_user_badge, col_user_logout = st.columns([0.66, 0.34])
            with col_user_badge:
                st.markdown(f"""
                <div style="background: rgba(16, 185, 129, 0.14); border: 1px solid rgba(52, 211, 153, 0.35); border-radius: 8px; padding: 6px 9px; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; overflow: hidden;">
                    <i class="fa-solid fa-circle-user" style="color: #34d399; font-size: 0.9rem; flex-shrink: 0;"></i>
                    <span style="color: #ecfdf5; font-size: 0.77rem; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{cur_user_display}">{cur_user_display}</span>
                </div>
                """, unsafe_allow_html=True)
            with col_user_logout:
                if st.button("ออก", icon=":material/logout:", key="btn_user_logout", use_container_width=True, help="ออกจากระบบ (Logout)"):
                    try:
                        user_logger.log_auth_event(
                            "logout",
                            username=st.session_state.get("auth_username", ""),
                            user_name=st.session_state.get("user_name", ""),
                            details="Logout from sidebar",
                        )
                    except Exception:
                        pass
                    try:
                        if "portal" in st.query_params:
                            del st.query_params["portal"]
                    except Exception:
                        pass
                    for _auth_k in (
                        "authenticated",
                        "auth_username",
                        "auth_display_name",
                        "user_name",
                        "portal_entered",
                        "preload_done",
                        "_visitor_logged",
                        "_log_auth",
                        "log_viewer_password",
                    ):
                        st.session_state.pop(_auth_k, None)
                    st.rerun()

        if df_raw is not None and not df_raw.empty:
            src_name = html.escape(str(getattr(df_raw, 'attrs', {}).get('source', 'all_assets.parquet')))
            # คำนวณวันที่ดึงข้อมูลโดยไม่นับรวมของ LED Legal
            _, exact_date_str = get_dataset_month_year(df_raw, exclude_legal=True)
            st.markdown(f"""
            <div style="background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(110, 231, 183, 0.25); border-radius: 8px; padding: 7px 10px; margin-top: 5px; margin-bottom: 8px; font-size: 0.8rem; color: #f0fdf4; font-weight: 600;">
                <i class="fa fa-database" style="color:#34d399;"></i> แหล่งข้อมูล: <code style="background:rgba(0,0,0,0.25); color:#a7f3d0; padding:1px 5px; border-radius:4px;">{src_name}</code><br/>
                <span style="font-size: 0.75rem; color: #6ee7b7; font-weight: 600;"><i class="fa fa-calendar-check" style="margin-right: 3px; color:#34d399;"></i> ดึงข้อมูล: <b style="color:#ffffff;">{exact_date_str}</b></span>
            </div>
            """, unsafe_allow_html=True)
            
        btn_reset_filters_clicked = st.button(
            "รีเซ็ตตัวกรอง",
            icon=":material/restart_alt:",
            key="btn_reset_filters_main",
            use_container_width=True,
            help="รีเซ็ตค่าตัวกรองและคืนค่าระบบทั้งหมด เสมือนเข้าเว็บไซต์ใหม่"
        )

        if btn_reset_filters_clicked:
            # ล้าง URL query params และ session state ของผู้ใช้ทั้งหมด เพื่อรีเซ็ตเหมือนเข้าเว็บใหม่เอี่ยม
            try:
                st.query_params.clear()
            except Exception:
                pass
            
            _preserved_keys = {
                "_visitor_logged",
                "authenticated",
                "auth_username",
                "auth_display_name",
                "user_name",
                "_login_attempts",
            }
            for k in list(st.session_state.keys()):
                if not k.startswith("log_") and k not in _preserved_keys:
                    st.session_state.pop(k, None)
            
            overlay_bg = "rgba(6, 78, 59, 0.95)" if is_dark_mode else "rgba(255, 255, 255, 0.96)"
            overlay_title = "#34d399" if is_dark_mode else "#059669"
            overlay_desc = "#a7f3d0" if is_dark_mode else "#475569"
            spinner_border = "rgba(52, 211, 153, 0.25)" if is_dark_mode else "rgba(5, 150, 105, 0.2)"
            spinner_top = "#34d399" if is_dark_mode else "#059669"

            st.html(f"""
            <div style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: {overlay_bg}; backdrop-filter: blur(8px); z-index: 99999999; display: flex; flex-direction: column; align-items: center; justify-content: center; font-family: 'Noto Sans Thai', 'Outfit', -apple-system, sans-serif;">
                <div style="width: 52px; height: 52px; border: 4px solid {spinner_border}; border-top: 4px solid {spinner_top}; border-radius: 50%; animation: spinReset 0.75s linear infinite; margin-bottom: 18px;"></div>
                <h3 style="color: {overlay_title}; font-weight: 800; font-size: 1.35rem; margin: 0 0 8px 0; letter-spacing: -0.3px;">กำลังรีเซ็ตระบบและคืนค่าเริ่มต้น...</h3>
                <p style="color: {overlay_desc}; font-size: 0.92rem; margin: 0; font-weight: 500;">ระบบกำลังล้างตัวกรองทั้งหมด และนำท่านกลับสู่หน้าเริ่มต้น</p>
            </div>
            <style>
            @keyframes spinReset {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
            </style>
            <script>
            setTimeout(function() {{
                var cleanUrl = window.location.origin + window.location.pathname;
                try {{
                    if (window.top && window.top !== window) {{
                        window.top.location.href = window.top.location.origin + window.top.location.pathname;
                        return;
                    }}
                }} catch(e1) {{}}
                try {{
                    if (window.parent && window.parent !== window) {{
                        window.parent.location.href = window.parent.location.origin + window.parent.location.pathname;
                        return;
                    }}
                }} catch(e2) {{}}
                window.location.href = cleanUrl;
            }}, 350);
            </script>
            """, unsafe_allow_javascript=True)
            st.stop()

        # Log visitor (first load logs visit; subsequent reruns & 60s heartbeat update duration only)
        if "_visitor_logged" not in st.session_state:
            try:
                user_logger.log_visit()
                st.session_state["_visitor_logged"] = True
            except Exception:
                st.session_state["_visitor_logged"] = True
        else:
            try:
                user_logger.touch_session()
            except Exception:
                pass

        _render_session_heartbeat_fragment()

        # Feedback Form Link for Users (High contrast, clearly visible link text & URL)
        st.markdown("""
        <div style="background: rgba(2, 44, 34, 0.85); border: 1px solid rgba(52, 211, 153, 0.35); border-radius: 9px; padding: 10px 12px; margin-top: 6px; margin-bottom: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);">
            <div style="display: flex; align-items: center; gap: 7px; margin-bottom: 6px;">
                <i class="fa-solid fa-comment-dots" style="color: #34d399; font-size: 0.95rem;"></i>
                <span style="font-weight: 700; font-size: 0.82rem; color: #ffffff;">แบบฟอร์มรับ Feedback</span>
            </div>
            <a href="https://forms.cloud.microsoft/r/TVjpiii28G" target="_blank" rel="noopener noreferrer" class="nova-feedback-link"
               style="display: flex; flex-direction: column; gap: 3px; background: rgba(16, 185, 129, 0.16); border: 1px solid rgba(52, 211, 153, 0.45); border-radius: 7px; padding: 8px 10px; text-decoration: none !important; transition: all 0.2s ease;">
                <div style="color: #ffffff; font-weight: 700; font-size: 0.80rem; display: flex; align-items: center; justify-content: space-between;">
                    <span>Feedback ระบบ NOVA – Fill out form</span>
                    <i class="fa-solid fa-arrow-up-right-from-square" style="color: #34d399; font-size: 0.75rem; margin-left: 6px;"></i>
                </div>
                <div style="color: #6ee7b7; font-size: 0.70rem; font-weight: 500; word-break: break-all; opacity: 0.95; line-height: 1.25;">
                    https://forms.cloud.microsoft/r/TVjpiii28G
                </div>
            </a>
        </div>
        """, unsafe_allow_html=True)

        # Visitor Access Logs (Admin Only)
        st.html("""<style>
        section[data-testid="stSidebar"] [data-testid="stExpander"] {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            padding: 0 !important;
            margin-bottom: 10px !important;
        }
        section[data-testid="stSidebar"] [data-testid="stExpander"] > details {
            background-color: rgba(2, 44, 34, 0.85) !important;
            background: rgba(2, 44, 34, 0.85) !important;
            border: 1px solid rgba(52, 211, 153, 0.35) !important;
            border-radius: 10px !important;
            overflow: hidden !important;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2) !important;
            padding: 0 !important;
            margin: 0 !important;
        }
        section[data-testid="stSidebar"] [data-testid="stExpander"] > details > summary {
            background-color: transparent !important;
            color: #ffffff !important;
            border: none !important;
            padding: 9px 12px !important;
            margin: 0 !important;
            display: flex !important;
            align-items: center !important;
            cursor: pointer !important;
        }
        section[data-testid="stSidebar"] [data-testid="stExpander"] > details > summary:hover {
            background-color: rgba(16, 185, 129, 0.15) !important;
        }
        section[data-testid="stSidebar"] [data-testid="stExpander"] > details[open] > summary {
            border-bottom: 1px solid rgba(52, 211, 153, 0.25) !important;
        }
        section[data-testid="stSidebar"] [data-testid="stExpander"] > details > summary p,
        section[data-testid="stSidebar"] [data-testid="stExpander"] > details > summary span,
        section[data-testid="stSidebar"] [data-testid="stExpander"] > details > summary div {
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            font-weight: 700 !important;
            font-size: 0.88rem !important;
        }
        section[data-testid="stSidebar"] [data-testid="stExpander"] > details > summary [data-testid="stIconMaterial"],
        section[data-testid="stSidebar"] [data-testid="stExpander"] > details > summary i {
            color: #34d399 !important;
            -webkit-text-fill-color: #34d399 !important;
            font-size: 1.15rem !important;
            margin-right: 6px !important;
        }
        section[data-testid="stSidebar"] [data-testid="stExpander"] > details > summary svg {
            fill: #34d399 !important;
            color: #34d399 !important;
        }
        section[data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stExpanderDetails"] {
            background-color: transparent !important;
            border: none !important;
            padding: 10px 12px 14px 12px !important;
        }
        .nova-feedback-link:hover {
            background: rgba(16, 185, 129, 0.28) !important;
            border-color: #34d399 !important;
            box-shadow: 0 0 10px rgba(52, 211, 153, 0.35) !important;
            transform: translateY(-1px);
        }
        </style>""")

        with st.expander("ระบบผู้ดูแล (Admin & Visitor Logs)", icon=":material/shield_person:", expanded=False):
            env_admin_pw = os.environ.get("NOVA_ADMIN_PASSWORD", "").strip()
            secret_admin_pw = ""
            try:
                if "ADMIN_PASSWORD" in st.secrets:
                    secret_admin_pw = str(st.secrets["ADMIN_PASSWORD"]).strip()
            except Exception:
                pass
            override_passwords = {pw for pw in (env_admin_pw, secret_admin_pw) if pw}

            if "_log_auth" not in st.session_state:
                st.session_state["_log_auth"] = False

            if not st.session_state["_log_auth"]:
                pwd_col, btn_unlock_col = st.columns([0.78, 0.22])
                with pwd_col:
                    pwd_input = st.text_input(
                        "รหัสผ่านผู้ดูแลระบบ (Admin Password)",
                        type="password",
                        key="log_viewer_password",
                        placeholder="รหัสผ่าน admin...",
                        label_visibility="collapsed"
                    )
                with btn_unlock_col:
                    btn_login = st.button("", icon=":material/lock_open:", key="btn_log_login", use_container_width=True, help="ปลดล็อคระบบผู้ดูแล (Admin Logs & Cache)")

                if pwd_input or btn_login:
                    candidate_pw = pwd_input or ""
                    is_valid_pw = False
                    if candidate_pw:
                        is_valid_pw = bool(authenticate_user("admin", candidate_pw).get("ok"))
                        if not is_valid_pw and override_passwords:
                            is_valid_pw = any(
                                hmac.compare_digest(candidate_pw.encode("utf-8"), v_pw.encode("utf-8"))
                                for v_pw in override_passwords
                            )
                    if is_valid_pw:
                        st.session_state["_log_auth"] = True
                        st.rerun()
                    elif pwd_input:
                        st.error("รหัสผ่านไม่ถูกต้อง", icon=":material/gpp_bad:")
            else:
                col_auth_info, col_logout_btn = st.columns([0.72, 0.28])
                with col_auth_info:
                    auth_badge_html = '<div style="display: flex; align-items: center; gap: 6px; font-size: 0.76rem; font-weight: 700; color: #10b981; padding-top: 5px;"><i class="fa-solid fa-shield-halved"></i> <span>ผู้ดูแลระบบ (Admin)</span></div>'
                    try:
                        st.html(auth_badge_html)
                    except Exception:
                        st.markdown(auth_badge_html, unsafe_allow_html=True)
                with col_logout_btn:
                    if st.button("ล็อค", icon=":material/lock:", key="btn_log_logout", use_container_width=True, help="ออกจากระบบและล็อคข้อมูล"):
                        st.session_state["_log_auth"] = False
                        st.session_state.pop("log_viewer_password", None)
                        st.rerun()

                # [SEC-02] ย้ายการล้าง Cache ระดับเซิร์ฟเวอร์เข้าสู่ส่วน Admin หลังล็อกอินแล้ว
                st.markdown("""
                <div style="margin-top: 8px; margin-bottom: 6px; padding: 6px 10px; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 6px;">
                    <span style="font-size: 0.75rem; color: #f87171; font-weight: 700;">
                        <i class="fa-solid fa-server" style="margin-right: 4px;"></i> จัดการแคชเซิร์ฟเวอร์ (Admin Only)
                    </span>
                </div>
                """, unsafe_allow_html=True)

                btn_clear_server_cache = st.button(
                    "ล้างแคชทั้งระบบ (Clear Server Cache)",
                    icon=":material/cleaning_services:",
                    key="btn_admin_clear_server_cache",
                    use_container_width=True,
                    help="ล้างแคชข้อมูลและทรัพยากรระดับเซิร์ฟเวอร์ทั้งหมด (st.cache_data และ st.cache_resource) โหลดข้อมูลใหม่จากดิสก์"
                )
                if btn_clear_server_cache:
                    st.session_state["_confirm_clear_server_cache"] = True

                if st.session_state.get("_confirm_clear_server_cache", False):
                    st.warning("⚠️ การล้างแคชเซิร์ฟเวอร์จะส่งผลต่อผู้ใช้งานทุกคนบน LAN ชั่วคราว ต้องการยืนยันหรือไม่?")
                    c_cf1, c_cf2 = st.columns(2)
                    with c_cf1:
                        confirm_clear = st.button("ยืนยันล้างแคช", type="primary", key="btn_confirm_clear_server_cache", use_container_width=True)
                    with c_cf2:
                        if st.button("ยกเลิก", key="btn_cancel_clear_server_cache", use_container_width=True):
                            st.session_state["_confirm_clear_server_cache"] = False
                            st.rerun()
                else:
                    confirm_clear = False

                if confirm_clear:
                    st.session_state["_confirm_clear_server_cache"] = False
                    st.cache_data.clear()
                    st.cache_resource.clear()
                    # เคลียร์ precomputed HTML และ merged df แคช
                    st.session_state.pop("cached_map_html_base", None)
                    st.session_state.pop("cached_bubble_html_v6", None)
                    st.session_state.pop("cached_bubble_html_v6_dark", None)
                    st.session_state.pop("_merged_df_cache", None)
                    st.session_state.pop("_merged_df_cache_key", None)
                    
                    overlay_bg = "rgba(15, 23, 42, 0.94)" if is_dark_mode else "rgba(255, 255, 255, 0.94)"
                    overlay_title = "#ef4444"
                    overlay_desc = "#94a3b8" if is_dark_mode else "#475569"
                    
                    st.html(f"""
                    <div style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: {overlay_bg}; backdrop-filter: blur(6px); z-index: 99999999; display: flex; flex-direction: column; align-items: center; justify-content: center; font-family: 'Noto Sans Thai', 'Inter', sans-serif;">
                        <div style="width: 52px; height: 52px; border: 4px solid rgba(239, 68, 68, 0.2); border-top: 4px solid #ef4444; border-radius: 50%; animation: spinClear 0.75s linear infinite; margin-bottom: 18px;"></div>
                        <h3 style="color: {overlay_title}; font-weight: 800; font-size: 1.35rem; margin: 0 0 8px 0; letter-spacing: -0.3px;">กำลังล้างแคชเซิร์ฟเวอร์ทั้งหมด...</h3>
                        <p style="color: {overlay_desc}; font-size: 0.92rem; margin: 0; font-weight: 500;">ระบบกำลังล้างข้อมูลใน RAM และโหลด Parquet ล่าสุด กรุณารอสักครู่</p>
                    </div>
                    <style>
                    @keyframes spinClear {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
                    </style>
                    <script>
                    setTimeout(function() {{
                        var cleanUrl = window.location.origin + window.location.pathname;
                        try {{
                            if (window.parent && window.parent !== window) {{
                                window.parent.location.href = window.parent.location.origin + window.parent.location.pathname;
                                return;
                            }}
                        }} catch(err) {{}}
                        window.location.href = cleanUrl;
                    }}, 400);
                    </script>
                    """, unsafe_allow_javascript=True)
                    st.stop()

                st.markdown("<hr style='margin: 10px 0 12px 0; border: none; border-top: 1px solid rgba(52, 211, 153, 0.2);'>", unsafe_allow_html=True)

                def _format_ua_compact(ua_str):
                    if not ua_str or ua_str == "Unknown":
                        return "fa-solid fa-desktop", "ไม่ระบุอุปกรณ์"
                    ua = ua_str.lower()
                    if "iphone" in ua:
                        dev, icon = "iPhone", "fa-solid fa-mobile-screen"
                    elif "ipad" in ua:
                        dev, icon = "iPad", "fa-solid fa-tablet-screen-button"
                    elif "android" in ua:
                        dev, icon = "Android", "fa-brands fa-android"
                    elif "windows" in ua:
                        dev, icon = "Windows", "fa-brands fa-windows"
                    elif "macintosh" in ua or "mac os" in ua:
                        dev, icon = "macOS", "fa-brands fa-apple"
                    elif "linux" in ua:
                        dev, icon = "Linux", "fa-brands fa-linux"
                    else:
                        dev, icon = "PC", "fa-solid fa-laptop"
                        
                    br = ""
                    if "edg" in ua:
                        br = "Edge"
                    elif "chrome" in ua or "crios" in ua:
                        br = "Chrome"
                    elif "safari" in ua and "chrome" not in ua:
                        br = "Safari"
                    elif "firefox" in ua:
                        br = "Firefox"
                    elif "line" in ua:
                        br = "LINE"
                        
                    return icon, f"{dev} • {br}" if br else dev

                def _format_log_time(ts_str, today_str):
                    if not ts_str:
                        return "-"
                    try:
                        parts = str(ts_str).split(" ")
                        d_part = parts[0]
                        t_part = parts[1][:5] if len(parts) > 1 else ""
                        if d_part == today_str:
                            return f"วันนี้ {t_part} น."
                        sub_parts = d_part.split("-")
                        if len(sub_parts) == 3:
                            y, m, d = sub_parts
                            thai_months = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
                            m_idx = int(m) if m.isdigit() and 1 <= int(m) <= 12 else 0
                            m_thai = thai_months[m_idx] if m_idx else m
                            return f"{int(d)} {m_thai} {t_part} น."
                        return str(ts_str)
                    except Exception:
                        return str(ts_str)

                today_str = datetime.datetime.now(user_logger.TH_TZ).strftime("%Y-%m-%d")

                admin_log_section = st.radio(
                    "ประเภท Log",
                    ["ประวัติเข้าใช้งาน (Visitor)", "ประวัติ Login/Logout (Auth)"],
                    horizontal=True,
                    key="admin_log_section_mode",
                    label_visibility="collapsed",
                )

                if admin_log_section == "ประวัติ Login/Logout (Auth)":
                    col_aq, col_ae = st.columns([0.55, 0.45])
                    with col_aq:
                        auth_search_q = st.text_input(
                            "ค้นหา Auth Log",
                            key="log_auth_search_q",
                            placeholder="ค้นหาชื่อผู้ใช้ / IP...",
                            label_visibility="collapsed",
                        )
                    with col_ae:
                        auth_evt_label = st.selectbox(
                            "ประเภทเหตุการณ์",
                            ["ทั้งหมด", "login_success", "login_failed", "login_locked", "logout"],
                            key="log_auth_evt_filter",
                            label_visibility="collapsed",
                        )

                    auth_evt_param = "" if auth_evt_label == "ทั้งหมด" else auth_evt_label
                    try:
                        auth_logs_data = user_logger.get_auth_logs(
                            query=auth_search_q or "",
                            event_type=auth_evt_param,
                            limit=300,
                        )
                    except Exception:
                        auth_logs_data = []

                    evt_meta = {
                        "login_success": ("#10b981", "rgba(16, 185, 129, 0.15)", "เข้าสู่ระบบสำเร็จ"),
                        "login_failed": ("#ef4444", "rgba(239, 68, 68, 0.15)", "รหัสผ่านผิด"),
                        "login_locked": ("#f59e0b", "rgba(245, 158, 11, 0.15)", "ถูกล็อคชั่วคราว"),
                        "logout": ("#60a5fa", "rgba(59, 130, 246, 0.15)", "ออกจากระบบ"),
                    }

                    if auth_logs_data:
                        card_item_bg = "rgba(255, 255, 255, 0.04)" if is_dark_mode else "#ffffff"
                        card_item_border = "rgba(255, 255, 255, 0.08)" if is_dark_mode else "rgba(0, 0, 0, 0.08)"
                        sub_text_color = "#94a3b8" if is_dark_mode else "#64748b"
                        auth_cards = []
                        for a_item in auth_logs_data:
                            evt_t = str(a_item.get("event_type", "unknown"))
                            c_fg, c_bg, evt_th = evt_meta.get(evt_t, ("#94a3b8", "rgba(148,163,184,0.15)", evt_t))
                            disp_u = html.escape(str(a_item.get("user_name") or a_item.get("username") or "ไม่ระบุ"))
                            a_ip = html.escape(str(a_item.get("ip", "Unknown")))
                            a_time = _format_log_time(a_item.get("event_time", ""), today_str)
                            a_det = html.escape(str(a_item.get("details", "") or ""))
                            det_line = f'<div style="font-size: 0.65rem; color: {sub_text_color}; margin-top: 2px;">{a_det}</div>' if a_det else ""
                            auth_cards.append(
                                f'<div style="background: {card_item_bg}; border: 1px solid {card_item_border}; border-radius: 8px; padding: 7px 10px; margin-bottom: 5px;">'
                                f'<div style="display: flex; justify-content: space-between; align-items: center; gap: 6px;">'
                                f'<span style="font-weight: 700; font-size: 0.79rem; color: {c_fg}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{disp_u}</span>'
                                f'<span style="background: {c_bg}; color: {c_fg}; font-size: 0.62rem; font-weight: 700; padding: 2px 7px; border-radius: 10px; white-space: nowrap;">{evt_th}</span>'
                                f'</div>'
                                f'<div style="display: flex; justify-content: space-between; font-size: 0.67rem; color: {sub_text_color}; margin-top: 2px;">'
                                f'<span><i class="fa-regular fa-clock" style="margin-right: 3px;"></i>{a_time}</span>'
                                f'<span><i class="fa-solid fa-network-wired" style="margin-right: 3px;"></i>{a_ip}</span>'
                                f'</div>'
                                f'{det_line}'
                                f'</div>'
                            )
                        auth_feed = f'<div style="max-height: 280px; overflow-y: auto; padding-right: 2px; margin-top: 4px;">{"".join(auth_cards)}</div>'
                        try:
                            st.html(auth_feed)
                        except Exception:
                            st.markdown(auth_feed, unsafe_allow_html=True)
                    else:
                        st.info("ไม่พบประวัติ Login/Logout ตามเงื่อนไขที่เลือก", icon=":material/info:")

                    a_col1, a_col2 = st.columns(2)
                    with a_col1:
                        try:
                            auth_csv = user_logger.export_auth_logs_csv()
                            if auth_csv:
                                st.download_button(
                                    "ส่งออก Auth CSV",
                                    icon=":material/download:",
                                    data=auth_csv,
                                    file_name=f"auth_logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                    mime="text/csv",
                                    use_container_width=True,
                                    key="btn_download_auth_logs",
                                )
                        except Exception:
                            pass
                    with a_col2:
                        if st.button("รีเฟรช", icon=":material/refresh:", use_container_width=True, key="btn_refresh_auth_logs"):
                            st.rerun()
                else:
                    # Get active search / preset from session state to reflect in KPI grid
                    cur_search = st.session_state.get("log_search_ip", "")
                    cur_preset = st.session_state.get("log_date_preset", "ทั้งหมด")
                    cur_custom_date = st.session_state.get("log_custom_date", datetime.date.today())

                    date_filter = None
                    start_date = None
                    if cur_preset == "วันนี้":
                        date_filter = today_str
                        ips_sub_label = "วันนี้ / ทั้งหมด"
                    elif cur_preset == "7 วันล่าสุด":
                        start_date = (datetime.datetime.now(user_logger.TH_TZ) - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
                        ips_sub_label = "7 วัน / ทั้งหมด"
                    elif cur_preset == "ระบุวันที่":
                        if cur_custom_date:
                            date_filter = cur_custom_date.strftime("%Y-%m-%d") if isinstance(cur_custom_date, (datetime.date, datetime.datetime)) else str(cur_custom_date)
                        ips_sub_label = "เลือก / ทั้งหมด"
                    else: # "ทั้งหมด"
                        ips_sub_label = "วันนี้ / ทั้งหมด"

                    # KPI Summary Micro-Grid
                    try:
                        stats = user_logger.get_stats(query=cur_search or "", date_filter=date_filter, start_date=start_date)
                    except Exception:
                        stats = {
                            "total_sessions": 0,
                            "unique_ips": 0,
                            "total_unique_ips": 0,
                            "today_visitors": 0,
                            "today_sessions": 0,
                            "today_unique_ips": 0,
                            "period_sessions": 0,
                            "period_unique_ips": 0,
                        }

                    curr_users = stats.get("period_unique_users" if cur_preset in ["7 วันล่าสุด", "ระบุวันที่"] else "today_unique_users", 0)
                    total_users = stats.get("total_unique_users", 0)
                    curr_ips = stats.get("period_unique_ips" if cur_preset in ["7 วันล่าสุด", "ระบุวันที่"] else "today_unique_ips", 0)
                    total_ips = stats.get("total_unique_ips", stats.get("unique_ips", 0))
                    today_sessions = stats.get("today_sessions", stats.get("today_visitors", 0))
                    total_sessions = stats.get("total_sessions", 0)

                    # Show user count if available, otherwise IP count
                    stat_col1_icon = "fa-solid fa-user-shield" if total_users > 0 else "fa-solid fa-network-wired"
                    stat_col1_label = "ผู้ใช้" if total_users > 0 else "อุปกรณ์"
                    stat_col1_curr = curr_users if total_users > 0 else curr_ips
                    stat_col1_total = total_users if total_users > 0 else total_ips

                    # Color definitions
                    # 1. อุปกรณ์ (Blue)
                    kpi_bg_ips = "rgba(59, 130, 246, 0.12)" if is_dark_mode else "rgba(59, 130, 246, 0.08)"
                    kpi_border_ips = "rgba(59, 130, 246, 0.3)" if is_dark_mode else "rgba(59, 130, 246, 0.2)"
                    kpi_num_ips = "#60a5fa" if is_dark_mode else "#2563eb"
                    kpi_sub_ips = "#93c5fd" if is_dark_mode else "#3b82f6"

                    # 2. ผู้เข้าชมวันนี้ (Orange)
                    kpi_bg_today = "rgba(249, 115, 22, 0.12)" if is_dark_mode else "rgba(249, 115, 22, 0.08)"
                    kpi_border_today = "rgba(249, 115, 22, 0.3)" if is_dark_mode else "rgba(249, 115, 22, 0.2)"
                    kpi_num_today = "#fb923c" if is_dark_mode else "#ea580c"

                    # 3. ทั้งหมด (Green)
                    kpi_bg_sessions = "rgba(16, 185, 129, 0.12)" if is_dark_mode else "rgba(16, 185, 129, 0.08)"
                    kpi_border_sessions = "rgba(16, 185, 129, 0.3)" if is_dark_mode else "rgba(16, 185, 129, 0.2)"
                    kpi_num_sessions = "#34d399" if is_dark_mode else "#059669"

                    kpi_grid_html = (
                        f'<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 5px; margin: 4px 0 10px 0;">'
                        # Card 1: ผู้ใช้/อุปกรณ์ (Unique Users or IPs)
                        f'<div style="background: {kpi_bg_ips}; border: 1px solid {kpi_border_ips}; border-radius: 8px; padding: 6px 2px; text-align: center; overflow: hidden;">'
                        f'<div style="font-size: 0.65rem; color: {kpi_num_ips}; font-weight: 700; display: flex; align-items: center; justify-content: center; gap: 3px;">'
                        f'<i class="{stat_col1_icon}" style="font-size: 0.62rem;"></i> {stat_col1_label}'
                        f'</div>'
                        f'<div style="font-size: 1.12rem; font-weight: 800; line-height: 1.25; margin: 2px 0 1px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">'
                        f'<span style="font-size: 1.15rem; font-weight: 800; color: {kpi_num_ips};">{stat_col1_curr:,}</span>'
                        f'<span style="font-size: 0.72rem; font-weight: 600; color: #94a3b8; margin: 0 1px;">/</span>'
                        f'<span style="font-size: 0.82rem; font-weight: 700; color: {kpi_sub_ips};">{stat_col1_total:,}</span>'
                        f'</div>'
                        f'<div style="font-size: 0.58rem; color: #94a3b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{ips_sub_label}</div>'
                        f'</div>'
                        # Card 2: ผู้เข้าชมวันนี้ (Today Sessions)
                        f'<div style="background: {kpi_bg_today}; border: 1px solid {kpi_border_today}; border-radius: 8px; padding: 6px 2px; text-align: center; overflow: hidden;">'
                        f'<div style="font-size: 0.65rem; color: {kpi_num_today}; font-weight: 700; display: flex; align-items: center; justify-content: center; gap: 3px;">'
                        f'<i class="fa-solid fa-calendar-day" style="font-size: 0.62rem;"></i> วันนี้'
                        f'</div>'
                        f'<div style="font-size: 1.15rem; font-weight: 800; color: {kpi_num_today}; line-height: 1.25; margin: 2px 0 1px 0;">{today_sessions:,}</div>'
                        f'<div style="font-size: 0.58rem; color: #94a3b8;">เซสชัน</div>'
                        f'</div>'
                        # Card 3: ทั้งหมด (Total Sessions)
                        f'<div style="background: {kpi_bg_sessions}; border: 1px solid {kpi_border_sessions}; border-radius: 8px; padding: 6px 2px; text-align: center; overflow: hidden;">'
                        f'<div style="font-size: 0.65rem; color: {kpi_num_sessions}; font-weight: 700; display: flex; align-items: center; justify-content: center; gap: 3px;">'
                        f'<i class="fa-solid fa-users" style="font-size: 0.62rem;"></i> ทั้งหมด'
                        f'</div>'
                        f'<div style="font-size: 1.15rem; font-weight: 800; color: {kpi_num_sessions}; line-height: 1.25; margin: 2px 0 1px 0;">{total_sessions:,}</div>'
                        f'<div style="font-size: 0.58rem; color: #94a3b8;">เซสชัน</div>'
                        f'</div>'
                        f'</div>'
                    )
                    try:
                        st.html(kpi_grid_html)
                    except Exception:
                        st.markdown(kpi_grid_html, unsafe_allow_html=True)

                    # Filter & Search Controls (Stacked compactly for sidebar)
                    col_flt_q, col_flt_d = st.columns([0.58, 0.42])
                    with col_flt_q:
                        log_search_q = st.text_input(
                            "ค้นหา IP / ผู้ใช้งาน",
                            key="log_search_ip",
                            placeholder="ค้นหาชื่อผู้ใช้ / IP / อุปกรณ์...",
                            label_visibility="collapsed"
                        )
                    with col_flt_d:
                        date_preset = st.selectbox(
                            "ช่วงเวลา",
                            ["ทั้งหมด", "วันนี้", "7 วันล่าสุด", "ระบุวันที่"],
                            key="log_date_preset",
                            label_visibility="collapsed"
                        )

                    custom_date = None
                    if date_preset == "ระบุวันที่":
                        custom_date = st.date_input("เลือกวันที่", value=datetime.date.today(), key="log_custom_date")
                        if custom_date:
                            date_filter = custom_date.strftime("%Y-%m-%d")

                    # Fetch logs
                    try:
                        logs_data = user_logger.search_logs(
                            query=log_search_q or "",
                            date_filter=date_filter,
                            start_date=start_date
                        )
                    except Exception:
                        logs_data = []

                    # View Choice & Counter Header
                    col_view_sel, col_cnt_badge = st.columns([0.62, 0.38])
                    with col_view_sel:
                        log_view_choice = st.radio(
                            "รูปแบบมุมมอง",
                            ["ฟีดการ์ด", "ตาราง"],
                            horizontal=True,
                            key="log_view_mode",
                            label_visibility="collapsed"
                        )
                    with col_cnt_badge:
                        cnt_html = f'<div style="text-align: right; padding-top: 3px; font-size: 0.72rem; color: #94a3b8; font-weight: 600;"><i class="fa-solid fa-list-check" style="color: #10b981; margin-right: 2px;"></i> {len(logs_data)} รายการ</div>'
                        try:
                            st.html(cnt_html)
                        except Exception:
                            st.markdown(cnt_html, unsafe_allow_html=True)

                    if logs_data:
                        if log_view_choice == "ฟีดการ์ด":
                            card_item_bg = "rgba(255, 255, 255, 0.04)" if is_dark_mode else "#ffffff"
                            card_item_border = "rgba(255, 255, 255, 0.08)" if is_dark_mode else "rgba(0, 0, 0, 0.08)"
                            user_color = "#34d399" if is_dark_mode else "#065f46"
                            badge_bg = "rgba(16, 185, 129, 0.2)" if is_dark_mode else "rgba(16, 185, 129, 0.12)"
                            badge_text = "#6ee7b7" if is_dark_mode else "#047857"
                            badge_border = "rgba(52, 211, 153, 0.3)" if is_dark_mode else "rgba(16, 185, 129, 0.25)"
                            dur_badge_bg = "rgba(59, 130, 246, 0.18)" if is_dark_mode else "rgba(59, 130, 246, 0.10)"
                            dur_badge_text = "#93c5fd" if is_dark_mode else "#1d4ed8"
                            dur_badge_border = "rgba(96, 165, 250, 0.3)" if is_dark_mode else "rgba(59, 130, 246, 0.25)"
                            sub_text_color = "#94a3b8" if is_dark_mode else "#64748b"

                            cards_html = []
                            for item in logs_data:
                                ip = html.escape(str(item.get("ip", "Unknown")))
                                raw_uname = str(item.get("user_name", "") or "").strip()
                                display_name = html.escape(raw_uname) if raw_uname else ip
                                has_domain_user = bool(raw_uname and "\\" in raw_uname)
                                user_icon = "fa-solid fa-id-badge" if has_domain_user else "fa-solid fa-circle-user"
                                machine_label = user_logger.format_machine_user_label(item.get("machine_user", ""), raw_uname, item.get("ip", ""))
                                machine_sub_line = (
                                    f'<div style="font-size: 0.65rem; color: {sub_text_color}; opacity: 0.82; padding-left: 17px; margin-top: -1px; margin-bottom: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">'
                                    f'ผู้ใช้เครื่อง: {html.escape(machine_label)}'
                                    f'</div>'
                                ) if machine_label else ""
                                
                                v_count = item.get("visit_count", 1) or 1
                                dur_label = html.escape(user_logger.format_duration_thai(item.get("duration_seconds", 0) or 0))
                                dev_icon, dev_name = _format_ua_compact(item.get("user_agent", ""))
                                last_time = _format_log_time(item.get("last_seen", ""), today_str)

                                # Subtitle shows IP if username is displayed, or device
                                ip_sub_line = f'<span><i class="fa-solid fa-network-wired" style="color: #60a5fa; margin-right: 3px;"></i> {ip}</span>' if (raw_uname and raw_uname != ip) else ""
                                
                                cards_html.append(
                                    f'<div style="background: {card_item_bg}; border: 1px solid {card_item_border}; border-radius: 8px; padding: 7px 10px; margin-bottom: 5px; box-shadow: 0 1px 3px rgba(0,0,0,0.06);">'
                                    f'<div style="display: flex; justify-content: space-between; align-items: center; gap: 6px; margin-bottom: 3px;">'
                                    f'<span style="font-weight: 700; font-size: 0.82rem; color: {user_color}; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif; display: flex; align-items: center; gap: 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">'
                                    f'<i class="{user_icon}" style="color: #10b981; font-size: 0.76rem; flex-shrink: 0;"></i> {display_name}'
                                    f'</span>'
                                    f'<div style="display: flex; align-items: center; gap: 4px; flex-shrink: 0;">'
                                    f'<span style="background: {dur_badge_bg}; color: {dur_badge_text}; font-size: 0.62rem; font-weight: 700; padding: 2px 7px; border-radius: 10px; border: 1px solid {dur_badge_border}; white-space: nowrap;">'
                                    f'<i class="fa-regular fa-hourglass-half" style="font-size: 0.55rem; margin-right: 2px;"></i> {dur_label}'
                                    f'</span>'
                                    f'<span style="background: {badge_bg}; color: {badge_text}; font-size: 0.62rem; font-weight: 700; padding: 2px 7px; border-radius: 10px; border: 1px solid {badge_border}; white-space: nowrap;">'
                                    f'<i class="fa-solid fa-arrow-rotate-right" style="font-size: 0.55rem; margin-right: 2px;"></i> {v_count:,} ครั้ง'
                                    f'</span>'
                                    f'</div>'
                                    f'</div>'
                                    f'{machine_sub_line}'
                                    f'<div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.68rem; color: {sub_text_color}; margin-top: 2px;">'
                                    f'<span><i class="fa-regular fa-clock" style="color: #10b981; margin-right: 3px;"></i> {last_time}</span>'
                                    f'{ip_sub_line}'
                                    f'<span><i class="{dev_icon}" style="margin-right: 3px;"></i> {dev_name}</span>'
                                    f'</div>'
                                    f'</div>'
                                )

                            feed_container = f'<div style="max-height: 280px; overflow-y: auto; padding-right: 2px; margin-top: 4px;">{"".join(cards_html)}</div>'
                            try:
                                st.html(feed_container)
                            except Exception:
                                st.markdown(feed_container, unsafe_allow_html=True)
                        else:
                            df_logs_disp = pd.DataFrame(logs_data)
                            if "user_name" not in df_logs_disp.columns:
                                df_logs_disp["user_name"] = ""
                            if "machine_user" not in df_logs_disp.columns:
                                df_logs_disp["machine_user"] = ""
                            if "duration_seconds" not in df_logs_disp.columns:
                                df_logs_disp["duration_seconds"] = 0
                            df_logs_disp["ผู้ใช้งาน"] = df_logs_disp["user_name"].fillna("").apply(lambda u: str(u).strip() or "ไม่ระบุ")
                            df_logs_disp["ผู้ใช้เครื่อง"] = df_logs_disp.apply(
                                lambda r: user_logger.format_machine_user_label(r.get("machine_user", ""), r.get("user_name", ""), r.get("ip", "")) or "-",
                                axis=1,
                            )
                            df_logs_disp["อุปกรณ์"] = df_logs_disp["user_agent"].apply(lambda u: _format_ua_compact(u)[1])
                            df_logs_disp["เข้าล่าสุด"] = df_logs_disp["last_seen"].apply(lambda t: _format_log_time(t, today_str))
                            df_logs_disp["ระยะเวลา"] = df_logs_disp["duration_seconds"].fillna(0).apply(user_logger.format_duration_thai)
                            df_logs_disp = df_logs_disp.rename(columns={
                                "ip": "IP Address",
                                "visit_count": "จำนวนครั้ง"
                            })
                            display_cols = [c for c in ["ผู้ใช้งาน", "ผู้ใช้เครื่อง", "IP Address", "เข้าล่าสุด", "ระยะเวลา", "จำนวนครั้ง", "อุปกรณ์"] if c in df_logs_disp.columns]
                            st.dataframe(df_logs_disp[display_cols], use_container_width=True, height=240, hide_index=True)
                    else:
                        st.info("ไม่พบประวัติการเข้าใช้งานตามเงื่อนไขที่เลือก", icon=":material/info:")

                    btn_col1, btn_col2 = st.columns(2)
                    with btn_col1:
                        try:
                            csv_data = user_logger.export_logs_csv()
                            if csv_data:
                                st.download_button(
                                    "ส่งออก CSV",
                                    icon=":material/download:",
                                    data=csv_data,
                                    file_name=f"access_logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                    mime="text/csv",
                                    use_container_width=True,
                                    key="btn_download_logs"
                                )
                        except Exception:
                            pass
                    with btn_col2:
                        if st.button("รีเฟรช", icon=":material/refresh:", use_container_width=True, key="btn_refresh_logs"):
                            st.rerun()

    return is_dark_mode
