.PHONY: dev install lint format typecheck test check clean coverage

# Development server
dev:
	uv run fastapi dev app.py --host 0.0.0.0 --port 5001

# Install dependencies
install:
	uv sync

# Run linter
lint:
	uv run ruff check --fix .
	uv run ruff format .

# Format only (no fixes)
format:
	uv run ruff format .

# Type checking
typecheck:
	uv run ty check

# Run tests
test:
	uv run pytest -v

# Run tests with coverage
coverage:
	uv run pytest --cov=. --cov-report=html --cov-report=xml
	@echo "Coverage report: htmlcov/index.html"

# Run all checks (lint + typecheck + test)
check: lint typecheck test

# Clean build artifacts
clean:
	rm -rf __pycache__ .pytest_cache .ruff_cache htmlcov .coverage coverage.xml
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Help
help:
	@echo "Available targets:"
	@echo "  dev        - Run development server"
	@echo "  install    - Install dependencies"
	@echo "  lint       - Run linter and formatter"
	@echo "  format     - Format code only"
	@echo "  typecheck  - Run type checker"
	@echo "  test       - Run tests"
	@echo "  coverage   - Run tests with coverage report"
	@echo "  check      - Run all checks (lint + typecheck + test)"
	@echo "  clean      - Remove build artifacts"
