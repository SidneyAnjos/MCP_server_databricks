"""
Tests for weather_broker.py using mocked HTTP responses.

weather_broker resolves locations via the Open-Meteo geocoding API and reads
forecast / archive data from api.open-meteo.com. These tests mock
`requests.get` with realistic Open-Meteo response shapes so the parsing,
WMO-code mapping, and prediction logic can be validated without touching the
network.

Run from the repo root:
    python -m pytest tests/ -v
"""

import sys
import os
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp_server"))

import weather_broker as wb


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TODAY = date(2026, 8, 9)

GEOCODE_RESPONSE = {
    "results": [
        {"name": "Chicago", "latitude": 41.85003, "longitude": -87.65005,
         "admin1": "Illinois", "country_code": "US"}
    ]
}


def _mock_response(json_data, status_code=200):
    resp = type("Resp", (), {})()
    resp.status_code = status_code
    resp.raise_for_status = lambda: None
    resp.json = lambda: json_data
    return resp


def _daily(n=7, start=TODAY, codes=None, probs=None, precip=None,
           tmax=None, tmin=None, wind=None):
    """Build an Open-Meteo `daily` block for n days from `start`."""
    dates = [(start + timedelta(days=i)).isoformat() for i in range(n)]
    default_codes = [0, 2, 61, 3, 1, 82, 63]
    default_probs = [5, 10, 30, 15, 20, 55, 60]
    default_precip = [0.0, 0.0, 0.8, 0.0, 0.1, 6.0, 12.0]
    default_tmax = [29.0, 27.5, 24.0, 26.0, 28.0, 25.0, 23.0]
    default_tmin = [16.0, 18.0, 17.0, 19.0, 20.0, 18.0, 17.0]
    default_wind = [15.0, 20.0, 18.0, 25.0, 30.0, 35.0, 45.0]

    return {
        "time": dates,
        "weather_code": codes or default_codes[:n],
        "temperature_2m_max": tmax or default_tmax[:n],
        "temperature_2m_min": tmin or default_tmin[:n],
        "precipitation_probability_max": probs or default_probs[:n],
        "precipitation_sum": precip or default_precip[:n],
        "wind_speed_10m_max": wind or default_wind[:n],
    }


def _forecast_response(daily, current=None):
    """Wrap a `daily` block in the full Open-Meteo forecast response."""
    if current is None:
        current = {
            "time": "2026-08-09T09:30",
            "temperature_2m": 21.5,
            "relative_humidity_2m": 85,
            "apparent_temperature": 23.1,
            "precipitation": 0.0,
            "weather_code": 2,
            "wind_speed_10m": 11.7,
            "wind_direction_10m": 171,
            "wind_gusts_10m": 24.8,
        }
    return {
        "timezone": "America/Chicago",
        "current": current,
        "daily": daily,
    }


def _patch_forecast(daily, current=None, archive=None, geocode=None):
    """Patch requests.get for forecast (+ optionally archive/geocode) calls."""
    def side_effect(url, **kwargs):
        if url == wb.FORECAST_API:
            return _mock_response(_forecast_response(daily, current))
        if url == wb.ARCHIVE_API:
            return _mock_response(archive or {"timezone": "UTC", "daily": _daily(1)})
        if url == wb.GEOCODING_API:
            return _mock_response(geocode if geocode is not None else GEOCODE_RESPONSE)
        raise AssertionError(f"unexpected URL {url}")
    return patch.object(wb.requests, "get", side_effect=side_effect)


# ---------------------------------------------------------------------------
# Location resolution
# ---------------------------------------------------------------------------

def test_resolve_location_lat_lon_shortcut():
    resolved = wb.resolve_location("41.88, -87.63")
    assert resolved == {"lat": 41.88, "lon": -87.63, "label": "41.88, -87.63"}


def test_resolve_location_empty_raises():
    try:
        wb.resolve_location("   ")
        assert False, "expected WeatherError"
    except wb.WeatherError as e:
        assert "empty" in str(e).lower()


def test_resolve_location_bad_lat_raises():
    try:
        wb.resolve_location("120, -87")
        assert False, "expected WeatherError"
    except wb.WeatherError as e:
        assert "between -90 and 90" in str(e)


def test_resolve_location_geocodes_place_name():
    with patch.object(wb.requests, "get", return_value=_mock_response(GEOCODE_RESPONSE)):
        resolved = wb.resolve_location("Chicago")
    assert resolved["lat"] == 41.85003
    assert resolved["lon"] == -87.65005
    assert resolved["label"] == "Chicago, Illinois, US"


def test_resolve_location_no_match_raises():
    with patch.object(wb.requests, "get", return_value=_mock_response({"results": []})):
        try:
            wb.resolve_location("Nowhereville")
            assert False, "expected WeatherError"
        except wb.WeatherError as e:
            assert "Could not resolve" in str(e)


