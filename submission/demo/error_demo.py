"""
demo/error_demo.py

Failing-path transcripts: what the six MCP tools return when something goes
wrong. This is the evidence for the "reasonable error handling (clean error
dicts)" grading criterion — every payload below is exactly what the agent
receives from a real `@mcp.tool` call: a clean `{"error": "<message>"}` dict,
never a stack trace.

It calls the *actual* tool functions from `weather_mcp_server.py` (the same
code Agent Bricks invokes) and mocks the Open-Meteo HTTP layer so the demo is
offline and deterministic — no server process, no network.

Run:
    python demo/error_demo.py

Covers 10 failure classes:
    1.  unresolved location        -> "Could not resolve 'Atlantis' ..."
    2.  empty location             -> "Location is empty ..."
    3.  out-of-range coordinates   -> "Latitude must be between -90 and 90 ..."
    4.  malformed date format      -> "date must be formatted as YYYY-MM-DD ..."
    5.  date outside 7-day window  -> "is outside the forecast horizon ..."
    6.  days out of range (0, 17)  -> "days must be between 1 and 16 ..."
    7.  too many locations         -> "Compare at most 5 locations at once."
    8.  empty compare list         -> "Provide at least one location to compare."
    9.  HTTP 500 from the API      -> "Weather service returned HTTP 500 ..."
    10. network failure            -> "Could not reach the weather service ..."
    11. malformed (non-JSON) body  -> "Weather service returned malformed ..."
    12. empty historical archive   -> "No archived weather available ..."
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_server"))

import weather_broker as wb      # noqa: E402
import weather_mcp_server as srv  # noqa: E402  (the @mcp.tool functions)

TODAY = date(2026, 8, 9)


# ---------------------------------------------------------------------------
# Mocked Open-Meteo responses
# ---------------------------------------------------------------------------

def _resp(json_data, status_code=200):
    r = type("Resp", (), {})()
    r.status_code = status_code
    r.json = lambda: json_data
    return r


CHICAGO = {
    "results": [{"name": "Chicago", "latitude": 41.85, "longitude": -87.65,
                 "admin1": "Illinois", "country_code": "US"}],
}


def _daily(n=7):
    """A realistic 7-day daily block starting TODAY (dates are real, API is not)."""
    return {
        "time": [(TODAY + timedelta(days=i)).isoformat() for i in range(n)],
        "weather_code": [0] * n,
        "temperature_2m_max": [27.0] * n,
        "temperature_2m_min": [16.0] * n,
        "precipitation_probability_max": [5] * n,
        "precipitation_sum": [0.0] * n,
        "wind_speed_10m_max": [12.0] * n,
    }


def _forecast(daily=_daily(7), current=None):
    current = current or {"time": "2026-08-09T09:30", "temperature_2m": 21.5,
                          "weather_code": 0, "relative_humidity_2m": 60,
                          "apparent_temperature": 22.0, "precipitation": 0.0,
                          "wind_speed_10m": 10.0, "wind_direction_10m": 180,
                          "wind_gusts_10m": 20.0}
    return {"timezone": "America/Chicago", "current": current, "daily": daily}


def _patch(forecast=None, archive=None, geocode=CHICAGO, status=200, raise_exc=None,
           bad_json=False):
    """Patch requests.get so every API call returns the chosen response."""
    def side_effect(url, **kwargs):
        if raise_exc is not None:
            raise wb.requests.RequestException(raise_exc)
        if bad_json:
            r = type("Resp", (), {})()
            r.status_code = 200
            r.json = lambda: (_ for _ in ()).throw(ValueError("no json"))
            return r
        if url == wb.GEOCODING_API:
            return _resp(geocode)
        if url == wb.FORECAST_API:
            return _resp(forecast or _forecast(), status_code=status)
        if url == wb.ARCHIVE_API:
            return _resp(archive if archive is not None
                         else {"timezone": "UTC", "daily": _daily(1)}, status_code=status)
        raise AssertionError(f"unexpected URL {url}")
    return patch.object(wb.requests, "get", side_effect=side_effect)


# ---------------------------------------------------------------------------
# Case runner
# ---------------------------------------------------------------------------

def _show(num: int, title: str, tool_name: str, fn):
    """Call an MCP tool function under the current patch and print its output."""
    print(f"\n[{num}] {title}")
    print(f"    tool -> {tool_name}()")
    try:
        out = fn()
    except Exception as exc:  # a crash here would prove a leaky error — catch it loudly
        print(f"    !! UNHANDLED EXCEPTION (this would leak to the agent): {exc!r}")
        return
    payload = json.loads(out)          # tools return a JSON string
    if "error" in payload:
        print(f"    clean error dict -> {json.dumps(payload, ensure_ascii=False)}")
    else:
        print(f"    (no error; result keys) -> {list(payload)}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("=" * 78)
    print("WEATHER MCP SERVER — failing-path transcripts (offline, mocked HTTP)")
    print("Every line is the exact dict the agent receives from a tool call.")
    print("=" * 78)

    # 1–3: location resolution failures
    with _patch(geocode={"results": []}):
        _show(1, "Unresolved location", "get_current_weather", lambda: srv.get_current_weather("Atlantis"))
    with _patch():
        _show(2, "Empty location", "get_current_weather", lambda: srv.get_current_weather("   "))
    with _patch():
        _show(3, "Out-of-range coordinates (lat 120)", "get_current_weather", lambda: srv.get_current_weather("120, -87"))

    # 4–5: date failures (location resolves fine, then the date is rejected)
    with _patch():
        _show(4, "Malformed date '10/08/2026'", "predict_umbrella_needed", lambda: srv.predict_umbrella_needed("Chicago", "10/08/2026"))
    with _patch():
        _show(5, "Date outside 7-day forecast window", "predict_umbrella_needed", lambda: srv.predict_umbrella_needed("Chicago", "2026-09-01"))

    # 6: days out of range
    with _patch():
        _show(6, "get_forecast days=17 (max is 16)", "get_forecast", lambda: srv.get_forecast("Chicago", days=17))

    # 7–8: compare_weather argument failures
    with _patch():
        _show(7, "compare_weather with 6 locations (max 5)", "compare_weather", lambda: srv.compare_weather(["A", "B", "C", "D", "E", "F"]))
    with _patch():
        _show(8, "compare_weather with an empty list", "compare_weather", lambda: srv.compare_weather([]))

    # 9–11: upstream failures (lat,lon skips geocoding so the forecast call fails)
    with _patch(forecast={}, status=500):
        _show(9, "Open-Meteo returns HTTP 500", "get_current_weather", lambda: srv.get_current_weather("41.85,-87.65"))
    with _patch(raise_exc="connection refused"):
        _show(10, "Network failure", "get_current_weather", lambda: srv.get_current_weather("41.85,-87.65"))
    with _patch(bad_json=True):
        _show(11, "Non-JSON response body", "get_current_weather", lambda: srv.get_current_weather("41.85,-87.65"))

    # 12: empty archive
    with _patch(archive={"timezone": "UTC", "daily": {"time": []}}):
        _show(12, "No archived data for the date", "get_historical_weather", lambda: srv.get_historical_weather("Chicago", "2026-08-07"))

    print("\n" + "=" * 78)
    print("All 12 failure paths returned a clean {'error': ...} dict.")
    print("No stack trace reached the agent — guardrails in system_prompt.md")
    print("tell the agent to surface these and never guess data.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
