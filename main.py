import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ui.app_shell import AppShellWindow


def main() -> int:
    app = QApplication(sys.argv)

    # Set application icon (works for taskbar, window title bar, alt-tab)
    if getattr(sys, "frozen", False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent

    icon_path = base_path / "assets" / "app.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = AppShellWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())