# ---------------------------------------------------------------------------
# WMO code mapping
# ---------------------------------------------------------------------------

def test_describe_weather_code_known_and_unknown():
    assert wb.describe_weather_code(61) == "Slight rain"
    assert wb.describe_weather_code(0) == "Clear sky"
    assert wb.describe_weather_code(999) == "Code 999"
    assert wb.describe_weather_code(None) == "Unknown"


def test_is_precipitation():
    assert wb._is_precipitation(61) is True   # rain
    assert wb._is_precipitation(95) is True   # thunderstorm
    assert wb._is_precipitation(71) is True   # snow
    assert wb._is_precipitation(0) is False   # clear
    assert wb._is_precipitation(2) is False   # partly cloudy


# ---------------------------------------------------------------------------
# Current weather
# ---------------------------------------------------------------------------

def test_get_current_weather_parses_current_block():
    with _patch_forecast(_daily(1)):
        result = wb.get_current_weather("Chicago")
    assert result["location"] == "Chicago, Illinois, US"
    assert result["condition"] == "Partly cloudy"          # code 2
    assert result["temperature_c"] == 21.5
    assert result["temperature_f"] == 70.7                  # 21.5 -> 70.7
    assert result["relative_humidity_pct"] == 85
    assert result["wind_speed_kmh"] == 11.7


def test_get_current_weather_unknown_location_is_clean_error():
    with _patch_forecast(_daily(1), geocode={"results": []}):
        try:
            wb.get_current_weather("Atlantis")
            assert False, "expected WeatherError"
        except wb.WeatherError as e:
            assert "Could not resolve" in str(e)


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------

def test_get_forecast_parses_daily_entries():
    with _patch_forecast(_daily(3)):
        result = wb.get_forecast("Chicago", days=3)
    assert result["days_requested"] == 3
    assert len(result["forecast"]) == 3
    day0 = result["forecast"][0]
    assert day0["date"] == "2026-08-09"
    assert day0["condition"] == "Clear sky"
    assert day0["temp_max_c"] == 29.0
    assert day0["temp_max_f"] == 84.2
    assert day0["precipitation_probability_pct"] == 5


def test_get_forecast_rejects_out_of_range_days():
    with _patch_forecast(_daily(3)):
        for bad in (0, 17):
            try:
                wb.get_forecast("Chicago", days=bad)
                assert False, f"expected WeatherError for days={bad}"
            except wb.WeatherError as e:
                assert "between 1 and 16" in str(e)


# ---------------------------------------------------------------------------
# Umbrella prediction
# ---------------------------------------------------------------------------

def test_umbrella_yes_when_high_probability():
    # day 1 (index 1, 2026-08-10) has prob 10 -> no; force prob high on day 1
    daily = _daily(7)
    daily["precipitation_probability_max"][1] = 55
    daily["precipitation_sum"][1] = 2.0
    with _patch_forecast(daily):
        result = wb.predict_umbrella_needed("Chicago", "2026-08-10")
    assert result["umbrella_verdict"] == "yes"
    assert "Bring an umbrella" in result["explanation"]


def test_umbrella_yes_when_precipitating_condition_even_with_low_prob():
    daily = _daily(7)
    daily["weather_code"][2] = 61          # slight rain, but prob stays 30
    daily["precipitation_probability_max"][2] = 5
    daily["precipitation_sum"][2] = 0.0
    with _patch_forecast(daily):
        result = wb.predict_umbrella_needed("Chicago", "2026-08-11")
    assert result["umbrella_verdict"] == "yes"


def test_umbrella_maybe_for_moderate_chance():
    daily = _daily(7)
    daily["precipitation_probability_max"][3] = 30
    daily["precipitation_sum"][3] = 0.0
    daily["weather_code"][3] = 3           # overcast, non-precipitating
    with _patch_forecast(daily):
        result = wb.predict_umbrella_needed("Chicago", "2026-08-12")
    assert result["umbrella_verdict"] == "maybe"


def test_umbrella_no_when_low_probability():
    daily = _daily(7)
    daily["precipitation_probability_max"][4] = 5
    daily["precipitation_sum"][4] = 0.0
    daily["weather_code"][4] = 1
    with _patch_forecast(daily):
        result = wb.predict_umbrella_needed("Chicago", "2026-08-13")
    assert result["umbrella_verdict"] == "no"
    assert "isn't needed" in result["explanation"]


def test_umbrella_strong_wind_adds_caveat():
    daily = _daily(7)
    daily["precipitation_probability_max"][1] = 55
    daily["wind_speed_10m_max"][1] = 60
    with _patch_forecast(daily):
        result = wb.predict_umbrella_needed("Chicago", "2026-08-10")
    assert "compact or strong umbrella" in result["explanation"]


