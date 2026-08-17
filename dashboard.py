"""
Agentic Pay Dashboard
---------------------
Web dashboard inspired by the shadcn/ui dashboard example.
Reads the local audit SQLite database and exposes the agent's
security posture, payment activity, and decision trail.
"""

import sqlite3
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from audit import DB_PATH, init_db
from permissions import PermissionPolicy


st.set_page_config(
    page_title="Agentic Pay",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# shadcn-inspired design tokens: neutral surfaces, subtle borders,
# compact typography, and restrained accent usage.
st.markdown(
    """
    <style>
    :root {
        --bg: #09090b;
        --card: #0f0f12;
        --border: #27272a;
        --muted: #a1a1aa;
        --text: #fafafa;
        --accent: #f4f4f5;
        --green: #4ade80;
        --red: #f87171;
        --amber: #fbbf24;
    }

    .stApp { background: var(--bg); color: var(--text); }
    [data-testid="stSidebar"] { background: #0b0b0e; border-right: 1px solid var(--border); }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1.25rem; }
    .block-container { padding: 2rem 2.5rem 3rem; max-width: 1500px; }

    .brand { display:flex; align-items:center; gap:10px; margin-bottom:26px; }
    .brand-mark { width:32px; height:32px; display:grid; place-items:center; border:1px solid #3f3f46;
                  border-radius:9px; background:#18181b; font-weight:700; }
    .brand-name { font-size:15px; font-weight:650; letter-spacing:-.01em; }
    .brand-sub { color:var(--muted); font-size:11px; margin-top:1px; }

    .eyebrow { color:var(--muted); font-size:12px; margin-bottom:5px; }
    .page-title { font-size:30px; font-weight:650; letter-spacing:-.035em; margin:0; }
    .page-subtitle { color:var(--muted); font-size:13px; margin-top:7px; }

    .metric { border:1px solid var(--border); background:linear-gradient(180deg,#111114,#0d0d10);
              border-radius:12px; padding:18px 18px 16px; min-height:116px; }
    .metric-label { color:var(--muted); font-size:12px; }
    .metric-value { font-size:27px; font-weight:650; letter-spacing:-.035em; margin-top:9px; }
    .metric-note { color:var(--muted); font-size:11px; margin-top:5px; }
    .positive { color:var(--green); }
    .warning { color:var(--amber); }
    .negative { color:var(--red); }

    .section-title { font-size:15px; font-weight:600; margin:25px 0 12px; letter-spacing:-.01em; }
    .security { border:1px solid var(--border); background:#0f0f12; border-radius:12px; padding:18px; }
    .security-row { display:flex; justify-content:space-between; align-items:center; padding:11px 0;
                    border-bottom:1px solid #1f1f22; font-size:13px; }
    .security-row:last-child { border-bottom:0; padding-bottom:0; }
    .security-label { color:#d4d4d8; }
    .pill { border:1px solid #3f3f46; border-radius:999px; padding:3px 8px; font-size:10px; }
    .pill-green { color:var(--green); border-color:#1f5f36; background:#0b1f12; }

    div[data-testid="stDataFrame"] { border:1px solid var(--border); border-radius:12px; overflow:hidden; }
    .stTabs [data-baseweb="tab-list"] { gap:18px; border-bottom:1px solid var(--border); }
    .stTabs [data-baseweb="tab"] { font-size:12px; }
    footer { visibility:hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=5)
def load_events(limit: int = 250) -> pd.DataFrame:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(
            """
            SELECT id, timestamp, action, amount_cents, currency, status, reason
            FROM audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            conn,
            params=(limit,),
        )
    finally:
        conn.close()

    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df["amount"] = df["amount_cents"].fillna(0) / 100
    return df


def brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


policy = PermissionPolicy()
events = load_events()

# Sidebar
st.sidebar.markdown(
    '<div class="brand"><div class="brand-mark">◈</div><div><div class="brand-name">Agentic Pay</div><div class="brand-sub">Trust layer for payments</div></div></div>',
    unsafe_allow_html=True,
)
page = st.sidebar.radio("Workspace", ["Overview", "Audit Trail", "Policy"], label_visibility="collapsed")
st.sidebar.divider()
st.sidebar.caption("ENVIRONMENT")
st.sidebar.markdown("**Sandbox**")
st.sidebar.caption("Stripe execution is isolated from production funds.")
st.sidebar.divider()
st.sidebar.caption("SECURITY")
st.sidebar.markdown("🟢  Policy enforcement active")
st.sidebar.markdown("🟢  Audit logging active")
st.sidebar.markdown("🟢  Idempotency enabled")


if page == "Overview":
    st.markdown('<div class="eyebrow">PAYMENTS / CONTROL PLANE</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="page-title">Agent overview</h1>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-subtitle">Monitor autonomous payment decisions without losing human control.</div>',
        unsafe_allow_html=True,
    )

    today = datetime.now(timezone.utc).date()
    if not events.empty:
        today_events = events[events["timestamp"].dt.date == today]
        executed = events[events["status"] == "executed"]
        approved = events[events["status"] == "approved"]
        denied = events[events["status"] == "denied"]
        failed = events[events["status"] == "failed"]
        spent_today = float(today_events.loc[today_events["status"] == "executed", "amount"].sum())
        total_processed = float(executed["amount"].sum())
        executions = len(executed)
    else:
        today_events = pd.DataFrame()
        approved = denied = failed = pd.DataFrame()
        spent_today = total_processed = 0.0
        executions = 0

    remaining = max(policy.daily_limit_cents / 100 - spent_today, 0)
    utilization = min(spent_today / (policy.daily_limit_cents / 100), 1.0)

    st.markdown('<div class="section-title">Today</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    metrics = [
        (c1, "Executed", str(executions), "successful payment actions", "positive"),
        (c2, "Moved", brl(spent_today), f"{utilization:.0%} of daily limit", "positive"),
        (c3, "Remaining limit", brl(remaining), "available under policy", "warning"),
        (c4, "Denied", str(len(denied)), "blocked by policy", "negative"),
    ]
    for col, label, value, note, cls in metrics:
        with col:
            st.markdown(
                f'<div class="metric"><div class="metric-label">{label}</div>'
                f'<div class="metric-value">{value}</div><div class="metric-note {cls}">{note}</div></div>',
                unsafe_allow_html=True,
            )

    left, right = st.columns([1.6, 1])
    with left:
        st.markdown('<div class="section-title">Payment activity</div>', unsafe_allow_html=True)
        if events.empty:
            st.info("No audit events yet. Run the agent to populate the dashboard.")
        else:
            chart = events.copy()
            chart["day"] = chart["timestamp"].dt.strftime("%d/%m")
            chart = (
                chart[chart["status"] == "executed"]
                .groupby("day", sort=False)["amount"]
                .sum()
                .sort_index()
            )
            if chart.empty:
                st.info("No executed payments recorded yet.")
            else:
                st.bar_chart(chart, height=280)

    with right:
        st.markdown('<div class="section-title">Security posture</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="security">'
            f'<div class="security-row"><span class="security-label">Auto-approval</span><span class="pill pill-green">{brl(policy.auto_approve_limit_cents / 100)}</span></div>'
            f'<div class="security-row"><span class="security-label">Daily limit</span><span class="pill pill-green">{brl(policy.daily_limit_cents / 100)}</span></div>'
            f'<div class="security-row"><span class="security-label">Allowed tools</span><span class="pill pill-green">{len(policy.allowed_actions)}</span></div>'
            f'<div class="security-row"><span class="security-label">Fail-safe default</span><span class="pill pill-green">DENY</span></div>'
            f'<div class="security-row"><span class="security-label">Audit trail</span><span class="pill pill-green">ACTIVE</span></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-title">Recent decisions</div>', unsafe_allow_html=True)
    if events.empty:
        st.info("No decisions recorded yet.")
    else:
        recent = events.head(8).copy()
        recent["timestamp"] = recent["timestamp"].dt.strftime("%d/%m/%Y %H:%M:%S UTC")
        recent["amount"] = recent["amount"].map(lambda x: brl(float(x)) if x else "—")
        recent = recent[["timestamp", "action", "amount", "status", "reason"]]
        recent.columns = ["Time", "Action", "Amount", "Status", "Reason"]
        st.dataframe(recent, use_container_width=True, hide_index=True)

elif page == "Audit Trail":
    st.markdown('<div class="eyebrow">COMPLIANCE / AUDIT</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="page-title">Audit trail</h1>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Every authorization decision and payment execution is traceable.</div>', unsafe_allow_html=True)

    if events.empty:
        st.info("The audit database is empty. Start the agent to create events.")
    else:
        status_filter = st.multiselect("Status", sorted(events["status"].dropna().unique()), default=sorted(events["status"].dropna().unique()))
        action_filter = st.multiselect("Action", sorted(events["action"].dropna().unique()), default=sorted(events["action"].dropna().unique()))
        filtered = events[events["status"].isin(status_filter) & events["action"].isin(action_filter)].copy()
        filtered["timestamp"] = filtered["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        filtered["amount"] = filtered["amount"].map(lambda x: brl(float(x)) if x else "—")
        filtered = filtered[["id", "timestamp", "action", "amount", "currency", "status", "reason"]]
        filtered.columns = ["ID", "Timestamp", "Action", "Amount", "Currency", "Status", "Reason"]
        st.dataframe(filtered, use_container_width=True, hide_index=True, height=560)

elif page == "Policy":
    st.markdown('<div class="eyebrow">TRUST LAYER / AUTHORIZATION</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="page-title">Permission policy</h1>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">The agent cannot bypass these constraints by changing its own plan.</div>', unsafe_allow_html=True)

    a, b = st.columns(2)
    with a:
        st.markdown('<div class="section-title">Limits</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="security">'
            f'<div class="security-row"><span class="security-label">Auto-approval ceiling</span><strong>{brl(policy.auto_approve_limit_cents / 100)}</strong></div>'
            f'<div class="security-row"><span class="security-label">Daily spending ceiling</span><strong>{brl(policy.daily_limit_cents / 100)}</strong></div>'
            f'<div class="security-row"><span class="security-label">Current daily usage</span><strong>{brl(spent_today)}</strong></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with b:
        st.markdown('<div class="section-title">Allowlist</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="security">' + ''.join(
                f'<div class="security-row"><span class="security-label">{action}</span><span class="pill pill-green">ALLOWED</span></div>'
                for action in policy.allowed_actions
            ) + '</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-title">Decision model</div>', unsafe_allow_html=True)
    st.info(
        "Actions outside the allowlist are denied by default. Payments above the auto-approval ceiling "
        "or beyond the daily limit require explicit human confirmation before execution."
    )

st.caption("Agentic Pay · local audit database · shadcn/ui-inspired dashboard")
