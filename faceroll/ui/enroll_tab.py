"""Enrol a student by capturing face samples from the webcam."""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..camera import CameraWorker, EnrollProcessor, to_qimage
from ..engine import Gallery
from .common import AppState, ClassCombo, VideoView, need_class


class EnrollTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.worker: CameraWorker | None = None
        self.processor: EnrollProcessor | None = None
        self.embeddings: list[np.ndarray] = []
        self.photo: bytes | None = None

        self.video = VideoView("Starting camera…")

        self.combo = ClassCombo(state)
        self.roll = QLineEdit()
        self.roll.setPlaceholderText("e.g. 23 or BSCS-23")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Student's full name")
        self.samples = QSpinBox()
        self.samples.setRange(3, 30)
        self.samples.setValue(state.samples_per_student)

        form = QFormLayout()
        form.addRow("Class:", self.combo)
        form.addRow("Roll no:", self.roll)
        form.addRow("Name:", self.name)
        form.addRow("Samples:", self.samples)
        details = QGroupBox("Student")
        details.setLayout(form)

        self.capture_btn = QPushButton("Start capture")
        self.capture_btn.setObjectName("primary")
        self.capture_btn.clicked.connect(self.start_capture)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset)
        self.save_btn = QPushButton("Save student")
        self.save_btn.setObjectName("success")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save)

        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.hint = QLabel("Fill in the details, look at the camera, then press Start capture.")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("hint")

        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListView.IconMode)
        self.thumbs.setIconSize(QSize(64, 64))
        self.thumbs.setResizeMode(QListView.Adjust)
        self.thumbs.setMovement(QListView.Static)
        self.thumbs.setMinimumHeight(160)

        btns = QHBoxLayout()
        btns.addWidget(self.capture_btn)
        btns.addWidget(self.reset_btn)

        side = QVBoxLayout()
        side.addWidget(details)
        side.addLayout(btns)
        side.addWidget(self.progress)
        side.addWidget(self.hint)
        side.addWidget(QLabel("Captured samples:"))
        side.addWidget(self.thumbs, 1)
        side.addWidget(self.save_btn)
        tips = QLabel(
            "Tips: even front lighting, no strong window behind the student, "
            "glasses on if they usually wear them. Slowly turn the head a little during capture."
        )
        tips.setWordWrap(True)
        tips.setObjectName("muted")
        side.addWidget(tips)

        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(340)

        lay = QHBoxLayout(self)
        lay.addWidget(self.video, 1)
        lay.addWidget(side_w)

    # ------------------------------------------------ camera lifecycle (called by MainWindow)
    def activate(self) -> None:
        if self.worker is not None:
            return
        self.processor = EnrollProcessor(target=self.samples.value())
        self.processor.sample_captured.connect(self.on_sample)
        self.processor.hint.connect(self.hint.setText)
        self.processor.finished.connect(self.on_finished)
        self.worker = CameraWorker(self.state.camera_index, self.processor)
        self.worker.frame_ready.connect(self.video.show_frame)
        self.worker.error.connect(self.on_error)
        self.worker.finished.connect(self._on_worker_stopped)
        self.video.clear_video("Starting camera…")
        self.worker.start()

    def deactivate(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
        self.video.clear_video("Camera is off")

    def _on_worker_stopped(self) -> None:
        self.capture_btn.setEnabled(True)

    def on_error(self, msg: str) -> None:
        self.video.clear_video(msg)
        self.worker = None

    # ------------------------------------------------ capture flow
    def start_capture(self) -> None:
        if not need_class(self, self.combo.class_id()):
            return
        if not self.roll.text().strip() or not self.name.text().strip():
            QMessageBox.information(self, "Missing details", "Enter the roll number and name first.")
            return
        if self.worker is None:
            self.activate()
        self.reset(keep_fields=True)
        self.processor.target = self.samples.value()
        self.progress.setRange(0, self.samples.value())
        self.processor.start()
        self.capture_btn.setEnabled(False)

    def on_sample(self, emb: np.ndarray, aligned: np.ndarray) -> None:
        self.embeddings.append(emb)
        if self.photo is None:
            self.photo = cv2.imencode(".jpg", aligned)[1].tobytes()
        pix = QPixmap.fromImage(to_qimage(aligned))
        self.thumbs.addItem(QListWidgetItem(QIcon(pix), ""))
        self.progress.setValue(len(self.embeddings))

    def on_finished(self) -> None:
        self.capture_btn.setEnabled(True)
        self.capture_btn.setText("Capture again")
        self.save_btn.setEnabled(True)

    def reset(self, keep_fields: bool = False) -> None:
        if self.processor:
            self.processor.stop()
        self.embeddings = []
        self.photo = None
        self.thumbs.clear()
        self.progress.setValue(0)
        self.save_btn.setEnabled(False)
        self.capture_btn.setEnabled(True)
        self.capture_btn.setText("Start capture")
        if not keep_fields:
            self.roll.clear()
            self.name.clear()

    def save(self) -> None:
        cid = self.combo.class_id()
        roll, name = self.roll.text().strip(), self.name.text().strip()
        if not self.embeddings or cid < 0 or not roll or not name:
            return

        # Warn if this face already belongs to someone else in the class.
        entries = self.state.db.gallery_entries(cid)
        others = {s.id for s in self.state.db.students(cid) if s.roll_no != roll}
        gallery = Gallery({sid: v for sid, v in entries.items() if sid in others})
        mean = np.mean(self.embeddings, axis=0)
        mean /= np.linalg.norm(mean)
        sid, score = gallery.match(mean, max(self.state.threshold, 0.45))
        if sid is not None:
            other = self.state.db.student(sid)
            if (
                QMessageBox.question(
                    self,
                    "Possible duplicate",
                    f"This face closely matches {other.label} (similarity {score:.2f}).\n"
                    "Save as a separate student anyway?",
                )
                != QMessageBox.Yes
            ):
                return

        existing = {s.roll_no for s in self.state.db.students(cid)}
        if roll in existing and (
            QMessageBox.question(
                self, "Roll no exists", f"Roll no {roll} is already enrolled. Replace its face samples?"
            )
            != QMessageBox.Yes
        ):
            return

        self.state.db.add_student(cid, roll, name, self.embeddings, self.photo)
        self.state.students_changed.emit(cid)
        self.hint.setText(f"Saved {roll} - {name}. Ready for the next student.")
        self.reset()
        self.roll.setFocus()
