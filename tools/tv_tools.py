"""TV control tools for Claude Agent SDK."""

import asyncio
import base64
import json
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from claude_agent_sdk import create_sdk_mcp_server, tool

from config import get_config


def _get_tv_devices() -> dict[str, dict[str, Any]]:
    """Get TV devices from configuration."""
    config = get_config()
    return {
        device_id: {"ip": tv.ip, "port": tv.port, "name": tv.name}
        for device_id, tv in config.tv_devices.items()
    }


# Cache for discovered packages per device
_package_cache: dict[str, dict[str, str]] = {}


def _get_package(device: str, app: str) -> str | None:
    """Get package name for an app on a device by querying it."""
    tv_devices = _get_tv_devices()
    addr = f"{tv_devices[device]['ip']}:{tv_devices[device]['port']}"

    # Check cache first
    if device in _package_cache and app in _package_cache[device]:
        return _package_cache[device][app]

    # Query device for installed packages
    patterns = {
        "youtube": ["youtube"],
        "netflix": ["netflix"],
        "prime": ["amazonvideo", "avod", "prime"],
        "appletv": ["appletv"],
    }

    if app not in patterns:
        return None

    result = subprocess.run(
        ["adb", "-s", addr, "shell", "pm", "list", "packages"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    if result.returncode != 0:
        return None

    packages = result.stdout.strip().split("\n")
    for pattern in patterns[app]:
        for pkg_line in packages:
            pkg = pkg_line.replace("package:", "").strip()
            if pattern in pkg.lower():
                # Cache it
                if device not in _package_cache:
                    _package_cache[device] = {}
                _package_cache[device][app] = pkg
                return pkg

    return None


def _get_device_address(device: str) -> str:
    """Get device IP:port string."""
    tv_devices = _get_tv_devices()
    if device not in tv_devices:
        raise ValueError(f"Unknown device: {device}. Available: {list(tv_devices.keys())}")
    d = tv_devices[device]
    return f"{d['ip']}:{d['port']}"


def _run_adb(device: str, *args: str, timeout: int = 10) -> tuple[str, str, int]:
    """Run ADB command and return stdout, stderr, returncode."""
    addr = _get_device_address(device)
    cmd = ["adb", "-s", addr] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout, result.stderr, result.returncode


# ============= HIGH-LEVEL TOOLS =============


def _normalize_url(url: str) -> str:
    """Convert web URLs to proper deep link URIs for streaming apps.

    Supported formats:

    Netflix:
        Input:  https://www.netflix.com/title/80057281
        Output: http://www.netflix.com/watch/80057281
        Note: Netflix deep links open details page, requires DPAD_CENTER to start playback

    HBO Max:
        Input:  https://www.hbomax.com/movies/broken-english/4cf01eb1-9257-4d25-8661-d0d9986ebdb0
        Output: https://play.max.com/movie/4cf01eb1-9257-4d25-8661-d0d9986ebdb0
        Note: Must use play.max.com domain (www.hbomax.com not handled by app)
              Content ID is UUID from website URL
              Works reliably after profile selection

    Apple TV+:
        Input:  https://tv.apple.com/us/show/the-morning-show/umc.cmc.XXXXXXXXXXXXXXXX
        Output: https://tv.apple.com/show/umc.cmc.XXXXXXXXXXXXXXXX
        Note: On Fire TV, forcing the Apple TV app package avoids Amazon intercept/"Open with"
    """
    import re

    url = url.strip()

    # Netflix: convert to http://www.netflix.com/watch/ID format for best compatibility
    netflix_match = re.match(
        r"(?:netflix://|https?://(?:www\.)?netflix\.com/)(?:title|watch)/(\d+)", url
    )
    if netflix_match:
        return f"http://www.netflix.com/watch/{netflix_match.group(1)}"

    # HBO Max: convert www.hbomax.com URLs to play.max.com format
    # Example: hbomax.com/movies/broken-english/4cf01eb1-... -> play.max.com/movie/4cf01eb1-...
    hbomax_movie_match = re.match(
        r"https?://(?:www\.)?hbomax\.com/movies?/[^/]+/([a-f0-9-]{36})", url
    )
    if hbomax_movie_match:
        return f"https://play.max.com/movie/{hbomax_movie_match.group(1)}"

    # HBO Max series: hbomax.com/series/show-name/UUID -> play.max.com/show/UUID
    hbomax_series_match = re.match(
        r"https?://(?:www\.)?hbomax\.com/series/[^/]+/([a-f0-9-]{36})", url
    )
    if hbomax_series_match:
        return f"https://play.max.com/show/{hbomax_series_match.group(1)}"

    # HBO Max "urn:" series/movie URLs:
    # https://www.hbomax.com/series/urn:hbo:series:<uuid> -> https://play.max.com/show/<uuid>
    hbomax_urn_series = re.match(
        r"https?://(?:www\.)?hbomax\.com/series/urn:hbo:series:([a-f0-9-]{36})",
        url,
    )
    if hbomax_urn_series:
        return f"https://play.max.com/show/{hbomax_urn_series.group(1)}"
    hbomax_urn_movie = re.match(
        r"https?://(?:www\.)?hbomax\.com/movies?/urn:hbo:movie:([a-f0-9-]{36})",
        url,
    )
    if hbomax_urn_movie:
        return f"https://play.max.com/movie/{hbomax_urn_movie.group(1)}"

    # Apple TV+: canonicalize show URLs so they consistently resolve inside the app
    # Example: https://tv.apple.com/us/show/the-morning-show/umc.cmc.X -> https://tv.apple.com/show/umc.cmc.X
    apple_show_match = re.match(
        r"https?://tv\.apple\.com/(?:[a-z]{2}/)?show/[^/]+/(umc\.cmc\.[A-Za-z0-9.]+)",
        url,
    )
    if apple_show_match:
        return f"https://tv.apple.com/show/{apple_show_match.group(1)}"
    apple_show_canonical = re.match(
        r"https?://tv\.apple\.com/(?:[a-z]{2}/)?show/(umc\.cmc\.[A-Za-z0-9.]+)",
        url,
    )
    if apple_show_canonical:
        return f"https://tv.apple.com/show/{apple_show_canonical.group(1)}"

    # Already correct play.max.com format - pass through
    # Example: https://play.max.com/movie/4cf01eb1-9257-4d25-8661-d0d9986ebdb0

    return url


def _appletv_component(device: str) -> str | None:
    """Return Apple TV main activity component for the device (if installed/known)."""
    # Prefer installed package detection for flexibility.
    pkg = _get_package(device, "appletv")
    if pkg:
        return f"{pkg}/.MainActivity"
    # Fallback known package names.
    if device == "fire_tv":
        return "com.apple.atve.amazon.appletv/.MainActivity"
    if device == "google_tv":
        return "com.apple.atve.androidtv.appletv/.MainActivity"
    return None


def _parse_playback_state(media_session_dump: str) -> tuple[int | None, int | None, float | None]:
    """Parse playback state/position/speed from dumpsys media_session output."""
    import re

    # Find first PlaybackState line.
    m = re.search(r"state=PlaybackState\\s*\\{[^}]*\\}", media_session_dump)
    if not m:
        return None, None, None
    line = m.group(0)
    state_m = re.search(r"state=(\\d+)", line)
    pos_m = re.search(r"position=(\\d+)", line)
    speed_m = re.search(r"speed=([0-9.]+)", line)
    state = int(state_m.group(1)) if state_m else None
    pos = int(pos_m.group(1)) if pos_m else None
    speed = float(speed_m.group(1)) if speed_m else None
    return state, pos, speed


async def _wait_for_playing(device: str, timeout_s: int = 20) -> bool:
    """Wait until PlaybackState is playing and position advances."""
    import time

    start = time.time()
    last_pos: int | None = None

    while time.time() - start < timeout_s:
        stdout, _, _ = _run_adb(device, "shell", "dumpsys", "media_session", timeout=8)
        state, pos, speed = _parse_playback_state(stdout)
        # PlaybackState: 3=playing, 2=paused, 6=buffering (common)
        if state == 3 and speed and speed > 0:
            if pos is None:
                return True
            if last_pos is not None and pos > last_pos:
                return True
            last_pos = pos
        await asyncio.sleep(1)

    return False


@tool(
    "play",
    "Deep link a URL to the TV. Works with streaming URLs (YouTube, Netflix, HBO Max).",
    {"device": str, "url": str},
)
async def play(args: dict[str, Any]) -> dict[str, Any]:
    """Open a URL on the TV and return status."""
    device = args["device"]
    url = _normalize_url(args["url"])  # Auto-convert to deep link
    addr = _get_device_address(device)

    is_netflix = "netflix" in url
    is_hbomax = "play.max.com" in url or "hbomax" in url
    is_appletv = urlparse(url).netloc == "tv.apple.com"

    # For Netflix/HBO Max/Apple TV: wake TV first
    if is_netflix or is_hbomax or is_appletv:
        subprocess.run(
            ["adb", "-s", addr, "shell", "input", "keyevent", "KEYCODE_WAKEUP"],
            capture_output=True,
            timeout=3,
        )

    # Detect app from URL to get package for Fire TV special handling
    package = None
    if "youtube" in url or "youtu.be" in url:
        package = _get_package(device, "youtube")
    elif is_netflix:
        package = _get_package(device, "netflix")

    # Build command
    if package and ("amazon" in package or "firetv" in package) and "youtube" in url:
        # Fire TV YouTube needs explicit activity
        cmd = [
            "adb",
            "-s",
            addr,
            "shell",
            "am",
            "start",
            "-n",
            f"{package}/dev.cobalt.app.MainActivity",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            url,
        ]
    elif is_appletv:
        # Apple TV on Fire TV: force explicit component to avoid Amazon intercept/"Open with"
        component = _appletv_component(device)
        if component:
            cmd = [
                "adb",
                "-s",
                addr,
                "shell",
                "am",
                "start",
                "-n",
                component,
                "-a",
                "android.intent.action.VIEW",
                "-d",
                url,
            ]
        else:
            cmd = [
                "adb",
                "-s",
                addr,
                "shell",
                "am",
                "start",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                url,
            ]
    elif is_netflix:
        # Netflix: use --activity-clear-task for clean launch
        cmd = [
            "adb",
            "-s",
            addr,
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "--activity-clear-task",
            "-d",
            url,
        ]
    else:
        cmd = [
            "adb",
            "-s",
            addr,
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            url,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        return {
            "content": [{"type": "text", "text": f"Failed: {result.stderr}"}],
            "is_error": True,
        }

    # For Netflix/HBO Max/Apple TV: deep links often land on a details page; press select then validate
    playback_started = False
    if is_netflix or is_hbomax or is_appletv:
        await asyncio.sleep(3)  # Wait for app to load title page

        # Keep pressing select until playback starts - be persistent (up to 15 tries over ~90 seconds)
        for _attempt in range(15):
            subprocess.run(
                ["adb", "-s", addr, "shell", "input", "keyevent", "KEYCODE_DPAD_CENTER"],
                capture_output=True,
                timeout=3,
            )
            if await _wait_for_playing(device, timeout_s=6):
                playback_started = True
                break

            # Check if we're stuck on profile selection or other screens
            status = await _get_status(device)
            context = status.get("context", "").lower() if status.get("context") else ""

            # If on profile selection, wait longer for user or try select again
            if "profile" in context:
                await asyncio.sleep(2)  # Give more time for profile screen
    else:
        # For YouTube and other apps, check if playback started
        await asyncio.sleep(2)
        playback_started = await _wait_for_playing(device, timeout_s=10)

    # Get final status and verify playback
    status = await _get_status(device)
    status["playback_verified"] = playback_started

    if not playback_started:
        status["warning"] = (
            "Playback may not have started. Check TV screen or use screenshot tool to verify."
        )
        return {
            "content": [{"type": "text", "text": json.dumps(status, indent=2)}],
            "is_error": True,
        }

    return {"content": [{"type": "text", "text": json.dumps(status, indent=2)}]}


async def _get_status(device: str) -> dict:
    """Get TV status with human-readable context."""
    status_cmd = (
        "dumpsys power | grep -E 'mWakefulness'; "
        "dumpsys window windows | grep -E 'mCurrentFocus'; "
        "dumpsys media_session | grep -E 'state=PlaybackState|description='"
    )
    stdout, _, _ = _run_adb(device, "shell", status_cmd)

    status = {
        "screen": "unknown",
        "foreground": None,
        "state": None,
        "context": None,
    }

    app = None
    activity = None
    playback = None
    media_desc = None

    for line in stdout.split("\n"):
        line = line.strip()
        if "mWakefulness=" in line:
            if "Awake" in line:
                status["screen"] = "on"
            elif "Asleep" in line:
                status["screen"] = "off"
            elif "Dreaming" in line:
                status["screen"] = "screensaver"
        elif "mCurrentFocus" in line:
            for part in line.split():
                if "/" in part and "." in part:
                    full = part.strip("{})/")
                    if "/" in full:
                        app, activity = full.split("/", 1)
                    break
        elif "state=PlaybackState" in line:
            if "state=3" in line:
                playback = "playing"
            elif "state=2" in line:
                playback = "paused"
        elif "description=" in line and "null" not in line:
            desc = line.split("description=")[-1].split(",")[0].strip()
            if desc:
                media_desc = desc

    # Build human-readable foreground description
    if app:
        app_name = app.split(".")[-1] if "." in app else app
        status["foreground"] = app_name

        # Infer context from activity name
        if activity:
            act_lower = activity.lower()
            if "profile" in act_lower or "who" in act_lower:
                status["context"] = "profile selection"
            elif "search" in act_lower:
                status["context"] = "search screen"
            elif "player" in act_lower or "playback" in act_lower:
                status["context"] = "player"
            elif "browse" in act_lower or "home" in act_lower:
                status["context"] = "browsing/home"
            elif "detail" in act_lower:
                status["context"] = "content details"
            else:
                status["context"] = activity.replace(".", " ").strip()

    # Set state
    if playback:
        status["state"] = f"{playback}" + (f" - {media_desc}" if media_desc else "")
    elif status["screen"] == "off":
        status["state"] = "TV is off"
    elif status["screen"] == "screensaver":
        status["state"] = "screensaver active"
    else:
        status["state"] = "idle"

    return status


@tool(
    "navigate",
    "Navigate on the TV. Actions: up, down, left, right, select, back, home, menu. Returns current UI state after navigation.",
    {"device": str, "action": str},
)
async def navigate(args: dict[str, Any]) -> dict[str, Any]:
    """Send navigation command to TV and return the resulting UI state."""
    device = args["device"]
    action = args["action"].lower()

    key_map = {
        "up": "KEYCODE_DPAD_UP",
        "down": "KEYCODE_DPAD_DOWN",
        "left": "KEYCODE_DPAD_LEFT",
        "right": "KEYCODE_DPAD_RIGHT",
        "select": "KEYCODE_DPAD_CENTER",
        "enter": "KEYCODE_DPAD_CENTER",
        "ok": "KEYCODE_DPAD_CENTER",
        "back": "KEYCODE_BACK",
        "home": "KEYCODE_HOME",
        "menu": "KEYCODE_MENU",
    }

    if action not in key_map:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Unknown action: {action}. Available: {list(key_map.keys())}",
                }
            ],
            "is_error": True,
        }

    # Capture state before navigation for comparison
    before_stdout, _, _ = _run_adb(
        device, "shell", "dumpsys window windows | grep -E 'mCurrentFocus'"
    )

    stdout, stderr, code = _run_adb(device, "shell", "input", "keyevent", key_map[action])

    if code != 0:
        return {
            "content": [{"type": "text", "text": f"Navigation command failed: {stderr}"}],
            "is_error": True,
        }

    # Wait for UI to settle
    await asyncio.sleep(0.5)

    # Get current state after navigation to confirm and inform
    status = await _get_status(device)

    # Check if focus changed (for actions like select, back, home)
    after_stdout, _, _ = _run_adb(
        device, "shell", "dumpsys window windows | grep -E 'mCurrentFocus'"
    )
    focus_changed = before_stdout.strip() != after_stdout.strip()

    result = {
        "action": action,
        "device": _get_tv_devices()[device]["name"],
        "focus_changed": focus_changed,
        "current_state": status,
    }

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool("play_pause", "Toggle play/pause on the TV.", {"device": str})
async def play_pause(args: dict[str, Any]) -> dict[str, Any]:
    """Toggle play/pause and verify the playback state changed."""
    device = args["device"]

    # Get playback state before
    before_stdout, _, _ = _run_adb(
        device, "shell", "dumpsys media_session | grep -E 'state=PlaybackState'"
    )
    before_state, _, _ = _parse_playback_state(before_stdout)

    stdout, stderr, code = _run_adb(
        device, "shell", "input", "keyevent", "KEYCODE_MEDIA_PLAY_PAUSE"
    )

    if code != 0:
        return {
            "content": [{"type": "text", "text": f"Play/pause command failed: {stderr}"}],
            "is_error": True,
        }

    # Wait for state change and verify
    await asyncio.sleep(0.5)

    after_stdout, _, _ = _run_adb(
        device, "shell", "dumpsys media_session | grep -E 'state=PlaybackState'"
    )
    after_state, _, _ = _parse_playback_state(after_stdout)

    # Map state codes to names
    state_names = {2: "paused", 3: "playing", 6: "buffering"}
    before_name = state_names.get(before_state, f"unknown({before_state})")
    after_name = state_names.get(after_state, f"unknown({after_state})")

    if before_state != after_state:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Play/pause toggled on {_get_tv_devices()[device]['name']}: {before_name} → {after_name} (verified)",
                }
            ]
        }
    elif after_state is None:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Play/pause sent to {_get_tv_devices()[device]['name']} but no active media session detected. Command may have had no effect.",
                }
            ],
            "is_error": True,
        }
    else:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Play/pause sent to {_get_tv_devices()[device]['name']} but state did not change (still {after_name}). App may not have responded.",
                }
            ],
            "is_error": True,
        }


