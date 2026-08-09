"""
weather_broker.py

Adapter/broker module for the Weather MCP Server (the same role `alpaca_broker.py`
plays in the Day-3 Alpaca MCP server). It owns ALL of the HTTP calls and
parsing against the free Open-Meteo API so the `@mcp.tool` functions in
`weather_mcp_server.py` stay thin.

Data source: Open-Meteo (https://open-meteo.com)
  - No API key, no signup, no credit card (10k calls/day non-commercial).
  - Geocoding  : https://geocoding-api.open-meteo.com/v1/search
  - Forecast   : https://api.open-meteo.com/v1/forecast
  - Historical : https://archive-api.open-meteo.com/v1/archive

Every public function accepts a location (free-text place name or "lat,lon")
and returns a plain dict. Every failure path raises `WeatherError` with a
human-readable message that the MCP tools surface cleanly to the agent.

The "prediction" helpers (`predict_umbrella_needed`, `get_travel_recommendation`)
apply explicit thresholds to the raw forecast data -- they are reasoning
layers, not passthroughs.
"""

import logging
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_API = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"

REQUEST_TIMEOUT = 15  # seconds
USER_AGENT = "weather-mcp-server/1.0 (MCP homework)"
MAX_FORECAST_DAYS = 16   # Open-Meteo free tier ceiling
DEFAULT_FORECAST_DAYS = 3
MAX_COMPARE_LOCATIONS = 5

# WMO weather interpretation codes -> human-readable label.
# Source: https://open-meteo.com/en/docs (weathercode column).
WMO_CODES: Dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

# WMO codes that count as "precipitation" for the umbrella / travel logic.
_PRECIPITATION_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67,
                        71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99}

# Prediction thresholds (documented in the tool docstrings / README).
UMBRELLA_PRECIP_PROB_THRESHOLD = 40.0   # precipitation chance % -> "yes"
UMBRELLA_MAYBE_THRESHOLD = 20.0         # precipitation chance % -> "maybe"
UMBRELLA_PRECIP_SUM_THRESHOLD = 0.5     # mm expected -> "yes"
UMBRELLA_WIND_GUST_THRESHOLD = 40.0     # km/h -> add a wind caveat


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class WeatherError(Exception):
    """Raised for any failure the caller should surface to the agent cleanly."""


# ---------------------------------------------------------------------------
# Low-level HTTP
# ---------------------------------------------------------------------------

def _get(url: str, params: dict) -> dict:
    """JSON GET helper. Raises WeatherError on any network/HTTP/parse failure."""
    try:
        resp = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
    except requests.RequestException as exc:
        raise WeatherError(
            f"Could not reach the weather service ({type(exc).__name__}). "
            "Try again shortly."
        ) from exc

    if resp.status_code != 200:
        raise WeatherError(
            f"Weather service returned HTTP {resp.status_code} for {url}. "
            "The service may be rate-limiting or down; try again shortly."
        )

    try:
        return resp.json()
    except ValueError as exc:
        raise WeatherError("Weather service returned malformed (non-JSON) data.") from exc


# ---------------------------------------------------------------------------
# Location resolution
# ---------------------------------------------------------------------------

def resolve_location(location: str) -> Dict:
    """
    Resolve a user location string to {lat, lon, label}.

    Accepts either a numeric "lat,lon" pair or a free-text place name
    ("Chicago", "Chicago, IL", "São Paulo, Brazil"), which is geocoded via
    the free Open-Meteo geocoding API (no key required).

    Raises WeatherError if the string is empty, the lat/lon are out of range,
    or geocoding finds no match.
    """
    location = (location or "").strip()
    if not location:
        raise WeatherError("Location is empty. Provide a city name or 'lat,lon'.")

    numeric = _parse_lat_lon(location)
    if numeric is not None:
        lat, lon = numeric
        return {"lat": lat, "lon": lon, "label": location}

    data = _get(GEOCODING_API, {"name": location, "count": 1, "language": "en", "format": "json"})
    results = data.get("results") or []

    if not results:
        raise WeatherError(
            f"Could not resolve '{location}' to a location. "
            "Try a different spelling, a larger city, or pass 'lat,lon' coordinates."
        )

    hit = results[0]
    name = hit.get("name") or location
    region = hit.get("admin1") or ""
    country = hit.get("country_code") or ""
    label = ", ".join(p for p in (name, region, country) if p)

    return {"lat": hit["latitude"], "lon": hit["longitude"], "label": label}


