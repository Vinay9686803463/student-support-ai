"""Correct VTU 2022 subject codes for semesters 1-4 (database part).

Code-driven (no id assumptions): matches rows by subject_code, so it is
robust against rows resurrected by older seed scripts.

Does ONLY:
1. Rename 5 subject codes (same rows, names preserved):
     BCEDK203 -> BCEDK103, BESCK104x -> BESCK104C, BETCK105x -> BETCK105F,
     BPLCK205x -> BPLCK205C, BESCK204x -> BESCK204D
2. Reconcile every kept sem1-4 row to (name, semester, CSE/2022, Core).
3. Delete every other sem1/2/3 row (unwanted resurrected rows included),
   each only after a zero-reference guard (questions/resources/units/notes
   + knowledge_documents).
4. Insert BYOK459 Yoga (sem 4, Core) if absent.

Never touches: semester 5, knowledge_documents/chunks, users, notes,
questions, resources. Guards abort before commit on any violation.
Run: venv\\Scripts\\python.exe fix_sem_codes_1_to_4.py (idempotent)
"""

from app import app
from sqlalchemy import text

from utils.database import db

CODE_RENAMES = [
    ("BCEDK203", "BCEDK103"),
    ("BESCK104x", "BESCK104C"),
    ("BETCK105x", "BETCK105F"),
    ("BPLCK205x", "BPLCK205C"),
    ("BESCK204x", "BESCK204D"),
]

# (final_code, name, semester) — the only rows allowed in semesters 1-4.
FINAL = [
    ("BCEDK103", "Computer Aided Engineering Drawing", 1),
    ("BCHES102", "Chemistry for CSE Stream", 1),
    ("BESCK104C", "Electronics and Communication Engineering", 1),
    ("BENGK106", "Communicative English", 1),
    ("BKSKK107", "Samskrutika Kannada", 1),
    ("BMATS101", "Mathematics for CSE-Stream-I", 1),
    ("BSFHK158", "Scientific Foundations of Health", 1),
    ("BETCK105F", "Waste Management", 1),
    ("BPWSK206", "Professional Writing Skills in English", 2),
    ("BICOK207", "Indian Constitution", 2),
    ("BIDTK258", "Innovation and Design Thinking", 2),
    ("BPLCK205C", "Baasics of Java Programming", 2),
    ("BMATS201", "Mathematics for CSE Stream-II", 2),
    ("BESCK204D", "Introduction to Mechanical Engineering", 2),
    ("BPHYS202", "Physics for CSE Stream", 2),
    ("BPOPS203", "Principles of Programming Using C", 2),
    ("BCS301", "Mathematics for Computer Science", 3),
    ("BCS302", "Digital Design & Computer Organization", 3),
    ("BCS303", "Operating Systems", 3),
    ("BCS304", "Data Structures and Applications", 3),
    ("BCSL305", "Data Structures Lab", 3),
    ("BCS306B", "Object Oriented Programming with C++", 3),
    ("BSCK307", "Social Connect and Responsibility", 3),
    ("BYOK359", "Yoga", 3),
    ("BCS401", "Analysis & Design of Algorithms", 4),
    ("BCS402", "Microcontrollers", 4),
    ("BCS403", "Database Management Systems", 4),
    ("BCSL404", "Analysis & Design of Algorithms Lab", 4),
    ("BCS405A", "Discrete Mathematical Structures", 4),
    ("BCSL456D", "Technical Writing using LATEX", 4),
    ("BBOC407", "Biology for Computer Engineers", 4),
    ("BUHK408", "Universal Human Values Course", 4),
    ("BYOK459", "Yoga", 4),
]

VTU_DOC_CODES = ["BCS501", "BCS502", "BCS503", "BCS504", "BCS515", "BCSL504", "BRMK557"]
FINAL_CODES = {code for code, _name, _sem in FINAL}


def row_by_code(code):
    return db.session.execute(
        text("SELECT id, subject_code, semester FROM subjects WHERE subject_code = :c"),
        {"c": code},
    ).first()