@tool("turn_on", "Wake/turn on the TV.", {"device": str})
async def turn_on(args: dict[str, Any]) -> dict[str, Any]:
    """Turn on/wake the TV and verify it actually woke up."""
    device = args["device"]

    # Get initial state
    initial_stdout, _, _ = _run_adb(device, "shell", "dumpsys power | grep mWakefulness")
    was_already_on = "Awake" in initial_stdout

    # Send wakeup command
    stdout, stderr, code = _run_adb(device, "shell", "input", "keyevent", "KEYCODE_WAKEUP")

    if code != 0:
        return {
            "content": [{"type": "text", "text": f"Turn on command failed: {stderr}"}],
            "is_error": True,
        }

    # Verify the TV is now awake (retry up to 3 times with delays)
    for _attempt in range(3):
        await asyncio.sleep(1)
        verify_stdout, _, _ = _run_adb(device, "shell", "dumpsys power | grep mWakefulness")
        if "Awake" in verify_stdout:
            if was_already_on:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"{_get_tv_devices()[device]['name']} was already on (verified: screen is awake)",
                        }
                    ]
                }
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"{_get_tv_devices()[device]['name']} turned on successfully (verified: screen is now awake)",
                    }
                ]
            }

    # Verification failed
    return {
        "content": [
            {
                "type": "text",
                "text": f"Turn on command sent but verification failed - TV may not have woken up. Last state: {verify_stdout.strip()}",
            }
        ],
        "is_error": True,
    }


