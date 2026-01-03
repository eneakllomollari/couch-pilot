# Smart Home - Developer Guide

Chat-based TV control using Claude Agent SDK + smart bulb control.

## Stack

- Python 3.11+
- FastAPI (web framework)
- Claude Agent SDK (AI integration)
- uv (package manager)
- ruff (linter/formatter)
- ty (type checker)

## Commands

```bash
uv sync                                              # Install deps
uv run fastapi dev app.py --host 0.0.0.0 --port 5001 # Dev server
uv run ruff check --fix . && uv run ruff format .    # Lint + format
uv run ty check                                      # Type check
uv run pytest -v                                     # Run tests
```

## Architecture

```
app.py              # FastAPI app - WebSocket chat + REST APIs
config.py           # Pydantic Settings config (loads from .env)
devices/
  base.py           # Abstract BaseDevice class
  tapo.py           # TP-Link Tapo L530 bulb controller
tools/
  tv_tools.py       # MCP tools for TV control via ADB
templates/
  chat.html         # Chat + remote control UI
static/
  css/style.css     # Styles
  js/chat.js        # Remote + chat JavaScript
tests/
  test_api.py       # API endpoint tests
  test_tv_tools.py  # URL normalization tests
```

## Key Components

### Configuration (`config.py`)

Uses Pydantic Settings for type-safe configuration:

```python
from config import get_config

config = get_config()
config.tv_devices      # Dict of TVDevice objects
config.tapo_username   # Tapo credentials
config.tapo_password
config.tapo_bulb_ips   # List of bulb IPs
```

Configuration loads from environment variables and `.env` file.

### WebSocket Chat (`/ws`)

- Connects to Claude Agent SDK
- Streams tool calls and responses
- Handles TV control via MCP tools

### REST APIs

| Route | Description |
|-------|-------------|
| `POST /api/remote/*` | Direct TV control (no AI) |
| `POST /api/bulb/*` | Smart bulb control |
| `GET /api/health` | Health check |

### MCP Tools (`tools/tv_tools.py`)

| Tool | Description |
|------|-------------|
| `play` | Deep link content (YouTube, Netflix, etc.) |
| `navigate` | D-pad navigation |
| `volume` | Volume control |
| `screenshot` | Capture TV screen |
| `get_tv_status` | Check TV state |
| `turn_on` / `turn_off` | Power control |
| `list_apps` | List installed streaming apps |

## Adding New Devices

1. Create `devices/foo.py` inheriting `BaseDevice`:

```python
from .base import BaseDevice

class FooDevice(BaseDevice):
    def connect(self) -> bool:
        """Connect to device."""
        pass

    def get_state(self) -> dict[str, Any]:
        """Get current state."""
        pass

    def turn_on(self) -> bool:
        """Turn device on."""
        pass

    def turn_off(self) -> bool:
        """Turn device off."""
        pass
```

2. Add API endpoints in `app.py`
3. Update `.env.example` with new config variables

## Adding New TV Tools

1. Add tool function in `tools/tv_tools.py`:

```python
@tool
async def my_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Tool description."""
    device = args.get("device", "fire_tv")
    # Implementation
    return {"result": [{"type": "text", "text": "Done"}]}
```

2. Tool is automatically registered with Claude Agent SDK
3. Update system prompt in `app.py` if needed

## Testing

```bash
# Run all tests
uv run pytest -v

# Run specific test file
uv run pytest tests/test_api.py -v

# Run with coverage
uv run pytest --cov=. --cov-report=html
```

## Notes

- Port 5001 is used (port 5000 conflicts with macOS AirPlay)
- TVs must have ADB debugging enabled over network
- Credentials are stored in `.env` (never commit this file)
- The application has no authentication - local network use only
