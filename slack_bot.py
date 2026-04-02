import asyncio
import os
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from weather import get_alerts, get_forecast, get_hourly_forecast

load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
ANTHROPIC_MODEL_CANDIDATES = os.getenv(
    "ANTHROPIC_MODEL_CANDIDATES",
    "claude-3-7-sonnet-latest,claude-3-5-sonnet-latest,claude-sonnet-4-20250514",
)

if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN or not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "Missing required env vars. Set SLACK_BOT_TOKEN, SLACK_APP_TOKEN, and ANTHROPIC_API_KEY."
    )

SYSTEM_PROMPT = (
    "You are a weather assistant in Slack. "
    "Use available tools for weather data instead of guessing. "
    "Keep responses concise and practical."
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_alerts",
        "description": "Get active weather alerts for a US state (e.g., TX, CA, NY).",
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "description": "Two-letter US state code, e.g. TX",
                }
            },
            "required": ["state"],
        },
    },
    {
        "name": "get_forecast",
        "description": "Get weather forecast for a location by latitude and longitude.",
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_hourly_forecast",
        "description": "Get next 12 hours forecast for a location by latitude and longitude.",
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
            },
            "required": ["latitude", "longitude"],
        },
    },
]

anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)
app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)


def _get_candidate_models() -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in [ANTHROPIC_MODEL, *ANTHROPIC_MODEL_CANDIDATES.split(",")]:
        model = name.strip()
        if model and model not in seen:
            seen.add(model)
            ordered.append(model)
    return ordered


def _is_model_not_found_error(exc: Exception) -> bool:
    message = str(exc)
    return "not_found_error" in message or "model" in message and "404" in message


def _create_with_model_fallback(messages: list[dict[str, Any]]):
    last_error: Exception | None = None
    tried: list[str] = []

    for model_name in _get_candidate_models():
        tried.append(model_name)
        try:
            return anthropic.messages.create(
                model=model_name,
                max_tokens=900,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        except Exception as exc:
            last_error = exc
            if _is_model_not_found_error(exc):
                continue
            raise

    raise RuntimeError(
        f"No accessible Anthropic model found. Tried: {', '.join(tried)}. "
        "Set ANTHROPIC_MODEL in .env to a model available for your account."
    ) from last_error


def run_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    try:
        if tool_name == "get_alerts":
            state = str(tool_input["state"]).upper().strip()
            return asyncio.run(get_alerts(state=state))
        if tool_name == "get_forecast":
            return asyncio.run(
                get_forecast(
                    latitude=float(tool_input["latitude"]),
                    longitude=float(tool_input["longitude"]),
                )
            )
        if tool_name == "get_hourly_forecast":
            return asyncio.run(
                get_hourly_forecast(
                    latitude=float(tool_input["latitude"]),
                    longitude=float(tool_input["longitude"]),
                )
            )
        return f"Unknown tool: {tool_name}"
    except Exception as exc:
        return f"Tool execution error: {exc}"


def ask_claude(user_text: str) -> str:
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_text}]

    for _ in range(5):
        response = _create_with_model_fallback(messages)

        assistant_content: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        final_text_parts: list[str] = []

        for block in response.content:
            if block.type == "text":
                final_text_parts.append(block.text)
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
                tool_output = run_tool(block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": tool_output,
                    }
                )

        if not tool_results:
            return "\n".join(part for part in final_text_parts if part).strip() or "No response."

        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})

    return "I couldn't finish the request after multiple tool calls. Please try again."


def _clean_user_text(raw_text: str, bot_user_id: str | None = None) -> str:
    text = raw_text or ""
    if bot_user_id:
        text = text.replace(f"<@{bot_user_id}>", "")
    return text.strip()


@app.event("app_mention")
def handle_mention(event: dict[str, Any], say, logger) -> None:
    try:
        text = _clean_user_text(event.get("text", ""), app.client.auth_test().get("user_id"))
        if not text:
            say("Ask me about weather alerts or forecasts.", thread_ts=event.get("ts"))
            return
        answer = ask_claude(text)
        say(answer, thread_ts=event.get("ts"))
    except Exception as exc:
        logger.exception("app_mention failed")
        say(f"Error: {exc}", thread_ts=event.get("ts"))


@app.event("message")
def handle_dm(event: dict[str, Any], say, logger) -> None:
    if event.get("channel_type") != "im":
        return
    if event.get("subtype") == "bot_message" or event.get("bot_id"):
        return
    try:
        text = (event.get("text") or "").strip()
        if not text:
            return
        answer = ask_claude(text)
        say(answer, thread_ts=event.get("ts"))
    except Exception as exc:
        logger.exception("dm failed")
        say(f"Error: {exc}", thread_ts=event.get("ts"))


if __name__ == "__main__":
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
