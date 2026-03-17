"""YAML configuration loader/saver."""

import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .credentials import load_app_key, store_app_key

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@dataclass
class LightMapping:
    monitor: int            # 1-based mss monitor index
    light_id: str
    light_name: str = ""    # Display name from bridge
    reversed: bool = False
    zone_count: int = 5     # Number of gradient zones (from bridge discovery)


@dataclass
class AvailableLight:
    id: str
    name: str
    zone_count: int


@dataclass
class SyncConfig:
    fps: int = 12
    smoothing_alpha: float = 0.4
    delta_threshold: float = 5.0
    brightness: float = 60.0          # Static brightness / opacity (0-100)
    margin_percent: float = 5.0
    downsample_stride: int = 4


@dataclass
class BridgeConfig:
    ip: str = ""
    app_key: str = ""  # Loaded from/stored to Keychain, NOT written to config file


@dataclass
class AppConfig:
    bridge: BridgeConfig = field(default_factory=BridgeConfig)
    profiles: dict[str, list[LightMapping]] = field(default_factory=dict)
    available_lights: list[AvailableLight] = field(default_factory=list)
    sync: SyncConfig = field(default_factory=SyncConfig)

    def get_mappings_for_fingerprint(self, fingerprint: str) -> list[LightMapping]:
        """Get light mappings for a monitor fingerprint, or empty list if none."""
        return self.profiles.get(fingerprint, [])

    def set_mappings_for_fingerprint(self, fingerprint: str, mappings: list[LightMapping]):
        """Store light mappings for a monitor fingerprint."""
        self.profiles[fingerprint] = mappings


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from YAML file. App key is loaded from Keychain."""
    path = path or DEFAULT_CONFIG_PATH
    config = AppConfig()

    if not path.exists():
        logger.info("No config file found at %s, using defaults", path)
        # Still try to load app_key from keychain
        config.bridge.app_key = load_app_key()
        return config

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    bridge_data = data.get("bridge", {})
    config.bridge = BridgeConfig(
        ip=bridge_data.get("ip", ""),
        app_key="",  # Never read from file
    )

    # Load app_key from Keychain
    config.bridge.app_key = load_app_key()

    # Migrate: if app_key is in config file but not in Keychain, move it
    file_app_key = bridge_data.get("app_key", "")
    if file_app_key and not config.bridge.app_key:
        logger.info("Migrating app_key from config file to Keychain")
        store_app_key(file_app_key)
        config.bridge.app_key = file_app_key
        # Re-save config without the app_key
        # (will happen on next save_config call)

    # Load profiles (new format)
    profiles_data = data.get("profiles", {})
    for fingerprint, mappings in profiles_data.items():
        config.profiles[str(fingerprint)] = [
            LightMapping(
                monitor=m.get("monitor", 1),
                light_id=m.get("light_id", ""),
                light_name=m.get("light_name", ""),
                reversed=m.get("reversed", False),
                zone_count=m.get("zone_count", 5),
            )
            for m in (mappings or [])
            if isinstance(m, dict)
        ]

    # Backwards compat: migrate old flat "lights" list
    if not config.profiles and "lights" in data:
        lights_data = data.get("lights", [])
        if isinstance(lights_data, list) and lights_data:
            config.profiles["migrated"] = [
                LightMapping(
                    monitor=m.get("monitor", 1),
                    light_id=m.get("light_id", ""),
                    light_name=m.get("light_name", ""),
                    reversed=m.get("reversed", False),
                    zone_count=m.get("zone_count", 5),
                )
                for m in lights_data
                if isinstance(m, dict)
            ]
            logger.info("Migrated old lights config to profile 'migrated'")

    # Available lights
    for item in data.get("available_lights", []):
        if isinstance(item, dict):
            config.available_lights.append(AvailableLight(
                id=item.get("id", ""),
                name=item.get("name", ""),
                zone_count=item.get("zone_count", 7),
            ))

    sync_data = data.get("sync", {})
    config.sync = SyncConfig(
        fps=sync_data.get("fps", 12),
        smoothing_alpha=sync_data.get("smoothing_alpha", 0.4),
        delta_threshold=sync_data.get("delta_threshold", 5.0),
        brightness=sync_data.get("brightness", 60.0),
        margin_percent=sync_data.get("margin_percent", 5.0),
        downsample_stride=sync_data.get("downsample_stride", 4),
    )

    return config


def save_config(config: AppConfig, path: Path | None = None):
    """Save configuration to YAML file. App key is stored in Keychain, not the file."""
    path = path or DEFAULT_CONFIG_PATH

    # Store app_key in Keychain
    if config.bridge.app_key:
        store_app_key(config.bridge.app_key)

    data = {
        "bridge": {
            "ip": config.bridge.ip,
            # app_key deliberately omitted — stored in Keychain
        },
        "profiles": {
            fingerprint: [
                {
                    "monitor": m.monitor,
                    "light_id": m.light_id,
                    "light_name": m.light_name,
                    "reversed": m.reversed,
                    "zone_count": m.zone_count,
                }
                for m in mappings
            ]
            for fingerprint, mappings in config.profiles.items()
        },
        "available_lights": [
            {
                "id": l.id,
                "name": l.name,
                "zone_count": l.zone_count,
            }
            for l in config.available_lights
        ],
        "sync": {
            "fps": config.sync.fps,
            "smoothing_alpha": config.sync.smoothing_alpha,
            "delta_threshold": config.sync.delta_threshold,
            "brightness": config.sync.brightness,
            "margin_percent": config.sync.margin_percent,
            "downsample_stride": config.sync.downsample_stride,
        },
    }

    # Write with secure permissions (owner read/write only)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    os.chmod(path, 0o600)

    logger.info("Config saved to %s", path)
