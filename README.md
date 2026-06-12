# 🛡️ DataSentinel
### 4-Agent Real-Time Data Pipeline Health Monitor
**Agents League Hackathon 2026 — Reasoning Agents Track**

---

## What it does
DataSentinel runs 4 AI agents in parallel that monitor a live financial data pipeline, detect anomalies, explain root causes using Claude, and auto-heal the data — all visible in real time.

| Agent | Role |
|---|---|
| **① IngestAgent** | Pulls live market data via yfinance every N seconds |
| **② AnomalyAgent** | Detects nulls, schema drift, price spikes, stale data, negative volume |
| **③ DiagnosticAgent** | Calls Claude LLM to explain root cause + suggest fixes |
| **④ HealerAgent** | Auto-patches issues: forward-fill, clipping, schema normalisation |

---

## Judging criteria alignment

| Criterion (weight) | How DataSentinel covers it |
|---|---|
| Reasoning & Multi-step (20%) | 4 visible agent reasoning chains shown simultaneously |
| Accuracy & Relevance (20%) | Real yfinance data, real pandas anomaly detection |
| Reliability & Safety (20%) | HealerAgent never invents data — only patches with documented methods |
| User Experience (15%) | One-click start, live charts, red/amber/green health dashboard |
| Creativity (15%) | Fault injection demo — break a live pipeline on demand |
| Community Vote (10%) | Deploy on Streamlit Cloud, share link in Discord |

---

## Setup

```bash
pip install streamlit yfinance pandas plotly anthropic
streamlit run app.py
```

Add your **Anthropic API key** in the sidebar for Claude-powered diagnostics.  
The app works without an API key (rule-based diagnostics) for judging without API costs.

---

## Demo script (for your 5-min video)

1. Start the pipeline → show all 4 agents turn green
2. Inject "Null Flood" fault → watch agents 2–4 react, health drops to 40%
3. Show HealerAgent forward-filling the data → health recovers
4. Inject "Price Spike" → show DiagnosticAgent's Claude explanation
5. Show health-over-time chart recovering after each heal

---

## Architecture

```
yfinance API
    │
    ▼
① IngestAgent (pandas)
    │  raw DataFrame
    ▼
[Fault Injector] ← sidebar toggle
    │
    ▼
② AnomalyAgent (pandas, z-score, schema checks)
    │  anomaly list
    ▼
③ DiagnosticAgent (Anthropic Claude API)
    │  root-cause text
    ▼
④ HealerAgent (pandas: ffill, clip, rename)
    │  healed DataFrame
    ▼
Streamlit UI (Plotly charts, health score, agent logs)
```

---

## GitHub Copilot usage
GitHub Copilot was used to:
- Scaffold the agent class structure
- Generate pandas anomaly detection logic
- Suggest Plotly chart configurations
- Write the CSS styling for the dark dashboard

---

## Author
Yash Chavan — Beginner Data Engineer  
Agents League Hackathon 2026
