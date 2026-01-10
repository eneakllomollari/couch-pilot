"""Smart Home Chat Agent - FastAPI Application with Claude Agent SDK."""

import json
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

import structlog
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import get_config
from devices.tapo import TapoBulb
from logging_config import setup_logging
from tools.tv_tools import tv_server

# Configure structured logging
setup_logging()
log = structlog.get_logger(__name__)


# =============================================================================
# Response Models
# =============================================================================


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(description="Health status")


class StatusResponse(BaseModel):
    """TV status response."""

    status: str = Field(description="Human-readable TV status message")


class CommandResponse(BaseModel):
    """Generic command response."""

    ok: bool = Field(description="Whether the command succeeded")
    error: str | None = Field(default=None, description="Error message if failed")


class AppInfo(BaseModel):
    """Streaming app information."""

    package: str = Field(description="Package name")
    name: str = Field(description="Display name")
    logo: str | None = Field(default=None, description="Logo URL")
    color: str | None = Field(default=None, description="Fallback color")


class AppsResponse(BaseModel):
    """List of installed apps response."""

    apps: list[AppInfo] = Field(default_factory=list, description="List of streaming apps")
    error: str | None = Field(default=None, description="Error message if failed")
    configured: bool = Field(default=True, description="Whether device is configured")


class BulbStateResponse(BaseModel):
    """Bulb state response."""

    device: str = Field(description="Device ID")
    state: dict[str, Any] = Field(description="Current bulb state")
    error: str | None = Field(default=None, description="Error message if failed")


class BulbToggleResponse(BaseModel):
    """Bulb toggle response."""

    ok: bool = Field(description="Whether the command succeeded")
    state: str | None = Field(default=None, description="New state (on/off)")
    error: str | None = Field(default=None, description="Error message if failed")


def build_system_prompt() -> str:
    """Build the system prompt for the Claude agent.

    Constructs a detailed system prompt that includes:
    - List of available TV devices with connection info
    - Netflix URL format requirements (must use netflix:// protocol)
    - HBO Max and Apple TV+ deep linking rules
    - Required workflow steps for verifying playback
    - Available tools and device selection instructions

    Returns:
        Complete system prompt string for configuring Claude's behavior.
    """
    config = get_config()
    tv_list = "\n".join(
        f"- {dev_id}{' (default)' if i == 0 else ''}: {tv.name} at {tv.ip}:{tv.port}"
        for i, (dev_id, tv) in enumerate(config.tv_devices.items())
    )
    return f"""You control TVs via ADB.

AVAILABLE TVs:
{tv_list}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚨 MANDATORY URL FORMAT FOR NETFLIX - DO NOT USE WEB URLS! 🚨
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ CORRECT: play(device, "netflix://title/80057281")
❌ WRONG:   play(device, "https://www.netflix.com/title/80057281")

Netflix Title IDs:
- Stranger Things: 80057281
- Wednesday: 81231974
- Squid Game: 81040344
- The Crown: 80025678

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MAX / HBO MAX DEEP LINK RULES (Fire TV)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Preferred: https://play.max.com/movie/<uuid>  OR  https://play.max.com/show/<uuid>
✅ Also OK (tool normalizes): https://www.hbomax.com/movies/<slug>/<uuid>
✅ Also OK (tool normalizes): https://www.hbomax.com/series/urn:hbo:series:<uuid>
❌ Avoid: www.hbomax.com links without a UUID (won't deep link)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
APPLE TV+ DEEP LINK RULES (Fire TV)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Use tv.apple.com show/movie pages that include a stable content id:
   - https://tv.apple.com/us/show/<slug>/<umc.cmc.*>
   - https://tv.apple.com/show/<umc.cmc.*>  (tool canonicalizes)
✅ If user says "play <AppleTV show>" and you don't have the URL:
   - Use WebSearch to find the OFFICIAL tv.apple.com URL containing the umc.cmc.* id
   - Then call play(device, that_url)
❌ Do NOT rely on in-app search navigation for Apple TV / Netflix / Max.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REQUIRED WORKFLOW - YOU MUST FOLLOW ALL STEPS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1: play(device, "netflix://title/ID")
Step 2: get_tv_status(device) ← REQUIRED! Check playback state
Step 3: If playback != "playing":
        - screenshot(device)
        - Read /tmp/tv_screenshot_<device>.png
        - navigate(device, "select") or navigate as needed
        - Go to Step 2
Step 4: Only say "Done" when get_tv_status shows playback=playing

IMPORTANT:
- screenshots can fail on DRM/secure video; if screenshot fails, continue using get_tv_status + navigate
- For Max/Apple TV, you may need to press select once after deep linking

Tools: play, get_tv_status, screenshot, navigate (up/down/left/right/select/back/home),
       play_pause, turn_on, turn_off, volume, type_text, list_apps, WebSearch, Read, Bash

DEVICE SELECTION:
- User messages are prefixed with [Target device: X] indicating which TV to control
- ALWAYS use the device specified in the prefix unless user explicitly mentions another device
- Example: "[Target device: google_tv] play Netflix" → use google_tv

DO NOT report success without calling get_tv_status first!"""


