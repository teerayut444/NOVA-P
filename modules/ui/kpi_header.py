import pandas as pd
import streamlit as st

def format_price_kpi(val_baht):
    """Formats numeric Baht values to compact legible strings (e.g. ฿1.25M, ฿500K)."""
    if pd.isna(val_baht) or val_baht is None or val_baht <= 0:
        return "฿0"
    if val_baht >= 1e9:
        return f"฿{val_baht / 1e9:,.2f}B"
    elif val_baht >= 1e6:
        return f"฿{val_baht / 1e6:,.2f}M"
    elif val_baht >= 1e3:
        return f"฿{val_baht / 1e3:,.1f}K"
    else:
        return f"฿{val_baht:,.0f}"

@st.cache_data(show_spinner=False, max_entries=8)
def _compute_floating_kpi_html(_df_filtered, _df_raw, cache_key=None):
    """Cached computation of the floating KPI cards summary ribbon HTML."""
    total_count = len(_df_raw) if _df_raw is not None else 0
    filtered_count = len(_df_filtered) if _df_filtered is not None else 0
    
    valid_prices = pd.Series(dtype=float)
    if _df_filtered is not None and not _df_filtered.empty and 'ราคา' in _df_filtered.columns:
        valid_prices = _df_filtered['ราคา'].dropna()
        valid_prices = valid_prices[valid_prices > 0]

    if not valid_prices.empty:
        total_value = valid_prices.sum()
        min_price = valid_prices.min()
        median_price = valid_prices.median()
        mean_price = valid_prices.mean()
        max_price = valid_prices.max()
        sd_price = valid_prices.std() if len(valid_prices) > 1 else 0.0
        
        total_value_str = format_price_kpi(total_value)
        min_price_str = format_price_kpi(min_price)
        median_price_str = format_price_kpi(median_price)
        mean_price_str = format_price_kpi(mean_price)
        max_price_str = format_price_kpi(max_price)
        sd_price_str = f"±{format_price_kpi(sd_price)}" if sd_price > 0 else "฿0"
    else:
        total_value_str = "฿0"
        min_price_str = "฿0"
        median_price_str = "฿0"
        mean_price_str = "฿0"
        max_price_str = "฿0"
        sd_price_str = "฿0"

    filtered_count_str = f"{filtered_count:,.0f}"
    val_count_str = f"{filtered_count_str} รายการ"

    return f"""
    <div class="floating-kpi-container" style="margin-top: 10px; margin-bottom: 20px;">
        <div class="floating-card" id="kpi-card-count" data-default-val="{val_count_str}">
            <div class="floating-card-title"><i class="fa fa-list" style="color: #047857;"></i> ทรัพย์สินที่พบ <span class="kpi-scope-badge" style="display:none;"></span></div>
            <div class="floating-card-value">{val_count_str}</div>
        </div>
        <div class="floating-card" id="kpi-card-total-val" data-default-val="{total_value_str}">
            <div class="floating-card-title"><i class="fa fa-wallet" style="color: #059669;"></i> มูลค่ารวมทรัพย์สิน <span class="kpi-scope-badge" style="display:none;"></span></div>
            <div class="floating-card-value">{total_value_str}</div>
        </div>
        <div class="floating-card" id="kpi-card-min-price" data-default-val="{min_price_str}">
            <div class="floating-card-title"><i class="fa fa-arrow-down" style="color: #10b981;"></i> ราคาต่ำสุด (Min) <span class="kpi-scope-badge" style="display:none;"></span></div>
            <div class="floating-card-value">{min_price_str}</div>
        </div>
        <div class="floating-card" id="kpi-card-median-price" data-default-val="{median_price_str}">
            <div class="floating-card-title"><i class="fa fa-tags" style="color: #047857;"></i> ราคากลาง (Median) <span class="kpi-scope-badge" style="display:none;"></span></div>
            <div class="floating-card-value">{median_price_str}</div>
        </div>
        <div class="floating-card" id="kpi-card-mean-price" data-default-val="{mean_price_str}">
            <div class="floating-card-title"><i class="fa fa-calculator" style="color: #059669;"></i> ราคาเฉลี่ย (Mean) <span class="kpi-scope-badge" style="display:none;"></span></div>
            <div class="floating-card-value">{mean_price_str}</div>
        </div>
        <div class="floating-card" id="kpi-card-max-price" data-default-val="{max_price_str}">
            <div class="floating-card-title"><i class="fa fa-arrow-up" style="color: #10b981;"></i> ราคาสูงสุด (Max) <span class="kpi-scope-badge" style="display:none;"></span></div>
            <div class="floating-card-value">{max_price_str}</div>
        </div>
        <div class="floating-card" id="kpi-card-sd-price" data-default-val="{sd_price_str}">
            <div class="floating-card-title"><i class="fa fa-chart-line" style="color: #047857;"></i> ส่วนเบี่ยงเบน (SD) <span class="kpi-scope-badge" style="display:none;"></span></div>
            <div class="floating-card-value">{sd_price_str}</div>
        </div>
    </div>
    """

def precompute_kpi_header(df_raw, data_mtime=0):
    """Pre-warms the KPI header cache during the Welcome Screen."""
    if df_raw is None or df_raw.empty:
        return
    cache_key = (data_mtime, len(df_raw), len(df_raw))
    _compute_floating_kpi_html(df_raw, df_raw, cache_key=cache_key)

def render_floating_kpi_cards(df_filtered, df_raw, is_dark_mode=False):
    """Computes and renders the floating KPI cards summary ribbon."""
    from modules.services.data_loader import get_data_mtime
    n_filt = len(df_filtered) if df_filtered is not None else 0
    n_raw = len(df_raw) if df_raw is not None else 0
    cache_key = (get_data_mtime(), n_filt, n_raw)
    floating_kpi_html = _compute_floating_kpi_html(df_filtered, df_raw, cache_key=cache_key)
    st.markdown(floating_kpi_html, unsafe_allow_html=True)
