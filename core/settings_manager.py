from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from core.runtime_paths import user_data_dir


DEFAULT_SETTINGS: dict[str, Any] = {
    "startup": {
        "default_page": "dashboard",
    },
    "window": {
        "remember_geometry": True,
        "start_maximized": False,
        "geometry": "",
    },
    "mtr_defaults": {
        "interval": 0.2,
        "packet_size": 64,
        "dns_enabled": True,
    },
    "app_behavior": {
        "debug_console_output": True,
        "auto_refresh_system_info": True,
    },
    "updates": {
        "check_on_startup": True,
        "skipped_version": "",
    },
    "dashboard": {
        "card_order": ["network_status", "devices_found", "sip_alg", "mtr_trace", "traceroute", "quick_actions"],
    },
}


def _deep_merge(defaults: dict[str, Any], custom: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for key, value in custom.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class SettingsManager:
    """Central JSON-backed app settings manager."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (user_data_dir() / "settings.json")
        self._settings: dict[str, Any] = deepcopy(DEFAULT_SETTINGS)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            self._settings = deepcopy(DEFAULT_SETTINGS)
            self.save()
            return self.snapshot()

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings payload must be a JSON object")
            self._settings = _deep_merge(DEFAULT_SETTINGS, raw)
        except Exception:
            # Corrupt or unreadable settings should not break startup.
            self._settings = deepcopy(DEFAULT_SETTINGS)
            self.save()
        return self.snapshot()

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._settings, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self._settings)

    def reset_to_defaults(self) -> dict[str, Any]:
        self._settings = deepcopy(DEFAULT_SETTINGS)
        self.save()
        return self.snapshot()

    def update(self, partial: dict[str, Any], *, save: bool = True) -> dict[str, Any]:
        self._settings = _deep_merge(self._settings, partial)
        if save:
            self.save()
        return self.snapshot()

    def get(self, *keys: str, default: Any = None) -> Any:
        current: Any = self._settings
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current
