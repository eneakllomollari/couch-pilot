# Couch Pilot

[![CI](https://github.com/eneakllomollari/couch-pilot/actions/workflows/ci.yml/badge.svg)](https://github.com/eneakllomollari/couch-pilot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

AI-powered TV control via natural language chat. Control your Fire TV and Google TV devices by simply telling them what to do.

> **Security Note**: This application is designed for local network use only. Do not expose to the public internet.

## Features

- **AI Chat Control**: Natural language TV control powered by Claude
- **Remote Control UI**: Virtual remote with D-pad, volume, and app launcher
- **Deep Linking**: Automatic deep linking for Netflix, HBO Max, Apple TV+, YouTube
- **Smart Bulb Control**: TP-Link Tapo L530 bulb integration
- **Keyboard Shortcuts**: Control your TV with keyboard when not typing

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- ADB (Android Debug Bridge)
- Anthropic API key (for Claude)
- Fire TV / Google TV with ADB debugging enabled

## Quick Start

1. **Clone and install**:
   ```bash
   git clone https://github.com/eneakllomollari/couch-pilot.git
   cd couch-pilot
   uv sync
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your device IPs and credentials
   ```

3. **Enable ADB on your TV**:
   - Fire TV: Settings > My Fire TV > Developer Options > ADB debugging
   - Google TV: Settings > System > Developer options > USB debugging

4. **Run**:
   ```bash
   uv run fastapi dev app.py --host 0.0.0.0 --port 5001
   ```

5. Open http://localhost:5001

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Required: TV devices (JSON)
TV_DEVICES='{"fire_tv": {"ip": "192.168.1.10", "port": 5555, "name": "Fire TV"}}'

# Optional: Tapo bulb credentials
TAPO_USERNAME=your_email@example.com
TAPO_PASSWORD=your_password
TAPO_BULB_IPS=192.168.1.29,192.168.1.90
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TV_DEVICES` | Yes | JSON object mapping device IDs to their config |
| `TAPO_USERNAME` | No | TP-Link/Tapo account email |
| `TAPO_PASSWORD` | No | TP-Link/Tapo account password |
| `TAPO_BULB_IPS` | No | Comma-separated list of bulb IPs |
| `TUYA_DEVICES` | No | JSON config for Tuya devices |
| `VESYNC_USERNAME` | No | VeSync account email |
| `VESYNC_PASSWORD` | No | VeSync account password |

## Usage

### Chat Commands

The AI understands natural language. Examples:

- "Play Stranger Things on Netflix"
- "Open YouTube"
- "Turn off the TV"
- "Volume up"
- "Go back"
- "Take a screenshot"

### Remote Control

Use the on-screen remote or keyboard shortcuts:

| Key | Action |
|-----|--------|
| Arrow keys | Navigate (up/down/left/right) |
| Enter | Select |
| Backspace | Back |
| Escape | Home |
| Space | Play/Pause |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Chat + remote UI |
| `/ws` | WebSocket | AI chat connection |
| `/api/remote/navigate` | POST | D-pad navigation |
| `/api/remote/volume` | POST | Volume control |
| `/api/remote/power` | POST | Power toggle |
| `/api/remote/apps/{device}` | GET | List installed apps |
| `/api/bulb/toggle` | POST | Toggle bulb on/off |
| `/api/bulb/control` | POST | Control bulb settings |
| `/api/health` | GET | Health check |

## Development

```bash
# Install dependencies
uv sync

# Run development server
uv run fastapi dev app.py --host 0.0.0.0 --port 5001

# Lint and format
uv run ruff check --fix . && uv run ruff format .

# Type check
uv run ty check

# Run tests
uv run pytest -v
```

## Project Structure

```
smart-home/
├── app.py              # FastAPI application
├── config.py           # Pydantic settings configuration
├── devices/            # Device controllers
│   ├── base.py         # Abstract base device
│   └── tapo.py         # Tapo bulb controller
├── tools/              # Claude Agent SDK tools
│   └── tv_tools.py     # TV control via ADB
├── templates/          # HTML templates
│   └── chat.html       # Chat + remote UI
├── static/             # Static assets
│   ├── css/            # Stylesheets
│   └── js/             # JavaScript
└── tests/              # Test suite
```

## Security Considerations

This application:
- Has **no authentication** - intended for local network use only
- Communicates with TVs over **unencrypted ADB**
- Stores credentials in environment variables (not in code)

**Do not expose this application to the public internet.**

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run linting and tests (`uv run ruff check . && uv run pytest`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## License

MIT
