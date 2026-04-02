# Weather MCP Server

A Model Context Protocol (MCP) server that provides real-time US weather alerts and forecasts by integrating with the National Weather Service API. It connects directly to Claude Desktop, enabling Claude to fetch live weather data through natural language requests.

## Demo

![Weather Alerts](assets/alert.jpg)
![Weather Forecast](assets/forecast.jpg)
![Hourly Forecast 1](assets/forecast_hourly_1.jpg)
![Hourly Forecast 2](assets/forecast_hourly_2.jpg)

## Tools

- `get_alerts` — Get active weather alerts for a US state (e.g. `TX`, `CA`)
- `get_forecast` — Get weather forecast for a location by latitude and longitude
- `get_hourly_forecast` — Get hour-by-hour forecast for the next 12 hours by latitude and longitude

## Setup

1. Install [uv](https://docs.astral.sh/uv/)
2. Clone the repo and run `uv sync`
3. Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "weather": {
      "command": "uv",
      "args": ["--directory", "/path/to/weather", "run", "weather.py"]
    }
  }
}
```

## Slack Chatbot Setup

Use this if you want Claude + weather tools inside Slack.

1. In your Slack app, ensure these are enabled:
- Bot scopes: `app_mentions:read`, `chat:write`, `channels:history`, `im:history`
- Events: `app_mention`, `message.im`
- Socket Mode ON with an app-level token (`connections:write`)

2. Create env file from template:

```bash
cp .env.example .env
```

3. Fill `.env` with your real values:
- `SLACK_BOT_TOKEN` (xoxb...)
- `SLACK_APP_TOKEN` (xapp...)
- `SLACK_SIGNING_SECRET`
- `ANTHROPIC_API_KEY`

4. Install dependencies and run:

```bash
uv sync
uv run slack_bot.py
```

5. In Slack:
- Mention the bot in a channel: `@MCP-NWS weather alerts for TX`
- Or DM the bot: `forecast for 37.7749, -122.4194`
