# Contributing to Couch Pilot

Thanks for your interest in contributing!

## Development Setup

1. **Clone the repo**:
   ```bash
   git clone https://github.com/eneakllomollari/couch-pilot.git
   cd couch-pilot
   ```

2. **Install dependencies**:
   ```bash
   uv sync
   ```

3. **Set up pre-commit hooks**:
   ```bash
   uv run pre-commit install
   ```

4. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your device IPs and credentials
   ```

5. **Run the dev server**:
   ```bash
   make dev
   ```

## Code Quality

Before submitting a PR, ensure:

```bash
make lint      # Run ruff linter and formatter
make typecheck # Run type checker
make test      # Run tests
```

Or run all checks at once:
```bash
make check
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Ensure all checks pass (`make check`)
5. Commit with a descriptive message
6. Push to your fork
7. Open a Pull Request

### PR Guidelines

- Keep PRs focused on a single change
- Update documentation if needed
- Add tests for new functionality
- Follow existing code style

## Adding New Devices

See [AGENTS.md](./AGENTS.md) for the device integration guide.

## Adding New TV Tools

See [AGENTS.md](./AGENTS.md) for the MCP tools guide.

## Reporting Issues

- Use GitHub Issues for bugs and feature requests
- Include reproduction steps for bugs
- Check existing issues before creating new ones

## Code of Conduct

Be respectful and constructive. We're all here to build something cool.
