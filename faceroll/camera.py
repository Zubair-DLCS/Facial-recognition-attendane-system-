"""Webcam capture thread plus the two frame processors (enrolment and attendance).

The worker thread owns its own FaceEngine; processors run inside that thread
and report back to the GUI through Qt signals (queued automatically).
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QImage

from .engine import DEFAULT_THRESHOLD, Face, FaceEngine, Gallery, iou

MAX_WORK_WIDTH = 960  # frames wider than this are downscaled before detection

GREEN = (60, 180, 75)
AMBER = (0, 170, 255)
RED = (60, 60, 230)
GREY = (160, 160, 160)


def open_camera(index: int) -> cv2.VideoCapture:
    if os.name == "nt":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)  # opens much faster on Windows
        if not cap.isOpened():
            cap = cv2.VideoCapture(index, cv2.CAP_MSMF)
    else:
        cap = cv2.VideoCapture(index)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    return cap


def list_cameras(max_index: int = 5) -> list[int]:
    found = []
    for i in range(max_index):
        cap = open_camera(i)
        if cap.isOpened():
            ok, _ = cap.read()
            if ok:
                found.append(i)
        cap.release()
    return found


def to_qimage(frame_bgr: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()


def draw_label(img: np.ndarray, box, text: str, color) -> None:
    x, y, w, h = box
    cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)
    if not text:
        return
    font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1
    (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    ty = y - 6 if y - th - 10 > 0 else y + h + th + 6
    cv2.rectangle(img, (x, ty - th - 4), (x + tw + 6, ty + base - 2), color, -1)
    cv2.putText(img, text, (x + 3, ty - 2), font, scale, (255, 255, 255), thick, cv2.LINE_AA)


def ascii_label(text: str) -> str:
    """OpenCV's font is ASCII-only; drop other characters from on-video labels."""
    return text.encode("ascii", "ignore").decode() or "?"


class FrameProcessor(QObject):
    """Base class. `process` runs in the camera thread and returns the frame to display."""

    def setup(self, engine: FaceEngine) -> None:
        self.engine = engine

    def process(self, frame: np.ndarray) -> np.ndarray:
        return frame


# --------------------------------------------------------------------- enrolment
class EnrollProcessor(FrameProcessor):
    """Collects N good, varied face samples of one person."""

    sample_captured = Signal(object, object)  # embedding (np.ndarray), aligned crop (BGR np.ndarray)
    hint = Signal(str)
    finished = Signal()

    def __init__(self, target: int = 10, interval: float = 0.35, min_face: int = 70):
        super().__init__()
        self.target = target
        self.interval = interval
        self.min_face = min_face
        self.capturing = False
        self._samples: list[np.ndarray] = []
        self._last = 0.0
        self._last_hint = ""

    def start(self) -> None:
        self._samples = []
        self._last = 0.0
        self.capturing = True

    def stop(self) -> None:
        self.capturing = False

    def _say(self, text: str) -> None:
        if text != self._last_hint:
            self._last_hint = text
            self.hint.emit(text)

    def process(self, frame: np.ndarray) -> np.ndarray:
        faces = self.engine.detect(frame)
        out = frame.copy()
        for f in faces:
            draw_label(out, f.box, "", GREY)

        if not faces:
            self._say("No face found. Face the camera with good lighting.")
            return out
        if len(faces) > 1:
            self._say("More than one face in view. Only the student being enrolled should be visible.")
            return out
        face = faces[0]
        if face.width < self.min_face:
            draw_label(out, face.box, "Come closer", AMBER)
            self._say("Come a little closer to the camera.")
            return out

        if not self.capturing:
            draw_label(out, face.box, "Ready", GREEN)
            self._say("Face detected. Press Start capture.")
            return out

        draw_label(out, face.box, f"{len(self._samples)}/{self.target}", GREEN)
        now = time.monotonic()
        if now - self._last < self.interval or face.score < 0.85:
            return out

        aligned = self.engine.align(frame, face)
        emb = self.engine.embed_aligned(aligned)
        if self._samples and max(float(s @ emb) for s in self._samples) > 0.985:
            self._say("Turn your head slightly left, right, up or down.")
            return out

        self._last = now
        self._samples.append(emb)
        self.sample_captured.emit(emb, aligned.copy())
        self._say(f"Captured {len(self._samples)} of {self.target}. Keep moving your head slowly.")
        if len(self._samples) >= self.target:
            self.capturing = False
            self._say("Done. Review and press Save student.")
            self.finished.emit()
        return out


# -------------------------------------------------------------------- attendance
@dataclass
class _Track:
    box: tuple[int, int, int, int]
    sid: int | None = None
    score: float = 0.0
    hits: int = 0
    confirmed: bool = False
    last_frame: int = 0
    verify_at: int = 0
    history: list = field(default_factory=list)