app = FastAPI(title="Smart Home Chat Agent")


@app.on_event("startup")
async def startup_event() -> None:
    """Validate configuration and log status at startup."""
    config = get_config()
    config.log_config_status()


static_path = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/", response_class=HTMLResponse)
async def chat_page():
    return FileResponse(Path(__file__).parent / "templates" / "chat.html")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Configure Claude Agent SDK - only TV tools + Bash
    options = ClaudeAgentOptions(
        mcp_servers={"tv-control": tv_server},
        allowed_tools=[
            # Our custom TV tools
            "mcp__tv-control__play",
            "mcp__tv-control__navigate",
            "mcp__tv-control__play_pause",
            "mcp__tv-control__turn_on",
            "mcp__tv-control__turn_off",
            "mcp__tv-control__volume",
            "mcp__tv-control__screenshot",
            "mcp__tv-control__type_text",
            "mcp__tv-control__get_tv_status",
            "mcp__tv-control__list_apps",
            "mcp__tv-control__list_tvs",
            # Bash for raw ADB commands
            "Bash",
            # Read for viewing screenshots
            "Read",
            # WebSearch to find YouTube video URLs
            "WebSearch",
        ],
        permission_mode="acceptEdits",
        system_prompt=build_system_prompt(),
    )

    try:
        log.info("NEW SESSION - Client connected")
        async with ClaudeSDKClient(options=options) as client:
            log.info("Claude Agent SDK initialized")

            # Build dynamic welcome message with TV status
            config = get_config()
            if config.tv_devices:
                default_device_id = next(iter(config.tv_devices.keys()))
                welcome = _get_tv_status_message(default_device_id)
            else:
                welcome = "No TVs configured. Add TV_DEVICES to your .env file."

            await websocket.send_json({"type": "assistant", "content": welcome})

            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                user_text = msg.get("content", "").strip()
                selected_device = msg.get("device", "fire_tv")

                if not user_text:
                    continue

                # Prepend device context so agent uses the selected TV by default
                query_text = f"[Target device: {selected_device}] {user_text}"

                log.info(f"{'=' * 60}")
                log.info(f"USER ({selected_device}): {user_text}")
                log.info(f"{'=' * 60}")
                await websocket.send_json({"type": "typing", "content": True})

                try:
                    start_time = time.time()

                    # Query Claude with device context
                    await client.query(query_text)

                    # Collect response
                    response_text = ""
                    tool_count = 0
                    pending_tools = {}  # tool_use_id -> (name, args, start_time)

                    async for message in client.receive_response():
                        if isinstance(message, AssistantMessage):
                            for block in message.content:
                                if isinstance(block, TextBlock):
                                    response_text += block.text
                                elif isinstance(block, ToolUseBlock):
                                    tool_count += 1
                                    tool_name = block.name.replace("mcp__tv-control__", "")
                                    args_str = (
                                        json.dumps(block.input) if hasattr(block, "input") else "{}"
                                    )
                                    log.info(f"  TOOL #{tool_count}: {tool_name}")
                                    log.info(f"    args: {args_str}")

                                    # Track pending tool for result logging
                                    if hasattr(block, "id"):
                                        pending_tools[block.id] = (
                                            tool_name,
                                            block.input,
                                            time.time(),
                                        )

                                    # Send user-friendly status updates
                                    status_map = {
                                        "WebSearch": "Searching...",
                                        "play": "Starting playback...",
                                        "get_tv_status": "Checking status...",
                                        "screenshot": "Taking screenshot...",
                                        "navigate": "Navigating...",
                                        "turn_on": "Turning on...",
                                        "turn_off": "Turning off...",
                                        "volume": "Adjusting volume...",
                                        "list_apps": "Checking apps...",
                                    }
                                    status = status_map.get(tool_name)
                                    if status:
                                        await websocket.send_json(
                                            {
                                                "type": "status",
                                                "content": status,
                                            }
                                        )
                                elif isinstance(block, ToolResultBlock):
                                    # Handle tool results that come in AssistantMessage
                                    tool_id = getattr(block, "tool_use_id", None)
                                    tool_info = (
                                        pending_tools.pop(tool_id, None) if tool_id else None
                                    )
                                    tool_name = tool_info[0] if tool_info else "unknown"
                                    tool_duration = (
                                        f"{time.time() - tool_info[2]:.1f}s" if tool_info else ""
                                    )

                                    # Extract result text from ToolResultBlock.content
                                    result_text = ""
                                    if hasattr(block, "content"):
                                        if isinstance(block.content, str):
                                            result_text = block.content
                                        elif isinstance(block.content, list):
                                            for item in block.content:
                                                if hasattr(item, "text"):
                                                    result_text += str(item.text)
                                                elif isinstance(item, str):
                                                    result_text += item

                                    # Log result (truncate if long)
                                    is_error = getattr(block, "is_error", False)
                                    status_icon = "FAIL" if is_error else "OK"
                                    log.info(f"    -> {status_icon} ({tool_duration})")

                                    # Log result content (first 200 chars)
                                    if result_text:
                                        preview = result_text[:200].replace("\n", " ")
                                        if len(result_text) > 200:
                                            preview += "..."
                                        log.info(f"    result: {preview}")

                        elif isinstance(message, ResultMessage):
                            # ResultMessage is a summary message about the entire query result
                            # It has 'result', 'is_error', 'duration_ms', etc. but not tool-specific results
                            # Tool results come as ToolResultBlock in AssistantMessage.content
                            # Just log the summary if needed
                            if hasattr(message, "result") and message.result:
                                log.info(
                                    f"  Final result: {message.result[:100] if len(message.result) > 100 else message.result}"
                                )
                            if hasattr(message, "is_error") and message.is_error:
                                log.warning("  Query had errors")

                    elapsed = time.time() - start_time

                    if response_text:
                        log.info(f"  RESPONSE ({elapsed:.1f}s, {tool_count} tools):")
                        for line in response_text.strip().split("\n")[:5]:
                            log.info(f"    {line[:80]}")
                        await websocket.send_json(
                            {
                                "type": "assistant",
                                "content": response_text,
                            }
                        )

                except Exception as e:
                    log.error(f"  ERROR: {e}")
                    await websocket.send_json(
                        {
                            "type": "error",
                            "content": f"Error: {str(e)}",
                        }
                    )

                await websocket.send_json({"type": "typing", "content": False})

    except WebSocketDisconnect:
        log.info("SESSION ENDED - Client disconnected")


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok")


