# Claude Code Instructions

See [AGENTS.md](./AGENTS.md) for project documentation.

## Quick Reference

```bash
uv sync                                              # Install deps
uv run fastapi dev app.py --host 0.0.0.0 --port 5001 # Dev server
uv run ruff check --fix . && uv run ruff format .    # Lint + format
```
