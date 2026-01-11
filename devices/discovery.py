"""TV auto-discovery via mDNS and network scanning."""

import asyncio
import contextlib
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Any

from zeroconf import ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

log = logging.getLogger("discovery")


@dataclass
class DiscoveredTV:
    """A discovered TV device."""

    id: str  # Stable ID (from MAC or IP)
    name: str  # Model name from ADB
    ip: str
    port: int = 5555
    model: str | None = None
    manufacturer: str | None = None
    online: bool = True
    last_seen: float = field(default_factory=time.time)


class TVDiscovery:
    """Discovers Android TV devices on the network."""

    # mDNS service types for Android TV
    SERVICE_TYPES = [
        "_androidtvremote2._tcp.local.",
        "_adb-tls-connect._tcp.local.",
    ]

    CACHE_TTL = 60.0  # Seconds before re-checking offline devices

    def __init__(self) -> None:
        self._devices: dict[str, DiscoveredTV] = {}
        self._zeroconf: AsyncZeroconf | None = None
        self._browsers: list[AsyncServiceBrowser] = []
        self._lock = asyncio.Lock()
        self._scan_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start mDNS discovery and background network scan."""
        log.info("Starting TV discovery...")
        self._zeroconf = AsyncZeroconf()

        for service_type in self.SERVICE_TYPES:
            log.info(f"Browsing mDNS service: {service_type}")
            browser = AsyncServiceBrowser(
                self._zeroconf.zeroconf,
                service_type,
                handlers=[self._on_service_state_change],
            )
            self._browsers.append(browser)

        self._scan_task = asyncio.create_task(self._periodic_scan())
        log.info("TV discovery started")

    async def stop(self) -> None:
        """Stop discovery."""
        log.info("Stopping TV discovery...")
        if self._scan_task:
            self._scan_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scan_task
        for browser in self._browsers:
            await browser.async_cancel()
        if self._zeroconf:
            await self._zeroconf.async_close()
        log.info("TV discovery stopped")

    def get_devices(self) -> dict[str, DiscoveredTV]:
        """Return cached discovered devices."""
        return self._devices.copy()

    def _on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        """Handle mDNS service discovery events."""
        log.info(f"mDNS event: {state_change.name} - {name} ({service_type})")
        asyncio.create_task(self._handle_service_change(zeroconf, service_type, name, state_change))

    async def _handle_service_change(
        self,
        zc: Zeroconf,
        stype: str,
        name: str,
        state: ServiceStateChange,
    ) -> None:
        """Process discovered service."""
        if state == ServiceStateChange.Added:
            if self._zeroconf is None:
                return
            info = await self._zeroconf.async_get_service_info(stype, name)
            if info and info.addresses:
                ip = ".".join(str(b) for b in info.addresses[0])
                port = info.port or 5555
                log.info(f"mDNS found device: {info.name} at {ip}:{port}")
                await self._add_device(ip, port, info.name)
            else:
                log.warning(f"mDNS service {name} has no address info")
        elif state == ServiceStateChange.Removed:
            log.info(f"mDNS device removed: {name}")
            async with self._lock:
                for dev in self._devices.values():
                    if name.startswith(dev.name):
                        dev.online = False

    async def _add_device(self, ip: str, port: int, name: str | None = None) -> DiscoveredTV | None:
        """Add or update a discovered device."""
        log.debug(f"Attempting to add device at {ip}:{port}")
        device_info = await self._get_device_info(ip, port)
        if not device_info:
            log.debug(f"Could not get device info from {ip}:{port}")
            return None

        dev_id = f"tv_{ip.replace('.', '_')}"

        device = DiscoveredTV(
            id=dev_id,
            name=device_info.get("name") or name or f"Android TV ({ip})",
            ip=ip,
            port=port,
            model=device_info.get("model"),
            manufacturer=device_info.get("manufacturer"),
            online=True,
            last_seen=time.time(),
        )

        async with self._lock:
            self._devices[dev_id] = device

        log.info(f"Discovered TV: {device.name} ({device.id}) at {ip}:{port}")
        return device

    async def _get_device_info(self, ip: str, port: int) -> dict[str, Any] | None:
        """Get device info via ADB."""
        addr = f"{ip}:{port}"
        log.debug(f"Connecting to ADB at {addr}...")

        proc = await asyncio.create_subprocess_exec(
            "adb",
            "connect",
            addr,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            output = stdout.decode().strip()
            log.debug(f"ADB connect {addr}: {output}")
            if "connected" not in output.lower() and "already" not in output.lower():
                log.debug(f"ADB connect failed: {output} {stderr.decode()}")
                return None
        except TimeoutError:
            log.debug(f"ADB connect timeout for {addr}")
            return None

        proc = await asyncio.create_subprocess_exec(
            "adb",
            "-s",
            addr,
            "shell",
            "getprop ro.product.model; getprop ro.product.manufacturer",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if proc.returncode == 0:
                lines = stdout.decode().strip().split("\n")
                model = lines[0].strip() if lines else None
                manufacturer = lines[1].strip() if len(lines) > 1 else None
                name = f"{manufacturer} {model}".strip() if manufacturer else model
                log.debug(f"Got device info: {name} (model={model}, mfr={manufacturer})")
                return {"name": name, "model": model, "manufacturer": manufacturer}
        except TimeoutError:
            log.debug(f"ADB shell timeout for {addr}")

        return None

    async def scan_subnet(self, subnet: str | None = None) -> list[DiscoveredTV]:
        """Scan network for ADB devices on port 5555."""
        if not subnet:
            subnet = await self._detect_subnet()
        if not subnet:
            log.warning("Could not detect subnet for scanning")
            return []

        base_ip = subnet.rsplit(".", 1)[0]
        log.info(f"Scanning subnet {subnet} for ADB devices...")

        tasks = []
        for i in range(1, 255):
            ip = f"{base_ip}.{i}"
            tasks.append(self._check_adb_port(ip))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        open_count = sum(1 for r in results if r is True)
        log.info(f"Found {open_count} IPs with port 5555 open")

        found = []
        for i, result in enumerate(results, 1):
            if result is True:
                ip = f"{base_ip}.{i}"
                log.info(f"Port 5555 open on {ip}, attempting ADB connection...")
                device = await self._add_device(ip, 5555)
                if device:
                    found.append(device)

        log.info(f"Subnet scan complete: {len(found)} TVs discovered")
        return found

    async def _check_adb_port(self, ip: str, port: int = 5555) -> bool:
        """Check if ADB port is open."""
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=0.5)
            writer.close()
            await writer.wait_closed()
            return True
        except (TimeoutError, OSError):
            return False

    async def _detect_subnet(self) -> str | None:
        """Detect local subnet from network interfaces."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            subnet = ".".join(local_ip.split(".")[:3]) + ".0/24"
            log.debug(f"Detected local IP: {local_ip}, subnet: {subnet}")
            return subnet
        except Exception as e:
            log.warning(f"Could not detect subnet: {e}")
            return None

    async def _periodic_scan(self) -> None:
        """Periodically scan for devices."""
        while True:
            try:
                await self.scan_subnet()
                log.debug(f"Next scan in 30s. Devices: {len(self._devices)}")
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                log.debug("Periodic scan cancelled")
                break
            except Exception as e:
                log.error(f"Subnet scan error: {e}")
                await asyncio.sleep(10)


_discovery: TVDiscovery | None = None


async def get_discovery() -> TVDiscovery:
    """Get or create the global discovery instance."""
    global _discovery
    if _discovery is None:
        log.info("Initializing global TV discovery instance")
        _discovery = TVDiscovery()
        await _discovery.start()
    return _discovery


async def shutdown_discovery() -> None:
    """Shutdown discovery on app exit."""
    global _discovery
    if _discovery:
        await _discovery.stop()
        _discovery = None
