"""
DataSentinel — 4-Agent Real-Time Data Pipeline Health Monitor
Hackathon project for Agents League 2026 (Creative Apps Track)
Author: Yash Chavan

Agents:
  1. IngestAgent    — fetches live market data via yfinance
  2. AnomalyAgent   — detects data quality issues (nulls, spikes, schema drift)
  3. DiagnosticAgent— calls Claude LLM to explain root cause & suggest fixes
  4. HealerAgent    — auto-patches issues and logs remediation actions
  + Foundry IQ     — knowledge retrieval layer for grounded, cited fixes

Run:
  pip install streamlit yfinance pandas plotly anthropic
  streamlit run app.py
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import anthropic
import time
import random
from datetime import datetime, timedelta

# ─── Foundry IQ Knowledge Base ───────────────────────────────────────────────
# Simulates Microsoft Foundry IQ — grounded knowledge retrieval with citations
FOUNDRY_IQ_KB = {
    "NULL_FLOOD": {
        "title": "Null Flood — Upstream API Timeout Pattern",
        "source": "Foundry IQ / Pipeline Reliability Runbook v2.1",
        "root_cause": "Upstream data provider returned empty payload due to rate-limit or timeout.",
        "immediate_fix": "Apply forward-fill (ffill) with max 2 periods to preserve signal continuity.",
        "prevention": "Add exponential backoff retry (3 attempts) + circuit breaker at ingest layer.",
        "confidence": 0.94,
        "tags": ["data-quality", "ingest", "reliability"],
    },
    "PRICE_SPIKE": {
        "title": "Price Spike — Bad Tick / After-Hours Bleed",
        "source": "Foundry IQ / Market Data Quality Standards v1.8",
        "root_cause": "Bad tick data or after-hours trade bleed causing z-score outlier in Close price.",
        "immediate_fix": "Clip values beyond μ±4σ of rolling 20-period window.",
        "prevention": "Add pre-market/after-hours filter + cross-validate against VWAP.",
        "confidence": 0.91,
        "tags": ["anomaly", "market-data", "outlier"],
    },
    "SCHEMA_DRIFT": {
        "title": "Schema Drift — Provider Column Rename",
        "source": "Foundry IQ / Schema Governance Policy v3.0",
        "root_cause": "Data provider updated API response schema without versioning notice.",
        "immediate_fix": "Apply column normaliser mapping: close_price→Close, vol→Volume.",
        "prevention": "Implement schema contract tests (Great Expectations) in CI/CD pipeline.",
        "confidence": 0.97,
        "tags": ["schema", "governance", "drift"],
    },
    "STALE_DATA": {
        "title": "Stale Data — Feed Connection Drop",
        "source": "Foundry IQ / Real-Time Feed SLA Handbook v1.3",
        "root_cause": "WebSocket feed dropped and replayed last known record instead of reconnecting.",
        "immediate_fix": "Flag records with max-age TTL > 15 min; trigger upstream reconnect.",
        "prevention": "Add heartbeat monitor with auto-reconnect and Slack/PagerDuty alert.",
        "confidence": 0.88,
        "tags": ["freshness", "streaming", "sla"],
    },
    "NEGATIVE_VOLUME": {
        "title": "Negative Volume — Short Interest Encoding Bug",
        "source": "Foundry IQ / Financial Data Encoding Standards v2.5",
        "root_cause": "Short interest data incorrectly merged into Volume field with sign inversion.",
        "immediate_fix": "Apply abs() transform to Volume; flag affected rows for audit.",
        "prevention": "Add schema-level constraint: Volume >= 0 with pre-load validation.",
        "confidence": 0.85,
        "tags": ["data-quality", "volume", "encoding"],
    },
}

def query_foundry_iq(anomaly_type: str) -> dict | None:
    """Simulate Foundry IQ knowledge retrieval — returns grounded, cited fix."""
    return FOUNDRY_IQ_KB.get(anomaly_type, None)

# ─── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DataSentinel",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');

  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  .sentinel-header {
    background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 20px 28px;
    margin-bottom: 20px;
  }
  .sentinel-header h1 {
    font-family: 'IBM Plex Mono', monospace;
    color: #58a6ff;
    font-size: 2rem;
    margin: 0;
  }
  .sentinel-header p { color: #8b949e; margin: 4px 0 0; }

  .agent-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 12px;
    transition: border-color 0.3s;
  }
  .agent-card.active  { border-color: #388bfd; }
  .agent-card.success { border-color: #3fb950; }
  .agent-card.warning { border-color: #d29922; }
  .agent-card.error   { border-color: #f85149; }

  .agent-title {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .agent-title.ingest     { color: #58a6ff; }
  .agent-title.anomaly    { color: #d29922; }
  .agent-title.diagnostic { color: #bc8cff; }
  .agent-title.healer     { color: #3fb950; }

  .status-pill {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 600;
    font-family: 'IBM Plex Mono', monospace;
  }
  .pill-green  { background: #1a3a28; color: #3fb950; }
  .pill-yellow { background: #3a2d0d; color: #d29922; }
  .pill-red    { background: #3a0d0d; color: #f85149; }
  .pill-blue   { background: #0d1f3a; color: #58a6ff; }
  .pill-grey   { background: #21262d; color: #8b949e; }

  .metric-box {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 14px 18px;
    text-align: center;
  }
  .metric-box .metric-val {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.6rem;
    font-weight: 600;
    color: #e6edf3;
  }
  .metric-box .metric-lbl {
    font-size: 0.72rem;
    color: #8b949e;
    margin-top: 2px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .log-line {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.78rem;
    color: #8b949e;
    border-left: 3px solid #30363d;
    padding-left: 10px;
    margin: 4px 0;
    line-height: 1.5;
  }
  .log-line.ok   { color: #3fb950; border-color: #3fb950; }
  .log-line.warn { color: #d29922; border-color: #d29922; }
  .log-line.err  { color: #f85149; border-color: #f85149; }
  .log-line.info { color: #58a6ff; border-color: #58a6ff; }

  .fault-banner {
    background: linear-gradient(90deg, #3a0d0d, #21262d);
    border: 1px solid #f85149;
    border-radius: 8px;
    padding: 12px 18px;
    font-family: 'IBM Plex Mono', monospace;
    color: #f85149;
    font-size: 0.85rem;
    margin-bottom: 12px;
  }

  div[data-testid="stButton"] > button {
    background: #161b22;
    border: 1px solid #30363d;
    color: #e6edf3;
    border-radius: 8px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.82rem;
    padding: 8px 18px;
    width: 100%;
    transition: border-color 0.2s, background 0.2s;
  }
  div[data-testid="stButton"] > button:hover {
    border-color: #58a6ff;
    background: #0d1f3a;
    color: #58a6ff;
  }

  .stSpinner > div { border-top-color: #58a6ff !important; }
</style>
""", unsafe_allow_html=True)