@tool("turn_off", "Sleep/turn off the TV.", {"device": str})
async def turn_off(args: dict[str, Any]) -> dict[str, Any]:
    """Turn off/sleep the TV and verify it actually went to sleep."""
    device = args["device"]

    # Get initial state
    initial_stdout, _, _ = _run_adb(device, "shell", "dumpsys power | grep mWakefulness")
    was_already_off = "Asleep" in initial_stdout

    # Send sleep command
    stdout, stderr, code = _run_adb(device, "shell", "input", "keyevent", "KEYCODE_SLEEP")

    if code != 0:
        return {
            "content": [{"type": "text", "text": f"Turn off command failed: {stderr}"}],
            "is_error": True,
        }

    # Verify the TV is now asleep (retry up to 3 times with delays)
    for _attempt in range(3):
        await asyncio.sleep(1)
        verify_stdout, _, _ = _run_adb(device, "shell", "dumpsys power | grep mWakefulness")
        if "Asleep" in verify_stdout:
            if was_already_off:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"{_get_tv_devices()[device]['name']} was already off (verified: screen is asleep)",
                        }
                    ]
                }
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"{_get_tv_devices()[device]['name']} turned off successfully (verified: screen is now asleep)",
                    }
                ]
            }

    # Verification failed
    return {
        "content": [
            {
                "type": "text",
                "text": f"Turn off command sent but verification failed - TV may not have gone to sleep. Last state: {verify_stdout.strip()}",
            }
        ],
        "is_error": True,
    }


