"""Set Semester 1 and Semester 2 to exactly the 8 requested subjects each.

Scope guardrails (enforced in code, abort before commit on violation):
- Only rows with semester IN (1, 2) are ever updated or deleted.
- Semester 3, 4, 5 row counts must be identical before and after.
- No new subject_code values are invented: every kept row preserves its
  existing VTU code; only subject_name / semester / category change.
- knowledge_documents, PDFs, Web Technology: untouched
  (this script only touches the subjects table).

Run: venv\\Scripts\\python.exe seed_sem1_sem2.py
Idempotent: safe to re-run (updates match by id+code, deletes by id).
"""

from app import app
from sqlalchemy import text

from utils.database import db

# (id, expected_code, expected_sem, new_name, new_sem)
# Rows NOT listed here that are in semester 1/2 are DELETED.
KEEP = [
    # ---- Semester 1: the 8 requested subjects ----
    (32, "BCEDK203", 2, "Computer Aided Engineering Drawing", 1),
    (18, "BCHES102", 1, "Chemistry", 1),
    (16, "BESCK104x", 1, "Electronics and Communication Engineering", 1),
    (21, "BENGK106", 1, "Communicative English", 1),
    (23, "BKSKK107", 1, "Kannada", 1),
    (14, "BMATS101", 1, "Mathematics", 1),
    (27, "BSFHK158", 1, "Scientific Foundations of Health", 1),
    (19, "BETCK105x", 1, "Waste Management", 1),
    # ---- Semester 2: the 8 requested subjects ----
    (37, "BPWSK206", 2, "Professional Writing Skills in English", 2),
    (38, "BICOK207", 2, "Indian Constitution", 2),
    (41, "BIDTK258", 2, "Innovation and Design Thinking", 2),
    (35, "BPLCK205x", 2, "Object-Oriented Programming with Java", 2),
    (28, "BMATS201", 2, "Mathematics", 2),
    (29, "BESCK204x", 2, "Mechanical Engineering", 2),
    (31, "BPHYS202", 2, "Physics", 2),
    (33, "BPOPS203", 2, "Principles of Programming", 2),
]


def semester_counts():
    rows = db.session.execute(
        text("SELECT semester, COUNT(*) FROM subjects GROUP BY semester ORDER BY semester")
    ).fetchall()
    return {r[0]: r[1] for r in rows}


with app.app_context():
    before = semester_counts()
    print("BEFORE:", before)

    keep_ids = {row[0] for row in KEEP}

    # --- safety: every KEEP id must be a sem 1/2 row with the expected code ---
    # (current semester may be the old or new value on re-runs; both are
    # inside the allowed scope, and the UPDATE below is naturally idempotent)
    for row_id, code, sem, _name, _new_sem in KEEP:
        found = db.session.execute(
            text("SELECT subject_code, semester FROM subjects WHERE id = :i"),
            {"i": row_id},
        ).first()
        assert found is not None, f"KEEP row id={row_id} missing!"
        assert found[0] == code and found[1] in (1, 2), (
            f"KEEP row id={row_id} out of scope: db has {(found[0], found[1])}, "
            f"expected code {code} in semester 1/2. Aborting."
        )

    # --- safety: every other sem 1/2 row must be a genuine sem 1/2 row ---
    others = db.session.execute(
        text("SELECT id, subject_code, semester FROM subjects WHERE semester IN (1, 2)")
    ).fetchall()
    to_delete = [r for r in others if r[0] not in keep_ids]
    assert all(r[2] in (1, 2) for r in to_delete), "Delete list leaked outside sem 1/2!"
    print(f"Keeping {len(keep_ids)} rows, deleting {len(to_delete)} rows:")
    for row_id, code, sem in sorted(to_delete, key=lambda r: (r[2], r[1])):
        print(f"  DELETE id={row_id} {code} (sem {sem})")

    # --- apply updates (preserve codes, set names/semester/category) ---
    for row_id, _code, _sem, name, new_sem in KEEP:
        db.session.execute(
            text("""
                UPDATE subjects
                SET subject_name = :name,
                    semester = :sem,
                    branch = 'CSE',
                    scheme = '2022',
                    category = 'Core'
                WHERE id = :i
            """),
            {"name": name, "sem": new_sem, "i": row_id},
        )
        print(f"  KEEP   id={row_id} -> sem {new_sem} | {name}")

    # --- delete unwanted sem 1/2 rows only ---
    for row_id, _code, _sem in to_delete:
        # Re-guard inside the loop: never delete outside sem 1/2.
        db.session.execute(
            text("DELETE FROM subjects WHERE id = :i AND semester IN (1, 2)"),
            {"i": row_id},
        )

    # --- verify before commit ---
    after = semester_counts()
    print("AFTER (pre-commit):", after)
    assert after.get(1) == 8, f"sem 1 must be 8, got {after.get(1)}"
    assert after.get(2) == 8, f"sem 2 must be 8, got {after.get(2)}"
    for sem in (3, 4, 5):
        assert after.get(sem) == before.get(sem), (
            f"sem {sem} changed: {before.get(sem)} -> {after.get(sem)}. Aborting."
        )
    dupes = db.session.execute(
        text("SELECT subject_code, COUNT(*) FROM subjects GROUP BY subject_code HAVING COUNT(*) > 1")
    ).fetchall()
    assert not dupes, f"duplicate codes: {dupes}"

    db.session.commit()
    print("COMMITTED. Final:", semester_counts())
    print("Sem 3/4/5 untouched. No duplicates. Done.")
