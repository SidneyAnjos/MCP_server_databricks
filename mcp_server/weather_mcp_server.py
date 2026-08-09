"""
weather_mcp_server.py

Weather-Prediction MCP Server -- a FastMCP server exposing weather-forecast
tools to a Databricks Agent Bricks agent (deployed as a Databricks App).

Transport: streamable HTTP, served on `$PORT` (Databricks Apps default 8000).
  - MCP endpoint : http://localhost:8000/mcp
  - Tool listing : http://localhost:8000/

All HTTP calls and parsing live in `weather_broker.py` (the adapter module);
the `@mcp.tool` functions below are intentionally thin and only translate
broker results into JSON for the agent.

Tools (6):
  - get_current_weather(location)
  - get_forecast(location, days)
  - predict_umbrella_needed(location, date)
  - get_travel_recommendation(location, date)
  - get_historical_weather(location, date)
  - compare_weather(locations, days)

Data source: Open-Meteo -- free, no API key, no signup, no credit card.
"""

import json
import os
import warnings
from typing import List

# Silence a harmless pydantic-settings warning emitted by mcp's settings
# model (unresolved forward ref on the lifespan field). Log noise only.
warnings.filterwarnings(
    "ignore",
    message=r"Field 'lifespan' has an incomplete definition.*",
    module=r"pydantic_settings.*",
)

from mcp.server.fastmcp import FastMCP  # noqa: E402

import weather_broker  # noqa: E402

mcp = FastMCP("weather-mcp-server")


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _ok(result: dict) -> str:
    """Serialize a broker result dict into a pretty JSON string for the agent."""
    return json.dumps(result, indent=2, ensure_ascii=False)


def _err(message: str) -> str:
    """Serialize a clean, agent-readable error (never a stack trace)."""
    return json.dumps({"error": message}, indent=2)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_current_weather(location: str) -> str:
    """
    Get current weather conditions for a location right now.

    Args:
        location: A city name ("Chicago", "Chicago, IL", "Austin, Texas") or a
            numeric "lat,lon" pair ("41.88,-87.63").

    Returns:
        JSON with temperature (C and F), apparent temperature, condition,
        humidity, precipitation, and wind (speed/direction/gusts) plus the
        resolved location label and observed time.
    """
    try:
        return _ok(weather_broker.get_current_weather(location))
    except weather_broker.WeatherError as exc:
        return _err(str(exc))


@mcp.tool()
def get_forecast(location: str, days: int = weather_broker.DEFAULT_FORECAST_DAYS) -> str:
    """
    Get a multi-day weather forecast for a location.

    Args:
        location: A city name or a numeric "lat,lon" pair.
        days: Number of days ahead to include (1-16, default 3).

    Returns:
        JSON with a per-day list: high/low temperature (C and F), precipitation
        chance (%), precipitation amount (mm), max wind (km/h), and a
        plain-language condition.
    """
    try:
        return _ok(weather_broker.get_forecast(location, days))
    except weather_broker.WeatherError as exc:
        return _err(str(exc))


@mcp.tool()
def predict_umbrella_needed(location: str, date: str) -> str:
    """
    Predict whether an umbrella is needed on a specific date at a location.

    Args:
        location: A city name or a numeric "lat,lon" pair.
        date: The target date as YYYY-MM-DD (within the next 7 days).

    Returns:
        JSON with an umbrella verdict ("yes"/"maybe"/"no") and a plain-language
        explanation. Decision rule: "yes" if precipitation chance >= 40% OR
        expected rain >= 0.5mm OR the day's condition is precipitating;
        "maybe" if chance >= 20%; otherwise "no". Strong wind (>40 km/h) adds
        a caveat.
    """
    try:
        return _ok(weather_broker.predict_umbrella_needed(location, date))
    except weather_broker.WeatherError as exc:
        return _err(str(exc))


@mcp.tool()
def get_travel_recommendation(location: str, date: str) -> str:
    """
    Recommend whether a date is good for outdoor plans at a location.

    Args:
        location: A city name or a numeric "lat,lon" pair.
        date: The target date as YYYY-MM-DD (within the next 7 days).

    Returns:
        JSON with a 0-100 comfort score, a verdict ("excellent"/"good"/"okay"/
        "poor"), the specific concerns that drove it (heat, cold, rain, wind),
        and plain-language advice. Uses thresholds on temperature, rain
        chance/amount, and wind speed.
    """
    try:
        return _ok(weather_broker.get_travel_recommendation(location, date))
    except weather_broker.WeatherError as exc:
        return _err(str(exc))


@mcp.tool()
def get_historical_weather(location: str, date: str) -> str:
    """
    Get observed weather for a single past date at a location.

    Args:
        location: A city name or a numeric "lat,lon" pair.
        date: The target date as YYYY-MM-DD (a past date).

    Returns:
        JSON with the observed high/low temperature (C and F), precipitation,
        wind, and condition for that date, flagged as observed (archive) data.
    """
    try:
        return _ok(weather_broker.get_historical_weather(location, date))
    except weather_broker.WeatherError as exc:
        return _err(str(exc))


@mcp.tool()
def compare_weather(locations: List[str], days: int = weather_broker.DEFAULT_FORECAST_DAYS) -> str:
    """
    Compare the upcoming forecast across up to 5 locations side by side.

    Args:
        locations: A list of city names or "lat,lon" pairs to compare.
        days: Number of days ahead to include (1-16, default 3).

    Returns:
        JSON with one forecast entry per location so the agent can compare
        conditions across cities for the same upcoming days.
    """
    try:
        return _ok(weather_broker.compare_weather(locations, days))
    except weather_broker.WeatherError as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# HTTP wiring (Starlette wrapper + streamable-http at /mcp)
# ---------------------------------------------------------------------------

# Tool catalog for the landing page / health endpoint.
TOOL_CATALOG = [
    {"name": "get_current_weather", "description": "Current conditions for a location."},
    {"name": "get_forecast", "description": "Multi-day forecast for a location."},
    {"name": "predict_umbrella_needed", "description": "Umbrella verdict + explanation for a date."},
    {"name": "get_travel_recommendation", "description": "Outdoor-plan recommendation + comfort score for a date."},
    {"name": "get_historical_weather", "description": "Observed weather for a past date."},
    {"name": "compare_weather", "description": "Side-by-side forecast for up to 5 locations."},
]


def create_app():
    """Build the ASGI app: MCP endpoint at /mcp plus a landing/health page at /.

    FastMCP's streamable-http app already routes the MCP endpoint at /mcp
    internally (mcp.settings.streamable_http_path), so it is mounted at the
    root and /mcp falls through to it. Because Starlette does not run the
    lifespan of mounted apps, we re-run mcp.session_manager.run() in the
    parent's lifespan (same wiring as the official Databricks example).
    """
    from contextlib import asynccontextmanager

    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    mcp_starlette = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp.session_manager.run():
            yield

    async def index(request) -> JSONResponse:
        return JSONResponse({
            "service": "Weather MCP Server",
            "mcp_endpoint": "/mcp",
            "tools": TOOL_CATALOG,
        })

    async def health(request) -> JSONResponse:
        return JSONResponse({"status": "ok", "tools": len(TOOL_CATALOG)})

    return Starlette(
        routes=[
            Route("/", index),
            Route("/health", health),
            Mount("/", app=mcp_starlette),
        ],
        lifespan=lifespan,
    )


app = create_app()


def main() -> None:
    """Run the server with uvicorn on $PORT (Databricks Apps default 8000)."""
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
