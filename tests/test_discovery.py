"""Tests for TV auto-discovery."""

import pytest

from devices.discovery import DiscoveredTV, TVDiscovery


def test_discovered_tv_dataclass():
    """Test DiscoveredTV dataclass defaults."""
    tv = DiscoveredTV(id="test", name="Test TV", ip="192.168.1.100")
    assert tv.port == 5555
    assert tv.online is True
    assert tv.model is None
    assert tv.manufacturer is None


def test_discovered_tv_with_all_fields():
    """Test DiscoveredTV with all fields specified."""
    tv = DiscoveredTV(
        id="tv_192_168_1_100",
        name="Living Room TV",
        ip="192.168.1.100",
        port=5555,
        model="AFTMM",
        manufacturer="Amazon",
        online=True,
    )
    assert tv.id == "tv_192_168_1_100"
    assert tv.name == "Living Room TV"
    assert tv.model == "AFTMM"
    assert tv.manufacturer == "Amazon"


@pytest.mark.asyncio
async def test_detect_subnet():
    """Test subnet detection returns valid format or None."""
    discovery = TVDiscovery()
    subnet = await discovery._detect_subnet()
    # Should either be None (if no network) or end with /24
    assert subnet is None or subnet.endswith("/24")


@pytest.mark.asyncio
async def test_check_adb_port_timeout():
    """Test ADB port check times out quickly for unreachable IPs."""
    discovery = TVDiscovery()
    # Non-routable IP should timeout quickly
    result = await discovery._check_adb_port("10.255.255.1")
    assert result is False


@pytest.mark.asyncio
async def test_check_adb_port_invalid_port():
    """Test ADB port check with invalid port."""
    discovery = TVDiscovery()
    # Localhost with unlikely port should fail
    result = await discovery._check_adb_port("127.0.0.1", port=59999)
    assert result is False


def test_tv_discovery_service_types():
    """Test that TVDiscovery has correct mDNS service types."""
    assert "_androidtvremote2._tcp.local." in TVDiscovery.SERVICE_TYPES
    assert "_adb-tls-connect._tcp.local." in TVDiscovery.SERVICE_TYPES


def test_tv_discovery_cache_ttl():
    """Test that cache TTL is reasonable."""
    assert TVDiscovery.CACHE_TTL > 0
    assert TVDiscovery.CACHE_TTL <= 300  # Not more than 5 minutes


@pytest.mark.asyncio
async def test_get_devices_returns_copy():
    """Test that get_devices returns a copy, not the internal dict."""
    discovery = TVDiscovery()
    devices1 = discovery.get_devices()
    devices2 = discovery.get_devices()
    # Should be equal but not the same object
    assert devices1 == devices2
    assert devices1 is not discovery._devices
