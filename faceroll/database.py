"""SQLite storage for classes, students, face samples, sessions and attendance.

Only "present" rows are stored in `attendance`; anyone without a row for a
session is absent. Use from the GUI thread only.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from .engine import blob_to_vec, vec_to_blob

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY,
    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    roll_no TEXT NOT NULL,
    name TEXT NOT NULL,
    photo BLOB,
    created_at TEXT NOT NULL,
    UNIQUE (class_id, roll_no)
);
CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    vector BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE TABLE IF NOT EXISTS attendance (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    marked_at TEXT NOT NULL,
    method TEXT NOT NULL,          -- 'face' or 'manual'
    score REAL,
    PRIMARY KEY (session_id, student_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_id);
CREATE INDEX IF NOT EXISTS idx_emb_student ON embeddings(student_id);
CREATE INDEX IF NOT EXISTS idx_sessions_class ON sessions(class_id);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Student:
    id: int
    class_id: int
    roll_no: str
    name: str
    photo: bytes | None
    samples: int = 0

    @property
    def label(self) -> str:
        return f"{self.roll_no} - {self.name}"


@dataclass
class Session:
    id: int
    class_id: int
    title: str
    started_at: str
    ended_at: str | None


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------- settings ----------
    def get_setting(self, key: str, default: str) -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    # ---------- classes ----------
    def add_class(self, name: str) -> int:
        cur = self.conn.execute("INSERT INTO classes(name, created_at) VALUES(?, ?)", (name.strip(), now()))
        self.conn.commit()
        return cur.lastrowid

    def rename_class(self, class_id: int, name: str) -> None:
        self.conn.execute("UPDATE classes SET name=? WHERE id=?", (name.strip(), class_id))
        self.conn.commit()

    def delete_class(self, class_id: int) -> None:
        self.conn.execute("DELETE FROM classes WHERE id=?", (class_id,))
        self.conn.commit()

    def classes(self) -> list[tuple[int, str]]:
        return [(r["id"], r["name"]) for r in self.conn.execute("SELECT id, name FROM classes ORDER BY name")]

    # ---------- students ----------
    def add_student(
        self,
        class_id: int,
        roll_no: str,
        name: str,
        embeddings: list[np.ndarray],
        photo: bytes | None = None,
    ) -> int:
        """Add a student, or replace the face samples of an existing roll number."""
        roll_no, name = roll_no.strip(), name.strip()
        row = self.conn.execute(
            "SELECT id FROM students WHERE class_id=? AND roll_no=?", (class_id, roll_no)
        ).fetchone()
        if row:
            sid = row["id"]
            self.conn.execute(
                "UPDATE students SET name=?, photo=COALESCE(?, photo) WHERE id=?", (name, photo, sid)
            )
            self.conn.execute("DELETE FROM embeddings WHERE student_id=?", (sid,))
        else:
            cur = self.conn.execute(
                "INSERT INTO students(class_id, roll_no, name, photo, created_at) VALUES(?,?,?,?,?)",
                (class_id, roll_no, name, photo, now()),
            )
            sid = cur.lastrowid
        self.conn.executemany(
            "INSERT INTO embeddings(student_id, vector) VALUES(?, ?)",
            [(sid, vec_to_blob(e)) for e in embeddings],
        )
        self.conn.commit()
        return sid

    def update_student(self, student_id: int, roll_no: str, name: str) -> None:
        self.conn.execute(
            "UPDATE students SET roll_no=?, name=? WHERE id=?", (roll_no.strip(), name.strip(), student_id)
        )
        self.conn.commit()

    def delete_student(self, student_id: int) -> None:
        self.conn.execute("DELETE FROM students WHERE id=?", (student_id,))
        self.conn.commit()

    def students(self, class_id: int) -> list[Student]:
        rows = self.conn.execute(
            """SELECT s.id, s.class_id, s.roll_no, s.name, s.photo, COUNT(e.id) AS samples
               FROM students s LEFT JOIN embeddings e ON e.student_id = s.id
               WHERE s.class_id=? GROUP BY s.id""",
            (class_id,),
        ).fetchall()
        result = [Student(r["id"], r["class_id"], r["roll_no"], r["name"], r["photo"], r["samples"]) for r in rows]
        result.sort(key=lambda s: _roll_sort_key(s.roll_no))
        return result

    def student(self, student_id: int) -> Student | None:
        r = self.conn.execute(
            "SELECT id, class_id, roll_no, name, photo FROM students WHERE id=?", (student_id,)
        ).fetchone()
        return Student(r["id"], r["class_id"], r["roll_no"], r["name"], r["photo"]) if r else None

    def gallery_entries(self, class_id: int) -> dict[int, np.ndarray]:
        rows = self.conn.execute(
            """SELECT e.student_id, e.vector FROM embeddings e
               JOIN students s ON s.id = e.student_id WHERE s.class_id=?""",
            (class_id,),
        ).fetchall()
        out: dict[int, list[np.ndarray]] = {}
        for r in rows:
            out.setdefault(r["student_id"], []).append(blob_to_vec(r["vector"]))
        return {sid: np.vstack(v) for sid, v in out.items()}

    # ---------- sessions & attendance ----------
    def start_session(self, class_id: int, title: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO sessions(class_id, title, started_at) VALUES(?,?,?)", (class_id, title.strip(), now())
        )
        self.conn.commit()
        return cur.lastrowid

    def end_session(self, session_id: int) -> None:
        self.conn.execute("UPDATE sessions SET ended_at=? WHERE id=?", (now(), session_id))
        self.conn.commit()

    def delete_session(self, session_id: int) -> None:
        self.conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        self.conn.commit()

    def sessions(self, class_id: int) -> list[Session]:
        rows = self.conn.execute(
            "SELECT * FROM sessions WHERE class_id=? ORDER BY started_at, id", (class_id,)
        ).fetchall()
        return [Session(r["id"], r["class_id"], r["title"], r["started_at"], r["ended_at"]) for r in rows]

    def mark_present(self, session_id: int, student_id: int, method: str = "face", score: float | None = None) -> bool:
        """Returns True if newly marked, False if already present."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO attendance(session_id, student_id, marked_at, method, score) VALUES(?,?,?,?,?)",
            (session_id, student_id, now(), method, score),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def mark_absent(self, session_id: int, student_id: int) -> None:
        self.conn.execute("DELETE FROM attendance WHERE session_id=? AND student_id=?", (session_id, student_id))
        self.conn.commit()

    def session_attendance(self, session_id: int) -> dict[int, sqlite3.Row]:
        rows = self.conn.execute("SELECT * FROM attendance WHERE session_id=?", (session_id,)).fetchall()
        return {r["student_id"]: r for r in rows}

    def class_matrix(self, class_id: int) -> tuple[list[Student], list[Session], set[tuple[int, int]]]:
        """Students, sessions and the set of (student_id, session_id) pairs marked present."""
        studs = self.students(class_id)
        sess = self.sessions(class_id)
        rows = self.conn.execute(
            """SELECT a.student_id, a.session_id FROM attendance a
               JOIN sessions s ON s.id = a.session_id WHERE s.class_id=?""",
            (class_id,),
        ).fetchall()
        return studs, sess, {(r["student_id"], r["session_id"]) for r in rows}


def _roll_sort_key(roll: str):
    """Sort '2' before '10', and keep alphanumeric rolls like 'BS-12' sensible."""
    import re

    parts = re.split(r"(\d+)", roll)
    return [int(p) if p.isdigit() else p.lower() for p in parts]
