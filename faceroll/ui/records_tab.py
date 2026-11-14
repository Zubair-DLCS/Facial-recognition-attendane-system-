"""Attendance register: students x sessions, percentages, corrections and export."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import AUTHOR, AUTHOR_TITLE
from ..export import export_csv, export_xlsx
from .common import AppState, ClassCombo, need_class

P_BG = QColor("#e3f4e1")
A_BG = QColor("#fbe5e1")
LOW = QColor("#c00000")


class RecordsTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.combo = ClassCombo(state)
        self.combo.class_selected.connect(self.reload)

        self.low_spin = QSpinBox()
        self.low_spin.setRange(0, 100)
        self.low_spin.setValue(75)
        self.low_spin.setSuffix(" %")
        self.low_spin.setToolTip("Highlight students below this attendance percentage")
        self.low_spin.valueChanged.connect(self.reload)

        xlsx_b = QPushButton("Export Excel")
        xlsx_b.setObjectName("primary")
        csv_b = QPushButton("Export CSV")
        xlsx_b.clicked.connect(lambda: self.export("xlsx"))
        csv_b.clicked.connect(lambda: self.export("csv"))

        top = QHBoxLayout()
        top.addWidget(QLabel("Class:"))
        top.addWidget(self.combo)
        top.addSpacing(16)
        top.addWidget(QLabel("Short attendance below:"))
        top.addWidget(self.low_spin)
        top.addStretch()
        top.addWidget(csv_b)
        top.addWidget(xlsx_b)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self.toggle_cell)

        self.session_box = QComboBox()
        self.session_box.setMinimumWidth(300)
        del_b = QPushButton("Delete session")
        del_b.setObjectName("danger")
        del_b.clicked.connect(self.delete_session)
        self.summary = QLabel()
        self.summary.setObjectName("muted")

        bottom = QHBoxLayout()
        bottom.addWidget(self.summary)
        bottom.addStretch()
        bottom.addWidget(self.session_box)
        bottom.addWidget(del_b)

        hint = QLabel("Double-click a P/A cell to correct it. Corrections are saved as manual entries.")
        hint.setObjectName("muted")

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(hint)
        lay.addWidget(self.table, 1)
        lay.addLayout(bottom)

        state.sessions_changed.connect(lambda cid: cid == self.combo.class_id() and self.reload())
        state.students_changed.connect(lambda cid: cid == self.combo.class_id() and self.reload())
        self.reload()

    def activate(self) -> None:
        self.reload()

    def deactivate(self) -> None:
        pass

    def reload(self, *_):
        cid = self.combo.class_id()
        if cid < 0:
            self.table.clear()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.session_box.clear()
            self.summary.setText("")
            return
        students, sessions, present = self.state.db.class_matrix(cid)
        self._students, self._sessions = students, sessions

        headers = ["Roll", "Name"]
        for s in sessions:
            try:
                d = datetime.fromisoformat(s.started_at).strftime("%d %b\n%H:%M")
            except ValueError:
                d = s.started_at
            headers.append(d)
        headers += ["Present", "%"]
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setRowCount(len(students))
        self.table.setHorizontalHeaderLabels(headers)
        for i, s in enumerate(sessions):
            self.table.horizontalHeaderItem(2 + i).setToolTip(s.title)

        total = len(sessions)
        low = self.low_spin.value()
        n_low = 0
        for r, st in enumerate(students):
            self.table.setItem(r, 0, QTableWidgetItem(st.roll_no))
            self.table.setItem(r, 1, QTableWidgetItem(st.name))
            count = 0
            for c, s in enumerate(sessions):
                p = (st.id, s.id) in present
                count += p
                it = QTableWidgetItem("P" if p else "A")
                it.setTextAlignment(Qt.AlignCenter)
                it.setBackground(QBrush(P_BG if p else A_BG))
                self.table.setItem(r, 2 + c, it)
            pct = 100 * count / total if total else 0.0
            pc = QTableWidgetItem(f"{count}/{total}")
            pc.setTextAlignment(Qt.AlignCenter)
            pp = QTableWidgetItem(f"{pct:.0f}")
            pp.setTextAlignment(Qt.AlignCenter)
            if total and pct < low:
                pp.setForeground(QBrush(LOW))
                self.table.item(r, 1).setForeground(QBrush(LOW))
                n_low += 1
            self.table.setItem(r, 2 + total, pc)
            self.table.setItem(r, 3 + total, pp)

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 200)

        self.session_box.clear()
        for s in reversed(sessions):
            self.session_box.addItem(f"{s.started_at.replace('T', ' ')[:16]}  {s.title}", s.id)
        self.summary.setText(
            f"{len(students)} students · {total} sessions · {n_low} below {low}%"
        )

    def toggle_cell(self, row: int, col: int) -> None:
        n = len(self._sessions)
        if not (2 <= col < 2 + n):
            return
        st = self._students[row]
        sess = self._sessions[col - 2]
        if self.table.item(row, col).text() == "P":
            self.state.db.mark_absent(sess.id, st.id)
        else:
            self.state.db.mark_present(sess.id, st.id, "manual")
        self.reload()
        self.state.sessions_changed.emit(st.class_id)

    def delete_session(self) -> None:
        sid = self.session_box.currentData()
        if sid is None:
            return
        if (
            QMessageBox.question(
                self, "Delete session", f"Delete session '{self.session_box.currentText()}' and its attendance?"
            )
            == QMessageBox.Yes
        ):
            self.state.db.delete_session(int(sid))
            self.state.sessions_changed.emit(self.combo.class_id())

    def export(self, kind: str) -> None:
        cid = self.combo.class_id()
        if not need_class(self, cid):
            return
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in self.combo.class_name()).strip()
        default = f"Attendance - {safe} - {datetime.now():%Y-%m-%d}.{kind}"
        flt = "Excel workbook (*.xlsx)" if kind == "xlsx" else "CSV file (*.csv)"
        path, _ = QFileDialog.getSaveFileName(self, "Export attendance", default, flt)
        if not path:
            return
        try:
            if kind == "xlsx":
                inst = self.state.institution
                credit = f"FaceRoll by {AUTHOR}, {AUTHOR_TITLE}" + (f" | {inst}" if inst else "")
                export_xlsx(self.state.db, cid, path, self.combo.class_name(), credit)
            else:
                export_csv(self.state.db, cid, path)
        except PermissionError:
            QMessageBox.warning(self, "File in use", "Close the file in Excel and try again.")
            return
        QMessageBox.information(self, "Exported", f"Saved to:\n{path}")
