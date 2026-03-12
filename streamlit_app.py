# =============================================================================
# streamlit_app.py — Real-time Metrics Dashboard
# Version    : 1.0.0
# Stack      : Streamlit | Pandas | Plotly | Requests
# Compatible : Streamlit Cloud (no system dependencies)
# =============================================================================

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG  (must be the very first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="📊 System Metrics Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
une_api = 'https://pushdev.pythonanywhere.com/'
ressource = 'metrics'
DEFAULT_API = os.environ.get("API_URL", une_api + ressource)
REFRESH_SEC = int(os.environ.get("REFRESH_SEC", "5"))
DEFAULT_N   = int(os.environ.get("DEFAULT_N",   "120"))   # ~10 min at 5s

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Dark header bar */
  .metric-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    padding: 1.2rem 1.5rem;
    border-radius: 12px;
    margin-bottom: 1rem;
    color: white;
  }
  .metric-header h1 { margin: 0; font-size: 1.8rem; }
  .metric-header p  { margin: 0.2rem 0 0 0; opacity: 0.7; font-size: 0.9rem; }

  /* KPI cards */
  [data-testid="metric-container"] {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 0.8rem 1rem;
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
  }

  /* Status badges */
  .badge-ok      { background:#dcfce7; color:#166534; padding:2px 8px;
                   border-radius:9999px; font-size:.78rem; font-weight:600; }
  .badge-warn    { background:#fef9c3; color:#854d0e; padding:2px 8px;
                   border-radius:9999px; font-size:.78rem; font-weight:600; }
  .badge-crit    { background:#fee2e2; color:#991b1b; padding:2px 8px;
                   border-radius:9999px; font-size:.78rem; font-weight:600; }
  .badge-offline { background:#f1f5f9; color:#475569; padding:2px 8px;
                   border-radius:9999px; font-size:.78rem; font-weight:600; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configuration")

    api_url = st.text_input(
        "API Base URL",
        value=DEFAULT_API,
        help="URL of your Flask metrics API",
    )
    api_url = api_url.rstrip("/")

    n_rows = st.slider(
        "Data window (rows)",
        min_value=20, max_value=2000, value=DEFAULT_N, step=20,
        help="Number of most-recent rows to display",
    )

    refresh = st.selectbox(
        "Auto-refresh interval",
        options=[5, 10, 30, 60],
        index=0,
        format_func=lambda x: f"{x}s",
    )

    hostname_filter = st.text_input(
        "Filter by hostname",
        value="",
        placeholder="(all hosts)",
    )

    thresholds = st.expander("🚨 Alert thresholds", expanded=False)
    with thresholds:
        cpu_warn  = st.slider("CPU warn %",    50, 95, 70)
        cpu_crit  = st.slider("CPU crit %",    70, 99, 90)
        mem_warn  = st.slider("Mem warn %",    50, 95, 75)
        mem_crit  = st.slider("Mem crit %",    70, 99, 90)
        disk_warn = st.slider("Disk warn %",   50, 95, 80)
        disk_crit = st.slider("Disk crit %",   70, 99, 90)

    st.markdown("---")
    st.caption("Monitoring Pipeline v1.0")
    st.caption("Flask + SQLite + Streamlit")

# ─────────────────────────────────────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=refresh, show_spinner=False)
def fetch_metrics(base_url: str, n: int, hostname: str) -> tuple[pd.DataFrame, str]:
    """
    Fetch metrics from API.
    Returns (dataframe, error_string).
    error_string is empty string on success.
    """
    params: dict[str, Any] = {"n": n}
    if hostname:
        params["hostname"] = hostname

    try:
        resp = requests.get(
            f"{base_url}/metrics",
            params=params,
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.ConnectionError:
        return pd.DataFrame(), "API unreachable — check URL and that Flask is running"
    except requests.exceptions.Timeout:
        return pd.DataFrame(), "Request timed out (>8s)"
    except requests.exceptions.HTTPError as exc:
        return pd.DataFrame(), f"HTTP error: {exc}"
    except Exception as exc:
        return pd.DataFrame(), f"Unexpected error: {exc}"

    if not data:
        return pd.DataFrame(), ""

    df = pd.DataFrame(data)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df, ""


@st.cache_data(ttl=refresh, show_spinner=False)
def fetch_stats(base_url: str, n: int, hostname: str) -> dict:
    params: dict[str, Any] = {"n": n}
    if hostname:
        params["hostname"] = hostname
    try:
        resp = requests.get(f"{base_url}/metrics/stats", params=params, timeout=8)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — STATUS BADGE
# ─────────────────────────────────────────────────────────────────────────────
def status_badge(val: float, warn: float, crit: float) -> str:
    if val >= crit:
        return f'<span class="badge-crit">CRITICAL {val:.1f}%</span>'
    if val >= warn:
        return f'<span class="badge-warn">WARNING {val:.1f}%</span>'
    return f'<span class="badge-ok">OK {val:.1f}%</span>'


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — PLOTLY LINE CHART
# ─────────────────────────────────────────────────────────────────────────────
PALETTE = {
    "cpu":    "#ef4444",
    "memory": "#3b82f6",
    "disk":   "#f59e0b",
    "load1":  "#8b5cf6",
    "process":"#10b981",
}

def make_chart(
    df: pd.DataFrame,
    col: str,
    title: str,
    color: str,
    yrange: list[float] | None = None,
    warn_line: float | None = None,
    crit_line: float | None = None,
    unit: str = "%",
) -> go.Figure:
    fig = go.Figure()

    # Area fill
    fig.add_trace(go.Scatter(
        x=df["datetime"],
        y=df[col],
        mode="lines",
        name=title,
        line=dict(color=color, width=2),
        fill="tozeroy",
        fillcolor=color.replace(")", ",0.12)").replace("rgb(", "rgba("),
        hovertemplate=f"<b>%{{x|%H:%M:%S}}</b><br>{title}: %{{y:.2f}}{unit}<extra></extra>",
    ))

    # Rolling average (10-point)
    if len(df) >= 10:
        rolling_avg = df[col].rolling(window=10, min_periods=1).mean()
        fig.add_trace(go.Scatter(
            x=df["datetime"],
            y=rolling_avg,
            mode="lines",
            name=f"{title} avg",
            line=dict(color=color, width=1, dash="dot"),
            opacity=0.6,
            hoverinfo="skip",
        ))

    # Threshold lines
    if warn_line is not None:
        fig.add_hline(
            y=warn_line, line_dash="dash",
            line_color="#f59e0b", line_width=1,
            annotation_text=f"warn {warn_line}%",
            annotation_font_size=10,
            annotation_font_color="#f59e0b",
        )
    if crit_line is not None:
        fig.add_hline(
            y=crit_line, line_dash="dash",
            line_color="#ef4444", line_width=1,
            annotation_text=f"crit {crit_line}%",
            annotation_font_size=10,
            annotation_font_color="#ef4444",
        )

    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color="#1e293b")),
        margin=dict(l=10, r=10, t=40, b=10),
        height=220,
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.15, font=dict(size=10)),
        xaxis=dict(
            tickformat="%H:%M:%S",
            showgrid=True,
            gridcolor="#f1f5f9",
            title="",
        ),
        yaxis=dict(
            range=yrange,
            ticksuffix=unit,
            showgrid=True,
            gridcolor="#f1f5f9",
            title="",
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────────────
now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
st.markdown(f"""
<div class="metric-header">
  <h1>📊 System Metrics Dashboard</h1>
  <p>Real-time distributed monitoring — last refresh: {now_utc}</p>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# FETCH DATA
# ─────────────────────────────────────────────────────────────────────────────
with st.spinner("Fetching metrics…"):
    df, fetch_error = fetch_metrics(api_url, n_rows, hostname_filter.strip())
    stats = fetch_stats(api_url, n_rows, hostname_filter.strip())

# ─────────────────────────────────────────────────────────────────────────────
# ERROR STATE
# ─────────────────────────────────────────────────────────────────────────────
if fetch_error:
    st.error(f"🔴 **Connection error**: {fetch_error}")
    st.info("ℹ️ Configure the **API Base URL** in the sidebar and ensure Flask is running.")
    st.stop()

if df.empty:
    st.warning("⚠️ No data yet — waiting for the agent to send metrics…")
    st.info("Run `bash agent/agent_metrics.sh` to start collecting.")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# KPI CARDS  (latest values)
# ─────────────────────────────────────────────────────────────────────────────
latest = df.iloc[-1]

col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    delta_cpu = round(latest["cpu"] - df.iloc[-2]["cpu"], 1) if len(df) > 1 else None
    st.metric("🔥 CPU", f"{latest['cpu']:.1f}%",
              delta=f"{delta_cpu:+.1f}%" if delta_cpu is not None else None,
              delta_color="inverse")

with col2:
    delta_mem = round(latest["memory"] - df.iloc[-2]["memory"], 1) if len(df) > 1 else None
    st.metric("💾 Memory", f"{latest['memory']:.1f}%",
              delta=f"{delta_mem:+.1f}%" if delta_mem is not None else None,
              delta_color="inverse")

with col3:
    st.metric("💿 Disk", f"{latest['disk']:.1f}%")

with col4:
    st.metric("⚡ Load avg", f"{latest['load1']:.2f}")

with col5:
    st.metric("🔧 Processes", f"{int(latest['process'])}")

with col6:
    ts = pd.to_datetime(latest["timestamp"], unit="s", utc=True)
    age_s = int(time.time()) - latest["timestamp"]
    st.metric("🕐 Last seen", f"{age_s}s ago")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# STATUS BADGES
# ─────────────────────────────────────────────────────────────────────────────
badge_cols = st.columns(4)
with badge_cols[0]:
    st.markdown(f"**CPU** &nbsp; {status_badge(latest['cpu'], cpu_warn, cpu_crit)}",
                unsafe_allow_html=True)
with badge_cols[1]:
    st.markdown(f"**Memory** &nbsp; {status_badge(latest['memory'], mem_warn, mem_crit)}",
                unsafe_allow_html=True)
with badge_cols[2]:
    st.markdown(f"**Disk** &nbsp; {status_badge(latest['disk'], disk_warn, disk_crit)}",
                unsafe_allow_html=True)
with badge_cols[3]:
    host_label = df["hostname"].iloc[-1] if "hostname" in df.columns else "unknown"
    st.markdown(f"**Host** &nbsp; <span class='badge-ok'>{host_label}</span>",
                unsafe_allow_html=True)

st.markdown("")

# ─────────────────────────────────────────────────────────────────────────────
# CHARTS  — Row 1: CPU + Memory
# ─────────────────────────────────────────────────────────────────────────────
row1_left, row1_right = st.columns(2)

with row1_left:
    fig_cpu = make_chart(
        df, "cpu", "CPU Usage", PALETTE["cpu"],
        yrange=[0, 100],
        warn_line=cpu_warn, crit_line=cpu_crit,
    )
    st.plotly_chart(fig_cpu, use_container_width=True, config={"displayModeBar": False})

with row1_right:
    fig_mem = make_chart(
        df, "memory", "Memory Usage", PALETTE["memory"],
        yrange=[0, 100],
        warn_line=mem_warn, crit_line=mem_crit,
    )
    st.plotly_chart(fig_mem, use_container_width=True, config={"displayModeBar": False})

# ─────────────────────────────────────────────────────────────────────────────
# CHARTS  — Row 2: Disk + Load average
# ─────────────────────────────────────────────────────────────────────────────
row2_left, row2_right = st.columns(2)

with row2_left:
    fig_disk = make_chart(
        df, "disk", "Disk Usage", PALETTE["disk"],
        yrange=[0, 100],
        warn_line=disk_warn, crit_line=disk_crit,
    )
    st.plotly_chart(fig_disk, use_container_width=True, config={"displayModeBar": False})

with row2_right:
    fig_load = make_chart(
        df, "load1", "Load Average (1 min)", PALETTE["load1"],
        yrange=[0, max(df["load1"].max() * 1.2, 4)],
        unit="",
    )
    st.plotly_chart(fig_load, use_container_width=True, config={"displayModeBar": False})

# ─────────────────────────────────────────────────────────────────────────────
# CHART — Process count (full width)
# ─────────────────────────────────────────────────────────────────────────────
fig_proc = make_chart(
    df, "process", "Process Count", PALETTE["process"],
    yrange=[0, max(df["process"].max() * 1.2, 10)],
    unit="",
)
st.plotly_chart(fig_proc, use_container_width=True, config={"displayModeBar": False})

# ─────────────────────────────────────────────────────────────────────────────
# STATISTICS TABLE
# ─────────────────────────────────────────────────────────────────────────────
with st.expander("📋 Aggregate statistics", expanded=False):
    if stats:
        scols = st.columns(4)
        metrics_stats = [
            ("CPU %",   stats.get("cpu",  {})),
            ("Memory %", stats.get("memory", {})),
            ("Disk %",  stats.get("disk", {})),
            ("Load avg", stats.get("load1", {})),
        ]
        for col_el, (label, s) in zip(scols, metrics_stats):
            with col_el:
                st.markdown(f"**{label}**")
                if s:
                    rows_stat = {
                        "Avg": s.get("avg"),
                        "Min": s.get("min"),
                        "Max": s.get("max"),
                    }
                    for k, v in rows_stat.items():
                        if v is not None:
                            st.caption(f"{k}: **{v:.2f}**")
    else:
        st.caption("Stats endpoint not available")

# ─────────────────────────────────────────────────────────────────────────────
# RAW DATA TABLE
# ─────────────────────────────────────────────────────────────────────────────
with st.expander("🔢 Raw data (last 50 rows)", expanded=False):
    display_cols = ["datetime", "hostname", "cpu", "memory", "disk", "process", "load1"]
    available = [c for c in display_cols if c in df.columns]
    tail_df = df[available].tail(50).sort_values("datetime", ascending=False).reset_index(drop=True)
    st.dataframe(
        tail_df.style.format({
            "cpu":    "{:.1f}%",
            "memory": "{:.1f}%",
            "disk":   "{:.1f}%",
            "load1":  "{:.3f}",
        }),
        use_container_width=True,
        height=300,
    )

# ─────────────────────────────────────────────────────────────────────────────
# FOOTER + AUTO-REFRESH
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
footer_cols = st.columns([3, 1])
with footer_cols[0]:
    st.caption(f"📡 API: `{api_url}/metrics` &nbsp;|&nbsp; "
               f"🔄 Refresh: every **{refresh}s** &nbsp;|&nbsp; "
               f"📦 Rows loaded: **{len(df)}**")
with footer_cols[1]:
    if st.button("🔄 Manual refresh"):
        st.cache_data.clear()
        st.rerun()

# Auto-refresh via Streamlit's rerun mechanism
time.sleep(refresh)
st.rerun()
