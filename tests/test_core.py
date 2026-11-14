"""Tests that need no webcam. Run with:  python -m pytest -q"""

import numpy as np
import pytest

from faceroll.database import Database
from faceroll.engine import Gallery, iou
from faceroll.export import export_csv, export_xlsx, register_rows


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    yield d
    d.close()


def test_gallery_match_and_unknown():
    rng = np.random.default_rng(0)
    a, b = unit(rng.normal(size=128)), unit(rng.normal(size=128))
    g = Gallery({1: np.vstack([a]), 2: np.vstack([b])})
    assert len(g) == 2
    sid, score = g.match(unit(a + 0.05 * rng.normal(size=128)), 0.4)
    assert sid == 1 and score > 0.8
    sid, _ = g.match(unit(rng.normal(size=128)), 0.4)
    assert sid is None


def test_empty_gallery():
    assert Gallery().match(unit(np.ones(128))) == (None, 0.0)


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 5, 5)) == 0.0


def test_students_sessions_attendance(db):
    cid = db.add_class("BS CS 3A")
    e = [unit(np.ones(128))]
    s10 = db.add_student(cid, "10", "Ali", e)
    s2 = db.add_student(cid, "2", "Sana", e * 3)
    assert [s.roll_no for s in db.students(cid)] == ["2", "10"]  # natural sort
    assert {s.id: s.samples for s in db.students(cid)} == {s10: 1, s2: 3}

    # Re-enrolling the same roll replaces samples instead of duplicating the student
    db.add_student(cid, "10", "Ali Khan", e * 5)
    studs = {s.roll_no: s for s in db.students(cid)}
    assert len(studs) == 2 and studs["10"].name == "Ali Khan" and studs["10"].samples == 5

    sess = db.start_session(cid, "Lecture 1")
    assert db.mark_present(sess, s10, "face", 0.7) is True
    assert db.mark_present(sess, s10, "face", 0.8) is False  # no double marking
    db.mark_present(sess, s2, "manual")
    db.mark_absent(sess, s2)
    assert set(db.session_attendance(sess)) == {s10}

    db.start_session(cid, "Lecture 2")
    header, rows = register_rows(db, cid)
    assert header[:2] == ["Roll No", "Name"] and header[-3:] == ["Present", "Total", "Percentage"]
    by_roll = {r[0]: r for r in rows}
    assert by_roll["10"][2:4] == ["P", "A"] and by_roll["10"][-1] == 50.0
    assert by_roll["2"][-3] == 0


def test_cascade_delete(db):
    cid = db.add_class("X")
    sid = db.add_student(cid, "1", "A", [unit(np.ones(128))])
    sess = db.start_session(cid, "s")
    db.mark_present(sess, sid)
    db.delete_class(cid)
    assert db.conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0] == 0


def test_gallery_entries_scoped_to_class(db):
    c1, c2 = db.add_class("A"), db.add_class("B")
    s1 = db.add_student(c1, "1", "A1", [unit(np.ones(128))] * 2)
    db.add_student(c2, "1", "B1", [unit(np.ones(128))])
    ent = db.gallery_entries(c1)
    assert list(ent) == [s1] and ent[s1].shape == (2, 128)


def test_exports(db, tmp_path):
    cid = db.add_class("Class")
    sid = db.add_student(cid, "1", "علی", [unit(np.ones(128))])  # non-ASCII name
    sess = db.start_session(cid, "L1")
    db.mark_present(sess, sid)
    export_csv(db, cid, tmp_path / "a.csv")
    assert "علی" in (tmp_path / "a.csv").read_text(encoding="utf-8-sig")
    export_xlsx(db, cid, tmp_path / "a.xlsx", "Class", "credit")
    from openpyxl import load_workbook

    ws = load_workbook(tmp_path / "a.xlsx").active
    assert ws["A5"].value == "1" and ws["C5"].value == "P"