def _parse_lat_lon(location: str) -> Optional[Tuple[float, float]]:
    """Parse 'lat,lon' -> (lat, lon), or None if not a numeric coordinate pair."""
    if "," not in location:
        return None
    parts = [p.strip() for p in location.split(",")]
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise WeatherError(
            "Latitude must be between -90 and 90, longitude between -180 and 180."
        )
    return lat, lon


# ---------------------------------------------------------------------------
# Weather code helpers
# ---------------------------------------------------------------------------

def describe_weather_code(code: Optional[int]) -> str:
    """Map a WMO weather code to a human-readable label, e.g. 61 -> 'Slight rain'."""
    if code is None:
        return "Unknown"
    return WMO_CODES.get(code, f"Code {code}")


def _is_precipitation(code: Optional[int]) -> bool:
    return code in _PRECIPITATION_CODES


# ---------------------------------------------------------------------------
# Forecast fetch + parsing
# ---------------------------------------------------------------------------

# Shared daily fields requested from Open-Meteo (forecast + archive).
_DAILY_FIELDS = ",".join([
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_probability_max",
    "precipitation_sum",
    "wind_speed_10m_max",
])

_CURRENT_FIELDS = ",".join([
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "weather_code",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
])


def _c_to_f(celsius: float) -> float:
    return round(celsius * 9 / 5 + 32, 1)


def _parse_daily(daily: dict) -> List[Dict]:
    """Turn Open-Meteo's parallel daily arrays into a list of per-day dicts."""
    days: List[Dict] = []
    times = daily.get("time", [])
    for i, date in enumerate(times):
        code = daily["weather_code"][i]
        tmax = daily["temperature_2m_max"][i]
        tmin = daily["temperature_2m_min"][i]
        days.append({
            "date": date,
            "condition": describe_weather_code(code),
            "weather_code": code,
            "temp_max_c": tmax,
            "temp_min_c": tmin,
            "temp_max_f": _c_to_f(tmax),
            "temp_min_f": _c_to_f(tmin),
            "precipitation_probability_pct": daily["precipitation_probability_max"][i],
            "precipitation_mm": round(daily["precipitation_sum"][i], 1),
            "wind_max_kmh": round(daily["wind_speed_10m_max"][i], 1),
        })
    return days


def _fetch_forecast(lat: float, lon: float, days: int, timezone: str = "auto") -> Dict:
    """Call the forecast API for `days` days and return the parsed payload."""
    if days < 1 or days > MAX_FORECAST_DAYS:
        raise WeatherError(
            f"days must be between 1 and {MAX_FORECAST_DAYS}, got {days}."
        )
    data = _get(FORECAST_API, {
        "latitude": lat,
        "longitude": lon,
        "current": _CURRENT_FIELDS,
        "daily": _DAILY_FIELDS,
        "forecast_days": days,
        "timezone": timezone,
    })
    return {
        "timezone": data.get("timezone", "auto"),
        "current": data.get("current", {}),
        "days": _parse_daily(data.get("daily", {})),
    }


# ---------------------------------------------------------------------------
# Public tool-facing functions
# ---------------------------------------------------------------------------

def get_current_weather(location: str) -> Dict:
    """
    Current observed conditions for a location.

    Returns temperature (C and F), apparent temperature, condition label,
    humidity, precipitation, and wind (speed/direction/gusts).
    """
    resolved = resolve_location(location)
    payload = _fetch_forecast(resolved["lat"], resolved["lon"], days=1)
    cur = payload["current"] or {}

    return {
        "location": resolved["label"],
        "latitude": round(resolved["lat"], 4),
        "longitude": round(resolved["lon"], 4),
        "timezone": payload["timezone"],
        "observed_at": cur.get("time", ""),
        "condition": describe_weather_code(cur.get("weather_code")),
        "weather_code": cur.get("weather_code"),
        "temperature_c": cur.get("temperature_2m"),
        "temperature_f": _c_to_f(cur["temperature_2m"]) if cur.get("temperature_2m") is not None else None,
        "apparent_temperature_c": cur.get("apparent_temperature"),
        "relative_humidity_pct": cur.get("relative_humidity_2m"),
        "precipitation_mm": round(cur.get("precipitation") or 0.0, 1),
        "wind_speed_kmh": round(cur.get("wind_speed_10m") or 0.0, 1),
        "wind_direction_deg": cur.get("wind_direction_10m"),
        "wind_gusts_kmh": round(cur.get("wind_gusts_10m") or 0.0, 1),
    }