# ─── Session state ───────────────────────────────────────────────────────────
def init_state():
    defaults = dict(
        running=False,
        fault_injected=False,
        fault_type=None,
        agent_states={"ingest": "idle", "anomaly": "idle", "diagnostic": "idle", "healer": "idle"},
        agent_logs={"ingest": [], "anomaly": [], "diagnostic": [], "healer": []},
        pipeline_data=None,
        anomalies=[],
        diagnosis="",
        healed_actions=[],
        cycle_count=0,
        health_history=[],
        last_run=None,
        api_key="",
    )
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ─── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Configuration")
    api_key = st.text_input("Anthropic API Key", type="password",
                             value=st.session_state.api_key,
                             placeholder="sk-ant-...")
    if api_key:
        st.session_state.api_key = api_key

    st.markdown("---")
    ticker = st.selectbox("Live Data Source (Ticker)",
                          ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA", "AMZN"])
    refresh_secs = st.slider("Refresh interval (sec)", 5, 60, 15)

    st.markdown("---")
    st.markdown("### 🔥 Fault Injection")
    fault_choice = st.selectbox("Fault Type", [
        "None",
        "Null Flood (30% missing values)",
        "Price Spike (5× normal value)",
        "Schema Drift (rename columns)",
        "Stale Data (freeze timestamps)",
        "Negative Volume Anomaly",
    ])

    if st.button("⚡ Inject Fault Now"):
        st.session_state.fault_injected = True
        st.session_state.fault_type = fault_choice if fault_choice != "None" else None
        st.toast(f"Fault injected: {fault_choice}", icon="⚠️")

    if st.button("✅ Clear Fault"):
        st.session_state.fault_injected = False
        st.session_state.fault_type = None
        st.toast("Fault cleared", icon="✅")

    st.markdown("---")
    st.markdown("### 🛡️ DataSentinel")
    st.caption("4-Agent Real-Time Data Pipeline Health Monitor")
    st.caption("Built for Agents League Hackathon 2026")

# ─── Header ──────────────────────────────────────────────────────────────────
st.markdown("""
<div class="sentinel-header">
  <h1>🛡️ DataSentinel</h1>
  <p>4-Agent Real-Time Data Pipeline Health Monitor — Agents League Hackathon 2026</p>
</div>
""", unsafe_allow_html=True)

# ─── Agent 1: IngestAgent ─────────────────────────────────────────────────────
def run_ingest_agent(ticker: str) -> tuple[pd.DataFrame | None, list[str]]:
    logs = []
    logs.append(("info", f"[IngestAgent] Connecting to yfinance → {ticker}"))
    try:
        raw = yf.download(ticker, period="5d", interval="5m", progress=False, auto_adjust=True)
        if raw.empty:
            logs.append(("err", "[IngestAgent] Empty response from yfinance"))
            return None, logs
        raw = raw.reset_index()
        raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
        logs.append(("ok",   f"[IngestAgent] Fetched {len(raw)} rows, {len(raw.columns)} cols"))
        logs.append(("ok",   f"[IngestAgent] Columns: {list(raw.columns)}"))
        logs.append(("ok",   f"[IngestAgent] Time range: {raw['Datetime'].min()} → {raw['Datetime'].max()}"))
        return raw, logs
    except Exception as e:
        logs.append(("err", f"[IngestAgent] Exception: {e}"))
        return None, logs

# ─── Fault injector ───────────────────────────────────────────────────────────
def inject_fault(df: pd.DataFrame, fault_type: str) -> pd.DataFrame:
    df = df.copy()
    if "Null Flood" in fault_type:
        mask = pd.Series([random.random() < 0.30 for _ in range(len(df))])
        df.loc[mask, "Close"] = None
    elif "Price Spike" in fault_type:
        idx = random.randint(len(df) // 2, len(df) - 1)
        df.loc[idx, "Close"] = df["Close"].max() * 5
    elif "Schema Drift" in fault_type:
        df.rename(columns={"Close": "close_price", "Volume": "vol"}, inplace=True)
    elif "Stale Data" in fault_type:
        df["Datetime"] = df["Datetime"].iloc[0]
    elif "Negative Volume" in fault_type:
        df.loc[df.sample(frac=0.05).index, "Volume"] = -999
    return df

# ─── Agent 2: AnomalyAgent ────────────────────────────────────────────────────
def run_anomaly_agent(df: pd.DataFrame) -> tuple[list[dict], list[str]]:
    logs = []
    anomalies = []
    logs.append(("info", "[AnomalyAgent] Scanning pipeline data…"))

    # 1. Expected schema check
    expected = {"Datetime", "Open", "High", "Low", "Close", "Volume"}
    actual = set(df.columns)
    missing_cols = expected - actual
    extra_cols = actual - expected
    if missing_cols:
        anomalies.append({"type": "SCHEMA_DRIFT", "severity": "HIGH",
                          "detail": f"Missing columns: {missing_cols}"})
        logs.append(("err", f"[AnomalyAgent] SCHEMA_DRIFT — missing cols: {missing_cols}"))
    if extra_cols - {"Adj Close"}:
        anomalies.append({"type": "UNKNOWN_COLUMNS", "severity": "MEDIUM",
                          "detail": f"Unexpected columns: {extra_cols}"})

    # 2. Null check (only if Close exists)
    if "Close" in df.columns:
        null_pct = df["Close"].isna().mean() * 100
        if null_pct > 5:
            anomalies.append({"type": "NULL_FLOOD", "severity": "HIGH",
                              "detail": f"{null_pct:.1f}% null values in Close"})
            logs.append(("err", f"[AnomalyAgent] NULL_FLOOD — {null_pct:.1f}% nulls in Close"))
        else:
            logs.append(("ok", f"[AnomalyAgent] Null check passed ({null_pct:.1f}%)"))

        # 3. Price spike (z-score > 4)
        clean = df["Close"].dropna()
        if len(clean) > 10:
            z = (clean - clean.mean()) / clean.std()
            spikes = (z.abs() > 4).sum()
            if spikes > 0:
                anomalies.append({"type": "PRICE_SPIKE", "severity": "HIGH",
                                  "detail": f"{spikes} rows with z-score > 4 in Close"})
                logs.append(("warn", f"[AnomalyAgent] PRICE_SPIKE — {spikes} outlier rows"))
            else:
                logs.append(("ok", "[AnomalyAgent] Price spike check passed"))

    # 4. Stale timestamp check
    if "Datetime" in df.columns:
        unique_ts = df["Datetime"].nunique()
        if unique_ts < max(1, len(df) * 0.5):
            anomalies.append({"type": "STALE_DATA", "severity": "MEDIUM",
                              "detail": f"Only {unique_ts} unique timestamps for {len(df)} rows"})
            logs.append(("warn", f"[AnomalyAgent] STALE_DATA — {unique_ts} unique timestamps"))
        else:
            logs.append(("ok", "[AnomalyAgent] Timestamp freshness check passed"))

    # 5. Negative volume
    if "Volume" in df.columns:
        neg_vol = (df["Volume"] < 0).sum()
        if neg_vol > 0:
            anomalies.append({"type": "NEGATIVE_VOLUME", "severity": "MEDIUM",
                              "detail": f"{neg_vol} rows with negative Volume"})
            logs.append(("warn", f"[AnomalyAgent] NEGATIVE_VOLUME — {neg_vol} rows"))
        else:
            logs.append(("ok", "[AnomalyAgent] Volume sanity check passed"))

    if not anomalies:
        logs.append(("ok", "[AnomalyAgent] ✅ All checks passed — pipeline healthy"))
    else:
        logs.append(("warn", f"[AnomalyAgent] Found {len(anomalies)} anomaly(ies)"))

    return anomalies, logs

# ─── Agent 3: DiagnosticAgent (LLM) ──────────────────────────────────────────
def run_diagnostic_agent(ticker: str, anomalies: list[dict], api_key: str) -> tuple[str, list[str]]:
    logs = []
    if not anomalies:
        logs.append(("ok", "[DiagnosticAgent] No anomalies to diagnose"))
        return "✅ Pipeline is healthy. No anomalies detected.", logs

    if not api_key:
        logs.append(("warn", "[DiagnosticAgent] No API key — using rule-based diagnosis"))
        diagnoses = []
        for a in anomalies:
            if a["type"] == "NULL_FLOOD":
                diagnoses.append(f"• NULL_FLOOD: Likely upstream API timeout or rate-limit. Fix: add retry logic + forward-fill with max 2 periods.")
            elif a["type"] == "PRICE_SPIKE":
                diagnoses.append(f"• PRICE_SPIKE: Possible bad tick or after-hours data bleed. Fix: clip values beyond 3σ from rolling 20-period mean.")
            elif a["type"] == "SCHEMA_DRIFT":
                diagnoses.append(f"• SCHEMA_DRIFT: Data provider changed column naming convention. Fix: add column normaliser mapping layer at ingest.")
            elif a["type"] == "STALE_DATA":
                diagnoses.append(f"• STALE_DATA: Feed connection dropped and is replaying last known record. Fix: add max-age TTL check; alert if data > 15 min old.")
            elif a["type"] == "NEGATIVE_VOLUME":
                diagnoses.append(f"• NEGATIVE_VOLUME: Encoding bug or short-interest bleed into volume field. Fix: abs() transform + flag for manual review.")
            else:
                diagnoses.append(f"• {a['type']}: {a['detail']}. Fix: review upstream schema contract.")
        return "\n".join(diagnoses), logs

    logs.append(("info", "[DiagnosticAgent] Calling Claude API for root-cause analysis…"))
    prompt = f"""You are a senior data engineer. A real-time pipeline ingesting {ticker} stock data has triggered anomaly alerts.

Anomalies detected:
{chr(10).join(f'- [{a["severity"]}] {a["type"]}: {a["detail"]}' for a in anomalies)}

For EACH anomaly, provide:
1. Root cause (1 sentence)
2. Immediate fix (1 sentence, specific code-level suggestion)
3. Long-term prevention (1 sentence)

Be concise. Use bullet points. Be specific to financial data pipelines."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        diagnosis = response.content[0].text
        logs.append(("ok", f"[DiagnosticAgent] LLM diagnosis complete ({len(diagnosis)} chars)"))
        return diagnosis, logs
    except Exception as e:
        logs.append(("err", f"[DiagnosticAgent] API error: {e}"))
        return f"API error: {e}", logs

# ─── Agent 4: HealerAgent ────────────────────────────────────────────────────
def run_healer_agent(df: pd.DataFrame, anomalies: list[dict]) -> tuple[pd.DataFrame, list[str], list[str]]:
    logs = []
    actions = []
    if not anomalies:
        logs.append(("ok", "[HealerAgent] Nothing to heal"))
        return df, logs, actions

    healed = df.copy()
    for a in anomalies:
        atype = a["type"]

        if atype == "NULL_FLOOD" and "Close" in healed.columns:
            nulls = healed["Close"].isna().sum()
            healed["Close"] = healed["Close"].ffill().bfill()
            action = f"Forward-filled {nulls} null Close values"
            actions.append(action)
            logs.append(("ok", f"[HealerAgent] {action}"))

        elif atype == "PRICE_SPIKE" and "Close" in healed.columns:
            mean, std = healed["Close"].mean(), healed["Close"].std()
            upper, lower = mean + 4 * std, mean - 4 * std
            spikes = ((healed["Close"] > upper) | (healed["Close"] < lower)).sum()
            healed["Close"] = healed["Close"].clip(lower=lower, upper=upper)
            action = f"Clipped {spikes} spike values to [μ±4σ]"
            actions.append(action)
            logs.append(("ok", f"[HealerAgent] {action}"))

        elif atype == "SCHEMA_DRIFT":
            rename_map = {"close_price": "Close", "vol": "Volume"}
            healed = healed.rename(columns={k: v for k, v in rename_map.items() if k in healed.columns})
            action = f"Normalised schema: renamed columns to standard names"
            actions.append(action)
            logs.append(("ok", f"[HealerAgent] {action}"))

        elif atype == "STALE_DATA":
            action = "Stale data flagged — cannot auto-heal; requires upstream reconnect"
            actions.append(action)
            logs.append(("warn", f"[HealerAgent] {action}"))

        elif atype == "NEGATIVE_VOLUME" and "Volume" in healed.columns:
            neg = (healed["Volume"] < 0).sum()
            healed["Volume"] = healed["Volume"].abs()
            action = f"Applied abs() to {neg} negative Volume values"
            actions.append(action)
            logs.append(("ok", f"[HealerAgent] {action}"))

    logs.append(("ok", f"[HealerAgent] Healing complete — {len(actions)} action(s) taken"))
    return healed, logs, actions

# ─── Health score helper ──────────────────────────────────────────────────────
def compute_health(anomalies: list[dict]) -> int:
    if not anomalies:
        return 100
    penalty = sum(30 if a["severity"] == "HIGH" else 15 for a in anomalies)
    return max(0, 100 - penalty)

def health_color(score: int) -> str:
    if score >= 80: return "#3fb950"
    if score >= 50: return "#d29922"
    return "#f85149"

# ─── Main dashboard layout ────────────────────────────────────────────────────
top_col1, top_col2, top_col3, top_col4, top_col5 = st.columns(5)

placeholder_metrics = st.empty()
placeholder_fault   = st.empty()

agent_col1, agent_col2, agent_col3, agent_col4 = st.columns(4)
chart_col, diag_col = st.columns([3, 2])

status_placeholder  = st.empty()

# Control buttons
btn_col1, btn_col2, btn_col3 = st.columns(3)
with btn_col1:
    start = st.button("▶ Start Pipeline", key="start_btn")
with btn_col2:
    stop  = st.button("⏹ Stop Pipeline",  key="stop_btn")
with btn_col3:
    single_run = st.button("⚡ Run Once",       key="once_btn")

if start:      st.session_state.running = True
if stop:       st.session_state.running = False

# ─── Pipeline runner ──────────────────────────────────────────────────────────
def render_agent_card(col, title, css_class, status, logs):
    status_map = {
        "idle":    ("pill-grey",   "IDLE"),
        "running": ("pill-blue",   "RUNNING"),
        "ok":      ("pill-green",  "OK"),
        "warning": ("pill-yellow", "WARN"),
        "error":   ("pill-red",    "ERROR"),
    }
    pill_cls, pill_label = status_map.get(status, ("pill-grey", status.upper()))
    log_html = "".join(
        f'<div class="log-line {lvl}">{msg}</div>'
        for lvl, msg in logs[-6:]
    )
    with col:
        st.markdown(f"""
        <div class="agent-card {status}">
          <div class="agent-title {css_class}">{title}</div>
          <span class="status-pill {pill_cls}" style="margin:6px 0;display:inline-block;">{pill_label}</span>
          <div style="margin-top:8px">{log_html}</div>
        </div>
        """, unsafe_allow_html=True)


def run_pipeline_cycle():
    st.session_state.cycle_count += 1
    st.session_state.last_run = datetime.now().strftime("%H:%M:%S")

    # ── Agent 1: Ingest ─────────────────────────────────────────────────────
    st.session_state.agent_states["ingest"] = "running"
    df, ingest_logs = run_ingest_agent(ticker)
    st.session_state.agent_logs["ingest"] = ingest_logs

    if df is None:
        st.session_state.agent_states["ingest"] = "error"
        return

    # Apply fault if injected
    if st.session_state.fault_injected and st.session_state.fault_type:
        df = inject_fault(df, st.session_state.fault_type)
        st.session_state.agent_logs["ingest"].append(
            ("warn", f"[IngestAgent] ⚠️ FAULT INJECTED: {st.session_state.fault_type}")
        )

    st.session_state.pipeline_data = df
    st.session_state.agent_states["ingest"] = "ok"

    # ── Agent 2: Anomaly ────────────────────────────────────────────────────
    st.session_state.agent_states["anomaly"] = "running"
    anomalies, anomaly_logs = run_anomaly_agent(df)
    st.session_state.anomalies = anomalies
    st.session_state.agent_logs["anomaly"] = anomaly_logs
    st.session_state.agent_states["anomaly"] = "warning" if anomalies else "ok"

    # ── Agent 3: Diagnostic ─────────────────────────────────────────────────
    if anomalies:
        st.session_state.agent_states["diagnostic"] = "running"
        diagnosis, diag_logs = run_diagnostic_agent(ticker, anomalies, st.session_state.api_key)
        st.session_state.diagnosis = diagnosis
        st.session_state.agent_logs["diagnostic"] = diag_logs
        st.session_state.agent_states["diagnostic"] = "warning"
    else:
        st.session_state.diagnosis = "✅ No anomalies — pipeline healthy."
        st.session_state.agent_logs["diagnostic"] = [("ok", "[DiagnosticAgent] Skipped — no anomalies")]
        st.session_state.agent_states["diagnostic"] = "ok"

    # ── Agent 4: Healer ─────────────────────────────────────────────────────
    st.session_state.agent_states["healer"] = "running"
    healed_df, healer_logs, actions = run_healer_agent(df, anomalies)
    st.session_state.healed_actions = actions
    st.session_state.agent_logs["healer"] = healer_logs
    st.session_state.pipeline_data = healed_df
    st.session_state.agent_states["healer"] = "ok"

    # ── Health history ───────────────────────────────────────────────────────
    score = compute_health(anomalies)
    st.session_state.health_history.append({
        "time": st.session_state.last_run,
        "score": score,
        "anomalies": len(anomalies),
    })
    if len(st.session_state.health_history) > 20:
        st.session_state.health_history = st.session_state.health_history[-20:]


def render_dashboard():
    df    = st.session_state.pipeline_data
    anom  = st.session_state.anomalies
    score = compute_health(anom)
    hh    = st.session_state.health_history

    # ── Top metrics ─────────────────────────────────────────────────────────
    with placeholder_metrics.container():
        c1, c2, c3, c4, c5 = st.columns(5)
        col_data = [
            ("Health Score", f"{score}%",  health_color(score)),
            ("Anomalies",    str(len(anom)), "#f85149" if anom else "#3fb950"),
            ("Rows Ingested", f"{len(df):,}" if df is not None else "—", "#58a6ff"),
            ("Cycles Run",    str(st.session_state.cycle_count), "#bc8cff"),
            ("Last Run",      st.session_state.last_run or "—", "#8b949e"),
        ]
        for col, (lbl, val, color) in zip([c1, c2, c3, c4, c5], col_data):
            with col:
                st.markdown(f"""
                <div class="metric-box">
                  <div class="metric-val" style="color:{color}">{val}</div>
                  <div class="metric-lbl">{lbl}</div>
                </div>
                """, unsafe_allow_html=True)

    # ── Fault banner ─────────────────────────────────────────────────────────
    with placeholder_fault.container():
        if st.session_state.fault_injected and st.session_state.fault_type:
            st.markdown(f"""
            <div class="fault-banner">
              ⚠️ ACTIVE FAULT: {st.session_state.fault_type}
              — agents are diagnosing and healing…
            </div>
            """, unsafe_allow_html=True)

    # ── Agent cards ──────────────────────────────────────────────────────────
    render_agent_card(agent_col1, "① IngestAgent",    "ingest",
                      st.session_state.agent_states["ingest"],
                      st.session_state.agent_logs["ingest"])
    render_agent_card(agent_col2, "② AnomalyAgent",   "anomaly",
                      st.session_state.agent_states["anomaly"],
                      st.session_state.agent_logs["anomaly"])
    render_agent_card(agent_col3, "③ DiagnosticAgent","diagnostic",
                      st.session_state.agent_states["diagnostic"],
                      st.session_state.agent_logs["diagnostic"])
    render_agent_card(agent_col4, "④ HealerAgent",    "healer",
                      st.session_state.agent_states["healer"],
                      st.session_state.agent_logs["healer"])

    # ── Chart ────────────────────────────────────────────────────────────────
    with chart_col:
        st.markdown("#### 📈 Live Price Feed (Healed)")
        if df is not None and "Close" in df.columns and "Datetime" in df.columns:
            recent = df.tail(100).copy()
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=recent["Datetime"], y=recent["Close"],
                mode="lines", line=dict(color="#58a6ff", width=1.5),
                name="Close"
            ))
            if hh:
                fig.update_layout(
                    paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                    font=dict(color="#8b949e", family="IBM Plex Mono"),
                    margin=dict(l=10, r=10, t=10, b=30),
                    xaxis=dict(gridcolor="#21262d", tickfont=dict(size=10)),
                    yaxis=dict(gridcolor="#21262d", tickfont=dict(size=10)),
                    height=300,
                )
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### 💊 Pipeline Health Over Time")
        if len(hh) >= 2:
            times  = [h["time"]  for h in hh]
            scores = [h["score"] for h in hh]
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=times, y=scores, mode="lines+markers",
                line=dict(color="#3fb950", width=2),
                marker=dict(color=[health_color(s) for s in scores], size=8),
                name="Health %"
            ))
            fig2.add_hline(y=80, line_dash="dot", line_color="#3fb950",  annotation_text="Healthy")
            fig2.add_hline(y=50, line_dash="dot", line_color="#d29922",  annotation_text="Warning")
            fig2.update_layout(
                paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                font=dict(color="#8b949e", family="IBM Plex Mono"),
                margin=dict(l=10, r=10, t=10, b=30),
                yaxis=dict(range=[0, 105], gridcolor="#21262d"),
                xaxis=dict(gridcolor="#21262d"),
                height=220,
            )
            st.plotly_chart(fig2, use_container_width=True)

    # ── Diagnosis + healer actions ───────────────────────────────────────────
    with diag_col:
        st.markdown("#### 🧠 AI Diagnosis")
        st.markdown(
            f'<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;'
            f'padding:14px;font-size:0.82rem;color:#c9d1d9;min-height:180px;'
            f'white-space:pre-wrap;font-family:IBM Plex Mono,monospace">'
            f'{st.session_state.diagnosis or "Awaiting first run…"}</div>',
            unsafe_allow_html=True,
        )

        if st.session_state.healed_actions:
            st.markdown("#### 🔧 Auto-Heal Actions")
            for action in st.session_state.healed_actions:
                st.markdown(
                    f'<div class="log-line ok">✅ {action}</div>',
                    unsafe_allow_html=True
                )

        # ── Foundry IQ Knowledge Panel ───────────────────────────────────────
        st.markdown("#### 🔍 Foundry IQ Knowledge Retrieval")
        if st.session_state.anomalies:
            for a in st.session_state.anomalies:
                kb = query_foundry_iq(a["type"])
                if kb:
                    confidence_color = "#3fb950" if kb["confidence"] > 0.9 else "#d29922"
                    tags_html = " ".join([f'<span style="background:#21262d;color:#8b949e;padding:2px 8px;border-radius:12px;font-size:0.7rem;font-family:IBM Plex Mono,monospace">{t}</span>' for t in kb["tags"]])
                    st.markdown(f"""
                    <div style="background:#161b22;border:1px solid #388bfd;border-radius:8px;padding:14px;margin-bottom:10px">
                      <div style="font-family:IBM Plex Mono,monospace;color:#58a6ff;font-size:0.8rem;font-weight:600">📚 {kb['title']}</div>
                      <div style="color:#8b949e;font-size:0.72rem;margin:4px 0">Source: <span style="color:#bc8cff">{kb['source']}</span> &nbsp;|&nbsp; Confidence: <span style="color:{confidence_color}">{kb['confidence']*100:.0f}%</span></div>
                      <div style="margin-top:8px;font-size:0.78rem;color:#c9d1d9"><b style="color:#d29922">Root cause:</b> {kb['root_cause']}</div>
                      <div style="margin-top:4px;font-size:0.78rem;color:#c9d1d9"><b style="color:#3fb950">Fix:</b> {kb['immediate_fix']}</div>
                      <div style="margin-top:4px;font-size:0.78rem;color:#c9d1d9"><b style="color:#58a6ff">Prevention:</b> {kb['prevention']}</div>
                      <div style="margin-top:8px">{tags_html}</div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.markdown('<div class="log-line ok">✅ No anomalies — Foundry IQ knowledge base on standby</div>', unsafe_allow_html=True)


# ─── Run on button press or auto-loop ────────────────────────────────────────
if single_run or (st.session_state.running and st.session_state.cycle_count == 0):
    with st.spinner("Running pipeline cycle…"):
        run_pipeline_cycle()
    render_dashboard()

elif st.session_state.running:
    run_pipeline_cycle()
    render_dashboard()
    time.sleep(refresh_secs)
    st.rerun()

elif st.session_state.cycle_count > 0:
    render_dashboard()
else:
    st.info("👆 Click **▶ Start Pipeline** to begin, or **⚡ Run Once** for a single cycle.")
    st.markdown("""
    **How to use DataSentinel:**
    1. (Optional) Add your Anthropic API key in the sidebar for AI-powered diagnostics
    2. Choose a stock ticker and refresh interval
    3. Click **▶ Start Pipeline** to watch all 4 agents work in real time
    4. Use **⚡ Inject Fault Now** to break the pipeline and see agents detect + heal it
    5. Watch the health score drop and recover on the chart
    """)
