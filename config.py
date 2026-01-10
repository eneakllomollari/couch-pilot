"""Smart Home Configuration.

Configuration is loaded from environment variables and .env file.
Copy .env.example to .env and fill in your values.
"""

from functools import lru_cache
from typing import Any

import structlog
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = structlog.get_logger(__name__)


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
        populate_by_name=True,
    )

    # TV Devices - JSON string parsed to dict
    tv_devices: dict[str, TVDevice] = Field(default_factory=dict)

    # TP-Link Tapo credentials
    tapo_username: str = ""
    tapo_password: str = ""
    tapo_bulb_ips_raw: str = Field(default="", alias="TAPO_BULB_IPS")

    @property
    def tapo_bulb_ips(self) -> list[str]:
        """Parse TAPO_BULB_IPS from comma-separated string."""
        if not self.tapo_bulb_ips_raw:
            return []
        return [ip.strip() for ip in self.tapo_bulb_ips_raw.split(",") if ip.strip()]

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

    def validate_config(self) -> list[str]:
        """Validate configuration and return list of warnings.

        Returns:
            List of warning messages for missing or incomplete configuration.
        """
        warnings = []

        # Check TV devices
        if not self.tv_devices:
            warnings.append("No TV devices configured. Set TV_DEVICES environment variable.")

        # Check Tapo credentials if bulbs are configured
        if self.tapo_bulb_ips:
            if not self.tapo_username:
                warnings.append("TAPO_USERNAME not set but bulb IPs are configured.")
            if not self.tapo_password:
                warnings.append("TAPO_PASSWORD not set but bulb IPs are configured.")

        # Check VeSync credentials if configured
        if self.vesync_username and not self.vesync_password:
            warnings.append("VESYNC_USERNAME set but VESYNC_PASSWORD is missing.")

        return warnings

    def log_config_status(self) -> None:
        """Log configuration status at startup."""
        warnings = self.validate_config()

        # Log configuration summary
        log.info(
            "Configuration loaded",
            tv_count=len(self.tv_devices),
            bulb_count=len(self.tapo_bulb_ips),
            tuya_count=len(self.tuya_devices),
        )

        # Log TV devices
        for device_id, tv in self.tv_devices.items():
            log.info("TV configured", device_id=device_id, name=tv.name, ip=tv.ip, port=tv.port)

        # Log warnings
        for warning in warnings:
            log.warning(warning)


@lru_cache
def get_config() -> Config:
    return Config()
