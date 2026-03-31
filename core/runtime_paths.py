from __future__ import annotations

import os
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resource_path(relative_path: str) -> Path:
    """
    Resolve a bundled/resource file path for both source and PyInstaller builds.
    """
    base_dir = getattr(sys, "_MEIPASS", None)
    if base_dir:
        return Path(base_dir) / relative_path
    return project_root() / relative_path


def user_data_dir(app_name: str = "Advanced-IP-Scanner") -> Path:
    """
    Writable runtime directory for logs/temp files.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        target = Path(base) / app_name
    else:
        target = Path.home() / f".{app_name.lower().replace(' ', '-')}"
    target.mkdir(parents=True, exist_ok=True)
    return target
