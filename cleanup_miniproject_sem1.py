"""Semester-1 renames + Mini Project removal (database part).

Does ONLY:
1. Rename 3 Semester-1 subjects (same rows, same codes, no duplicates):
     BMATS101 -> 'Mathematics for CSE-Stream-I'
     BCHES102 -> 'Chemistry for CSE Stream'
     BKSKK107 -> 'Samskrutika Kannada'
2. Delete the BCS586 'Mini Project' subject row (verified: zero references
   in questions / important_questions / resources / units / notes).
3. Delete Mini-Project-specific knowledge data (subject_code='MINI_PROJECTS'
   only): processing logs, chunks, then documents.

Never touches: semesters 2/3/4/5 subjects, VTU knowledge documents,
Web Technology, RMIP, users, notes, questions, resources.

Guards abort before commit on any violation.
Run: venv\\Scripts\\python.exe cleanup_miniproject_sem1.py
"""

from app import app
from sqlalchemy import text

from utils.database import db

RENAMES = [
    (14, "BMATS101", "Mathematics for CSE-Stream-I"),
    (18, "BCHES102", "Chemistry for CSE Stream"),
    (23, "BKSKK107", "Samskrutika Kannada"),
]

VTU_DOC_CODES = ["BCS501", "BCS502", "BCS503", "BCS504", "BCS515", "BCSL504", "BRMK557"]


def sem_counts():
    return dict(
        db.session.execute(
            text("SELECT semester, COUNT(*) FROM subjects GROUP BY semester ORDER BY semester")
        ).fetchall()
    )


def vtu_doc_counts():
    return {
        code: db.session.execute(
            text("SELECT COUNT(*) FROM knowledge_documents WHERE subject_code = :c"),
            {"c": code},
        ).scalar()
        for code in VTU_DOC_CODES
    }


with app.app_context():
    before_sem = sem_counts()
    before_docs = vtu_doc_counts()
    print("BEFORE sem:", before_sem)

    # --- guard: rename targets must be the expected sem-1 rows ---
    for row_id, code, _name in RENAMES:
        found = db.session.execute(
            text("SELECT subject_code, semester FROM subjects WHERE id = :i"),
            {"i": row_id},
        ).first()
        assert found is not None, f"row id={row_id} missing!"
        assert found[0] == code and found[1] == 1, (
            f"row id={row_id} is {(found[0], found[1])}, expected ({code}, 1). Aborting."
        )

    # --- guard: BCS586 must be sem 5 with zero references ---
    bcs = db.session.execute(
        text("SELECT id, semester FROM subjects WHERE subject_code = 'BCS586'")
    ).first()
    assert bcs is not None and bcs[1] == 5, "BCS586 not found in sem 5. Aborting."
    for tbl in ["questions", "important_questions", "resources", "units", "notes"]:
        n = db.session.execute(
            text(f"SELECT COUNT(*) FROM {tbl} WHERE subject_id = :i"), {"i": bcs[0]}
        ).scalar()
        assert n == 0, f"{tbl} references BCS586 ({n} rows). Aborting."

    # --- 1. renames (same rows, same codes) ---
    for row_id, _code, name in RENAMES:
        db.session.execute(
            text("UPDATE subjects SET subject_name = :n WHERE id = :i"),
            {"n": name, "i": row_id},
        )
        print(f"  RENAME id={row_id} -> {name}")

    # --- 2. delete Mini Project subject row ---
    deleted = db.session.execute(
        text("DELETE FROM subjects WHERE subject_code = 'BCS586' AND semester = 5")
    ).rowcount
    assert deleted == 1, f"expected to delete 1 BCS586 row, deleted {deleted}. Aborting."
    print("  DELETE BCS586 subject row")

    # --- 3. delete Mini-Project-specific knowledge data ---
    n_logs = db.session.execute(
        text("DELETE FROM knowledge_processing_logs WHERE document_id IN "
             "(SELECT id FROM knowledge_documents WHERE subject_code = 'MINI_PROJECTS')")
    ).rowcount
    n_chunks = db.session.execute(
        text("DELETE FROM knowledge_chunks WHERE subject_code = 'MINI_PROJECTS'")
    ).rowcount
    n_docs = db.session.execute(
        text("DELETE FROM knowledge_documents WHERE subject_code = 'MINI_PROJECTS'")
    ).rowcount
    print(f"  DELETE MINI_PROJECTS knowledge: docs={n_docs} chunks={n_chunks} logs={n_logs}")

    # --- verify before commit ---
    sem1 = sorted(
        r[0]
        for r in db.session.execute(
            text("SELECT subject_name FROM subjects WHERE semester = 1")
        ).fetchall()
    )
    assert sem1 == sorted([
        "Computer Aided Engineering Drawing",
        "Chemistry for CSE Stream",
        "Electronics and Communication Engineering",
        "Communicative English",
        "Samskrutika Kannada",
        "Mathematics for CSE-Stream-I",
        "Scientific Foundations of Health",
        "Waste Management",
    ]), f"sem1 mismatch: {sem1}"

    after_sem = sem_counts()
    assert after_sem.get(1) == 8, after_sem
    for sem in (2, 3, 4):
        assert after_sem.get(sem) == before_sem.get(sem), (
            f"sem {sem} changed: {before_sem.get(sem)} -> {after_sem.get(sem)}. Aborting."
        )
    assert after_sem.get(5) == before_sem.get(5) - 1, "sem5 count unexpected"
    assert db.session.execute(
        text("SELECT COUNT(*) FROM subjects WHERE subject_code = 'BCS586'")
    ).scalar() == 0
    assert db.session.execute(
        text("SELECT COUNT(*) FROM knowledge_documents WHERE subject_code = 'MINI_PROJECTS'")
    ).scalar() == 0
    assert db.session.execute(
        text("SELECT COUNT(*) FROM knowledge_chunks WHERE subject_code = 'MINI_PROJECTS'")
    ).scalar() == 0
    assert vtu_doc_counts() == before_docs, "VTU knowledge docs changed. Aborting."
    dupes = db.session.execute(
        text("SELECT subject_code, COUNT(*) FROM subjects GROUP BY 1 HAVING COUNT(*) > 1")
    ).fetchall()
    assert not dupes, f"duplicates: {dupes}"

    db.session.commit()
    print("AFTER sem:", sem_counts())
    print("COMMITTED. Sem-1 renamed; Mini Project subject + knowledge data removed.")
