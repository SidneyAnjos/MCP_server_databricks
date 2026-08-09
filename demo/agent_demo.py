"""
demo/agent_demo.py

End-to-end demonstration of the Weather Agent's tool-calling pipeline.

It boots the real Weather MCP Server (weather_mcp_server.py) and drives it
exactly the way Agent Bricks does: over the streamable-HTTP transport, using
an MCP client, with natural-language questions turned into tool calls.

The intent router below is a *stand-in* for the agent LLM's tool selection:
it maps each question to the tools the system prompt tells the agent to use.
Every tool result is real -- fetched live from Open-Meteo through the server.

Run (from the repo root, inside the project venv):
    python demo/agent_demo.py

Requires a working network connection (Open-Meteo). Exits 0 on success.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "mcp_server"
PORT = int(os.environ.get("DEMO_PORT", "8125"))
URL = f"http://127.0.0.1:{PORT}/mcp"

KNOWN_CITIES = {
    "chicago": "Chicago, IL",
    "austin": "Austin, Texas",
    "seattle": "Seattle, WA",
    "new york": "New York, NY",
    "london": "London",
    "paris": "Paris",
    "são paulo": "São Paulo, Brazil",
}


def start_server():
    """Boot the MCP server as a subprocess and wait until /health responds."""
    proc = subprocess.Popen(
        [sys.executable, "weather_mcp_server.py"],
        cwd=str(SERVER_DIR),
        env={**os.environ, "PORT": str(PORT)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                json.loads(r.read())
                return proc
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise SystemExit("MCP server failed to start")


# ---------------------------------------------------------------------------
# Intent router (stands in for the agent LLM's tool selection)
# ---------------------------------------------------------------------------

def resolve_location(question: str) -> str:
    q = question.lower()
    for name, canonical in KNOWN_CITIES.items():
        if name in q:
            return canonical
    return "Chicago, IL"


def weekend_start(today: date) -> date:
    """The nearest upcoming Saturday (this weekend)."""
    days_until_sat = (5 - today.weekday()) % 7
    return today + timedelta(days=days_until_sat)


def plan(question: str, today: date):
    """
    Decide which MCP tools the agent should call for `question`.

    Mirrors the guardrails in agent_config/system_prompt.md: current ->
    get_current_weather; rain/umbrella -> predict_umbrella_needed; travel /
    picnic / jacket -> get_forecast + get_travel_recommendation; compare ->
    compare_weather; otherwise a plain forecast.
    """
    q = question.lower()
    location = resolve_location(question)

    if any(k in q for k in ("compare", "which city", " between ")):
        cities = [resolve_location(sent) for sent in _split_cities(q)]
        return [("compare_weather", {"locations": cities, "days": 2})]
    if any(k in q for k in ("right now", "current", "how's the weather")):
        return [("get_current_weather", {"location": location})]
    if any(k in q for k in ("rain", "umbrella", "raincoat")):
        day = (today + timedelta(days=1)) if "tomorrow" in q else weekend_start(today)
        return [("predict_umbrella_needed", {"location": location, "date": day.isoformat()})]
    if any(k in q for k in ("jacket", "travel", "picnic", "weekend", "good day", "bring")):
        day = weekend_start(today)
        return [
            ("get_forecast", {"location": location, "days": 7}),  # wide enough to cover the weekend
            ("get_travel_recommendation", {"location": location, "date": day.isoformat()}),
        ]
    return [("get_forecast", {"location": location, "days": 3})]


def _split_cities(question: str) -> list:
    """Naive city extraction for 'which city ... Austin or Seattle?' style asks."""
    names = [name for name in KNOWN_CITIES if name in question.lower()]
    # Preserve question order by scanning known names.
    q = question.lower()
    found = [name for name in KNOWN_CITIES if name in q]
    return found or ["Chicago, IL", "Seattle, WA"]


# ---------------------------------------------------------------------------
# Answer composition (stands in for the agent LLM's final response)
# ---------------------------------------------------------------------------

def compose(tool_name: str, result: dict) -> str:
    if "error" in result:
        return f"[!] Tool error: {result['error']} -- no data returned."
    if tool_name == "get_current_weather":
        return (f"It's currently {result['condition']} in {result['location']} at "
                f"{result['temperature_c']}°C ({result['temperature_f']}°F), with "
                f"{result['relative_humidity_pct']}% humidity and "
                f"{result['wind_speed_kmh']} km/h wind.")
    if tool_name == "get_forecast":
        lines = [f"Forecast for {result['location']}:"]
        for d in result["forecast"]:
            lines.append(f"- {d['date']}: {d['condition']}, high {d['temp_max_c']}°C / "
                         f"low {d['temp_min_c']}°C, {d['precipitation_probability_pct']}% rain, "
                         f"{d['wind_max_kmh']} km/h wind")
        return "\n".join(lines)
    if tool_name == "predict_umbrella_needed":
        return (f"Umbrella verdict for {result['date']} in {result['location']}: "
                f"**{result['umbrella_verdict'].upper()}**. {result['explanation']}")
    if tool_name == "get_travel_recommendation":
        return (f"Travel verdict for {result['date']} in {result['location']}: "
                f"**{result['verdict'].upper()}** ({result['comfort_score']}/100). "
                f"{result['advice']}")
    if tool_name == "compare_weather":
        lines = [f"Comparison across {len(result['locations'])} locations:"]
        for entry in result["locations"]:
            d = entry["forecast"][0]
            lines.append(f"- {entry['location']}: {d['date']} {d['condition']}, "
                         f"high {d['temp_max_c']}°C, {d['precipitation_probability_pct']}% rain")
        return "\n".join(lines)
    return json.dumps(result)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run():
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    today = date.today()
    questions = [
        "Will it rain in Chicago tomorrow?",
        "Should I bring a jacket to Austin this weekend?",
        "How's the weather right now in Seattle?",
        "Which city has better weather this weekend: Austin or Seattle?",
    ]

    print("=" * 78)
    print("WEATHER AGENT DEMO — driving the MCP server over streamable-http")
    print(f"Endpoint: {URL}   (today: {today.isoformat()})")
    print("=" * 78)

    async with streamablehttp_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"\nConnected. Server advertises {len(tools.tools)} tools:")
            print("  " + ", ".join(t.name for t in tools.tools) + "\n")

            for question in questions:
                steps = plan(question, today)
                print("-" * 78)
                print(f"Q: {question}")
                final_bits = []
                for tool_name, args in steps:
                    print(f"   -> tool_call: {tool_name}({json.dumps(args)})")
                    res = await session.call_tool(tool_name, args)
                    text = "\n".join(c.text for c in res.content)
                    result = json.loads(text)
                    print(f"      -> result (abridged): {text[:220].replace(chr(10), ' ')}...")
                    final_bits.append(compose(tool_name, result))
                print(f"\nA:\n" + "\n".join(final_bits) + "\n")

    print("=" * 78)
    print("Demo complete. The tool traces above are real MCP calls; in Agent")
    print("Bricks the LLM performs the same tool selection and composes the")
    print("final answer from these results.")
    print("=" * 78)


def main() -> int:
    import asyncio

    # Emit UTF-8 so ° / accented city names render correctly when piped.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    proc = None
    try:
        proc = start_server()
        asyncio.run(run())
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
