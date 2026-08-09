"""
dashboard/app.py -- Weather Intelligence dashboard (stretch).

A small Streamlit app that mirrors the Weather MCP Server's tools so anyone
with access to the Databricks App can explore the same data the agent uses:

  * Current conditions for a location
  * Multi-day forecast table
  * Umbrella verdict + travel recommendation per day (the same prediction
    logic the agent's tools apply)
  * A session-scoped query log (the "recent queries" view)

The dashboard re-imports `weather_broker` from the same folder: Databricks
Apps deploy each app folder independently, so this app ships its own copy of
the adapter module rather than importing across apps.

Data source: Open-Meteo (free, no API key).
"""

import json

import streamlit as st

import weather_broker as wb

st.set_page_config(page_title="Weather Intelligence", page_icon="🌦️", layout="wide")


# ---------------------------------------------------------------------------
# Cached broker calls (cache so repeated interactions don't re-hit the API)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=600, show_spinner=False)
def current_for(location: str) -> dict:
    return wb.get_current_weather(location)


@st.cache_data(ttl=600, show_spinner=False)
def forecast_for(location: str, days: int) -> dict:
    return wb.get_forecast(location, days)


@st.cache_data(ttl=600, show_spinner=False)
def umbrella_for(location: str, date: str) -> dict:
    return wb.predict_umbrella_needed(location, date)


@st.cache_data(ttl=600, show_spinner=False)
def travel_for(location: str, date: str) -> dict:
    return wb.get_travel_recommendation(location, date)


# ---------------------------------------------------------------------------
# Session-scoped query log
# ---------------------------------------------------------------------------

def log_query(question: str, summary: str) -> None:
    entry = {"question": question, "summary": summary}
    if "query_log" not in st.session_state:
        st.session_state.query_log = []
    st.session_state.query_log.insert(0, entry)
    st.session_state.query_log = st.session_state.query_log[:50]


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.title("🌦️ Weather Intelligence")
st.caption("Explorer for the Weather MCP Server — same data and prediction "
           "logic the agent uses, powered by Open-Meteo (no API key).")

with st.sidebar:
    st.header("Location")
    location = st.text_input("City or `lat,lon`", value="Chicago, IL",
                             help="e.g. 'Austin, Texas', 'São Paulo, Brazil', or '41.88,-87.63'")
    days = st.slider("Forecast days", 1, 16, 7)
    go = st.button("Run", type="primary", use_container_width=True)
    st.caption("Select a question to log it as a demo query:")

    sample_question = st.selectbox(
        "Sample query", [
            "Will it rain in Chicago tomorrow?",
            "Should I bring a jacket to Austin this weekend?",
            "Is it a good day for a picnic in Seattle?",
        ], index=None, placeholder="Choose an example..."
    )
    if sample_question and go:
        log_query(sample_question, f"Asked about '{location}'")

if not go:
    st.info("Enter a location and click **Run** to load current conditions, "
            "the forecast, and the agent's prediction logic.")
    st.stop()

# --- current conditions -----------------------------------------------------
st.subheader("Current conditions")
try:
    cur = current_for(location)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Temperature", f"{cur['temperature_c']} °C", f"{cur['temperature_f']} °F")
    c2.metric("Condition", cur["condition"])
    c3.metric("Humidity", f"{cur['relative_humidity_pct']} %")
    c4.metric("Precipitation", f"{cur['precipitation_mm']} mm")
    c5.metric("Wind", f"{cur['wind_speed_kmh']} km/h")
    st.caption(f"{cur['location']} · observed {cur['observed_at']} ({cur['timezone']})")
    log_query(f"Current weather in {location}", f"{cur['condition']}, {cur['temperature_c']} °C")
except wb.WeatherError as exc:
    st.error(f"Could not load current conditions: {exc}")
    st.stop()

# --- forecast + predictions -------------------------------------------------
st.subheader(f"Forecast for the next {days} days")
try:
    fc = forecast_for(location, days)
    rows = []
    for day in fc["forecast"]:
        umb = umbrella_for(location, day["date"])
        trv = travel_for(location, day["date"])
        rows.append({
            "date": day["date"],
            "condition": day["condition"],
            "high_c": f"{day['temp_max_c']} °C",
            "low_c": f"{day['temp_min_c']} °C",
            "rain_chance": f"{day['precipitation_probability_pct']} %",
            "rain_mm": f"{day['precipitation_mm']} mm",
            "wind": f"{day['wind_max_kmh']} km/h",
            "umbrella": umb["umbrella_verdict"],
            "travel": f"{trv['verdict']} ({trv['comfort_score']})",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.caption("Prediction rules (same as the MCP tools): umbrella **yes** when "
               "rain chance ≥ 40% or ≥ 0.5 mm expected; travel score 0–100 from "
               "temperature, rain, and wind.")
except wb.WeatherError as exc:
    st.error(f"Could not load the forecast: {exc}")
    st.stop()

# --- recent queries ----------------------------------------------------------
st.subheader("Recent queries")
if st.session_state.get("query_log"):
    for entry in st.session_state.query_log:
        st.markdown(f"- **{entry['question']}** → {entry['summary']}")
else:
    st.caption("No queries logged yet this session.")

st.divider()
st.caption(json.dumps({"location": location, "days": days,
                       "resolved": fc.get("location"), "source": "Open-Meteo"},
                      ensure_ascii=False))
