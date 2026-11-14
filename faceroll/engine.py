"""Face detection (YuNet) and recognition (SFace) on top of OpenCV's DNN module.

Both models ship in the repo's models/ folder, so the app runs fully offline.
YuNet  - MIT licence,      https://github.com/opencv/opencv_zoo
SFace  - Apache-2.0,       https://github.com/opencv/opencv_zoo
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .paths import models_dir

DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec.onnx"

# SFace's published cosine threshold is 0.363. We default slightly higher to
# prefer "unknown" over marking the wrong student present.
DEFAULT_THRESHOLD = 0.40


@dataclass
class Face:
    """One detected face. `raw` is YuNet's 15-value row (box, 5 landmarks, score)."""

    raw: np.ndarray

    @property
    def box(self) -> tuple[int, int, int, int]:
        x, y, w, h = self.raw[:4]
        return int(x), int(y), int(w), int(h)

    @property
    def score(self) -> float:
        return float(self.raw[14])

    @property
    def width(self) -> int:
        return int(self.raw[2])


class FaceEngine:
    """Not thread-safe: create one engine per thread."""

    def __init__(self, model_folder: Path | None = None, det_threshold: float = 0.8):
        folder = Path(model_folder) if model_folder else models_dir()
        det = folder / DETECTOR_FILE
        rec = folder / RECOGNIZER_FILE
        for f in (det, rec):
            if not f.exists():
                raise FileNotFoundError(f"Model file missing: {f}")
        self.detector = cv2.FaceDetectorYN.create(str(det), "", (320, 320), det_threshold, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(str(rec), "")

    def detect(self, image: np.ndarray) -> list[Face]:
        h, w = image.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(image)
        if faces is None:
            return []
        return [Face(row) for row in faces]

    def align(self, image: np.ndarray, face: Face) -> np.ndarray:
        """112x112 aligned face crop (also used as the student's thumbnail)."""
        return self.recognizer.alignCrop(image, face.raw)

    def embed_aligned(self, aligned: np.ndarray) -> np.ndarray:
        feat = self.recognizer.feature(aligned).flatten().astype(np.float32)
        return feat / (np.linalg.norm(feat) + 1e-9)

    def embed(self, image: np.ndarray, face: Face) -> np.ndarray:
        return self.embed_aligned(self.align(image, face))

    def largest_face(self, image: np.ndarray) -> Face | None:
        faces = self.detect(image)
        return max(faces, key=lambda f: f.width) if faces else None


class Gallery:
    """Enrolled embeddings for one class, matched by cosine similarity.

    A student's score is the best similarity over all of that student's samples,
    which copes better with pose and lighting changes than a single mean vector.
    """

    def __init__(self, entries: dict[int, np.ndarray] | None = None):
        self.set(entries or {})

    def set(self, entries: dict[int, np.ndarray]) -> None:
        mats, owners = [], []
        for sid, vecs in entries.items():
            vecs = np.atleast_2d(np.asarray(vecs, dtype=np.float32))
            if len(vecs):
                mats.append(vecs)
                owners.extend([sid] * len(vecs))
        self.matrix = np.vstack(mats) if mats else np.zeros((0, 128), np.float32)
        self.owners = np.asarray(owners, dtype=np.int64)

    def __len__(self) -> int:
        return len(set(self.owners.tolist()))

    def match(self, emb: np.ndarray, threshold: float = DEFAULT_THRESHOLD) -> tuple[int | None, float]:
        """Return (student_id, score), or (None, best_score) when nobody passes the threshold."""
        if len(self.owners) == 0:
            return None, 0.0
        sims = self.matrix @ emb
        i = int(np.argmax(sims))
        best = float(sims[i])
        if best < threshold:
            return None, best
        return int(self.owners[i]), best


def iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def vec_to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def blob_to_vec(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32).copy()
