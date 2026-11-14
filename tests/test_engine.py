"""Checks the bundled ONNX models load and produce sane embeddings (no webcam needed)."""

import cv2
import numpy as np
import pytest

from faceroll.engine import FaceEngine


@pytest.fixture(scope="module")
def engine():
    return FaceEngine()


def test_models_load_and_handle_blank_frame(engine):
    blank = np.zeros((480, 640, 3), np.uint8)
    assert engine.detect(blank) == []


def test_same_face_matches_itself(engine):
    skimage = pytest.importorskip("skimage")  # bundled sample photo with a face
    img = cv2.cvtColor(skimage.data.astronaut(), cv2.COLOR_RGB2BGR)
    face = engine.largest_face(img)
    assert face is not None and face.score > 0.8
    a = engine.embed(img, face)
    assert abs(np.linalg.norm(a) - 1.0) < 1e-4

    # Different scale and lighting of the same photo should still match strongly
    img2 = cv2.convertScaleAbs(cv2.resize(img, None, fx=0.6, fy=0.6), alpha=0.8, beta=25)
    b = engine.embed(img2, engine.largest_face(img2))
    assert float(a @ b) > 0.6
