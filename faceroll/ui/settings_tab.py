"""Camera choice, recognition sensitivity, data folder and backup."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, AUTHOR, AUTHOR_TITLE, REPO_URL, __version__
from ..camera import list_cameras
from ..paths import data_dir, db_path
from .common import AppState


class SettingsTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state

        # camera
        self.camera = QComboBox()
        self.camera.addItem(f"Camera {state.camera_index}", state.camera_index)
        scan = QPushButton("Find cameras")
        scan.clicked.connect(self.scan)
        cam_row = QHBoxLayout()
        cam_row.addWidget(self.camera, 1)
        cam_row.addWidget(scan)

        # recognition
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.30, 0.80)
        self.threshold.setSingleStep(0.01)
        self.threshold.setDecimals(2)
        self.threshold.setValue(state.threshold)
        self.threshold.setToolTip("Higher = stricter (fewer wrong matches, more 'Unknown'). Default 0.40.")
        self.confirm = QSpinBox()
        self.confirm.setRange(1, 15)
        self.confirm.setValue(state.confirm_frames)
        self.confirm.setToolTip("How many consecutive frames must agree before a student is marked present.")
        self.min_face = QSpinBox()
        self.min_face.setRange(20, 200)
        self.min_face.setSuffix(" px")
        self.min_face.setValue(state.min_face)
        self.min_face.setToolTip("Faces smaller than this are ignored. Lower it for a large room.")
        self.samples = QSpinBox()
        self.samples.setRange(3, 30)
        self.samples.setValue(state.samples_per_student)
        self.institution = QLineEdit(state.institution)
        self.institution.setPlaceholderText("Printed on exported registers (optional)")

        for w in (self.threshold, self.confirm, self.min_face, self.samples):
            w.setMaximumWidth(160)
        form = QFormLayout()
        form.addRow("Camera:", cam_row)
        form.addRow("Match threshold:", self.threshold)
        form.addRow("Confirm frames:", self.confirm)
        form.addRow("Minimum face size:", self.min_face)
        form.addRow("Samples per student:", self.samples)
        form.addRow("Institution:", self.institution)
        save = QPushButton("Save settings")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        defaults = QPushButton("Restore defaults")
        defaults.clicked.connect(self.restore_defaults)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(defaults)
        row.addWidget(save)
        form.addRow(row)
        rec_box = QGroupBox("Camera and recognition")
        rec_box.setLayout(form)

        # data
        path_lbl = QLabel(str(data_dir()))
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        open_b = QPushButton("Open data folder")
        open_b.clicked.connect(self.open_folder)
        backup_b = QPushButton("Back up database…")
        backup_b.clicked.connect(self.backup)
        restore_b = QPushButton("Restore from backup…")
        restore_b.clicked.connect(self.restore)
        drow = QHBoxLayout()
        drow.addWidget(open_b)
        drow.addWidget(backup_b)
        drow.addWidget(restore_b)
        drow.addStretch()
        dlay = QVBoxLayout()
        dlay.addWidget(path_lbl)
        dlay.addLayout(drow)
        privacy = QLabel(
            "All face data stays on this computer in the database above; nothing is uploaded. "
            "Face templates are biometric data: inform students (or parents) and get consent before enrolling, "
            "and delete a student's record when they leave."
        )
        privacy.setWordWrap(True)
        privacy.setObjectName("muted")
        dlay.addWidget(privacy)
        data_box = QGroupBox("Data and privacy")
        data_box.setLayout(dlay)

        about = QLabel(
            f"<b>{APP_NAME}</b> v{__version__}<br>"
            f"Developed by <b>{AUTHOR}</b>, {AUTHOR_TITLE}<br>"
            f"<a href='{REPO_URL}'>{REPO_URL}</a><br><br>"
            "Face detection: YuNet (MIT) · Face recognition: SFace (Apache-2.0) · via OpenCV"
        )
        about.setOpenExternalLinks(True)
        about.setWordWrap(True)
        about_box = QGroupBox("About")
        QVBoxLayout(about_box).addWidget(about)

        lay = QVBoxLayout(self)
        lay.addWidget(rec_box)
        lay.addWidget(data_box)
        lay.addWidget(about_box)
        lay.addStretch()

    def activate(self) -> None:
        pass

    def deactivate(self) -> None:
        pass

    def scan(self) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            cams = list_cameras()
        finally:
            QApplication.restoreOverrideCursor()
        self.camera.clear()
        if not cams:
            self.camera.addItem("No camera found", 0)
            return
        for i in cams:
            self.camera.addItem(f"Camera {i}" + (" (built-in / default)" if i == 0 else ""), i)
        idx = self.camera.findData(self.state.camera_index)
        self.camera.setCurrentIndex(max(idx, 0))

    def save(self) -> None:
        db = self.state.db
        db.set_setting("camera_index", self.camera.currentData() or 0)
        db.set_setting("threshold", f"{self.threshold.value():.2f}")
        db.set_setting("confirm_frames", self.confirm.value())
        db.set_setting("min_face", self.min_face.value())
        db.set_setting("samples_per_student", self.samples.value())
        db.set_setting("institution", self.institution.text().strip())
        self.state.settings_changed.emit()
        QMessageBox.information(self, "Saved", "Settings saved. Camera changes apply the next time it starts.")

    def restore_defaults(self) -> None:
        self.threshold.setValue(0.40)
        self.confirm.setValue(3)
        self.min_face.setValue(36)
        self.samples.setValue(10)

    def open_folder(self) -> None:
        path = str(data_dir())
        if os.name == "nt":
            os.startfile(path)  # noqa: S606
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])

    def backup(self) -> None:
        default = f"faceroll-backup-{datetime.now():%Y%m%d-%H%M}.db"
        path, _ = QFileDialog.getSaveFileName(self, "Back up database", default, "Database (*.db)")
        if not path:
            return
        import sqlite3

        dest = sqlite3.connect(path)
        self.state.db.conn.backup(dest)
        dest.close()
        QMessageBox.information(self, "Backed up", f"Backup saved to:\n{path}")

    def restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Restore backup", "", "Database (*.db)")
        if not path:
            return
        if (
            QMessageBox.question(
                self,
                "Restore",
                "Replace ALL current classes, students and attendance with this backup?\n"
                "The app will close; open it again afterwards.",
            )
            != QMessageBox.Yes
        ):
            return
        self.state.db.close()
        shutil.copyfile(path, db_path())
        QApplication.quit()
