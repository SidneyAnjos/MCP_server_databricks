# 🌦️ Weather-Prediction MCP Server + Agent

A homework submission (based on Day 3's *Agent Bricks + Alpaca Markets
paper-trading MCP server* pattern): a **FastMCP weather server** with a thin
**adapter module** (`weather_broker.py`), deployed as a **Databricks App**, and
a **Databricks Agent Bricks agent** that uses it as an external tool to answer
natural-language weather questions and make simple predictions.

Data source: **Open-Meteo** — free, **no API key, no signup, no credit card**
(~10,000 calls/day non-commercial). This means the entire pipeline is testable
locally before any secrets or workspace setup are needed.

---

## What's in the repo

| Piece | Where | Role |
| --- | --- | --- |
| MCP server | `mcp_server/weather_mcp_server.py` | FastMCP server, 6 `@mcp.tool()` tools, streamable-HTTP at `/mcp` |
| Adapter / broker | `mcp_server/weather_broker.py` | **All** HTTP + parsing vs Open-Meteo + prediction logic |
| Server app config | `mcp_server/app.yaml`, `requirements.txt` | Databricks App manifest + deps |
| Agent config | `agent_config/system_prompt.md` | Paste-ready Agent Bricks system prompt |
| Tool manifest | `agent_config/tools.md` | Tool catalog + exact `inputJsonSchema` + decision rules |
| Dashboard (stretch) | `dashboard/` | Streamlit explorer that mirrors the tools & logs queries |
| Unit tests | `tests/test_weather_broker.py` | 28 tests, mocked HTTP |
| Demo | `demo/agent_demo.py` | Boots the real server, drives it over MCP, prints Q&A traces |

---

## Weather API + auth

**Open-Meteo**, with the free geocoding API for place-name resolution.

| Endpoint | Purpose |
| --- | --- |
| `geocoding-api.open-meteo.com/v1/search` | City name → lat/lon (no key) |
| `api.open-meteo.com/v1/forecast` | Current + daily forecast |
| `archive-api.open-meteo.com/v1/archive` | Historical (past dates) |

