# Recommended Improvements

This document outlines areas for improvement in the Couch Pilot codebase, organized by priority.

## High Priority

### 1. Testing Coverage

**Current state:** Only 2 tests exist covering trivial endpoints.

**Issues:**
- `tests/test_api.py` - Only tests root and health endpoints
- `tools/tv_tools.py` (1092 lines) - Only URL normalization tested
- `devices/tapo.py` - No tests at all

**Missing test coverage:**
- WebSocket handler (`/ws` endpoint)
- Remote control endpoints (`/api/remote/*`)
- Bulb control endpoints (`/api/bulb/*`)
- Error conditions and timeout scenarios
- Invalid device names
- Concurrent WebSocket connections

**Recommendation:** Expand test coverage to 20+ tests covering all major code paths.

---

### 2. Error Handling

**Issues:**

| Location | Problem |
|----------|---------|
| `app.py:442` | Generic exception returns misleading "selected." message |
| `tools/tv_tools.py:338,821,983` | Subprocess failures not logged before returning |
| `devices/tapo.py:48,60,99` | `except Exception` logs without stack traces |

**Recommendation:** Replace generic `except Exception` with specific exception handlers and include tracebacks in logs.

---

### 3. Logging Inconsistency

**Current state:**
- `logging_config.py` defines structlog setup (never called)
- `app.py:29-33` uses basic `logging.basicConfig()`
- Two competing logging systems

**Recommendation:** Use structlog consistently throughout the application.

---

## Medium Priority

### 4. API Design

**Issues:**
- Inconsistent response formats across endpoints:
  - `{"status": "..."}` (status endpoint)
  - `{"ok": bool}` (remote endpoints)
  - `{"result": [...]}` (tools)
  - `{"apps": [], "error": ""}` (apps endpoint)
- Remote endpoints return `{"ok": false}` with no failure context
- Status endpoint returns HTML string instead of structured data

**Recommendation:** Create Pydantic response models for consistent API responses.

---

### 5. Type Safety

**Issues:**
- Missing return type annotations:
  - `_parse_playback_state()` at `tools/tv_tools.py:191`
  - `_get_package()` at `tools/tv_tools.py:29`
  - `_appletv_component()` at `tools/tv_tools.py:177`
- `dict[str, Any]` used everywhere instead of TypedDict or Pydantic models
- No JSON validation on WebSocket messages (`app.py:170`)

**Recommendation:** Add complete type annotations and use TypedDict/Pydantic for structured data.

---

### 6. Code Duplication

**Issues:**
- `tools/tv_tools.py:120-174` - 9 separate regex patterns for URL normalization
- Duplicate ADB command patterns across `app.py` and `tools/tv_tools.py`
- Identical error response structure repeated in every tool function

**Recommendation:** Extract shared patterns into helper functions or configuration dicts.

---

### 7. Configuration Validation

**Issues:**
- App starts successfully with no TVs configured (silent failure)
- TAPO credentials not validated until first connection attempt
- Hardcoded timeouts (5s, 8s, 3s) with no environment variable control

**Recommendation:** Validate required configuration at startup and log warnings for missing optional config.

---

## Low Priority

### 8. Performance

**Issues:**
- `tools/tv_tools.py:26` - Package cache grows unbounded (no TTL/eviction)
- No connection pooling for ADB (spawns new subprocess per call)
- Up to 15+ ADB calls possible for single play command (`tools/tv_tools.py:352-360`)

**Recommendation:** Add cache eviction, consider connection pooling for frequently-accessed devices.

---

### 9. Async/Concurrency

**Issues:**
- `devices/tapo.py:31-50` - Complex async/sync boundary with potential deadlocks
- Fixed 3 retries with no exponential backoff (`tools/tv_tools.py:624-644`)

**Recommendation:** Simplify async handling, use tenacity or similar for retry logic.

---

### 10. Dependencies

**Issues:**
- `pyproject.toml` requires Python 3.14+ (unreleased version)
- Unused packages: `pychromecast`, `tinytuya`, `pyvesync`, `python-kasa`

**Recommendation:** Lower Python requirement to 3.11+, remove unused dependencies.

---

### 11. Documentation

**Issues:**
- Missing docstrings on complex functions:
  - `build_system_prompt()` in `app.py`
  - `_get_tv_status_message()` in `app.py`
- No OpenAPI/Swagger documentation for REST endpoints
- Complex regex patterns not explained

**Recommendation:** Add docstrings to public functions and enable FastAPI's automatic OpenAPI docs.

---

## Summary Table

| Priority | Category | Effort | Impact |
|----------|----------|--------|--------|
| High | Testing coverage | Medium | High |
| High | Error handling | Medium | High |
| High | Logging consistency | Medium | Medium |
| Medium | API design | Medium | Medium |
| Medium | Type safety | Low | Medium |
| Medium | Code duplication | Low | Medium |
| Medium | Configuration validation | Low | High |
| Low | Performance | High | Low |
| Low | Async/concurrency | Medium | Low |
| Low | Dependencies | Low | Low |
| Low | Documentation | Low | Medium |