class AttendanceProcessor(FrameProcessor):
    """Recognises every face in view and confirms a student after several consistent frames.

    A light IoU tracker means a face that is already confirmed is only
    re-verified every few frames, which keeps a full classroom responsive on CPU.
    """

    student_confirmed = Signal(int, float)  # student_id, similarity
    stats = Signal(int, int)  # faces in view, unknown faces

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self.gallery = Gallery()
        self.names: dict[int, str] = {}
        self.threshold = DEFAULT_THRESHOLD
        self.confirm_frames = 3
        self.min_face = 36
        self.reverify_every = 12
        self.active = False
        self.already_present: set[int] = set()
        self.blocked: set[int] = set()  # manually marked absent: never auto-mark again this session
        self._tracks: list[_Track] = []
        self._frame_no = 0

    def configure(self, entries, names, threshold, confirm_frames, min_face) -> None:
        with self._lock:
            self.gallery = Gallery(entries)
            self.names = dict(names)
            self.threshold = threshold
            self.confirm_frames = max(1, confirm_frames)
            self.min_face = min_face
            self._tracks = []

    def set_present(self, present: set[int], blocked: set[int] | None = None) -> None:
        with self._lock:
            self.already_present = set(present)
            self.blocked = set(blocked or ())

    def _assign(self, face: Face) -> _Track:
        best, best_iou = None, 0.4
        for t in self._tracks:
            v = iou(t.box, face.box)
            if v > best_iou:
                best, best_iou = t, v
        if best is None:
            best = _Track(box=face.box)
            self._tracks.append(best)
        best.box = face.box
        best.last_frame = self._frame_no
        return best

    def process(self, frame: np.ndarray) -> np.ndarray:
        self._frame_no += 1
        out = frame.copy()
        faces = self.engine.detect(frame)
        unknown = 0
        with self._lock:
            for face in faces:
                if face.width < self.min_face:
                    draw_label(out, face.box, "", GREY)
                    continue
                t = self._assign(face)
                if not (t.confirmed and self._frame_no < t.verify_at):
                    emb = self.engine.embed(frame, face)
                    sid, score = self.gallery.match(emb, self.threshold)
                    if sid is not None and sid == t.sid:
                        t.hits += 1
                    else:
                        t.sid, t.hits, t.confirmed = sid, (1 if sid is not None else 0), False
                    t.score = score
                    if t.sid is not None and t.hits >= self.confirm_frames:
                        t.confirmed = True
                        t.verify_at = self._frame_no + self.reverify_every
                        if self.active and t.sid not in self.already_present and t.sid not in self.blocked:
                            self.already_present.add(t.sid)
                            self.student_confirmed.emit(t.sid, t.score)

                if t.sid is None:
                    unknown += 1
                    draw_label(out, face.box, "Unknown", RED)
                else:
                    name = ascii_label(self.names.get(t.sid, str(t.sid)))
                    color = GREEN if t.confirmed else AMBER
                    tick = " [P]" if t.sid in self.already_present else ""
                    draw_label(out, face.box, f"{name}{tick}", color)
            # drop tracks not seen for a while
            self._tracks = [t for t in self._tracks if self._frame_no - t.last_frame <= 8]
        self.stats.emit(len(faces), unknown)
        return out


# ------------------------------------------------------------------------ thread
class CameraWorker(QThread):
    frame_ready = Signal(QImage)
    fps = Signal(float)
    error = Signal(str)

    def __init__(self, camera_index: int, processor: FrameProcessor, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self.processor = processor
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()
        self.wait(3000)

    def run(self) -> None:
        try:
            engine = FaceEngine()
        except Exception as exc:  # pragma: no cover - surfaced in the GUI
            self.error.emit(f"Could not load face models: {exc}")
            return
        self.processor.setup(engine)

        cap = open_camera(self.camera_index)
        if not cap.isOpened():
            self.error.emit(
                f"Could not open camera {self.camera_index}. "
                "Check that it is connected and not used by another app, or pick another camera in Settings."
            )
            return

        failures, t0, frames = 0, time.monotonic(), 0
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    failures += 1
                    if failures > 30:
                        self.error.emit("The camera stopped sending frames.")
                        break
                    time.sleep(0.03)
                    continue
                failures = 0
                h, w = frame.shape[:2]
                if w > MAX_WORK_WIDTH:
                    frame = cv2.resize(frame, (MAX_WORK_WIDTH, int(h * MAX_WORK_WIDTH / w)))
                try:
                    shown = self.processor.process(frame)
                except Exception as exc:  # keep the camera alive on a bad frame
                    shown = frame
                    print("processing error:", exc)
                self.frame_ready.emit(to_qimage(shown))
                frames += 1
                el = time.monotonic() - t0
                if el >= 1.0:
                    self.fps.emit(frames / el)
                    t0, frames = time.monotonic(), 0
        finally:
            cap.release()