def get_forecast(location: str, days: int = DEFAULT_FORECAST_DAYS) -> Dict:
    """
    Multi-day forecast for a location.

    `days` (1-16) controls how many days ahead are included. Each day carries
    high/low temp (C and F), precipitation chance and amount, wind, and a
    plain-language condition.
    """
    resolved = resolve_location(location)
    payload = _fetch_forecast(resolved["lat"], resolved["lon"], days=days)
    return {
        "location": resolved["label"],
        "latitude": round(resolved["lat"], 4),
        "longitude": round(resolved["lon"], 4),
        "timezone": payload["timezone"],
        "days_requested": days,
        "forecast": payload["days"],
    }


def predict_umbrella_needed(location: str, date: str) -> Dict:
    """
    Should you carry an umbrella on `date` (YYYY-MM-DD) at `location`?

    Decision rule (documented):
      - "yes"  when precipitation probability >= 40% OR expected rain >= 0.5mm
               OR the day's condition is a precipitating WMO code.
      - "maybe" when probability >= 20%.
      - "no"   otherwise.
    Strong wind (>= 40 km/h) adds a caveat (a compact/strong umbrella).

    Only dates within the next 7 days can be predicted (forecast horizon).
    """
    resolved = resolve_location(location)
    day = _find_forecast_day(resolved, date)

    code = day["weather_code"]
    prob = day["precipitation_probability_pct"] or 0
    precip_mm = day["precipitation_mm"] or 0
    wind = day["wind_max_kmh"] or 0

    precipitating = _is_precipitation(code)
    if precipitating or prob >= UMBRELLA_PRECIP_PROB_THRESHOLD or precip_mm >= UMBRELLA_PRECIP_SUM_THRESHOLD:
        verdict = "yes"
    elif prob >= UMBRELLA_MAYBE_THRESHOLD:
        verdict = "maybe"
    else:
        verdict = "no"

    reasons = [f"{prob:.0f}% chance of precipitation", f"{precip_mm:.1f} mm expected",
               day["condition"]]
    explanation = _compose_explanation(verdict, reasons, wind)

    return {
        "location": resolved["label"],
        "date": date,
        "condition": day["condition"],
        "weather_code": code,
        "precipitation_probability_pct": prob,
        "precipitation_mm": precip_mm,
        "wind_max_kmh": wind,
        "umbrella_verdict": verdict,
        "explanation": explanation,
    }


def get_travel_recommendation(location: str, date: str) -> Dict:
    """
    Is `date` (YYYY-MM-DD) a good day to be outdoors at `location`?

    Scores the day 0-100 from the forecast: moderate temps score best, extreme
    heat/cold, high rain chance, and strong wind reduce the score. Returns a
    verdict ("excellent"/"good"/"okay"/"poor"), the score, the specific
    concerns that drove it, and plain-language advice.
    """
    resolved = resolve_location(location)
    day = _find_forecast_day(resolved, date)

    tmax = day["temp_max_c"]
    prob = day["precipitation_probability_pct"] or 0
    precip_mm = day["precipitation_mm"] or 0
    wind = day["wind_max_kmh"] or 0

    concerns: List[str] = []
    score = 100

    if tmax is not None:
        if 18 <= tmax <= 28:
            score += 0  # ideal
        elif tmax > 32:
            concerns.append(f"hot (high of {tmax:.0f}°C / {day['temp_max_f']:.0f}°F)")
            score -= 25
        elif tmax > 28:
            concerns.append(f"warm (high of {tmax:.0f}°C / {day['temp_max_f']:.0f}°F)")
            score -= 5
        elif tmax < 5:
            concerns.append(f"cold (high of {tmax:.0f}°C / {day['temp_max_f']:.0f}°F)")
            score -= 25
        else:
            score -= 5  # cool but fine

    if prob >= 60 or precip_mm >= 10:
        concerns.append(f"{prob:.0f}% rain chance / {precip_mm:.1f}mm expected")
        score -= 30
    elif prob >= 30:
        concerns.append(f"{prob:.0f}% rain chance")
        score -= 10

    if wind >= 50:
        concerns.append(f"strong wind ({wind:.0f} km/h)")
        score -= 20
    elif wind >= 30:
        concerns.append(f"breezy ({wind:.0f} km/h)")
        score -= 5

    if score >= 90:
        verdict = "excellent"
    elif score >= 70:
        verdict = "good"
    elif score >= 45:
        verdict = "okay"
    else:
        verdict = "poor"

    advice = _travel_advice(verdict, concerns)

    return {
        "location": resolved["label"],
        "date": date,
        "condition": day["condition"],
        "temp_max_c": tmax,
        "temp_max_f": day["temp_max_f"],
        "precipitation_probability_pct": prob,
        "precipitation_mm": precip_mm,
        "wind_max_kmh": wind,
        "comfort_score": max(0, score),
        "verdict": verdict,
        "concerns": concerns,
        "advice": advice,
    }


