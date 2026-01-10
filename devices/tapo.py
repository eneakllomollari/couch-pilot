"""TP-Link Tapo smart device controller using the tapo library."""

import asyncio
import socket
import traceback
from typing import Any

import structlog

from .base import BaseDevice

log = structlog.get_logger(__name__)


class TapoBulb(BaseDevice):
    """Controller for TP-Link Tapo L530 smart bulbs."""

    def __init__(self, device_id: str, name: str, ip: str, username: str = "", password: str = ""):
        super().__init__(device_id, name, ip)
        self.username = username
        self.password = password
        self._device = None
        self._client = None
        self._state.update(
            {
                "brightness": 0,
                "color_temp": 0,
                "hue": 0,
                "saturation": 0,
            }
        )

    def _run_async(self, coro):
        """Run async code in sync context.

        Handles the complexity of running async code from sync context,
        whether or not an event loop is already running.
        """
        try:
            # Try to get existing loop
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, coro)
                    return future.result(timeout=15)
            else:
                return asyncio.run(coro)
        except TimeoutError:
            log.warning("Async operation timed out", device=self.device_id, ip=self.ip)
            return None
        except ConnectionError as e:
            log.warning("Connection error", device=self.device_id, ip=self.ip, error=str(e))
            return None
        except Exception as e:
            log.error(
                "Async operation failed",
                device=self.device_id,
                ip=self.ip,
                error=str(e),
                traceback=traceback.format_exc(),
            )
            return None

    async def _get_device(self):
        """Get or create device connection."""
        if self._device is None and self.username and self.password:
            try:
                from tapo import ApiClient

                self._client = ApiClient(self.username, self.password)
                self._device = await self._client.l530(self.ip)
            except ConnectionError as e:
                log.warning(
                    "Tapo connection failed", device=self.device_id, ip=self.ip, error=str(e)
                )
                self._device = None
            except Exception as e:
                log.error(
                    "Tapo device init error",
                    device=self.device_id,
                    ip=self.ip,
                    error=str(e),
                    traceback=traceback.format_exc(),
                )
                self._device = None
        return self._device

    def _check_reachable(self) -> bool:
        """Check if device is reachable on port 80."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((self.ip, 80))
            sock.close()
            return result == 0
        except Exception:
            return False

    def connect(self) -> bool:
        """Connect to Tapo bulb."""
        self._state["online"] = self._check_reachable()
        return self._state["online"]

    def get_state(self) -> dict[str, Any]:
        """Get bulb state."""

        async def _get_state():
            if not self._check_reachable():
                self._state["online"] = False
                return self._state

            device = await self._get_device()
            if device:
                try:
                    info = await device.get_device_info()
                    self._state["online"] = True
                    self._state["on"] = info.device_on
                    self._state["brightness"] = getattr(info, "brightness", 0)
                    self._state["color_temp"] = getattr(info, "color_temp", 0)
                    self._state["hue"] = getattr(info, "hue", 0)
                    self._state["saturation"] = getattr(info, "saturation", 0)
                except Exception as e:
                    log.error(
                        "Tapo get_state error", device=self.device_id, ip=self.ip, error=str(e)
                    )
                    self._state["online"] = False
            return self._state

        result = self._run_async(_get_state())
        return result if result else self._state

    def turn_on(self) -> bool:
        """Turn bulb on."""

        async def _turn_on():
            device = await self._get_device()
            if device:
                await device.on()
                self._state["on"] = True
                return True
            return False

        result = self._run_async(_turn_on())
        return bool(result)

    def turn_off(self) -> bool:
        """Turn bulb off."""

        async def _turn_off():
            device = await self._get_device()
            if device:
                await device.off()
                self._state["on"] = False
                return True
            return False

        result = self._run_async(_turn_off())
        return bool(result)

    def set_brightness(self, level: int) -> bool:
        """Set brightness (1-100)."""

        async def _set():
            device = await self._get_device()
            if device:
                await device.set_brightness(max(1, min(100, level)))
                self._state["brightness"] = level
                return True
            return False

        result = self._run_async(_set())
        return bool(result)

    def set_color(self, hue: int, saturation: int) -> bool:
        """Set color (hue 0-360, saturation 0-100)."""

        async def _set():
            device = await self._get_device()
            if device:
                await device.set_hue_saturation(hue, saturation)
                self._state["hue"] = hue
                self._state["saturation"] = saturation
                return True
            return False

        result = self._run_async(_set())
        return bool(result)

    def set_color_temp(self, temp: int) -> bool:
        """Set color temperature (2500-6500K)."""

        async def _set():
            device = await self._get_device()
            if device:
                await device.set_color_temperature(temp)
                self._state["color_temp"] = temp
                return True
            return False

        result = self._run_async(_set())
        return bool(result)
