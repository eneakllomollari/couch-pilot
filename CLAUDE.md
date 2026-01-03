# Couch Pilot

AI-powered TV control via natural language. See `AGENTS.md` for detailed documentation.

## Commands

```bash
uv sync                                              # Install deps
uv run fastapi dev app.py --host 0.0.0.0 --port 5001 # Dev server
uv run ruff check --fix . && uv run ruff format .    # Lint + format
uv run pytest                                        # Run tests
```