with app.app_context():
    before_sem5 = db.session.execute(
        text("SELECT subject_code, subject_name, category FROM subjects "
             "WHERE semester = 5 ORDER BY subject_code")
    ).fetchall()
    before_docs = {
        code: db.session.execute(
            text("SELECT COUNT(*) FROM knowledge_documents WHERE subject_code = :c"),
            {"c": code},
        ).scalar()
        for code in VTU_DOC_CODES
    }

    # --- 1. code renames ---
    for old_code, new_code in CODE_RENAMES:
        old = row_by_code(old_code)
        new = row_by_code(new_code)
        if old is None:
            print(f"  CODE {old_code} already gone")
            continue
        assert old[2] in (1, 2), f"{old_code} not in sem 1/2. Aborting."
        if new is not None:
            assert new[0] != old[0]
            # Duplicate pair: drop the obsolete old-code row if unreferenced.
            refs = 0
            for tbl in ["questions", "resources", "units", "notes"]:
                refs += db.session.execute(
                    text(f"SELECT COUNT(*) FROM {tbl} WHERE subject_id = :i"),
                    {"i": old[0]},
                ).scalar()
            assert refs == 0, f"duplicate {old_code} referenced {refs}x. Aborting."
            db.session.execute(text("DELETE FROM subjects WHERE id = :i"), {"i": old[0]})
            print(f"  DUPLICATE {old_code} removed (kept {new_code})")
            continue
        db.session.execute(
            text("UPDATE subjects SET subject_code = :c WHERE id = :i"),
            {"c": new_code, "i": old[0]},
        )
        print(f"  CODE {old_code} -> {new_code}")

    # --- 2. reconcile kept rows ---
    for code, name, sem in FINAL:
        row = row_by_code(code)
        if row is None and code == "BYOK459":
            db.session.execute(
                text("INSERT INTO subjects (subject_code, subject_name, semester, branch, "
                     "scheme, credits, icon, category) VALUES ('BYOK459', 'Yoga', 4, 'CSE', "
                     "'2022', 1, '📚', 'Core')")
            )
            print("  INSERT BYOK459 Yoga (sem 4, Core)")
            continue
        assert row is not None, f"final row {code} missing and not insertable. Aborting."
        db.session.execute(
            text("UPDATE subjects SET subject_name = :n, semester = :s, "
                 "branch = 'CSE', scheme = '2022', category = 'Core' WHERE id = :i"),
            {"n": name, "s": sem, "i": row[0]},
        )
    print(f"  RECONCILED {len(FINAL) - 1} kept rows + BYOK459 ensured")

    # --- 3. delete every other sem1/2/3 row (guarded) ---
    others = db.session.execute(
        text("SELECT id, subject_code, semester FROM subjects WHERE semester IN (1, 2, 3)")
    ).fetchall()
    pruned = 0
    for row_id, code, sem in others:
        if code in FINAL_CODES:
            continue
        refs = 0
        for tbl in ["questions", "resources", "units", "notes"]:
            refs += db.session.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE subject_id = :i"), {"i": row_id}
            ).scalar()
        refs += db.session.execute(
            text("SELECT COUNT(*) FROM knowledge_documents WHERE subject_code = :c"),
            {"c": code},
        ).scalar()
        assert refs == 0, f"unwanted {code} referenced {refs}x. Aborting."
        db.session.execute(
            text("DELETE FROM subjects WHERE id = :i AND semester IN (1, 2, 3)"),
            {"i": row_id},
        )
        pruned += 1
        print(f"  PRUNE {code} (sem {sem})")
    print(f"  PRUNED {pruned} unwanted rows")

    # --- 3b. re-remove BCS586 if some other script resurrected it ---
    # (forbidden as a normal card; sem 5 otherwise untouched)
    bcs = db.session.execute(
        text("SELECT id, semester FROM subjects WHERE subject_code = 'BCS586'")
    ).first()
    if bcs is None:
        print("  BCS586 already absent")
    else:
        assert bcs[1] == 5, f"BCS586 outside sem 5 ({bcs[1]}). Aborting."
        refs = 0
        for tbl in ["questions", "resources", "units", "notes"]:
            refs += db.session.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE subject_id = :i"), {"i": bcs[0]}
            ).scalar()
        assert refs == 0, f"BCS586 referenced {refs}x. Aborting."
        db.session.execute(
            text("DELETE FROM subjects WHERE id = :i AND semester = 5"), {"i": bcs[0]}
        )
        print("  PRUNE BCS586 (resurrected Mini Project row)")

    # --- verify before commit ---
    counts = dict(
        db.session.execute(
            text("SELECT semester, COUNT(*) FROM subjects GROUP BY semester ORDER BY semester")
        ).fetchall()
    )
    assert counts.get(1) == 8 and counts.get(2) == 8 and counts.get(3) == 8 \
        and counts.get(4) == 9, counts
    for sem, want in [
        (1, ["BCEDK103", "BCHES102", "BESCK104C", "BENGK106",
             "BKSKK107", "BMATS101", "BSFHK158", "BETCK105F"]),
        (2, ["BPWSK206", "BICOK207", "BIDTK258", "BPLCK205C",
             "BMATS201", "BESCK204D", "BPHYS202", "BPOPS203"]),
        (3, ["BCS301", "BCS302", "BCS303", "BCS304",
             "BCSL305", "BCS306B", "BSCK307", "BYOK359"]),
        (4, ["BBOC407", "BCS401", "BCS402", "BCS403", "BCS405A",
             "BCSL404", "BCSL456D", "BUHK408", "BYOK459"]),
    ]:
        got = sorted(
            r[0]
            for r in db.session.execute(
                text("SELECT subject_code FROM subjects WHERE semester = :s"), {"s": sem}
            ).fetchall()
        )
        assert got == sorted(want), f"sem{sem}: {got}"
    after_sem5 = db.session.execute(
        text("SELECT subject_code, subject_name, category FROM subjects "
             "WHERE semester = 5 ORDER BY subject_code")
    ).fetchall()
    before_set = {(r[0], r[1], r[2]) for r in before_sem5 if r[0] != "BCS586"}
    after_set = {(r[0], r[1], r[2]) for r in after_sem5}
    assert after_set == before_set, "semester 5 changed beyond BCS586 removal. Aborting."
    assert counts.get(5) == len(before_set), counts
    after_docs = {
        code: db.session.execute(
            text("SELECT COUNT(*) FROM knowledge_documents WHERE subject_code = :c"),
            {"c": code},
        ).scalar()
        for code in VTU_DOC_CODES
    }
    assert after_docs == before_docs, "VTU knowledge docs changed. Aborting."
    dupes = db.session.execute(
        text("SELECT subject_code, COUNT(*) FROM subjects GROUP BY 1 HAVING COUNT(*) > 1")
    ).fetchall()
    assert not dupes, f"duplicates: {dupes}"

    db.session.commit()
    print("AFTER sem:", counts)
    print("COMMITTED. Sem 1-4 codes corrected; sem 5 + knowledge base untouched.")
