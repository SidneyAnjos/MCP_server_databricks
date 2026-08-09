# Weather-Prediction MCP Server + Agent — Submission

**Homework:** Build Your Own Weather-Prediction MCP Server + Agent
**Date:** 2026-08-08 · based on Day 3 (*Agent Bricks + Alpaca Markets paper-trading MCP server*)

---

## 1. Repo link

**Repository:** https://github.com/SidneyAnjos/MCP_server_databricks

Everything below is committed to `main` (this folder is a self-contained copy
of the submission artifacts for review):

| Artifact | In repo | Copy in this folder |
| --- | --- | --- |
| MCP server (FastMCP, 6 tools) | `mcp_server/weather_mcp_server.py` | — (see repo) |
| Adapter module (all HTTP/parsing) | `mcp_server/weather_broker.py` | — (see repo) |
| Server Databricks App config | `mcp_server/app.yaml`, `requirements.txt` | — (see repo) |
| Agent system prompt | `agent_config/system_prompt.md` | `agent_config/system_prompt.md` |
| Tool manifest (schemas + rules) | `agent_config/tools.md` | `agent_config/tools.md` |
| Submission README | `README.md` | `README.md` |
| Dashboard (stretch) | `dashboard/` | — (see repo) |
| Unit tests (28, mocked HTTP) | `tests/test_weather_broker.py` | — (see repo) |
| Live demo (Q&A traces) | `demo/agent_demo.py` | — (see repo) |

## 2. Databricks App URLs

Two apps deploy from this repo (same `mcp_server/` + `dashboard/` split as
Day 3). They are **not yet deployed** — deployment requires the Databricks
workspace, so fill these in after running the steps in `README.md →
Deploy to Databricks`:

- **MCP server** (`mcp-weather-server`, source folder `mcp_server/`):
  `https://mcp-weather-server-<APP_ID>.aws.databricksapps.com/mcp`
  (MCP endpoint; register this URL in Agent Bricks as the external MCP server)
- **Dashboard** (`weather-dashboard`, source folder `dashboard/`, optional):
  `https://weather-dashboard-<APP_ID>.aws.databricksapps.com`

> If you can't share workspace access, screenshots of the **Agent Bricks
> playground** showing the tool-call + final answer for the three questions
> in section 3 are the accepted substitute.

## 3. Demonstrate the agent working

Real traces from `python demo/agent_demo.py` (boots the actual MCP server and
drives it over streamable HTTP exactly as Agent Bricks does). Generated
2026-08-09.

### Q1. "Will it rain in Chicago tomorrow?"
```
tool_call: predict_umbrella_needed({"location": "Chicago, IL", "date": "2026-08-10"})
result:    precipitation_probability_pct 49 · precipitation_mm 1.5 · condition "Slight rain showers"
           umbrella_verdict "yes" · "Rain looks likely (49% chance; 1.5 mm expected). Bring an umbrella."
A: Yes — 49% chance of rain tomorrow in Chicago (~1.5 mm); bring an umbrella.
```

### Q2. "Should I bring a jacket to Austin this weekend?"
```
tool_call: get_forecast({"location": "Austin, Texas", "days": 7})
tool_call: get_travel_recommendation({"location": "Austin, Texas", "date": "2026-08-15"})
result:    temp_max 37.8°C (100°F) · rain 2% · comfort_score 75 · verdict "good"
           concerns ["hot (high of 38°C / 100°F)"]
A: Austin is hot this weekend (~38°C/100°F), no rain. Skip the jacket; bring water + sun protection.
```

### Q3. "How's the weather right now in Seattle?"
```
tool_call: get_current_weather({"location": "Seattle, WA"})
result:    Partly cloudy · 14.9°C (58.8°F) · humidity 82% · wind 4.9 km/h
A: Partly cloudy in Seattle right now, ~15°C (59°F), 82% humidity, light wind.
```

### Q4. (stretch) "Which city has better weather this weekend: Austin or Seattle?"
```
tool_call: compare_weather({"locations": ["Austin, Texas", "Seattle, WA"], "days": 2})
A: Seattle — high ~24°C vs Austin's 38°C, both with little rain.
```

## 4. Weather API + auth method

**Open-Meteo** (free, no API key, no signup, no credit card) — geocoding API for
place names, forecast API, archive API for history. **Auth method: none** —
no secrets are required or committed. If a keyed provider is swapped in later,
the Day-3 `WorkspaceClient().secrets.get_secret()` pattern is documented in
`README.md → Security`.

## 5. Checklist (all pass)

- ✅ FastMCP server, `@mcp.tool` decorators, streamable-HTTP at `/mcp`
- ✅ Separate adapter module (`weather_broker.py`) — no HTTP in tool functions
- ✅ `requirements.txt` + `app.yaml`, deployable as its own Databricks App
- ✅ Agent config: system prompt + tool list (this folder)
- ✅ Clear system prompt with tool order + guardrails (no hallucination)
- ✅ README with architecture, tools, setup, API + auth
- ✅ 3+ demo questions with tool-calls + answers (section 3)
- ✅ Clean errors on bad location / API outage (unit-tested)
- ✅ Prediction tools apply explicit thresholds and explain them in docstrings
- ✅ No secrets / hardcoded keys in the repo
