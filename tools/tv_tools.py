"""TV control tools for Claude Agent SDK."""

import asyncio
import base64
import contextlib
import time
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

# Status cache to reduce slow ADB calls (device -> (status, timestamp))
_status_cache: dict[str, tuple[dict, float]] = {}
_status_cache_duration = 2.0  # seconds


async def _get_package(device: str, app: str) -> str | None:
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

    try:
        proc = await asyncio.create_subprocess_exec(
            "adb",
            "-s",
            addr,
            "shell",
            "pm",
            "list",
            "packages",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        result_stdout = stdout.decode()
        returncode = proc.returncode

    except TimeoutError:
        return None

    if returncode != 0:
        return None

    packages = result_stdout.strip().split("\n")
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


async def _run_adb(
    device: str, *args: str, timeout: int = 10, retries: int = 2
) -> tuple[str, str, int]:
    """Run ADB command asynchronously with retry logic for transient failures.

    Args:
        device: Device ID from configuration
        *args: ADB command arguments
        timeout: Command timeout in seconds (default: 10)
        retries: Number of retries for transient failures (default: 2)

    Returns:
        Tuple of (stdout, stderr, returncode)
    """
    addr = _get_device_address(device)
    cmd = ["adb", "-s", addr] + list(args)

    last_error = None
    for attempt in range(retries + 1):
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            stderr_text = stderr.decode()

            # Success or non-retryable error - return immediately
            if proc.returncode == 0 or not _is_transient_adb_error(stderr_text):
                return stdout.decode(), stderr_text, proc.returncode or 0

            # Transient error detected - retry with exponential backoff
            last_error = stderr_text
            if attempt < retries:
                await asyncio.sleep(0.5 * (attempt + 1))  # 0.5s, 1.0s, 1.5s...
                continue

        except TimeoutError:
            # Kill process if it times out
            with contextlib.suppress(Exception):
                proc.kill()
            return "", "Command timed out", -1

    # All retries exhausted
    return "", f"Failed after {retries} retries: {last_error}", -1


def _is_transient_adb_error(stderr: str) -> bool:
    """Check if ADB error is transient and worth retrying."""
    transient_patterns = [
        "device offline",
        "device not found",
        "connection refused",
        "connection reset",
        "broken pipe",
    ]
    stderr_lower = stderr.lower()
    return any(pattern in stderr_lower for pattern in transient_patterns)


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


async def _appletv_component(device: str) -> str | None:
    """Return Apple TV main activity component for the device (if installed/known)."""
    # Prefer installed package detection for flexibility.
    pkg = await _get_package(device, "appletv")
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
        stdout, _, _ = await _run_adb(device, "shell", "dumpsys", "media_session", timeout=8)
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
        try:
            proc = await asyncio.create_subprocess_exec(
                "adb",
                "-s",
                addr,
                "shell",
                "input",
                "keyevent",
                "KEYCODE_WAKEUP",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=3.0)
        except TimeoutError:
            pass  # Best effort wakeup

    # Detect app from URL to get package for Fire TV special handling
    package = None
    if "youtube" in url or "youtu.be" in url:
        package = await _get_package(device, "youtube")
    elif is_netflix:
        package = await _get_package(device, "netflix")

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
        component = await _appletv_component(device)
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

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        result_stderr = stderr.decode()
        returncode = proc.returncode
    except TimeoutError:
        return {
            "content": [{"type": "text", "text": "Command timed out"}],
            "is_error": True,
        }

    if returncode != 0:
        return {
            "content": [{"type": "text", "text": f"Failed: {result_stderr}"}],
            "is_error": True,
        }

    # For Netflix/HBO Max/Apple TV: deep links often land on a details page; press select then validate
    playback_started = False
    if is_netflix or is_hbomax or is_appletv:
        await asyncio.sleep(3)  # Wait for app to load title page

        # Try pressing select up to 3 times intelligently (reduced from 15 to avoid being annoying)
        for attempt in range(3):
            # Check current state first
            status = await _get_status(device)

            # If already playing, we're done
            if "playing" in status.get("state", "").lower():
                playback_started = True
                break

            # If on profile selection, wait longer (not our fault)
            context = status.get("context", "").lower() if status.get("context") else ""
            if "profile" in context:
                if attempt == 0:  # Only wait once
                    await asyncio.sleep(5)  # Give time for user to select profile
                continue

            # Press select and check if playback started
            try:
                proc = await asyncio.create_subprocess_exec(
                    "adb",
                    "-s",
                    addr,
                    "shell",
                    "input",
                    "keyevent",
                    "KEYCODE_DPAD_CENTER",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=3.0)
            except TimeoutError:
                pass  # Continue trying

            # Wait briefly and check if playback started (reduced from 6s to 3s)
            await asyncio.sleep(2)
            if await _wait_for_playing(device, timeout_s=3):
                playback_started = True
                break
    else:
        # For YouTube and other apps, check if playback started
        await asyncio.sleep(2)
        playback_started = await _wait_for_playing(device, timeout_s=10)

    # Get final status and verify playback
    status = await _get_status(device)

    if not playback_started:
        # Playback not verified - return warning
        msg = (
            f"Content opened but playback not verified. TV state: {status.get('state', 'unknown')}"
        )
        if status.get("context"):
            msg += f", Context: {status['context']}"
        return {
            "content": [{"type": "text", "text": msg}],
            "is_error": False,  # Not an error - content was opened
        }

    # Success - playback started
    msg = f"Playing on {status.get('foreground', 'TV')}"
    if status.get("state"):
        msg += f" - {status['state']}"
    return {"content": [{"type": "text", "text": msg}]}


async def _get_status(device: str, use_cache: bool = True) -> dict:
    """Get TV status with human-readable context. Cached for 2 seconds to reduce ADB calls.

    Args:
        device: Device ID from configuration
        use_cache: If True, return cached status if available (default: True)

    Returns:
        Status dict with screen, foreground, state, context
    """
    # Check cache
    now = time.time()
    if use_cache and device in _status_cache:
        cached_status, cached_time = _status_cache[device]
        if now - cached_time < _status_cache_duration:
            return cached_status

    # Cache miss or expired - fetch fresh status
    status_cmd = (
        "dumpsys power | grep -E 'mWakefulness'; "
        "dumpsys window windows | grep -E 'mCurrentFocus'; "
        "dumpsys media_session | grep -E 'state=PlaybackState|description='"
    )
    stdout, _, _ = await _run_adb(device, "shell", status_cmd)

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

    # Cache the status
    _status_cache[device] = (status, now)

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
    before_stdout, _, _ = await _run_adb(
        device, "shell", "dumpsys window windows | grep -E 'mCurrentFocus'"
    )

    stdout, stderr, code = await _run_adb(device, "shell", "input", "keyevent", key_map[action])

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
    after_stdout, _, _ = await _run_adb(
        device, "shell", "dumpsys window windows | grep -E 'mCurrentFocus'"
    )
    focus_changed = before_stdout.strip() != after_stdout.strip()

    # Return concise message
    device_name = _get_tv_devices()[device]["name"]
    msg = f"{action.title()} on {device_name}"
    if status:
        msg += f" - {status}"
    if focus_changed:
        msg += " (screen changed)"

    return {"content": [{"type": "text", "text": msg}]}


@tool("play_pause", "Toggle play/pause on the TV.", {"device": str})
async def play_pause(args: dict[str, Any]) -> dict[str, Any]:
    """Toggle play/pause and verify the playback state changed."""
    device = args["device"]

    # Get playback state before
    before_stdout, _, _ = await _run_adb(
        device, "shell", "dumpsys media_session | grep -E 'state=PlaybackState'"
    )
    before_state, _, _ = _parse_playback_state(before_stdout)

    stdout, stderr, code = await _run_adb(
        device, "shell", "input", "keyevent", "KEYCODE_MEDIA_PLAY_PAUSE"
    )

    if code != 0:
        return {
            "content": [{"type": "text", "text": f"Play/pause command failed: {stderr}"}],
            "is_error": True,
        }

    # Wait for state change and verify
    await asyncio.sleep(0.5)

    after_stdout, _, _ = await _run_adb(
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
    initial_stdout, _, _ = await _run_adb(device, "shell", "dumpsys power | grep mWakefulness")
    was_already_on = "Awake" in initial_stdout

    # Send wakeup command
    stdout, stderr, code = await _run_adb(device, "shell", "input", "keyevent", "KEYCODE_WAKEUP")

    if code != 0:
        return {
            "content": [{"type": "text", "text": f"Turn on command failed: {stderr}"}],
            "is_error": True,
        }

    # Verify the TV is now awake (retry up to 3 times with delays)
    for _attempt in range(3):
        await asyncio.sleep(1)
        verify_stdout, _, _ = await _run_adb(device, "shell", "dumpsys power | grep mWakefulness")
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
    initial_stdout, _, _ = await _run_adb(device, "shell", "dumpsys power | grep mWakefulness")
    was_already_off = "Asleep" in initial_stdout

    # Send sleep command
    stdout, stderr, code = await _run_adb(device, "shell", "input", "keyevent", "KEYCODE_SLEEP")

    if code != 0:
        return {
            "content": [{"type": "text", "text": f"Turn off command failed: {stderr}"}],
            "is_error": True,
        }

    # Verify the TV is now asleep (retry up to 3 times with delays)
    for _attempt in range(3):
        await asyncio.sleep(1)
        verify_stdout, _, _ = await _run_adb(device, "shell", "dumpsys power | grep mWakefulness")
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


async def _get_volume(device: str) -> tuple[int | None, bool | None]:
    """Get current volume level and mute state from audio service."""
    import re

    stdout, _, _ = await _run_adb(device, "shell", "dumpsys audio | grep -E 'STREAM_MUSIC|muted'")

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
    before_vol, before_muted = await _get_volume(device)

    stdout, stderr, code = await _run_adb(device, "shell", "input", "keyevent", key_map[action])

    if code != 0:
        return {
            "content": [{"type": "text", "text": f"Volume command failed: {stderr}"}],
            "is_error": True,
        }

    # Wait for change to take effect
    await asyncio.sleep(0.3)

    # Get volume after
    after_vol, after_muted = await _get_volume(device)

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

    # Return concise message
    msg = result.get("message", "Volume command sent")
    if not result["verified"]:
        return {
            "content": [{"type": "text", "text": msg}],
            "is_error": True,
        }

    return {"content": [{"type": "text", "text": msg}]}


@tool("screenshot", "Take a screenshot of the TV screen.", {"device": str})
async def screenshot(args: dict[str, Any]) -> dict[str, Any]:
    """Take screenshot and return as base64 image."""
    device = args["device"]
    addr = _get_device_address(device)

    # Take screenshot and save locally
    tmp_path = Path(f"/tmp/tv_screenshot_{device}.png")

    try:
        proc = await asyncio.create_subprocess_exec(
            "adb",
            "-s",
            addr,
            "exec-out",
            "screencap",
            "-p",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        result_stdout, result_stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        result_returncode = proc.returncode
    except TimeoutError:
        return {
            "content": [{"type": "text", "text": "Screenshot command timed out"}],
            "is_error": True,
        }

    # Validate output is a PNG. Some apps (DRM/secure video surfaces) return empty/invalid.
    if result_returncode == 0 and result_stdout and result_stdout.startswith(b"\x89PNG\r\n\x1a\n"):
        tmp_path.write_bytes(result_stdout)

        # Return as base64 image
        img_base64 = base64.b64encode(result_stdout).decode("utf-8")
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
                    f"returncode={result_returncode}, bytes={len(result_stdout) if result_stdout else 0}, "
                    f"stderr={result_stderr.decode() if result_stderr else 'No output'}"
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
    focus_stdout, _, _ = await _run_adb(
        device, "shell", "dumpsys window windows | grep -E 'mCurrentFocus'"
    )

    # Escape special characters for ADB
    escaped = text.replace(" ", "%s").replace("'", "\\'").replace('"', '\\"')

    stdout, stderr, code = await _run_adb(device, "shell", "input", "text", escaped)

    if code != 0:
        return {
            "content": [{"type": "text", "text": f"Typing command failed: {stderr}"}],
            "is_error": True,
        }

    # Wait a moment for text to appear
    await asyncio.sleep(0.3)

    # Get current state for context
    status = await _get_status(device)

    # Check if the context looks like an input screen
    context = status.get("context", "").lower() if status.get("context") else ""
    if "search" in context or "input" in context or "edit" in context:
        msg = f"Text '{text}' sent successfully. Context: {status.get('context')}"
    else:
        msg = f"Text '{text}' sent, but current context '{status.get('context')}' may not be an input field. Use screenshot to verify."

    return {"content": [{"type": "text", "text": msg}]}


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
    stdout, stderr, code = await _run_adb(device, "shell", cmd)

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

    # Format concise human-readable status
    if status["screen"] == "off":
        status_text = f"{status['device']}: Screen off"
    else:
        parts = [f"{status['device']}: Screen {status['screen']}"]
        if status["current_app"]:
            app_name = status["current_app"].split(".")[-1].title()
            parts.append(f"App: {app_name}")
        if status["playback"]:
            parts.append(f"Playback: {status['playback']}")
        if status["media_title"]:
            parts.append(f"Title: {status['media_title']}")
        status_text = ", ".join(parts)

    return {"content": [{"type": "text", "text": status_text}]}


@tool("list_apps", "List streaming apps installed on a TV.", {"device": str})
async def list_apps(args: dict[str, Any]) -> dict[str, Any]:
    """List installed streaming apps on a device."""
    device = args["device"]
    addr = _get_device_address(device)

    # Get all packages
    try:
        proc = await asyncio.create_subprocess_exec(
            "adb",
            "-s",
            addr,
            "shell",
            "pm",
            "list",
            "packages",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        result_stdout, result_stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        result_returncode = proc.returncode
    except TimeoutError:
        return {
            "content": [{"type": "text", "text": "List apps command timed out"}],
            "is_error": True,
        }

    if result_returncode != 0:
        return {
            "content": [{"type": "text", "text": f"Failed to list apps: {result_stderr.decode()}"}],
            "is_error": True,
        }

    packages = result_stdout.decode().strip().split("\n")

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
            proc = await asyncio.create_subprocess_exec(
                "adb",
                "-s",
                addr,
                "get-state",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            result_stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            result_returncode = proc.returncode
            status = (
                "Online"
                if result_returncode == 0 and "device" in result_stdout.decode()
                else "Offline"
            )
        except TimeoutError:
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
