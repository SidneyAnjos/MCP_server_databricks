# Weather MCP Server — tool catalog

The Agent Bricks agent discovers these six tools automatically when the Weather
MCP Server is connected as an external MCP server. The `inputJsonSchema` values
below are exactly what FastMCP advertises (`tools/list`); they are included here
as the submission's tool manifest and for manual registration / review.

All tools return **JSON text**. On failure they return `{"error": "<message>"}`
instead of raising — the agent must check for the `error` key and never guess.

Data source: **Open-Meteo** (no API key). Temperatures are reported in °C with
°F equivalents for daily extremes and current conditions.

---

## 1. `get_current_weather(location)`

Current observed conditions for a location.

```json
{
  "inputJsonSchema": {
    "type": "object",
    "properties": { "location": { "type": "string" } },
    "required": ["location"]
  }
}
```

`location` — city name (`"Chicago"`, `"Chicago, IL"`, `"Austin, Texas"`) or a
numeric `"lat,lon"` pair (`"41.88,-87.63"`).

Returns: temperature (°C/°F), apparent temperature, condition, relative
humidity, precipitation (mm), wind speed/direction/gusts, observed time, and
the resolved location label.

## 2. `get_forecast(location, days=3)`

Multi-day outlook.

```json
{
  "inputJsonSchema": {
    "type": "object",
    "properties": {
      "location": { "type": "string" },
      "days": { "type": "integer", "default": 3 }
    },
    "required": ["location"]
  }
}
```

`days` — 1 to 16 (Open-Meteo ceiling). Returns one entry per day: high/low
temp (°C/°F), precipitation chance (%), expected precipitation (mm), max wind
(km/h), and a plain-language condition.

## 3. `predict_umbrella_needed(location, date)`

Umbrella verdict for a specific date.

```json
{
  "inputJsonSchema": {
    "type": "object",
    "properties": {
      "location": { "type": "string" },
      "date": { "type": "string" }
    },
    "required": ["location", "date"]
  }
}
```

`date` — `YYYY-MM-DD` within the next **7 days** (the tool's forecast window).

Decision rule (documented in the tool docstring):
- **yes** — precipitation chance ≥ 40% OR expected rain ≥ 0.5 mm OR the day's
  condition is a precipitating WMO code.
- **maybe** — chance ≥ 20%.
- **no** — otherwise.
- Wind ≥ 40 km/h adds a "compact/strong umbrella" caveat.

Returns the verdict, the inputs that drove it, and a plain-language explanation.

## 4. `get_travel_recommendation(location, date)`

Outdoor-plan recommendation for a date.

```json
{
  "inputJsonSchema": {
    "type": "object",
    "properties": {
      "location": { "type": "string" },
      "date": { "type": "string" }
    },
    "required": ["location", "date"]
  }
}
```

`date` — `YYYY-MM-DD` within the next **7 days**.

Scores the day 0–100 from temperature (18–28 °C ideal), rain chance/amount,
and wind:
- ≥ 90 → `excellent` · ≥ 70 → `good` · ≥ 45 → `okay` · else → `poor`

Returns the comfort score, verdict, the specific concerns (heat, cold, rain,
wind) that reduced the score, and advice.

## 5. `get_historical_weather(location, date)`

Observed weather for a single past date.

```json
{
  "inputJsonSchema": {
    "type": "object",
    "properties": {
      "location": { "type": "string" },
      "date": { "type": "string" }
    },
    "required": ["location", "date"]
  }
}
```

`date` — any past `YYYY-MM-DD` (Open-Meteo archive). Returns the same per-day
shape as the forecast tool, flagged `"source": "archive (observed)"`.

## 6. `compare_weather(locations, days=3)`

Side-by-side forecast for up to 5 locations.

```json
{
  "inputJsonSchema": {
    "type": "object",
    "properties": {
      "locations": { "type": "array", "items": { "type": "string" } },
      "days": { "type": "integer", "default": 3 }
    },
    "required": ["locations"]
  }
}
```

Returns one `{location, forecast: [...]}` entry per input location.
