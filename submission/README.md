# 🌦️ Weather-Prediction MCP Server + Agent — submission package

Built by `scripts/build_submission.py` on **2026-08-10 00:03**. This package contains
the actual server code (the hard blocker) and machine-generated evidence for every
grading criterion. Re-run the builder anytime to regenerate.

## What's in the package

| Path | Contents |
| --- | --- |
| `code/weather_mcp_server.py` | FastMCP server — **6 `@mcp.tool()` tools**, thin, streamable-HTTP at `/mcp` |
| `code/weather_broker.py` | **Adapter module** — owns all HTTP + parsing vs Open-Meteo + prediction logic |
| `code/app.yaml` | Databricks App manifest (`python weather_mcp_server.py` on `$PORT`) |
| `code/requirements.txt` | Pinned deps — **`mcp>=1.16,<2`**, `requests`, `uvicorn` |
| `agent_config/system_prompt.md` | Paste-ready Agent Bricks system prompt (ordering + guardrails) |
| `agent_config/tools.md` | Tool catalog with exact `inputJsonSchema` + decision rules |
| `demo/` | Runnable demo scripts (boot the real server over MCP) |
| `evidence/test_results.txt` | `pytest` output — **28 passed** (mocked HTTP, offline) |
| `evidence/tools_list.json` | Exact `tools/list` payload — **6 tools + inputJsonSchema** |
| `evidence/secret_scan.txt` | Repo secret scan — **CLEAN** (20 files, 0 findings) |
| `evidence/failing_paths.txt` | **12 failing-path transcripts** — clean `{"error": ...}` dicts, no stack traces |
| `evidence/local_run_log.txt` | **Live HTTP MCP endpoint**: `initialize` + `tools/list` + a real `tools/call` |
| `evidence/agent_demo.txt` | **4 natural-language Q&A traces** with real tool calls + answers |
| `evidence/agent_registration.md` | Agent Bricks external-MCP registration steps (not deployed yet) |

## Grading criteria → evidence

| Criterion (max) | Proven by |
| --- | --- |
| ≥3 distinct tools via `@mcp.tool` (10) | `code/weather_mcp_server.py` (6 tools); `evidence/tools_list.json` |
| Docstrings with Args/Returns (5) | Each tool's docstring in `code/weather_mcp_server.py`; verbatim `description`s in `evidence/tools_list.json` |
| HTTP/parsing in a separate adapter (5) | `code/weather_broker.py` (all HTTP+parse+logic); tools in `code/weather_mcp_server.py` stay thin |
| Runs over streamable HTTP (5) | `code/weather_mcp_server.py` (`create_app`/`Mount`), `code/app.yaml`; `evidence/local_run_log.txt` (initialize + tools/list over HTTP) |
| Reasonable error handling — clean error dicts (5) | `code/weather_mcp_server.py` (`_err`), `code/weather_broker.py` (`WeatherError`); `evidence/failing_paths.txt` (12 clean errors); `evidence/test_results.txt` |
| Prediction tool applies derived logic (10) | `code/weather_broker.py` `predict_umbrella_needed` / `get_travel_recommendation` (thresholds, not passthrough) |
| Logic explained in docstring/README (5) | Tool docstrings + `agent_config/tools.md` + repo README |
| No hardcoded secrets (10) | `evidence/secret_scan.txt` (**CLEAN**, 20 files, 0 findings) |
| Key from secret store / no key needed (5) | `code/weather_broker.py` (no secrets), `code/app.yaml` ("No secrets required") — Open-Meteo needs no key |
| Agent registered to your MCP server (5) | `evidence/agent_registration.md` — steps + status (not deployed; local endpoint proven) |
| System prompt: tool order + scope (5) | `agent_config/system_prompt.md` (extract location → pick tool → derive date → call) |
| System prompt: explicit guardrail (5) | `agent_config/system_prompt.md` (Guardrails: never invent data, window limits, no alerts tool) |
| Transcripts match the system prompt (5) | `evidence/agent_demo.txt` (4 Q&As; tool selection follows the prompt's rules) |
| README explains arch/tools/api+auth (5) | Repo `README.md` |
| requirements/app.yaml present + plausible (5) | `code/requirements.txt` (**`mcp>=1.16,<2`**), `code/app.yaml` |
| 3+ NL questions with tool calls (5) | `evidence/agent_demo.txt` (4 questions, each with `tool_call:` lines) |
| Answers consistent with tool outputs (5) | `evidence/agent_demo.txt` — every number comes from a live tool result |

## The code (hard-blocker fix) — paste these directly

The four files the reviewer asked for are in `code/` and are byte-for-byte the
files that run:

- `code/weather_mcp_server.py` — 6 `@mcp.tool()` functions, `_ok`/`_err` helpers,
  `create_app()` mounting the streamable-HTTP app at `/mcp`.
- `code/weather_broker.py` — `WeatherError`, `_get()`, `resolve_location()`,
  `predict_umbrella_needed()` / `get_travel_recommendation()` (thresholds),
  `compare_weather()`, `get_historical_weather()`.
- `code/app.yaml` — Databricks App manifest; command `python weather_mcp_server.py`.
- `code/requirements.txt` — `mcp[cli]>=1.16,<2`, `requests>=2.31`, `uvicorn>=0.30`.

## Re-run

```bash
python scripts/build_submission.py   # from the repo root, inside the venv
```

Regenerates `submission/` and `submission.zip` from the live repo. The network
steps (`local_run_log.txt`, `agent_demo.txt`) degrade to a WARN when offline; all
other evidence is offline/mocked and always produced.
