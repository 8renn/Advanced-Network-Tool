from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import urllib.request
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from urllib.error import URLError

from PySide6.QtCore import QObject, Signal

from core.logger import logger
from core.version import GITHUB_REPO, __version__


@dataclass(slots=True)
class AssetInfo:
    name: str
    download_url: str
    size: int
    content_type: str


@dataclass(slots=True)
class ReleaseInfo:
    tag: str
    version: str
    name: str
    body: str
    html_url: str
    published_at: str
    assets: list[AssetInfo]


def parse_semver(tag: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (tag or "").strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_newer(remote_tag: str, local_version: str = __version__) -> bool:
    remote = parse_semver(remote_tag)
    local = parse_semver(local_version)
    if remote is None or local is None:
        return False
    return remote > local


def _gh_get(path: str):
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(
        url=url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "AdvancedNetworkTool-Updater",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = resp.read().decode("utf-8")
    return json.loads(payload)


def fetch_latest_release(repo: str = GITHUB_REPO) -> ReleaseInfo | None:
    try:
        data = _gh_get(f"/repos/{repo}/releases/latest")
        assets: list[AssetInfo] = []
        for a in data.get("assets", []):
            assets.append(
                AssetInfo(
                    name=str(a["name"]),
                    download_url=str(a["browser_download_url"]),
                    size=int(a["size"]),
                    content_type=str(a.get("content_type", "")),
                )
            )
        tag = str(data["tag_name"])
        return ReleaseInfo(
            tag=tag,
            version=tag.lstrip("v"),
            name=str(data.get("name", "")),
            body=str(data.get("body", "")),
            html_url=str(data.get("html_url", "")),
            published_at=str(data.get("published_at", "")),
            assets=assets,
        )
    except (URLError, OSError, JSONDecodeError, KeyError) as e:
        logger.warning("Updater: failed to fetch latest release: %s", e)
        return None


def pick_update_asset(release: ReleaseInfo) -> AssetInfo | None:
    if sys.platform == "darwin":
        # macOS: no auto-update; user installs from GitHub releases
        logger.info(
            "Updater: Auto-update is not available on macOS. "
            "Please download the latest version from GitHub."
        )
        return None
    if sys.platform != "win32":
        return None

    exe_assets = [a for a in release.assets if a.name.lower().endswith(".exe")]
    if not exe_assets:
        return None

    preferred = [
        a for a in exe_assets if ("setup" in a.name.lower() or "install" in a.name.lower())
    ]
    return preferred[0] if preferred else exe_assets[0]


def download_asset(asset: AssetInfo, dest_dir=None, progress_cb=None) -> Path:
    target_dir = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp(prefix="ant_update_"))
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / asset.name

    req = urllib.request.Request(
        url=asset.download_url,
        headers={"User-Agent": "AdvancedNetworkTool-Updater"},
        method="GET",
    )

    downloaded = 0
    hasher = hashlib.sha256()
    total = int(asset.size or 0)
    chunk_size = 64 * 1024
    with urllib.request.urlopen(req, timeout=15) as resp:
        with out_path.open("wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                if progress_cb is not None:
                    progress_cb(downloaded, total)

    if total > 0 and downloaded != total:
        raise IOError(f"Downloaded size mismatch: got {downloaded}, expected {total}")

    checksum = hasher.hexdigest()
    logger.info("Updater: downloaded %s (%d bytes, sha256=%s)", out_path, downloaded, checksum)
    return out_path


def _running_exe_path() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def _write_swap_script(old_exe: Path, new_exe: Path, script_dir: Path) -> Path:
    script_dir.mkdir(parents=True, exist_ok=True)
    bat_path = script_dir / "ant_swap_update.bat"
    pid = os.getpid()
    script = textwrap.dedent(
        f"""\
        @echo off
        setlocal
        :waitloop
        tasklist /FI "PID eq {pid}" | find "{pid}" >nul
        if not errorlevel 1 (
            timeout /T 1 /NOBREAK >nul
            goto waitloop
        )
        copy /Y "{new_exe}" "{old_exe}" >nul
        start "" "{old_exe}"
        del "%~f0"
        """
    )
    bat_path.write_text(script, encoding="utf-8")
    return bat_path


def apply_portable_update(downloaded_exe: Path) -> bool:
    if sys.platform != "win32":
        return False

    current = _running_exe_path()
    if current is None:
        logger.info("Updater: portable apply skipped (not frozen/dev mode)")
        return False

    bat = _write_swap_script(
        old_exe=current,
        new_exe=downloaded_exe.resolve(),
        script_dir=Path(tempfile.gettempdir()) / "ant_update_swap",
    )
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["cmd.exe", "/C", str(bat)],
        creationflags=create_no_window,
    )
    logger.info("Updater: launched portable swap script: %s", bat)
    return True


def apply_installer_update(installer_path: Path) -> bool:
    if sys.platform != "win32":
        return False

    detached = getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [str(installer_path)],
        creationflags=detached,
    )
    logger.info("Updater: launched installer: %s", installer_path)
    return True


def apply_update(downloaded_path: Path, asset: AssetInfo) -> bool:
    if sys.platform != "win32":
        return False

    name = asset.name.lower()
    if "setup" in name or "install" in name:
        return apply_installer_update(downloaded_path)
    return apply_portable_update(downloaded_path)


class UpdateCheckWorker(QObject):
    finished = Signal(object)
    error = Signal(str)

    def run(self) -> None:
        try:
            release = fetch_latest_release()
            if release and is_newer(release.tag):
                self.finished.emit(release)
            else:
                self.finished.emit(None)
        except Exception as e:
            self.error.emit(str(e))


class DownloadWorker(QObject):
    progress = Signal(int, int)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, asset: AssetInfo) -> None:
        super().__init__()
        self._asset = asset

    def run(self) -> None:
        try:
            path = download_asset(
                self._asset,
                progress_cb=lambda done, total: self.progress.emit(int(done), int(total)),
            )
            self.finished.emit(path)
        except Exception as e:
            self.error.emit(str(e))
