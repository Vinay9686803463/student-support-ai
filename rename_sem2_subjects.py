"""Rename 5 Semester-2 subjects to exact requested display names.

Same rows, same codes, no duplicates. All other semesters untouched.
NOTE: 'Baasics of Java Programming' spelling is intentional per request.

Run: venv\\Scripts\\python.exe rename_sem2_subjects.py
Idempotent: safe to re-run.
"""

from app import app
from sqlalchemy import text

from utils.database import db

# (id, expected_code, new_name) — all must currently be semester 2.
RENAMES = [
    (35, "BPLCK205x", "Baasics of Java Programming"),
    (28, "BMATS201", "Mathematics for CSE Stream-II"),
    (29, "BESCK204x", "Introduction to Mechanical Engineering"),
    (31, "BPHYS202", "Physics for CSE Stream"),
    (33, "BPOPS203", "Principles of Programming Using C"),
]

EXPECTED_SEM2 = sorted([
    "Professional Writing Skills in English",
    "Indian Constitution",
    "Innovation and Design Thinking",
    "Baasics of Java Programming",
    "Mathematics for CSE Stream-II",
    "Introduction to Mechanical Engineering",
    "Physics for CSE Stream",
    "Principles of Programming Using C",
])


def sem_counts():
    return dict(
        db.session.execute(
            text("SELECT semester, COUNT(*) FROM subjects GROUP BY semester ORDER BY semester")
        ).fetchall()
    )


with app.app_context():
    before = sem_counts()
    print("BEFORE:", before)

    for row_id, code, name in RENAMES:
        found = db.session.execute(
            text("SELECT subject_code, semester FROM subjects WHERE id = :i"),
            {"i": row_id},
        ).first()
        assert found is not None, f"row id={row_id} missing!"
        assert found[0] == code and found[1] == 2, (
            f"row id={row_id} is {(found[0], found[1])}, expected ({code}, 2). Aborting."
        )
        db.session.execute(
            text("UPDATE subjects SET subject_name = :n WHERE id = :i"),
            {"n": name, "i": row_id},
        )
        print(f"  RENAME id={row_id} {code} -> {name}")

    names = sorted(
        r[0]
        for r in db.session.execute(
            text("SELECT subject_name FROM subjects WHERE semester = 2")
        ).fetchall()
    )
    assert names == EXPECTED_SEM2, f"sem2 mismatch: {names}"
    assert db.session.execute(
        text("SELECT COUNT(*) FROM subjects WHERE semester = 2")
    ).scalar() == 8

    after = sem_counts()
    for sem in (1, 3, 4, 5):
        assert after.get(sem) == before.get(sem), (
            f"sem {sem} changed: {before.get(sem)} -> {after.get(sem)}. Aborting."
        )
    dupes = db.session.execute(
        text("SELECT subject_code, COUNT(*) FROM subjects GROUP BY 1 HAVING COUNT(*) > 1")
    ).fetchall()
    assert not dupes, f"duplicates: {dupes}"

    db.session.commit()
    print("AFTER:", sem_counts())
    print("COMMITTED. Semester-2 renames done; codes preserved; no duplicates.")
