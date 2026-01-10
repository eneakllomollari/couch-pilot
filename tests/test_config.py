"""Tests for configuration validation."""

from config import Config, TVDevice


def test_config_empty_tv_devices():
    """Test config validation warns when no TV devices configured."""
    config = Config(tv_devices={})
    warnings = config.validate_config()
    assert any("No TV devices" in w for w in warnings)


def test_config_with_tv_devices():
    """Test config validation passes with TV devices."""
    config = Config(tv_devices={"fire_tv": TVDevice(ip="192.168.1.100", port=5555, name="Test TV")})
    warnings = config.validate_config()
    assert not any("No TV devices" in w for w in warnings)


def test_config_tapo_credentials_warning():
    """Test config validation warns when bulb IPs set without credentials."""
    config = Config(
        tv_devices={},
        tapo_bulb_ips_raw="192.168.1.50",
        tapo_username="",
        tapo_password="",
    )
    warnings = config.validate_config()
    assert any("TAPO_USERNAME" in w for w in warnings)
    assert any("TAPO_PASSWORD" in w for w in warnings)


def test_config_tapo_complete():
    """Test config validation passes with complete Tapo setup."""
    config = Config(
        tv_devices={},
        tapo_bulb_ips_raw="192.168.1.50",
        tapo_username="user@example.com",
        tapo_password="secret",
    )
    warnings = config.validate_config()
    assert not any("TAPO" in w for w in warnings)


def test_config_vesync_incomplete():
    """Test config validation warns when VeSync username set without password."""
    config = Config(
        tv_devices={},
        vesync_username="user@example.com",
        vesync_password="",
    )
    warnings = config.validate_config()
    assert any("VESYNC_PASSWORD" in w for w in warnings)


def test_tv_device_model():
    """Test TVDevice model defaults."""
    tv = TVDevice(ip="192.168.1.100", name="Test TV")
    assert tv.port == 5555  # Default port


def test_config_get_all_devices():
    """Test get_all_devices includes TVs and bulbs."""
    config = Config(
        tv_devices={"fire_tv": TVDevice(ip="192.168.1.100", port=5555, name="Test TV")},
        tapo_bulb_ips_raw="192.168.1.50,192.168.1.51",
    )
    devices = config.get_all_devices()

    # Should have 1 TV + 2 bulbs
    assert len(devices) == 3
    assert "fire_tv" in devices
    assert "bulb_1" in devices
    assert "bulb_2" in devices


def test_config_get_tapo_bulbs():
    """Test get_tapo_bulbs parsing."""
    config = Config(tapo_bulb_ips_raw="192.168.1.50, 192.168.1.51 ")
    bulbs = config.get_tapo_bulbs()

    assert len(bulbs) == 2
    assert bulbs["bulb_1"]["ip"] == "192.168.1.50"
    assert bulbs["bulb_2"]["ip"] == "192.168.1.51"


def test_config_tapo_bulb_ips_empty():
    """Test tapo_bulb_ips returns empty list when not set."""
    config = Config(tapo_bulb_ips_raw="")
    assert config.tapo_bulb_ips == []


def test_config_parse_tv_devices_json():
    """Test TV devices can be parsed from JSON string."""
    config = Config(tv_devices='{"fire_tv": {"ip": "192.168.1.100", "port": 5555, "name": "Test"}}')
    assert "fire_tv" in config.tv_devices
    assert config.tv_devices["fire_tv"].ip == "192.168.1.100"


def test_config_parse_tv_devices_invalid_json():
    """Test invalid JSON for TV devices returns empty dict."""
    config = Config(tv_devices="not valid json")
    assert config.tv_devices == {}
