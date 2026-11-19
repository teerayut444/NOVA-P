import streamlit as st
import streamlit.components.v1 as stc
from bubble_chart import generate_3d_glossy_bubble_chart_html
from modules.services.data_loader import get_data_mtime

def render_tab1_bubble_view(df_filtered, is_dark_mode=False, has_active_filters=False):
    """Renders Tab 1: 3D Glossy Bubble Chart View."""
    with st.container(key="tab_bubble"):
        st.markdown("""
        <style>
        .st-key-tab_bubble {
            margin-top: -14px !important;
        }
        .st-key-tab_bubble div[data-testid="stHorizontalBlock"] {
            margin-bottom: -18px !important;
        }
        .st-key-tab_bubble iframe {
            margin-top: -8px !important;
        }
        </style>
        """, unsafe_allow_html=True)

        row_cnt = len(df_filtered) if df_filtered is not None else 0
        import_ver = int(st.session_state.get("_custom_import_ver", 0))
        data_sig = (get_data_mtime(), row_cnt, import_ver, bool(is_dark_mode))

        # Check cached initial bubble HTML keyed by data signature so updates invalidate stale HTML
        if not has_active_filters:
            cache_key = "cached_bubble_html_v6_dark" if is_dark_mode else "cached_bubble_html_v6"
            sig_key = f"{cache_key}_sig"
            if cache_key not in st.session_state or st.session_state.get(sig_key) != data_sig:
                st.session_state[cache_key] = generate_3d_glossy_bubble_chart_html(
                    df_filtered,
                    is_dark_mode=is_dark_mode
                )
                st.session_state[sig_key] = data_sig
            bubble_html = st.session_state[cache_key]
        else:
            bubble_html = generate_3d_glossy_bubble_chart_html(
                df_filtered, 
                is_dark_mode=is_dark_mode
            )
        
        try:
            stc.html(bubble_html, height=860)
        except Exception:
            st.html(bubble_html)
