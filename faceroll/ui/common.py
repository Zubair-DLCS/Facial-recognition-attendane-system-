"""Shared state and small widgets used across tabs."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QComboBox, QLabel, QMessageBox, QSizePolicy, QWidget

from ..database import Database
from ..engine import DEFAULT_THRESHOLD


class AppState(QObject):
    """Holds the database and broadcasts changes so every tab stays in sync."""

    classes_changed = Signal()
    students_changed = Signal(int)  # class_id
    sessions_changed = Signal(int)  # class_id
    settings_changed = Signal()

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    # settings with defaults
    @property
    def camera_index(self) -> int:
        return int(self.db.get_setting("camera_index", "0"))

    @property
    def threshold(self) -> float:
        return float(self.db.get_setting("threshold", str(DEFAULT_THRESHOLD)))

    @property
    def confirm_frames(self) -> int:
        return int(self.db.get_setting("confirm_frames", "3"))

    @property
    def min_face(self) -> int:
        return int(self.db.get_setting("min_face", "36"))

    @property
    def samples_per_student(self) -> int:
        return int(self.db.get_setting("samples_per_student", "10"))

    @property
    def institution(self) -> str:
        return self.db.get_setting("institution", "")


class ClassCombo(QComboBox):
    """Combo box of classes that refreshes itself and keeps the current selection."""

    class_selected = Signal(int)  # emits -1 when there are no classes

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.setMinimumWidth(220)
        self.currentIndexChanged.connect(lambda _: self.class_selected.emit(self.class_id()))
        state.classes_changed.connect(self.reload)
        self.reload()

    def class_id(self) -> int:
        data = self.currentData()
        return int(data) if data is not None else -1

    def class_name(self) -> str:
        return self.currentText() if self.class_id() >= 0 else ""

    def select(self, class_id: int) -> None:
        i = self.findData(class_id)
        if i >= 0:
            self.setCurrentIndex(i)

    def reload(self) -> None:
        current = self.class_id()
        self.blockSignals(True)
        self.clear()
        for cid, name in self.state.db.classes():
            self.addItem(name, cid)
        i = self.findData(current)
        self.setCurrentIndex(i if i >= 0 else (0 if self.count() else -1))
        self.blockSignals(False)
        self.class_selected.emit(self.class_id())


class VideoView(QLabel):
    """Shows camera frames scaled to fit while keeping the aspect ratio."""

    def __init__(self, placeholder: str = "Camera is off", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("video")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(480, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._placeholder = placeholder
        self._pix: QPixmap | None = None
        self.clear_video()

    def show_frame(self, image: QImage) -> None:
        self._pix = QPixmap.fromImage(image)
        self._rescale()

    def clear_video(self, text: str | None = None) -> None:
        self._pix = None
        self.setPixmap(QPixmap())
        self.setText(text or self._placeholder)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._pix is not None:
            self.setPixmap(self._pix.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


def photo_pixmap(data: bytes | None, size: int = 56) -> QPixmap:
    pix = QPixmap()
    if data:
        pix.loadFromData(data)
    if pix.isNull():
        return QPixmap()
    return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def need_class(parent: QWidget, class_id: int) -> bool:
    if class_id < 0:
        QMessageBox.information(parent, "No class", "Create a class first on the Students tab.")
        return False
    return True