def _get_volume(device: str) -> tuple[int | None, bool | None]:
    """Get current volume level and mute state from audio service."""
    import re

    stdout, _, _ = _run_adb(device, "shell", "dumpsys audio | grep -E 'STREAM_MUSIC|muted'")

    volume = None
    muted = None

    # Parse volume index from STREAM_MUSIC line
    vol_match = re.search(r"STREAM_MUSIC.*?index[=:](\d+)", stdout, re.IGNORECASE)
    if vol_match:
        volume = int(vol_match.group(1))

    # Check mute state
    if "muted=true" in stdout.lower() or "muted: true" in stdout.lower():
        muted = True
    elif "muted=false" in stdout.lower() or "muted: false" in stdout.lower():
        muted = False

    return volume, muted


@tool(
    "volume",
    "Control volume. Actions: up, down, mute. Returns verified volume level after change.",
    {"device": str, "action": str},
)
async def volume(args: dict[str, Any]) -> dict[str, Any]:
    """Control volume and verify the change took effect."""
    device = args["device"]
    action = args["action"].lower()

    key_map = {
        "up": "KEYCODE_VOLUME_UP",
        "down": "KEYCODE_VOLUME_DOWN",
        "mute": "KEYCODE_VOLUME_MUTE",
    }

    if action not in key_map:
        return {
            "content": [
                {"type": "text", "text": f"Unknown volume action: {action}. Use: up, down, mute"}
            ],
            "is_error": True,
        }

    # Get volume before
    before_vol, before_muted = _get_volume(device)

    stdout, stderr, code = _run_adb(device, "shell", "input", "keyevent", key_map[action])

    if code != 0:
        return {
            "content": [{"type": "text", "text": f"Volume command failed: {stderr}"}],
            "is_error": True,
        }

    # Wait for change to take effect
    await asyncio.sleep(0.3)

    # Get volume after
    after_vol, after_muted = _get_volume(device)

    # Build result with verification
    result = {
        "action": action,
        "device": _get_tv_devices()[device]["name"],
        "verified": False,
    }

    if action == "mute":
        if before_muted != after_muted:
            result["verified"] = True
            result["muted"] = after_muted
            result["message"] = f"Mute toggled: {'muted' if after_muted else 'unmuted'}"
        else:
            result["message"] = f"Mute command sent but state unchanged (muted={after_muted})"
    else:
        if before_vol is not None and after_vol is not None:
            if (action == "up" and after_vol >= before_vol) or (
                action == "down" and after_vol <= before_vol
            ):
                result["verified"] = True
            result["volume_before"] = before_vol
            result["volume_after"] = after_vol
            result["message"] = f"Volume {before_vol} → {after_vol}"
        elif after_vol is not None:
            result["volume"] = after_vol
            result["message"] = f"Volume is now {after_vol}"
        else:
            result["message"] = "Volume command sent but could not verify level"

    if not result["verified"]:
        return {
            "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
            "is_error": True,
        }

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool("screenshot", "Take a screenshot of the TV screen.", {"device": str})
async def screenshot(args: dict[str, Any]) -> dict[str, Any]:
    """Take screenshot and return as base64 image."""
    device = args["device"]
    addr = _get_device_address(device)

    # Take screenshot and save locally
    tmp_path = Path(f"/tmp/tv_screenshot_{device}.png")
    result = subprocess.run(
        ["adb", "-s", addr, "exec-out", "screencap", "-p"],
        capture_output=True,
        timeout=10,
    )

    # Validate output is a PNG. Some apps (DRM/secure video surfaces) return empty/invalid.
    if result.returncode == 0 and result.stdout and result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
        tmp_path.write_bytes(result.stdout)

        # Return as base64 image
        img_base64 = base64.b64encode(result.stdout).decode("utf-8")
        return {
            "content": [
                {"type": "text", "text": f"Screenshot from {_get_tv_devices()[device]['name']}:"},
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": img_base64},
                },
            ]
        }

    return {
        "content": [
            {
                "type": "text",
                "text": (
                    "Screenshot failed (often DRM/secure video blocks capture on Fire TV). "
                    f"returncode={result.returncode}, bytes={len(result.stdout) if result.stdout else 0}, "
                    f"stderr={result.stderr.decode() if result.stderr else 'No output'}"
                ),
            }
        ],
        "is_error": True,
    }