**Auth method: none.** There are no secrets anywhere in this repo and no
`_secret()` / `get_secret()` call is needed. (If you later swap in WeatherAPI.com
or another keyed provider, follow the Day-3 `WorkspaceClient().secrets.get_secret()`
pattern — see [Swapping providers](#swapping-providers).)

---

## Tools (minimum 3 satisfied)

| Tool | Type | What it returns |
| --- | --- | --- |
| `get_current_weather(location)` | current conditions | temp (°C/°F), apparent temp, condition, humidity, precip, wind (speed/dir/gusts) |
| `get_forecast(location, days=3)` | forecast | per-day high/low (°C/°F), rain chance & amount, wind, condition (1–16 days) |
| `predict_umbrella_needed(location, date)` | **prediction** | umbrella `yes/maybe/no` + explanation, from explicit thresholds |
| `get_travel_recommendation(location, date)` | **prediction** | 0–100 comfort score, `excellent/good/okay/poor`, concerns, advice |
| `get_historical_weather(location, date)` | stretch | observed weather for a past date (archive) |
| `compare_weather(locations, days=3)` | stretch | side-by-side forecast for up to 5 cities |

Locations accept a city name (`"Chicago, IL"`, `"Austin, Texas"`,
`"São Paulo, Brazil"`) or a numeric `"lat,lon"` pair. Dates are `YYYY-MM-DD`.

### Prediction logic (the "reasoning" layer)

- **Umbrella** — `yes` when precipitation chance ≥ 40% **or** expected rain
  ≥ 0.5 mm **or** the day's condition is a precipitating WMO code; `maybe` when
  chance ≥ 20%; otherwise `no`. Wind ≥ 40 km/h adds a *"compact/strong
  umbrella"* caveat. The rule is documented in the tool docstring.
- **Travel** — score 100, then subtract for extreme heat/cold (temp max
  > 32 °C or < 5 °C), rain (chance ≥ 60% or ≥ 10 mm), and wind (≥ 50 km/h);
  ≥ 90 → `excellent`, ≥ 70 → `good`, ≥ 45 → `okay`, else `poor`.

Both tools explain *why* in plain language, so the agent never has to guess.

---

## Architecture

```
        User asks a question (e.g. "Will it rain in Chicago tomorrow?")
                              │
                  ┌───────────▼───────────┐
                  │  Agent Bricks agent   │  system prompt: agent_config/system_prompt.md
                  └───────────┬───────────┘
                              │  MCP tool call (streamable HTTP + OAuth)
                  ┌───────────▼───────────┐
                  │  Databricks App        │  mcp_server/  (app.yaml)
                  │  weather_mcp_server.py │  @mcp.tool() functions stay thin
                  └───────────┬───────────┘
                  ┌───────────▼───────────┐
                  │  weather_broker.py     │  all HTTP + parsing + prediction logic
                  └───────────┬───────────┘
                  ┌───────────▼───────────┐
                  │  Open-Meteo (free)     │  geocoding + forecast + archive
                  └───────────────────────┘

   dashboard/  →  Streamlit explorer that calls weather_broker directly
                  (same data + prediction logic, for humans / recent queries)
```

---

## Local development

Prerequisites: Python 3.11+, network access to Open-Meteo. No API key.

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; `source .venv/bin/activate` on mac/Linux
pip install -r mcp_server/requirements.txt -r dashboard/requirements.txt pytest

# 1) Run the unit tests (mocked HTTP, offline)
python -m pytest tests/ -v

# 2) Run the MCP server
python mcp_server/weather_mcp_server.py      # serves on :8000, MCP at /mcp
#    health:      curl http://localhost:8000/health
#    tool list:   curl http://localhost:8000/
#    MCP endpoint: http://localhost:8000/mcp   (test with MCP Inspector, or:)

# 3) End-to-end agent demo (boots the server + drives it over MCP)
python demo/agent_demo.py

# 4) Dashboard
streamlit run dashboard/app.py
```

---

## Deploy to Databricks

Two Databricks Apps, same repo, separate source folders (the Day-3
`mcp_server/` + `dashboard/` split). **No secrets to configure.**

### MCP server app (name it `mcp-weather-server` — apps whose names start with `mcp-` are recognized as MCP servers)

**Via the CLI** (requires Databricks CLI configured with a profile):

```bash
export DATABRICKS_CONFIG_PROFILE=<your-profile>
databricks auth login --profile "$DATABRICKS_CONFIG_PROFILE"

databricks apps create mcp-weather-server
DATABRICKS_USERNAME=$(databricks current-user me | jq -r .userName)
databricks sync mcp_server "/Users/$DATABRICKS_USERNAME/weather-mcp-server"
databricks apps deploy mcp-weather-server --source-code-path "/Workspace/Users/$DATABRICKS_USERNAME/weather-mcp-server"
```

**Via the UI:** *Apps → Create app → Connect to Git provider → your repo →
source folder `mcp_server/` → Create → Deploy.*

The MCP endpoint becomes:
`https://<mcp-weather-server-app-url>/mcp` (streamable HTTP).

### Dashboard app (optional)

Same steps with app name `weather-dashboard` and source folder `dashboard/`
(app.yaml runs `streamlit run app.py`).

---

## Build the Agent Bricks agent

1. In your Databricks workspace, open **Agent Bricks → Create agent**.
2. Add a model of your choice.
3. Add the MCP server as an **external tool** (the same steps as Day 3,
   *"Register the MCP server as an external MCP"*): use the app's
   `/mcp` URL above as the MCP server endpoint and complete the OAuth
   client pairing that Agent Bricks guides you through.
4. Paste **`agent_config/system_prompt.md`** into the **System prompt** field.
   It tells the agent which tools to call in what order, how to derive dates,
   and the guardrails (only answer for resolvable locations; never invent
   values; say so when a call fails; respect the 7/16-day forecast windows).
5. The six tools appear in the agent's tool list automatically (their exact
   `inputJsonSchema` is documented in `agent_config/tools.md`).
6. **Test** the agent in the playground with the questions below.

---

## Demo — the agent working

Three+ natural-language questions and the agent's tool-calling + answers.
These are **real traces** from `demo/agent_demo.py`, which boots the actual
MCP server and drives it over streamable HTTP exactly as Agent Bricks does
(an LLM performs the same tool selection in the deployed agent).

### Q1. "Will it rain in Chicago tomorrow?"

```
tool_call: predict_umbrella_needed({"location": "Chicago, IL", "date": "2026-08-10"})
result:    {"condition": "Slight rain showers", "weather_code": 80,
            "precipitation_probability_pct": 49, "precipitation_mm": 1.5,
            "umbrella_verdict": "yes",
            "explanation": "Rain looks likely (49% chance of precipitation;
                            1.5 mm expected; Slight rain showers). Bring an umbrella."}

A: Yes — there's a 49% chance of rain in Chicago tomorrow (about 1.5 mm), so
   bring an umbrella.
```

### Q2. "Should I bring a jacket to Austin this weekend?"

```
tool_call: get_forecast({"location": "Austin, Texas", "days": 7})
tool_call: get_travel_recommendation({"location": "Austin, Texas", "date": "2026-08-15"})
result:    {"temp_max_c": 37.8, "temp_max_f": 100.0, "precipitation_probability_pct": 2,
            "comfort_score": 75, "verdict": "good",
            "concerns": ["hot (high of 38°C / 100°F)"],
            "advice": "Generally pleasant. Some minor considerations..."}

A: Austin this weekend is hot — highs around 38°C / 100°F with almost no rain.
   You don't need a jacket; bring water and sun protection instead.
```

### Q3. "How's the weather right now in Seattle?"

```
tool_call: get_current_weather({"location": "Seattle, WA"})
result:    {"condition": "Partly cloudy", "temperature_c": 14.9, "temperature_f": 58.8,
            "relative_humidity_pct": 82, "wind_speed_kmh": 4.9}

A: It's partly cloudy in Seattle right now, about 15°C (59°F), 82% humidity,
   with light wind around 5 km/h.
```

### Q4. (stretch) "Which city has better weather this weekend: Austin or Seattle?"

```
tool_call: compare_weather({"locations": ["Austin, Texas", "Seattle, WA"], "days": 2})
A: For the weekend, Seattle is far more comfortable: high ~24°C vs Austin's
   38°C, both with little rain.
```

> These traces were generated on **2026-08-09**. Re-run `python demo/agent_demo.py`
> anytime to get fresh, live data.

---

## Error handling (what "good" looks like)

- A bad location returns a clean `{"error": "Could not resolve 'Atlantis' ..."}`
  — no stack trace — and the agent asks the user to rephrase or give `lat,lon`.
- An API outage / network failure returns `"Could not reach the weather service..."`
  and the agent says data is unavailable rather than guessing.
- Out-of-window dates return the valid range (`"Data is available for the next
  7 days: ..."`), so the agent offers the nearest date instead of fabricating.

---

## Tests

`tests/test_weather_broker.py` — 28 tests, all HTTP mocked (no network):
location resolution, WMO-code mapping, current/forecast/historical parsing,
umbrella thresholds, travel scoring, compare limits, and error paths.
Run with `python -m pytest tests/ -v` → **28 passed**.

---

## Security

- **No secrets committed.** Open-Meteo needs no key, so there is nothing to
  leak. No env vars, no hardcoded tokens, no API keys in the repo.
- App-deployed endpoints are workspace-restricted (Databricks Apps do not
  support anonymous access); the agent authenticates to the MCP server via the
  OAuth client pairing set up in Agent Bricks.

### Swapping providers

If you replace Open-Meteo with a keyed API (e.g. WeatherAPI.com), follow the
Day-3 pattern: store the key in a Databricks secret scope and resolve it at
runtime with `databricks.sdk.WorkspaceClient().secrets.get_secret(...)` inside
`weather_broker.py` — never in code or `app.yaml`. All keyed logic should stay
inside the adapter module so the `@mcp.tool` functions remain thin.

---

## Design notes / reflection

- **Broker is the boundary.** `weather_broker.py` owns every HTTP call and the
  parsing; `weather_mcp_server.py` only serializes broker results to JSON.
  This made the module trivially unit-testable with mocked `requests.get`.
- **Prediction > passthrough.** The umbrella and travel tools apply explicit,
  documented thresholds and return an `explanation`/`advice`, so the agent
  can justify its answer without hallucinating.
- **Zero-credential first.** Choosing Open-Meteo meant the full pipeline
  (broker → server → MCP client → answers) could be built and verified locally
  before any Databricks workspace step.
- **`mcp` version pin.** Databricks Apps would install `mcp 2.x` by default,
  which removed the FastMCP high-level API the Day-3 pattern uses; `requirements.txt`
  pins `mcp>=1.16,<2` to keep `mcp.server.fastmcp` available.

## Roadmap

- [ ] Deploy `mcp-weather-server` and confirm the agent in the Agent Bricks
      playground end-to-end against the live app URL.
- [ ] Layer in the National Weather Service alerts tool as a second provider
      (US-only severe-weather, reusing the alert parsing pattern).
- [ ] Persist dashboard "recent queries" to Lakebase instead of the session log.