def test_umbrella_bad_date_format_raises():
    with _patch_forecast(_daily(7)):
        try:
            wb.predict_umbrella_needed("Chicago", "10/08/2026")
            assert False, "expected WeatherError"
        except wb.WeatherError as e:
            assert "YYYY-MM-DD" in str(e)


def test_umbrella_date_outside_window_raises():
    with _patch_forecast(_daily(7)):
        try:
            wb.predict_umbrella_needed("Chicago", "2026-09-01")
            assert False, "expected WeatherError"
        except wb.WeatherError as e:
            assert "forecast horizon" in str(e)


# ---------------------------------------------------------------------------
# Travel recommendation
# ---------------------------------------------------------------------------

def test_travel_excellent_day():
    daily = _daily(7)
    daily["temperature_2m_max"][0] = 22.0
    daily["precipitation_probability_max"][0] = 5
    daily["precipitation_sum"][0] = 0.0
    daily["wind_speed_10m_max"][0] = 10.0
    with _patch_forecast(daily):
        result = wb.get_travel_recommendation("Chicago", "2026-08-09")
    assert result["verdict"] == "excellent"
    assert result["comfort_score"] == 100


def test_travel_hot_day_flags_heat():
    daily = _daily(7)
    daily["temperature_2m_max"][0] = 38.0
    with _patch_forecast(daily):
        result = wb.get_travel_recommendation("Chicago", "2026-08-09")
    assert result["verdict"] == "good"       # 100 - 25 (hot) = 75
    assert any("hot" in c for c in result["concerns"])


def test_travel_poor_day_rain_and_wind():
    daily = _daily(7)
    daily["temperature_2m_max"][0] = 24.0
    daily["precipitation_probability_max"][0] = 95
    daily["precipitation_sum"][0] = 30.0
    daily["wind_speed_10m_max"][0] = 60.0
    with _patch_forecast(daily):
        result = wb.get_travel_recommendation("Chicago", "2026-08-09")
    assert result["verdict"] == "okay"       # 100 - 30 (rain) - 20 (wind) = 50
    assert result["comfort_score"] == 50


# ---------------------------------------------------------------------------
# Historical weather
# ---------------------------------------------------------------------------

def test_get_historical_weather_parses_archive():
    archive = {
        "timezone": "UTC",
        "daily": {
            "time": ["2026-08-07"],
            "weather_code": [51],
            "temperature_2m_max": [28.3],
            "temperature_2m_min": [20.5],
            "precipitation_probability_max": [40],
            "precipitation_sum": [0.7],
            "wind_speed_10m_max": [11.2],
        },
    }
    with _patch_forecast(_daily(1), archive=archive):
        result = wb.get_historical_weather("Chicago", "2026-08-07")
    assert result["source"] == "archive (observed)"
    assert result["date"] == "2026-08-07"
    assert result["day"]["condition"] == "Light drizzle"
    assert result["day"]["temp_max_c"] == 28.3


def test_get_historical_weather_empty_archive_raises():
    with _patch_forecast(_daily(1), archive={"timezone": "UTC", "daily": {"time": []}}):
        try:
            wb.get_historical_weather("Chicago", "2026-08-07")
            assert False, "expected WeatherError"
        except wb.WeatherError as e:
            assert "No archived weather" in str(e)


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

def test_compare_weather_multiple_locations():
    with _patch_forecast(_daily(1)):
        result = wb.compare_weather(["Chicago", "Austin"], days=1)
    assert result["days_requested"] == 1
    assert len(result["locations"]) == 2
    assert result["locations"][0]["location"] == "Chicago, Illinois, US"


def test_compare_weather_rejects_too_many_locations():
    with _patch_forecast(_daily(1)):
        try:
            wb.compare_weather(["A", "B", "C", "D", "E", "F"], days=1)
            assert False, "expected WeatherError"
        except wb.WeatherError as e:
            assert "at most 5" in str(e)


def test_compare_weather_rejects_empty_list():
    with _patch_forecast(_daily(1)):
        try:
            wb.compare_weather([], days=1)
            assert False, "expected WeatherError"
        except wb.WeatherError as e:
            assert "at least one location" in str(e)


# ---------------------------------------------------------------------------
# HTTP error handling
# ---------------------------------------------------------------------------

def test_http_non_200_raises_clean_error():
    with patch.object(wb.requests, "get", return_value=_mock_response({}, status_code=500)):
        try:
            wb.get_forecast("Chicago", days=3)
            assert False, "expected WeatherError"
        except wb.WeatherError as e:
            assert "HTTP 500" in str(e)


def test_network_error_raises_clean_error():
    def boom(url, **kwargs):
        raise wb.requests.RequestException("connection refused")
    with patch.object(wb.requests, "get", side_effect=boom):
        try:
            wb.get_current_weather("Chicago")
            assert False, "expected WeatherError"
        except wb.WeatherError as e:
            assert "Could not reach the weather service" in str(e)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