@tool(
    "type_text",
    "Type text into an input field on the TV. Use screenshot tool after to verify text was entered.",
    {"device": str, "text": str},
)
async def type_text(args: dict[str, Any]) -> dict[str, Any]:
    """Type text into input field and return current UI context.

    Note: Text input cannot be directly verified via ADB. The tool returns the
    current app/activity context so you can assess if typing is likely to work.
    Use the screenshot tool after typing to visually confirm the text appeared.
    """
    device = args["device"]
    text = args["text"]

    # Check if there's a focused window that might accept input
    focus_stdout, _, _ = _run_adb(
        device, "shell", "dumpsys window windows | grep -E 'mCurrentFocus'"
    )

    # Escape special characters for ADB
    escaped = text.replace(" ", "%s").replace("'", "\\'").replace('"', '\\"')

    stdout, stderr, code = _run_adb(device, "shell", "input", "text", escaped)

    if code != 0:
        return {
            "content": [{"type": "text", "text": f"Typing command failed: {stderr}"}],
            "is_error": True,
        }

    # Wait a moment for text to appear
    await asyncio.sleep(0.3)

    # Get current state for context
    status = await _get_status(device)

    result = {
        "action": "type_text",
        "text_sent": text,
        "device": _get_tv_devices()[device]["name"],
        "current_context": status.get("context"),
        "current_app": status.get("foreground"),
        "verification_note": "Text input sent successfully. Use screenshot tool to visually confirm text appeared in the input field.",
    }

    # Warn if the context doesn't look like an input screen
    context = status.get("context", "").lower() if status.get("context") else ""
    if "search" in context or "input" in context or "edit" in context:
        result["likely_input_field"] = True
    else:
        result["likely_input_field"] = False
        result["warning"] = (
            f"Current context '{status.get('context')}' may not be an input field. Text may not have been entered."
        )

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "get_tv_status",
    "Get current TV status: screen state, active app, and playback info.",
    {"device": str},
)
async def get_tv_status(args: dict[str, Any]) -> dict[str, Any]:
    """Get comprehensive TV status - single fast ADB call."""
    device = args["device"]

    # Single combined command for speed
    cmd = (
        "dumpsys power | grep mWakefulness; "
        "dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'; "
        "dumpsys media_session | grep -E 'state=PlaybackState|description='"
    )
    stdout, stderr, code = _run_adb(device, "shell", cmd)

    status = {
        "device": _get_tv_devices()[device]["name"],
        "screen": "unknown",
        "current_app": None,
        "playback": None,
        "media_title": None,
    }

    for line in stdout.split("\n"):
        line = line.strip()
        # Screen state
        if "mWakefulness=" in line:
            if "Awake" in line:
                status["screen"] = "on"
            elif "Asleep" in line:
                status["screen"] = "off"
            elif "Dreaming" in line:
                status["screen"] = "screensaver"
        # Current app
        elif "mCurrentFocus" in line or "mFocusedApp" in line:
            for part in line.split():
                if "/" in part and "." in part:
                    pkg = part.strip("{})/").split("/")[0]
                    status["current_app"] = pkg
                    break
        # Playback state
        elif "state=PlaybackState" in line:
            if "state=3" in line:
                status["playback"] = "playing"
            elif "state=2" in line:
                status["playback"] = "paused"
            elif "state=6" in line:
                status["playback"] = "buffering"
        # Media title
        elif "description=" in line and "null" not in line:
            desc = line.split("description=")[-1].strip()
            if desc:
                status["media_title"] = desc

    return {"content": [{"type": "text", "text": json.dumps(status, indent=2)}]}


