from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QStatusBar, QTabWidget, QVBoxLayout, QWidget

from .. import APP_NAME, AUTHOR, AUTHOR_TITLE, __version__
from ..paths import data_dir
from .attendance_tab import AttendanceTab
from .common import AppState
from .enroll_tab import EnrollTab
from .records_tab import RecordsTab
from .settings_tab import SettingsTab
from .students_tab import StudentsTab


class MainWindow(QMainWindow):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setWindowTitle(f"{APP_NAME} - Face Recognition Attendance")
        self.resize(1280, 780)

        header = QWidget()
        header.setObjectName("header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(18, 10, 18, 10)
        name = QLabel(APP_NAME)
        name.setObjectName("appname")
        credit = QLabel(f"Face recognition attendance  ·  Developed by {AUTHOR}, {AUTHOR_TITLE}")
        credit.setObjectName("credit")
        hl.addWidget(name)
        hl.addSpacing(14)
        hl.addWidget(credit)
        hl.addStretch()

        self.tabs = QTabWidget()
        self.attendance = AttendanceTab(state)
        self.enroll = EnrollTab(state)
        self.students = StudentsTab(state)
        self.records = RecordsTab(state)
        self.settings = SettingsTab(state)
        self.tabs.addTab(self.attendance, "Take Attendance")
        self.tabs.addTab(self.enroll, "Enroll")
        self.tabs.addTab(self.students, "Students")
        self.tabs.addTab(self.records, "Records")
        self.tabs.addTab(self.settings, "Settings")
        self._current = None
        self.tabs.currentChanged.connect(self.on_tab_changed)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(header)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(12, 10, 12, 6)
        il.addWidget(self.tabs)
        bl.addWidget(inner, 1)
        self.setCentralWidget(body)

        sb = QStatusBar()
        sb.showMessage(f"v{__version__}  ·  Data folder: {data_dir()}")
        self.setStatusBar(sb)

        # First run: send the user to Students to create a class.
        if not state.db.classes():
            self.tabs.setCurrentWidget(self.students)
        self.on_tab_changed(self.tabs.currentIndex())

    def on_tab_changed(self, index: int) -> None:
        """Only one tab may hold the webcam at a time."""
        new = self.tabs.widget(index)
        if self._current is not None and self._current is not new and hasattr(self._current, "deactivate"):
            self._current.deactivate()
        self._current = new
        # Students and Settings never use the camera; Enroll and Attendance start it on entry.
        if hasattr(new, "activate") and (new is not self.attendance or state_has_students(self.state)):
            new.activate()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.attendance.shutdown()
        self.enroll.deactivate()
        self.state.db.close()
        super().closeEvent(event)


def state_has_students(state: AppState) -> bool:
    return any(state.db.students(cid) for cid, _ in state.db.classes())
