"""Live attendance: recognise faces from the webcam and mark the roster."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..camera import AttendanceProcessor, CameraWorker
from .common import AppState, ClassCombo, VideoView, need_class

PRESENT_BG = QColor("#e3f4e1")
MANUAL_BG = QColor("#fff4d6")


class AttendanceTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.worker: CameraWorker | None = None
        self.processor = AttendanceProcessor()
        self.processor.student_confirmed.connect(self.on_confirmed)
        self.processor.stats.connect(self.on_stats)
        self.session_id: int | None = None
        self.rows: dict[int, int] = {}  # student_id -> table row
        self.present: dict[int, str] = {}  # student_id -> method
        self.blocked: set[int] = set()  # manually marked absent this session

        # ---- left: video + status
        self.video = VideoView("Camera is off")
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.flash = QLabel("")
        self.flash.setObjectName("flash")
        self.flash.setAlignment(Qt.AlignCenter)
        self._flash_timer = QTimer(self, singleShot=True, interval=2500)
        self._flash_timer.timeout.connect(lambda: self.flash.setText(""))

        left = QVBoxLayout()
        left.addWidget(self.video, 1)
        left.addWidget(self.flash)
        left.addWidget(self.status)

        # ---- right: session controls + roster
        self.combo = ClassCombo(state)
        self.combo.class_selected.connect(self.on_class_changed)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Session title, e.g. Lecture 12 - Data Structures")
        self.start_btn = QPushButton("Start session")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start_session)
        self.end_btn = QPushButton("End session")
        self.end_btn.setObjectName("danger")
        self.end_btn.setEnabled(False)
        self.end_btn.clicked.connect(self.end_session)
        self.cam_btn = QPushButton("Camera on")
        self.cam_btn.setCheckable(True)
        self.cam_btn.toggled.connect(self.toggle_camera)

        sess = QVBoxLayout()
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Class:"))
        row1.addWidget(self.combo, 1)
        sess.addLayout(row1)
        sess.addWidget(self.title)
        row2 = QHBoxLayout()
        row2.addWidget(self.start_btn)
        row2.addWidget(self.end_btn)
        row2.addWidget(self.cam_btn)
        sess.addLayout(row2)
        self.session_lbl = QLabel("No session running. The camera preview shows who would be recognised.")
        self.session_lbl.setWordWrap(True)
        self.session_lbl.setObjectName("muted")
        sess.addWidget(self.session_lbl)
        box = QGroupBox("Session")
        box.setLayout(sess)

        self.counter = QLabel("Present 0 / 0")
        self.counter.setObjectName("counter")
        self.absent_only = QCheckBox("Show absent only")
        self.absent_only.toggled.connect(self.apply_filter)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Roll", "Name", "Status", "Time"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 60)
        self.table.doubleClicked.connect(self.toggle_selected)
        toggle_btn = QPushButton("Mark present / absent")
        toggle_btn.setToolTip("Manual override for the selected student (or double-click a row)")
        toggle_btn.clicked.connect(self.toggle_selected)

        cnt = QHBoxLayout()
        cnt.addWidget(self.counter)
        cnt.addStretch()
        cnt.addWidget(self.absent_only)

        right = QVBoxLayout()
        right.addWidget(box)
        right.addLayout(cnt)
        right.addWidget(self.table, 1)
        right.addWidget(toggle_btn)
        right_w = QWidget()
        right_w.setLayout(right)
        right_w.setFixedWidth(400)

        lay = QHBoxLayout(self)
        lay.addLayout(left, 1)
        lay.addWidget(right_w)

        state.students_changed.connect(lambda cid: cid == self.combo.class_id() and self.on_class_changed(cid))
        state.settings_changed.connect(lambda: self.on_class_changed(self.combo.class_id()))
        self.on_class_changed(self.combo.class_id())

    # ------------------------------------------------ camera lifecycle
    def activate(self) -> None:
        self.cam_btn.setChecked(True)

    def deactivate(self) -> None:
        self.cam_btn.setChecked(False)

    def toggle_camera(self, on: bool) -> None:
        if on and self.worker is None:
            self.worker = CameraWorker(self.state.camera_index, self.processor)
            self.worker.frame_ready.connect(self.video.show_frame)
            self.worker.fps.connect(lambda f: setattr(self, "_fps", f))
            self.worker.error.connect(self.on_error)
            self.video.clear_video("Starting camera…")
            self.worker.start()
            self.cam_btn.setText("Camera off")
        elif not on and self.worker is not None:
            self.worker.stop()
            self.worker = None
            self.video.clear_video("Camera is off" + (" - session still open" if self.session_id else ""))
            self.cam_btn.setText("Camera on")
            self.status.setText("")

    def on_error(self, msg: str) -> None:
        self.worker = None
        self.cam_btn.blockSignals(True)
        self.cam_btn.setChecked(False)
        self.cam_btn.setText("Camera on")
        self.cam_btn.blockSignals(False)
        self.video.clear_video(msg)

    def on_stats(self, faces: int, unknown: int) -> None:
        fps = getattr(self, "_fps", 0.0)
        self.status.setText(f"Faces in view: {faces}   Unknown: {unknown}   {fps:.0f} fps")

    # ------------------------------------------------ roster
    def on_class_changed(self, class_id: int) -> None:
        db = self.state.db
        students = db.students(class_id) if class_id >= 0 else []
        names = {s.id: s.name for s in students}
        self.processor.configure(
            db.gallery_entries(class_id) if class_id >= 0 else {},
            names,
            self.state.threshold,
            self.state.confirm_frames,
            self.state.min_face,
        )
        self.present = {}
        if self.session_id is not None:
            self.present = {sid: r["method"] for sid, r in db.session_attendance(self.session_id).items()}
        times = {}
        if self.session_id is not None:
            times = {sid: r["marked_at"][11:16] for sid, r in db.session_attendance(self.session_id).items()}

        self.table.setRowCount(len(students))
        self.rows = {}
        for r, s in enumerate(students):
            self.rows[s.id] = r
            roll = QTableWidgetItem(s.roll_no)
            roll.setData(Qt.UserRole, s.id)
            self.table.setItem(r, 0, roll)
            self.table.setItem(r, 1, QTableWidgetItem(s.name))
            self.table.setItem(r, 2, QTableWidgetItem(""))
            self.table.setItem(r, 3, QTableWidgetItem(times.get(s.id, "")))
            self._paint_row(s.id)
        self.processor.set_present(set(self.present), self.blocked)
        self._update_counter()
        self.apply_filter()

    def _paint_row(self, sid: int) -> None:
        r = self.rows.get(sid)
        if r is None:
            return
        method = self.present.get(sid)
        text = "" if self.session_id is None else ("Present" if method else "Absent")
        if method == "manual":
            text = "Present*"
        self.table.item(r, 2).setText(text)
        bg = PRESENT_BG if method == "face" else MANUAL_BG if method == "manual" else None
        for c in range(4):
            self.table.item(r, c).setBackground(QBrush(bg) if bg else QBrush())

    def _update_counter(self) -> None:
        self.counter.setText(f"Present {len(self.present)} / {len(self.rows)}")

    def apply_filter(self, *_):
        only = self.absent_only.isChecked()
        for sid, r in self.rows.items():
            self.table.setRowHidden(r, only and sid in self.present)

    # ------------------------------------------------ session
    def start_session(self) -> None:
        cid = self.combo.class_id()
        if not need_class(self, cid):
            return
        if not self.rows:
            QMessageBox.information(self, "No students", "Enrol students in this class first.")
            return
        db = self.state.db
        open_sessions = [s for s in db.sessions(cid) if s.ended_at is None]
        sid = None
        if open_sessions:
            last = open_sessions[-1]
            ans = QMessageBox.question(
                self,
                "Open session found",
                f"'{last.title}' (started {last.started_at.replace('T', ' ')}) was never ended.\n\n"
                "Yes: continue that session\nNo: close it and start a new one",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if ans == QMessageBox.Cancel:
                return
            for s in open_sessions:
                if ans == QMessageBox.Yes and s.id == last.id:
                    sid = s.id
                else:
                    db.end_session(s.id)
        if sid is None:
            title = self.title.text().strip() or f"Session {datetime.now().strftime('%d %b %Y %H:%M')}"
            sid = db.start_session(cid, title)
            self.title.setText(title)

        self.session_id = sid
        self.blocked = set()
        self.combo.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.end_btn.setEnabled(True)
        self.title.setEnabled(False)
        self.session_lbl.setText("Session running. Students are marked present automatically when recognised.")
        self.on_class_changed(cid)
        self.processor.active = True
        self.cam_btn.setChecked(True)
        self.state.sessions_changed.emit(cid)

    def end_session(self) -> None:
        if self.session_id is None:
            return
        absent = len(self.rows) - len(self.present)
        if (
            QMessageBox.question(
                self, "End session", f"End this session?\n\nPresent: {len(self.present)}\nAbsent: {absent}"
            )
            != QMessageBox.Yes
        ):
            return
        self.processor.active = False
        self.state.db.end_session(self.session_id)
        cid = self.combo.class_id()
        self.session_id = None
        self.combo.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.end_btn.setEnabled(False)
        self.title.setEnabled(True)
        self.title.clear()
        self.session_lbl.setText("Session saved. See the Records tab to review or export.")
        self.on_class_changed(cid)
        self.state.sessions_changed.emit(cid)

    def on_confirmed(self, sid: int, score: float) -> None:
        if self.session_id is None or sid in self.present:
            return
        if self.state.db.mark_present(self.session_id, sid, "face", score):
            self.present[sid] = "face"
            r = self.rows.get(sid)
            if r is not None:
                self.table.item(r, 3).setText(datetime.now().strftime("%H:%M"))
                self._paint_row(sid)
                self.table.scrollToItem(self.table.item(r, 0))
            name = self.table.item(r, 1).text() if r is not None else str(sid)
            self.flash.setText(f"✓  {name} marked present")
            self._flash_timer.start()
            QApplication.beep()
            self._update_counter()
            self.apply_filter()

    def toggle_selected(self, *_):
        if self.session_id is None:
            QMessageBox.information(self, "No session", "Start a session first.")
            return
        for idx in self.table.selectionModel().selectedRows():
            sid = int(self.table.item(idx.row(), 0).data(Qt.UserRole))
            if sid in self.present:
                self.state.db.mark_absent(self.session_id, sid)
                del self.present[sid]
                self.blocked.add(sid)
                self.table.item(idx.row(), 3).setText("")
            else:
                self.state.db.mark_present(self.session_id, sid, "manual")
                self.present[sid] = "manual"
                self.blocked.discard(sid)
                self.table.item(idx.row(), 3).setText(datetime.now().strftime("%H:%M"))
            self._paint_row(sid)
        self.processor.set_present(set(self.present), self.blocked)
        self._update_counter()
        self.apply_filter()

    def shutdown(self) -> None:
        """Called on app exit: stop the camera and close any running session."""
        self.deactivate()
        if self.session_id is not None:
            self.state.db.end_session(self.session_id)