@app.get("/api/remote/status/{device}", response_model=StatusResponse)
async def remote_status(device: str) -> StatusResponse:
    """Get TV status message for display."""
    return StatusResponse(status=_get_tv_status_message(device))


# =============================================================================
# Direct Remote API - Fast, no AI
# =============================================================================


class RemoteCommand(BaseModel):
    device: str
    action: str | None = None


def _get_device_addr(device: str) -> str:
    """Get device address from device ID."""
    config = get_config()
    tv = config.tv_devices.get(device)
    if not tv:
        raise ValueError(f"Unknown device: {device}")
    return f"{tv.ip}:{tv.port}"


def _adb(device: str, *args: str) -> tuple[str, str, int]:
    """Run ADB command and return (stdout, stderr, returncode)."""
    addr = _get_device_addr(device)
    cmd = ["adb", "-s", addr, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return result.stdout, result.stderr, result.returncode


# Package name to friendly app name mapping
APP_NAMES = {
    "com.netflix.ninja": "Netflix",
    "com.netflix.mediaclient": "Netflix",
    "com.google.android.youtube.tv": "YouTube",
    "com.amazon.firetv.youtube": "YouTube",
    "com.disney.disneyplus": "Disney+",
    "com.amazon.avod": "Prime Video",
    "com.hulu.plus": "Hulu",
    "com.hulu.livingroomplus": "Hulu",
    "com.apple.atve.amazon.appletv": "Apple TV",
    "com.apple.atve.androidtv.appletv": "Apple TV",
    "com.hbo.hbonow": "Max",
    "com.wbd.stream": "Max",
    "com.peacocktv.peacockandroid": "Peacock",
    "com.peacock.peacockfiretv": "Peacock",
    "com.cbs.ott": "Paramount+",
    "com.spotify.tv.android": "Spotify",
    "com.plexapp.android": "Plex",
    "tv.twitch.android.app": "Twitch",
    "com.amazon.tv.launcher": "Home",
    "com.google.android.tvlauncher": "Home",
    "com.amazon.firetv.settings": "Settings",
}


def _get_tv_status_message(device_id: str) -> str:
    """Get a human-readable TV status message.

    Queries the TV via ADB to determine:
    - Power/wakefulness state (on/off/screensaver)
    - Current foreground app (Netflix, YouTube, etc.)
    - Playback state (playing/paused)
    - Currently playing media title (if available)

    Args:
        device_id: The device identifier from config.

    Returns:
        Human-readable status string like:
        - "Living Room TV: Playing Stranger Things"
        - "Living Room TV: Netflix"
        - "Living Room TV is off."
        - "Living Room TV is not responding." (on timeout)
    """
    config = get_config()
    tv = config.tv_devices.get(device_id)
    if not tv:
        return "No TV configured."

    try:
        # Get power state, current app, and media info
        cmd = (
            "dumpsys power | grep mWakefulness || true; "
            "dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp' || true; "
            "dumpsys media_session | grep -E 'state=PlaybackState|metadata:' || true"
        )
        stdout, _, _ = _adb(device_id, "shell", cmd)

        # Check if we got any output (ADB connected)
        if not stdout.strip():
            return f"{tv.name} is offline."

        screen_on = False
        current_app = None
        playback_state = None  # None, "playing", "paused"
        media_title = None

        for line in stdout.split("\n"):
            line = line.strip()
            if "mWakefulness=" in line:
                screen_on = "Awake" in line
            elif "mCurrentFocus" in line or "mFocusedApp" in line:
                for part in line.split():
                    if "/" in part and "." in part:
                        pkg = part.strip("{})/").split("/")[0]
                        current_app = APP_NAMES.get(pkg, pkg.split(".")[-1].title())
                        break
            elif "state=PlaybackState" in line:
                if "state=3" in line:  # Playing
                    playback_state = "playing"
                elif "state=2" in line:  # Paused
                    playback_state = "paused"
            elif "metadata:" in line and "description=" in line:
                # Extract title from metadata: size=X, description=Title, Subtitle, ...
                try:
                    desc_part = line.split("description=")[1]
                    title = desc_part.split(",")[0].strip()
                    if title and title.lower() != "null":
                        media_title = title
                except (IndexError, AttributeError):
                    pass

        if not screen_on:
            return f"{tv.name} is off."

        # Build status message
        if playback_state == "playing" and media_title:
            return f"{tv.name}: Playing {media_title}"
        elif playback_state == "paused" and media_title:
            return f"{tv.name}: {media_title} (paused)"
        elif playback_state == "playing" and current_app:
            return f"{tv.name}: Playing on {current_app}"
        elif current_app and current_app != "Home":
            return f"{tv.name}: {current_app}"
        else:
            return f"{tv.name} is on."

    except subprocess.TimeoutExpired:
        log.warning("TV status check timed out", device=device_id, ip=tv.ip)
        return f"{tv.name} is not responding."
    except subprocess.SubprocessError as e:
        log.warning("ADB command failed", device=device_id, error=str(e))
        return f"{tv.name} connection failed."
    except Exception as e:
        log.error(
            "Unexpected error getting TV status",
            device=device_id,
            error=str(e),
            traceback=traceback.format_exc(),
        )
        return f"{tv.name} status unavailable."


@app.post("/api/remote/navigate", response_model=CommandResponse)
async def remote_navigate(cmd: RemoteCommand) -> CommandResponse:
    """Navigate: up, down, left, right, select, back, home."""
    key_map = {
        "up": "KEYCODE_DPAD_UP",
        "down": "KEYCODE_DPAD_DOWN",
        "left": "KEYCODE_DPAD_LEFT",
        "right": "KEYCODE_DPAD_RIGHT",
        "select": "KEYCODE_DPAD_CENTER",
        "back": "KEYCODE_BACK",
        "home": "KEYCODE_HOME",
    }
    keycode = key_map.get(cmd.action)
    if not keycode:
        return CommandResponse(ok=False, error=f"Unknown action: {cmd.action}")

    stdout, stderr, rc = _adb(cmd.device, "shell", "input", "keyevent", keycode)
    log.info("Remote navigate", device=cmd.device, action=cmd.action)
    return CommandResponse(ok=rc == 0, error=stderr if rc != 0 else None)


@app.post("/api/remote/play_pause", response_model=CommandResponse)
async def remote_play_pause(cmd: RemoteCommand) -> CommandResponse:
    """Toggle play/pause."""
    stdout, stderr, rc = _adb(cmd.device, "shell", "input", "keyevent", "KEYCODE_MEDIA_PLAY_PAUSE")
    log.info("Remote play_pause", device=cmd.device)
    return CommandResponse(ok=rc == 0, error=stderr if rc != 0 else None)


@app.post("/api/remote/power", response_model=CommandResponse)
async def remote_power(cmd: RemoteCommand) -> CommandResponse:
    """Toggle power."""
    stdout, stderr, rc = _adb(cmd.device, "shell", "input", "keyevent", "KEYCODE_POWER")
    log.info("Remote power", device=cmd.device)
    return CommandResponse(ok=rc == 0, error=stderr if rc != 0 else None)


@app.post("/api/remote/volume", response_model=CommandResponse)
async def remote_volume(cmd: RemoteCommand) -> CommandResponse:
    """Volume: up, down, mute."""
    key_map = {
        "up": "KEYCODE_VOLUME_UP",
        "down": "KEYCODE_VOLUME_DOWN",
        "mute": "KEYCODE_VOLUME_MUTE",
    }
    keycode = key_map.get(cmd.action)
    if not keycode:
        return CommandResponse(ok=False, error=f"Unknown action: {cmd.action}")

    stdout, stderr, rc = _adb(cmd.device, "shell", "input", "keyevent", keycode)
    log.info("Remote volume", device=cmd.device, action=cmd.action)
    return CommandResponse(ok=rc == 0, error=stderr if rc != 0 else None)


@app.get("/api/remote/apps/{device}", response_model=AppsResponse)
async def remote_list_apps(device: str) -> AppsResponse:
    """List streaming apps installed on device."""
    # Using simple-icons.org CDN for consistent logos
    streaming_apps = {
        # Netflix
        "com.netflix.ninja": {
            "name": "Netflix",
            "logo": "https://cdn.simpleicons.org/netflix/E50914",
        },
        "com.netflix.mediaclient": {
            "name": "Netflix",
            "logo": "https://cdn.simpleicons.org/netflix/E50914",
        },
        # YouTube
        "com.google.android.youtube.tv": {
            "name": "YouTube",
            "logo": "https://cdn.simpleicons.org/youtube/FF0000",
        },
        "com.amazon.firetv.youtube": {
            "name": "YouTube",
            "logo": "https://cdn.simpleicons.org/youtube/FF0000",
        },
        "com.google.android.youtube.tvkids": {
            "name": "YT Kids",
            "logo": "https://cdn.simpleicons.org/youtubekids/FF0000",
        },
        # Disney+
        "com.disney.disneyplus": {
            "name": "Disney+",
            "logo": "https://cdn.simpleicons.org/disneyplus/113CCF",
        },
        # Prime Video
        "com.amazon.avod": {
            "name": "Prime",
            "logo": "https://cdn.simpleicons.org/primevideo/00A8E1",
        },
        "com.amazon.avod.thirdpartyclient": {
            "name": "Prime",
            "logo": "https://cdn.simpleicons.org/primevideo/00A8E1",
        },
        # Hulu
        "com.hulu.plus": {
            "name": "Hulu",
            "logo": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect fill='%231CE783' width='24' height='24' rx='4'/%3E%3Ctext x='12' y='17' text-anchor='middle' fill='%23000' font-family='Arial,sans-serif' font-weight='bold' font-size='12'%3Ehulu%3C/text%3E%3C/svg%3E",
        },
        "com.hulu.livingroomplus": {
            "name": "Hulu",
            "logo": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect fill='%231CE783' width='24' height='24' rx='4'/%3E%3Ctext x='12' y='17' text-anchor='middle' fill='%23000' font-family='Arial,sans-serif' font-weight='bold' font-size='12'%3Ehulu%3C/text%3E%3C/svg%3E",
        },
        # Apple TV
        "com.apple.atve.amazon.appletv": {
            "name": "Apple TV",
            "logo": "https://cdn.simpleicons.org/appletv/ffffff",
        },
        "com.apple.atve.androidtv.appletv": {
            "name": "Apple TV",
            "logo": "https://cdn.simpleicons.org/appletv/ffffff",
        },
        # HBO Max
        "com.hbo.hbonow": {"name": "Max", "logo": "https://cdn.simpleicons.org/hbo/ffffff"},
        "com.wbd.stream": {"name": "Max", "logo": "https://cdn.simpleicons.org/hbo/ffffff"},
        # Peacock
        "com.peacocktv.peacockandroid": {
            "name": "Peacock",
            "logo": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect fill='%23000' width='24' height='24' rx='4'/%3E%3Ctext x='12' y='16' text-anchor='middle' fill='%23fff' font-family='Arial,sans-serif' font-weight='bold' font-size='7'%3EPEACOCK%3C/text%3E%3C/svg%3E",
        },
        "com.peacock.peacockfiretv": {
            "name": "Peacock",
            "logo": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect fill='%23000' width='24' height='24' rx='4'/%3E%3Ctext x='12' y='16' text-anchor='middle' fill='%23fff' font-family='Arial,sans-serif' font-weight='bold' font-size='7'%3EPEACOCK%3C/text%3E%3C/svg%3E",
        },
        # Paramount+
        "com.cbs.ott": {
            "name": "Paramount+",
            "logo": "https://cdn.simpleicons.org/paramountplus/0064FF",
        },
        "com.cbs.app": {
            "name": "Paramount+",
            "logo": "https://cdn.simpleicons.org/paramountplus/0064FF",
        },
        # Plex
        "com.plexapp.android": {"name": "Plex", "logo": "https://cdn.simpleicons.org/plex/E5A00D"},
        # Spotify
        "com.spotify.tv.android": {
            "name": "Spotify",
            "logo": "https://cdn.simpleicons.org/spotify/1DB954",
        },
        # Tubi
        "com.tubitv": {"name": "Tubi", "logo": "https://cdn.simpleicons.org/tubi/FA382F"},
        # Crunchyroll
        "com.crunchyroll.crunchyroid": {
            "name": "Crunchyroll",
            "logo": "https://cdn.simpleicons.org/crunchyroll/F47521",
        },
        # Twitch
        "tv.twitch.android.app": {
            "name": "Twitch",
            "logo": "https://cdn.simpleicons.org/twitch/9146FF",
        },
        # ESPN
        "com.espn.score_center": {
            "name": "ESPN",
            "logo": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect fill='%23D00' width='24' height='24' rx='4'/%3E%3Ctext x='12' y='16' text-anchor='middle' fill='%23fff' font-family='Arial,sans-serif' font-weight='bold' font-size='8'%3EESPN%3C/text%3E%3C/svg%3E",
        },
        # Fox Sports
        "com.foxsports.videogo": {
            "name": "Fox Sports",
            "logo": "https://cdn.simpleicons.org/fox/ffffff",
        },
        # DirecTV / AT&T TV
        "com.att.tv": {
            "name": "DirecTV",
            "logo": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect fill='%2300A8E1' width='24' height='24' rx='4'/%3E%3Ctext x='12' y='15' text-anchor='middle' fill='%23fff' font-family='Arial,sans-serif' font-weight='bold' font-size='5'%3EDIRECTV%3C/text%3E%3C/svg%3E",
        },
        # Sling TV
        "com.sling": {"name": "Sling", "logo": "https://cdn.simpleicons.org/sling/0095D5"},
        # Vudu / Fandango
        "com.vudu.air": {"name": "Vudu", "logo": "https://cdn.simpleicons.org/vudu/3399FF"},
        # Pluto TV
        "tv.pluto.android": {
            "name": "Pluto TV",
            "logo": "https://cdn.simpleicons.org/plutotv/000000",
        },
    }

    try:
        stdout, stderr, rc = _adb(device, "shell", "pm", "list", "packages")
    except ValueError:
        # Device not configured
        return AppsResponse(apps=[], configured=False)

    if rc != 0:
        return AppsResponse(apps=[], error=stderr)

    installed = {line.replace("package:", "").strip() for line in stdout.splitlines()}
    apps: list[AppInfo] = []
    seen_names: set[str] = set()
    for pkg, info in streaming_apps.items():
        if pkg in installed and info["name"] not in seen_names:
            seen_names.add(info["name"])
            apps.append(
                AppInfo(
                    package=pkg,
                    name=info["name"],
                    logo=info.get("logo"),
                    color=info.get("color", "#3b82f6") if not info.get("logo") else None,
                )
            )

    log.info("Remote list_apps", device=device, app_count=len(apps))
    return AppsResponse(apps=apps)


@app.post("/api/remote/launch", response_model=CommandResponse)
async def remote_launch_app(cmd: RemoteCommand) -> CommandResponse:
    """Launch streaming app on device."""
    if not cmd.action:
        return CommandResponse(ok=False, error="App name required")

    stdout, stderr, rc = _adb(
        cmd.device,
        "shell",
        "monkey",
        "-p",
        cmd.action,
        "-c",
        "android.intent.category.LAUNCHER",
        "1",
    )
    log.info("Remote launch", device=cmd.device, app=cmd.action)
    return CommandResponse(ok=rc == 0, error=stderr if rc != 0 else None)


# =============================================================================
# Light Bulb Control API
# =============================================================================


class BulbCommand(BaseModel):
    device: str
    action: str
    brightness: int | None = None
    hue: int | None = None
    saturation: int | None = None


def get_bulb_instance(device_id: str) -> TapoBulb | None:
    """Get Tapo bulb instance."""
    config = get_config()
    devices = config.get_all_devices()
    device_config = devices.get(device_id)
    if not device_config or device_config.get("type") != "tapo_bulb":
        return None

    return TapoBulb(
        device_id=device_id,
        name=device_config["name"],
        ip=device_config["ip"],
        username=config.tapo_username,
        password=config.tapo_password,
    )


@app.post("/api/bulb/toggle", response_model=BulbToggleResponse)
async def bulb_toggle(cmd: BulbCommand) -> BulbToggleResponse:
    """Toggle bulb on/off."""
    bulb = get_bulb_instance(cmd.device)
    if not bulb:
        return BulbToggleResponse(ok=False, error=f"Unknown bulb: {cmd.device}")

    # Get current state
    current_state = bulb.get_state()
    is_on = current_state.get("on", False)

    # Toggle
    if is_on:
        success = bulb.turn_off()
        new_state = "off"
    else:
        success = bulb.turn_on()
        new_state = "on"

    log.info("Bulb toggle", device=cmd.device, state=new_state)
    return BulbToggleResponse(ok=success, state=new_state if success else None)


@app.post("/api/bulb/control", response_model=CommandResponse)
async def bulb_control(cmd: BulbCommand) -> CommandResponse:
    """Control bulb (on, off, brightness, color)."""
    bulb = get_bulb_instance(cmd.device)
    if not bulb:
        return CommandResponse(ok=False, error=f"Unknown bulb: {cmd.device}")

    success = False
    action = cmd.action.lower()

    if action == "on":
        success = bulb.turn_on()
    elif action == "off":
        success = bulb.turn_off()
    elif action == "brightness" and cmd.brightness:
        success = bulb.set_brightness(cmd.brightness)
    elif action == "color" and cmd.hue is not None and cmd.saturation is not None:
        success = bulb.set_color(cmd.hue, cmd.saturation)
    else:
        return CommandResponse(ok=False, error=f"Invalid action: {cmd.action}")

    log.info("Bulb control", device=cmd.device, action=action)
    return CommandResponse(ok=success)


@app.get("/api/bulb/{device_id}/state", response_model=BulbStateResponse)
async def bulb_state(device_id: str) -> BulbStateResponse:
    """Get bulb state."""
    bulb = get_bulb_instance(device_id)
    if not bulb:
        return BulbStateResponse(device=device_id, state={}, error=f"Unknown bulb: {device_id}")

    state = bulb.get_state()
    return BulbStateResponse(device=device_id, state=state)


if __name__ == "__main__":
    import uvicorn

    print("Starting Smart Home Chat Agent at http://localhost:5001")
    uvicorn.run(app, host="0.0.0.0", port=5001)
