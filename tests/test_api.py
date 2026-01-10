"""Tests for FastAPI endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import (
    AppInfo,
    AppsResponse,
    BulbStateResponse,
    BulbToggleResponse,
    CommandResponse,
    HealthResponse,
    StatusResponse,
    app,
)


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


# =============================================================================
# Health & Basic Endpoints
# =============================================================================


def test_root_endpoint(client):
    """Test that root endpoint returns HTML chat page."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_health_endpoint(client):
    """Test health check endpoint returns ok status."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "ok"}
    # Validate against response model
    HealthResponse(**data)


# =============================================================================
# Remote Control Endpoints
# =============================================================================


@patch("app._adb")
def test_remote_navigate_valid_action(mock_adb, client):
    """Test navigate endpoint with valid action."""
    mock_adb.return_value = ("", "", 0)

    response = client.post("/api/remote/navigate", json={"device": "fire_tv", "action": "up"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["error"] is None
    CommandResponse(**data)


@patch("app._adb")
def test_remote_navigate_invalid_action(mock_adb, client):
    """Test navigate endpoint with invalid action."""
    response = client.post("/api/remote/navigate", json={"device": "fire_tv", "action": "invalid"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "Unknown action" in data["error"]
    CommandResponse(**data)


@patch("app._adb")
def test_remote_navigate_adb_failure(mock_adb, client):
    """Test navigate endpoint when ADB command fails."""
    mock_adb.return_value = ("", "ADB error: device offline", 1)

    response = client.post("/api/remote/navigate", json={"device": "fire_tv", "action": "select"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "ADB error" in data["error"]
    CommandResponse(**data)


@patch("app._adb")
def test_remote_play_pause(mock_adb, client):
    """Test play/pause endpoint."""
    mock_adb.return_value = ("", "", 0)

    response = client.post("/api/remote/play_pause", json={"device": "fire_tv"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    CommandResponse(**data)


@patch("app._adb")
def test_remote_power(mock_adb, client):
    """Test power toggle endpoint."""
    mock_adb.return_value = ("", "", 0)

    response = client.post("/api/remote/power", json={"device": "fire_tv"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    CommandResponse(**data)


@patch("app._adb")
def test_remote_volume_up(mock_adb, client):
    """Test volume up endpoint."""
    mock_adb.return_value = ("", "", 0)

    response = client.post("/api/remote/volume", json={"device": "fire_tv", "action": "up"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    CommandResponse(**data)


@patch("app._adb")
def test_remote_volume_invalid_action(mock_adb, client):
    """Test volume with invalid action."""
    response = client.post("/api/remote/volume", json={"device": "fire_tv", "action": "invalid"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "Unknown" in data["error"]


@patch("app._adb")
def test_remote_launch_app(mock_adb, client):
    """Test app launch endpoint."""
    mock_adb.return_value = ("", "", 0)

    response = client.post(
        "/api/remote/launch", json={"device": "fire_tv", "action": "com.netflix.ninja"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    CommandResponse(**data)


def test_remote_launch_no_app(client):
    """Test launch endpoint without app name."""
    response = client.post("/api/remote/launch", json={"device": "fire_tv"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "required" in data["error"].lower()


# =============================================================================
# TV Status Endpoint
# =============================================================================


@patch("app._adb")
def test_remote_status_tv_on(mock_adb, client):
    """Test status endpoint when TV is on."""
    mock_adb.return_value = (
        "mWakefulness=Awake\nmCurrentFocus=Window{com.netflix.ninja/.MainActivity}",
        "",
        0,
    )

    with patch("app.get_config") as mock_config:
        mock_tv = MagicMock()
        mock_tv.name = "Test TV"
        mock_tv.ip = "192.168.1.100"
        mock_tv.port = 5555
        mock_config.return_value.tv_devices = {"fire_tv": mock_tv}

        response = client.get("/api/remote/status/fire_tv")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "Test TV" in data["status"]
        StatusResponse(**data)


@patch("app._adb")
def test_remote_status_tv_off(mock_adb, client):
    """Test status endpoint when TV is off."""
    mock_adb.return_value = ("mWakefulness=Asleep", "", 0)

    with patch("app.get_config") as mock_config:
        mock_tv = MagicMock()
        mock_tv.name = "Test TV"
        mock_tv.ip = "192.168.1.100"
        mock_tv.port = 5555
        mock_config.return_value.tv_devices = {"fire_tv": mock_tv}

        response = client.get("/api/remote/status/fire_tv")
        assert response.status_code == 200
        data = response.json()
        assert "off" in data["status"].lower()


# =============================================================================
# Apps List Endpoint
# =============================================================================


@patch("app._adb")
def test_remote_list_apps(mock_adb, client):
    """Test list apps endpoint."""
    mock_adb.return_value = (
        "package:com.netflix.ninja\npackage:com.google.android.youtube.tv\n",
        "",
        0,
    )

    response = client.get("/api/remote/apps/fire_tv")
    assert response.status_code == 200
    data = response.json()
    assert "apps" in data
    assert len(data["apps"]) >= 1
    AppsResponse(**data)


@patch("app._adb")
def test_remote_list_apps_none_found(mock_adb, client):
    """Test list apps endpoint when no streaming apps installed."""
    mock_adb.return_value = ("package:com.example.app\n", "", 0)

    response = client.get("/api/remote/apps/fire_tv")
    assert response.status_code == 200
    data = response.json()
    assert data["apps"] == []


@patch("app._get_device_addr")
def test_remote_list_apps_unknown_device(mock_get_addr, client):
    """Test list apps endpoint with unknown device."""
    mock_get_addr.side_effect = ValueError("Unknown device")

    response = client.get("/api/remote/apps/unknown_device")
    assert response.status_code == 200
    data = response.json()
    assert data["apps"] == []
    assert data["configured"] is False


# =============================================================================
# Bulb Control Endpoints
# =============================================================================


@patch("app.get_bulb_instance")
def test_bulb_toggle_on(mock_get_bulb, client):
    """Test bulb toggle endpoint (off -> on)."""
    mock_bulb = MagicMock()
    mock_bulb.get_state.return_value = {"on": False}
    mock_bulb.turn_on.return_value = True
    mock_get_bulb.return_value = mock_bulb

    response = client.post("/api/bulb/toggle", json={"device": "bulb_1", "action": "toggle"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["state"] == "on"
    BulbToggleResponse(**data)


@patch("app.get_bulb_instance")
def test_bulb_toggle_off(mock_get_bulb, client):
    """Test bulb toggle endpoint (on -> off)."""
    mock_bulb = MagicMock()
    mock_bulb.get_state.return_value = {"on": True}
    mock_bulb.turn_off.return_value = True
    mock_get_bulb.return_value = mock_bulb

    response = client.post("/api/bulb/toggle", json={"device": "bulb_1", "action": "toggle"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["state"] == "off"


@patch("app.get_bulb_instance")
def test_bulb_toggle_unknown_bulb(mock_get_bulb, client):
    """Test bulb toggle with unknown bulb."""
    mock_get_bulb.return_value = None

    response = client.post("/api/bulb/toggle", json={"device": "unknown", "action": "toggle"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "Unknown bulb" in data["error"]


@patch("app.get_bulb_instance")
def test_bulb_control_brightness(mock_get_bulb, client):
    """Test bulb brightness control."""
    mock_bulb = MagicMock()
    mock_bulb.set_brightness.return_value = True
    mock_get_bulb.return_value = mock_bulb

    response = client.post(
        "/api/bulb/control",
        json={"device": "bulb_1", "action": "brightness", "brightness": 50},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    CommandResponse(**data)


@patch("app.get_bulb_instance")
def test_bulb_control_color(mock_get_bulb, client):
    """Test bulb color control."""
    mock_bulb = MagicMock()
    mock_bulb.set_color.return_value = True
    mock_get_bulb.return_value = mock_bulb

    response = client.post(
        "/api/bulb/control",
        json={"device": "bulb_1", "action": "color", "hue": 180, "saturation": 100},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True


@patch("app.get_bulb_instance")
def test_bulb_control_invalid_action(mock_get_bulb, client):
    """Test bulb control with invalid action."""
    mock_bulb = MagicMock()
    mock_get_bulb.return_value = mock_bulb

    response = client.post("/api/bulb/control", json={"device": "bulb_1", "action": "invalid"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "Invalid action" in data["error"]


@patch("app.get_bulb_instance")
def test_bulb_state(mock_get_bulb, client):
    """Test get bulb state endpoint."""
    mock_bulb = MagicMock()
    mock_bulb.get_state.return_value = {"on": True, "brightness": 80}
    mock_get_bulb.return_value = mock_bulb

    response = client.get("/api/bulb/bulb_1/state")
    assert response.status_code == 200
    data = response.json()
    assert data["device"] == "bulb_1"
    assert data["state"]["on"] is True
    BulbStateResponse(**data)


@patch("app.get_bulb_instance")
def test_bulb_state_unknown(mock_get_bulb, client):
    """Test get bulb state with unknown bulb."""
    mock_get_bulb.return_value = None

    response = client.get("/api/bulb/unknown/state")
    assert response.status_code == 200
    data = response.json()
    assert "Unknown bulb" in data["error"]


# =============================================================================
# Response Model Validation
# =============================================================================


def test_health_response_model():
    """Test HealthResponse model validation."""
    response = HealthResponse(status="ok")
    assert response.status == "ok"


def test_command_response_model():
    """Test CommandResponse model validation."""
    # Success case
    response = CommandResponse(ok=True)
    assert response.ok is True
    assert response.error is None

    # Failure case
    response = CommandResponse(ok=False, error="Some error")
    assert response.ok is False
    assert response.error == "Some error"


def test_apps_response_model():
    """Test AppsResponse model validation."""
    apps = [AppInfo(package="com.netflix.ninja", name="Netflix", logo="https://...")]
    response = AppsResponse(apps=apps)
    assert len(response.apps) == 1
    assert response.apps[0].name == "Netflix"


def test_bulb_state_response_model():
    """Test BulbStateResponse model validation."""
    response = BulbStateResponse(device="bulb_1", state={"on": True})
    assert response.device == "bulb_1"
    assert response.state["on"] is True
