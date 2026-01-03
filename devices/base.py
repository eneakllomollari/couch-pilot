"""Base device class for all smart home devices."""

from abc import ABC, abstractmethod
from typing import Any


class BaseDevice(ABC):
    """Abstract base class for smart home devices."""

    def __init__(self, device_id: str, name: str, ip: str):
        self.device_id = device_id
        self.name = name
        self.ip = ip
        self._state = {"online": False, "on": False}

    @abstractmethod
    def connect(self) -> bool:
        """Connect to the device."""
        pass

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """Get current device state."""
        pass

    @abstractmethod
    def turn_on(self) -> bool:
        """Turn the device on."""
        pass

    @abstractmethod
    def turn_off(self) -> bool:
        """Turn the device off."""
        pass

    def to_dict(self) -> dict[str, Any]:
        """Return device info as dictionary."""
        return {
            "id": self.device_id,
            "name": self.name,
            "ip": self.ip,
            "type": self.__class__.__name__,
            "state": self._state,
        }
