"""Smart Home Configuration.

Configuration is loaded from environment variables and .env file.
Copy .env.example to .env and fill in your values.
"""

from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TVDevice(BaseModel):
    """TV device configuration."""

    ip: str
    port: int = 5555
    name: str


class Config(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # TV Devices - JSON string parsed to dict
    tv_devices: dict[str, TVDevice] = Field(default_factory=dict)

    # TP-Link Tapo credentials
    tapo_username: str = ""
    tapo_password: str = ""
    tapo_bulb_ips: list[str] = Field(default_factory=list)

    # Tuya devices - JSON string parsed to dict
    tuya_devices: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # VeSync credentials (for Levoit purifiers)
    vesync_username: str = ""
    vesync_password: str = ""

    @field_validator("tv_devices", mode="before")
    @classmethod
    def parse_tv_devices(cls, v: str | dict) -> dict:
        """Parse TV_DEVICES from JSON string."""
        if isinstance(v, str):
            import json

            try:
                return json.loads(v) if v else {}
            except json.JSONDecodeError:
                return {}
        return v

    @field_validator("tapo_bulb_ips", mode="before")
    @classmethod
    def parse_bulb_ips(cls, v: str | list) -> list:
        """Parse TAPO_BULB_IPS from comma-separated string."""
        if isinstance(v, str):
            return [ip.strip() for ip in v.split(",") if ip.strip()]
        return v

    @field_validator("tuya_devices", mode="before")
    @classmethod
    def parse_tuya_devices(cls, v: str | dict) -> dict:
        """Parse TUYA_DEVICES from JSON string."""
        if isinstance(v, str):
            import json

            try:
                return json.loads(v) if v else {}
            except json.JSONDecodeError:
                return {}
        return v

    def get_tapo_bulbs(self) -> dict[str, dict[str, Any]]:
        """Generate bulb device configs from IP list."""
        bulbs = {}
        for i, ip in enumerate(self.tapo_bulb_ips, 1):
            bulbs[f"bulb_{i}"] = {
                "name": f"L530 Bulb {i}",
                "type": "tapo_bulb",
                "ip": ip,
                "enabled": True,
            }
        return bulbs

    def get_all_devices(self) -> dict[str, dict[str, Any]]:
        """Get all devices as a combined dictionary."""
        devices: dict[str, dict[str, Any]] = {}

        # Add TV devices
        for dev_id, tv in self.tv_devices.items():
            device_type = "firetv" if "fire" in dev_id.lower() else "googletv"
            devices[dev_id] = {
                "name": tv.name,
                "type": device_type,
                "ip": tv.ip,
                "port": tv.port,
                "enabled": True,
            }

        # Add Tapo bulbs
        devices.update(self.get_tapo_bulbs())

        return devices


@lru_cache
def get_config() -> Config:
    """Get cached configuration instance."""
    return Config()
