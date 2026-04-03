import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ui.app_shell import AppShellWindow
from ui.launcher import LauncherWindow


def _maybe_macos_relaunch_elevated() -> None:
    """
    MTR uses raw ICMP sockets on macOS, which requires root. Prompt via osascript
    and relaunch with administrator privileges; this process then exits.
    """
    if platform.system() != "Darwin" or os.geteuid() == 0:
        return
    if getattr(sys, "frozen", False):
        cmd = shlex.join(sys.argv)
    else:
        cmd = shlex.join([sys.executable, *sys.argv])
    inner = cmd.replace("\\", "\\\\").replace('"', '\\"')
    script = f'do shell script "{inner}" with administrator privileges'
    try:
        subprocess.run(["osascript", "-e", script])
    except Exception:
        pass
    sys.exit()


def main() -> int:
    _maybe_macos_relaunch_elevated()

    app = QApplication(sys.argv)

    # Set application icon (works for taskbar, window title bar, alt-tab)
    if getattr(sys, "frozen", False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent

    if sys.platform == "darwin":
        # macOS: .icns if present; else bundle icon from .app
        icns_path = base_path / "assets" / "app.icns"
        if icns_path.exists():
            app.setWindowIcon(QIcon(str(icns_path)))
    else:
        icon_path = base_path / "assets" / "app.ico"
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))

    launcher = LauncherWindow()

    def _open_app() -> None:
        window = AppShellWindow()
        window.show()
        # prevent garbage collection
        app.setProperty("_main_window", window)

    launcher.launch_app.connect(_open_app)
    launcher.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
