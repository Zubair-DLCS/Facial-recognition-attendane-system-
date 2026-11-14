"""FaceRoll - face recognition attendance for Windows.

Run:  python app.py
"""

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from faceroll import APP_NAME
from faceroll.database import Database
from faceroll.engine import DETECTOR_FILE, RECOGNIZER_FILE
from faceroll.paths import db_path, models_dir, resource_dir
from faceroll.ui.common import AppState
from faceroll.ui.main_window import MainWindow
from faceroll.ui.style import STYLE


def main() -> int:
    if sys.platform == "win32":
        # Own taskbar icon/group instead of python.exe's
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ZubairDLCS.FaceRoll")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    icon = resource_dir() / "assets" / "icon.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    missing = [f for f in (DETECTOR_FILE, RECOGNIZER_FILE) if not (models_dir() / f).exists()]
    if missing:
        QMessageBox.critical(None, APP_NAME, "Model files are missing from the models folder:\n" + "\n".join(missing))
        return 1

    state = AppState(Database(db_path()))
    win = MainWindow(state)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