def get_historical_weather(location: str, date: str) -> Dict:
    """
    Observed weather for a single past `date` (YYYY-MM-DD) at `location`.

    Uses the Open-Meteo archive API. Returns the same per-day shape as the
    forecast tool, flagged as historical observations rather than predictions.
    """
    resolved = resolve_location(location)
    data = _get(ARCHIVE_API, {
        "latitude": resolved["lat"],
        "longitude": resolved["lon"],
        "start_date": date,
        "end_date": date,
        "daily": _DAILY_FIELDS,
        "timezone": "auto",
    })
    daily = data.get("daily", {})
    if not daily.get("time"):
        raise WeatherError(f"No archived weather available for {date} at {resolved['label']}.")

    day = _parse_daily(daily)[0]
    return {
        "location": resolved["label"],
        "latitude": round(resolved["lat"], 4),
        "longitude": round(resolved["lon"], 4),
        "timezone": data.get("timezone", "auto"),
        "date": date,
        "source": "archive (observed)",
        "day": day,
    }


def compare_weather(locations: List[str], days: int = DEFAULT_FORECAST_DAYS) -> Dict:
    """
    Side-by-side forecast for up to 5 locations.

    Returns one forecast entry per location so the agent can compare
    conditions across cities for the same upcoming days.
    """
    if not locations:
        raise WeatherError("Provide at least one location to compare.")
    if len(locations) > MAX_COMPARE_LOCATIONS:
        raise WeatherError(f"Compare at most {MAX_COMPARE_LOCATIONS} locations at once.")
    if days < 1 or days > MAX_FORECAST_DAYS:
        raise WeatherError(f"days must be between 1 and {MAX_FORECAST_DAYS}, got {days}.")

    entries = []
    for raw in locations:
        resolved = resolve_location(raw)
        payload = _fetch_forecast(resolved["lat"], resolved["lon"], days=days)
        entries.append({
            "location": resolved["label"],
            "latitude": round(resolved["lat"], 4),
            "longitude": round(resolved["lon"], 4),
            "forecast": payload["days"],
        })
    return {"days_requested": days, "locations": entries}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_forecast_day(resolved: Dict, date: str) -> Dict:
    """Fetch a 7-day forecast and return the entry for `date`, or a clean error."""
    if not date or len(date) != 10 or date[4] != "-" or date[7] != "-":
        raise WeatherError(
            f"date must be formatted as YYYY-MM-DD, got '{date}'."
        )

    payload = _fetch_forecast(resolved["lat"], resolved["lon"], days=7)
    for day in payload["days"]:
        if day["date"] == date:
            return day

    dates = ", ".join(d["date"] for d in payload["days"])
    raise WeatherError(
        f"{date} is outside the forecast horizon. Data is available for "
        f"the next 7 days: {dates}. (For a past date, use the historical "
        "weather tool instead.)"
    )


def _compose_explanation(verdict: str, reasons: List[str], wind: float) -> str:
    """Human-readable justification for an umbrella verdict."""
    reason_text = "; ".join(reasons)
    if verdict == "yes":
        text = f"Rain looks likely ({reason_text}). Bring an umbrella."
    elif verdict == "maybe":
        text = f"Some chance of rain ({reason_text}). An umbrella is a safe call."
    else:
        text = f"Precipitation is unlikely ({reason_text}). An umbrella probably isn't needed."
    if wind >= UMBRELLA_WIND_GUST_THRESHOLD:
        text += f" Winds up to {wind:.0f} km/h — favor a compact or strong umbrella."
    return text


def _travel_advice(verdict: str, concerns: List[str]) -> str:
    """Plain-language advice for a travel verdict."""
    concern_text = f" Concerns: {'; '.join(concerns)}." if concerns else ""
    base = {
        "excellent": "Great conditions for being outside — no weather-related plans needed.",
        "good": "Generally pleasant. Some minor considerations, but outdoor plans should work.",
        "okay": "Outdoor plans are possible but check the specifics before committing.",
        "poor": "Poor conditions for outdoor plans — consider indoor options or rescheduling.",
    }[verdict]
    return base + concern_text
