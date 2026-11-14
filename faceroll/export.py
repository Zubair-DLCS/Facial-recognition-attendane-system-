"""Export the attendance register to Excel (.xlsx) or CSV."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .database import Database


def register_rows(db: Database, class_id: int) -> tuple[list[str], list[list]]:
    students, sessions, present = db.class_matrix(class_id)
    header = ["Roll No", "Name"] + [_session_label(s.started_at, s.title) for s in sessions]
    header += ["Present", "Total", "Percentage"]
    rows = []
    total = len(sessions)
    for st in students:
        marks = ["P" if (st.id, s.id) in present else "A" for s in sessions]
        count = marks.count("P")
        pct = round(100 * count / total, 1) if total else 0.0
        rows.append([st.roll_no, st.name, *marks, count, total, pct])
    return header, rows


def _session_label(started_at: str, title: str) -> str:
    try:
        d = datetime.fromisoformat(started_at).strftime("%d-%b-%Y %H:%M")
    except ValueError:
        d = started_at
    return f"{d}\n{title}" if title else d


def export_csv(db: Database, class_id: int, path: Path | str) -> None:
    header, rows = register_rows(db, class_id)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel reads Urdu names
        w = csv.writer(f)
        w.writerow([h.replace("\n", " ") for h in header])
        w.writerows(rows)


def export_xlsx(db: Database, class_id: int, path: Path | str, class_name: str, credit: str = "") -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    header, rows = register_rows(db, class_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance"

    ws["A1"] = f"Attendance Register - {class_name}"
    ws["A1"].font = Font(size=14, bold=True)
    ws["A2"] = f"Generated {datetime.now().strftime('%d %b %Y, %H:%M')}" + (f"  |  {credit}" if credit else "")
    ws["A2"].font = Font(italic=True, color="666666")

    thin = Side(style="thin", color="BBBBBB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="1F4E79")
    p_fill = PatternFill("solid", fgColor="E2F0D9")
    a_fill = PatternFill("solid", fgColor="FBE5E1")

    start = 4
    for c, h in enumerate(header, 1):
        cell = ws.cell(row=start, column=c, value=h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    ws.row_dimensions[start].height = 34

    n_sess = len(header) - 5
    for r, row in enumerate(rows, start + 1):
        for c, v in enumerate(row, 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.border = border
            if 3 <= c < 3 + n_sess:
                cell.alignment = Alignment(horizontal="center")
                cell.fill = p_fill if v == "P" else a_fill
            elif c == len(header):
                cell.number_format = '0.0"%"'
                if isinstance(v, (int, float)) and v < 75:
                    cell.font = Font(color="C00000", bold=True)

    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 26
    for c in range(3, len(header) + 1):
        ws.column_dimensions[get_column_letter(c)].width = 14
    ws.freeze_panes = ws.cell(row=start + 1, column=3)
    wb.save(path)