@tool("list_apps", "List streaming apps installed on a TV.", {"device": str})
async def list_apps(args: dict[str, Any]) -> dict[str, Any]:
    """List installed streaming apps on a device."""
    device = args["device"]
    addr = _get_device_address(device)

    # Get all packages
    result = subprocess.run(
        ["adb", "-s", addr, "shell", "pm", "list", "packages"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode != 0:
        return {
            "content": [{"type": "text", "text": f"Failed to list apps: {result.stderr}"}],
            "is_error": True,
        }

    packages = result.stdout.strip().split("\n")

    # Filter for streaming/media apps
    streaming_keywords = [
        "youtube",
        "netflix",
        "prime",
        "amazonvideo",
        "hulu",
        "disney",
        "hbo",
        "peacock",
        "paramount",
        "apple.tv",
        "plex",
        "kodi",
        "spotify",
        "pandora",
        "tidal",
        "twitch",
        "crunchyroll",
    ]

    found_apps = []
    for pkg_line in packages:
        pkg = pkg_line.replace("package:", "").strip()
        for keyword in streaming_keywords:
            if keyword in pkg.lower():
                found_apps.append(pkg)
                break

    if found_apps:
        apps_list = "\n".join(f"- {app}" for app in sorted(found_apps))
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Streaming apps on {_get_tv_devices()[device]['name']}:\n{apps_list}",
                }
            ]
        }
    else:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"No streaming apps found on {_get_tv_devices()[device]['name']}",
                }
            ]
        }


@tool("list_tvs", "List all available TVs and their connection status.", {})
async def list_tvs(args: dict[str, Any]) -> dict[str, Any]:
    """List available TVs with status."""
    results = []

    for device_id, config in _get_tv_devices().items():
        addr = f"{config['ip']}:{config['port']}"

        # Check if connected
        try:
            result = subprocess.run(
                ["adb", "-s", addr, "get-state"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            status = "Online" if result.returncode == 0 and "device" in result.stdout else "Offline"
        except subprocess.TimeoutExpired:
            status = "Offline"
        except Exception:
            status = "Unknown"

        results.append(f"- {config['name']} ({device_id}): {config['ip']} - {status}")

    return {"content": [{"type": "text", "text": "Available TVs:\n" + "\n".join(results)}]}


# Create the MCP server with all tools
tv_server = create_sdk_mcp_server(
    name="tv-control",
    version="1.0.0",
    tools=[
        play,
        navigate,
        play_pause,
        turn_on,
        turn_off,
        volume,
        screenshot,
        type_text,
        get_tv_status,
        list_apps,
        list_tvs,
    ],
)
