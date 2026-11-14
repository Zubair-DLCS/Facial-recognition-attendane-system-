"""Classes and student roster: add/rename/delete classes, edit students, bulk import from photos."""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..engine import FaceEngine
from .common import AppState, ClassCombo, need_class, photo_pixmap

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_roll_name(stem: str) -> tuple[str, str]:
    """'12_Ali Khan' / '12 - Ali Khan' / '12 Ali Khan' -> ('12', 'Ali Khan')."""
    stem = stem.strip()
    for sep in ("_", " - ", "-"):
        if sep in stem:
            roll, name = stem.split(sep, 1)
            return roll.strip(), name.replace("_", " ").strip() or roll.strip()
    m = re.match(r"^(\S+)\s+(.+)$", stem)
    if m:
        return m.group(1), m.group(2)
    return stem, stem


def read_image(path: Path) -> np.ndarray | None:
    # np.fromfile + imdecode handles non-ASCII Windows paths, unlike cv2.imread
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


class StudentDialog(QDialog):
    def __init__(self, roll: str, name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit student")
        form = QFormLayout(self)
        self.roll = QLineEdit(roll)
        self.name = QLineEdit(name)
        form.addRow("Roll no:", self.roll)
        form.addRow("Name:", self.name)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class StudentsTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self._engine: FaceEngine | None = None

        self.combo = ClassCombo(state)
        add_c = QPushButton("New class")
        ren_c = QPushButton("Rename")
        del_c = QPushButton("Delete class")
        del_c.setObjectName("danger")
        add_c.clicked.connect(self.new_class)
        ren_c.clicked.connect(self.rename_class)
        del_c.clicked.connect(self.delete_class)

        top = QHBoxLayout()
        top.addWidget(QLabel("Class:"))
        top.addWidget(self.combo)
        top.addWidget(add_c)
        top.addWidget(ren_c)
        top.addWidget(del_c)
        top.addStretch()

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Photo", "Roll no", "Name", "Face samples"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(62)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 110)
        self.table.doubleClicked.connect(self.edit_student)

        edit_b = QPushButton("Edit")
        del_b = QPushButton("Delete student")
        del_b.setObjectName("danger")
        imp_b = QPushButton("Import from photos…")
        imp_b.setToolTip(
            "Pick a folder. Each image named like '12_Ali Khan.jpg', or each sub-folder named\n"
            "'12_Ali Khan' holding several photos, becomes one student."
        )
        edit_b.clicked.connect(self.edit_student)
        del_b.clicked.connect(self.delete_student)
        imp_b.clicked.connect(self.import_photos)
        self.count_lbl = QLabel()

        bottom = QHBoxLayout()
        bottom.addWidget(self.count_lbl)
        bottom.addStretch()
        bottom.addWidget(imp_b)
        bottom.addWidget(edit_b)
        bottom.addWidget(del_b)

        tip = QLabel("Enrol students with the webcam on the <b>Enroll</b> tab, or import existing photos here.")
        tip.setObjectName("muted")

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(tip)
        lay.addWidget(self.table)
        lay.addLayout(bottom)

        self.combo.class_selected.connect(self.reload)
        state.students_changed.connect(lambda cid: cid == self.combo.class_id() and self.reload())
        self.reload()

    # ---------------- classes
    def new_class(self) -> None:
        name, ok = QInputDialog.getText(self, "New class", "Class name (e.g. BS CS 3rd Semester - Section A):")
        if not ok or not name.strip():
            return
        try:
            cid = self.state.db.add_class(name)
        except Exception:
            QMessageBox.warning(self, "Class exists", f"A class named '{name}' already exists.")
            return
        self.state.classes_changed.emit()
        self.combo.select(cid)

    def rename_class(self) -> None:
        cid = self.combo.class_id()
        if not need_class(self, cid):
            return
        name, ok = QInputDialog.getText(self, "Rename class", "New name:", text=self.combo.class_name())
        if ok and name.strip():
            try:
                self.state.db.rename_class(cid, name)
            except Exception:
                QMessageBox.warning(self, "Class exists", f"A class named '{name}' already exists.")
                return
            self.state.classes_changed.emit()

    def delete_class(self) -> None:
        cid = self.combo.class_id()
        if not need_class(self, cid):
            return
        if (
            QMessageBox.question(
                self,
                "Delete class",
                f"Delete '{self.combo.class_name()}' with all its students, face data and attendance records?\n"
                "This cannot be undone.",
            )
            == QMessageBox.Yes
        ):
            self.state.db.delete_class(cid)
            self.state.classes_changed.emit()

    # ---------------- students
    def reload(self, *_):
        cid = self.combo.class_id()
        students = self.state.db.students(cid) if cid >= 0 else []
        self.table.setRowCount(len(students))
        for r, s in enumerate(students):
            ph = QTableWidgetItem()
            pix = photo_pixmap(s.photo)
            if not pix.isNull():
                ph.setData(Qt.DecorationRole, pix)
            ph.setData(Qt.UserRole, s.id)
            self.table.setItem(r, 0, ph)
            self.table.setItem(r, 1, QTableWidgetItem(s.roll_no))
            self.table.setItem(r, 2, QTableWidgetItem(s.name))
            n = QTableWidgetItem(str(s.samples))
            n.setTextAlignment(Qt.AlignCenter)
            if s.samples < 3:
                n.setToolTip("Few samples - re-enrol for better accuracy")
                n.setForeground(Qt.red)
            self.table.setItem(r, 3, n)
        self.count_lbl.setText(f"{len(students)} student(s)")

    def _selected_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return int(self.table.item(rows[0].row(), 0).data(Qt.UserRole))

    def edit_student(self, *_):
        sid = self._selected_id()
        if sid is None:
            return
        st = self.state.db.student(sid)
        dlg = StudentDialog(st.roll_no, st.name, self)
        if dlg.exec() and dlg.roll.text().strip() and dlg.name.text().strip():
            try:
                self.state.db.update_student(sid, dlg.roll.text(), dlg.name.text())
            except Exception:
                QMessageBox.warning(self, "Duplicate roll no", "Another student in this class has that roll number.")
                return
            self.state.students_changed.emit(st.class_id)

    def delete_student(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        ids = [int(self.table.item(r.row(), 0).data(Qt.UserRole)) for r in rows]
        if (
            QMessageBox.question(
                self, "Delete", f"Delete {len(ids)} student(s) with their face data and attendance history?"
            )
            == QMessageBox.Yes
        ):
            for sid in ids:
                self.state.db.delete_student(sid)
            self.state.students_changed.emit(self.combo.class_id())

    # ---------------- bulk import
    def import_photos(self):
        cid = self.combo.class_id()
        if not need_class(self, cid):
            return
        folder = QFileDialog.getExistingDirectory(self, "Folder of student photos")
        if not folder:
            return
        root = Path(folder)
        items: list[tuple[str, list[Path]]] = []
        for p in sorted(root.iterdir()):
            if p.is_dir():
                imgs = [f for f in sorted(p.iterdir()) if f.suffix.lower() in IMAGE_EXT]
                if imgs:
                    items.append((p.name, imgs))
            elif p.suffix.lower() in IMAGE_EXT:
                items.append((p.stem, [p]))
        if not items:
            QMessageBox.information(self, "No photos", "No images found in that folder.")
            return

        if self._engine is None:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._engine = FaceEngine()
            finally:
                QApplication.restoreOverrideCursor()

        prog = QProgressDialog("Importing…", "Cancel", 0, len(items), self)
        prog.setWindowModality(Qt.WindowModal)
        added, skipped = 0, []
        for i, (stem, files) in enumerate(items):
            if prog.wasCanceled():
                break
            prog.setValue(i)
            prog.setLabelText(f"Processing {stem}")
            QApplication.processEvents()
            roll, name = parse_roll_name(stem)
            embs, photo = [], None
            for f in files:
                img = read_image(f)
                if img is None:
                    continue
                face = self._engine.largest_face(img)
                if face is None:
                    continue
                aligned = self._engine.align(img, face)
                embs.append(self._engine.embed_aligned(aligned))
                if photo is None:
                    photo = cv2.imencode(".jpg", aligned)[1].tobytes()
            if embs:
                self.state.db.add_student(cid, roll, name, embs, photo)
                added += 1
            else:
                skipped.append(stem)
        prog.setValue(len(items))
        self.state.students_changed.emit(cid)
        msg = f"Imported {added} student(s)."
        if skipped:
            msg += f"\n\nNo face found for {len(skipped)}:\n" + "\n".join(skipped[:15])
            if len(skipped) > 15:
                msg += "\n…"
        QMessageBox.information(self, "Import finished", msg)
