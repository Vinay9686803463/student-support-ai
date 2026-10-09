"""Ensure DB-backed Module 1-5 for every required normal subject (Sem 1-5).

Architecture (existing, reused - no parallel system):
- subjects.subject_code (unique) -> subjects.id
- units.subject_id FK -> subjects.id, unit_number 1-5, unit_name
- knowledge_documents.subject_code + module_number (PDFs, untouched here)
- knowledge_chunks.document_id/subject_code/module_number (RAG, untouched here)
- subject_detail (app.py) already queries units + knowledge_documents
  scoped by subject_id / subject_code, so modules never leak across subjects.

Safety (idempotent):
- Only SELECT + INSERT missing subjects/units. Never DELETE subjects,
  knowledge_documents, or knowledge_chunks.
- Existing unit_name values (e.g. BCS501/BCS502/BCS503 real titles) are
  preserved; only missing unit_numbers are inserted as "Module N".
- Web Technology (BCSL504) is the one-file exception: this script ensures
  it has ZERO units rows (so no Module 1-5) and only reports its existing
  "Web Technology Programs.pdf" knowledge row. It never creates modules
  for BCSL504 and never deletes its PDF row.
- Excluded codes (BCS515x, BNSK559, BPEK559, BCS586) are never inserted
  and never touched.

Run: venv\\Scripts\\python.exe seed_subject_modules.py
"""

from sqlalchemy import text

from app import app
from utils.database import db

BRANCH = "CSE"
SCHEME = "2022"

# (code, name, semester). Category is left untouched for existing rows;
# new rows default to 'Core'.
REQUIRED = [
    # Semester 1
    ("BCEDK103", "Computer Aided Engineering Drawing", 1),
    ("BCHES102", "Chemistry for CSE Stream", 1),
    ("BESCK104C", "Electronics and Communication Engineering", 1),
    ("BENGK106", "Communicative English", 1),
    ("BKSKK107", "Samskrutika Kannada", 1),
    ("BMATS101", "Mathematics for CSE-Stream-I", 1),
    ("BSFHK158", "Scientific Foundations of Health", 1),
    ("BETCK105F", "Waste Management", 1),
    # Semester 2
    ("BPWSK206", "Professional Writing Skills in English", 2),
    ("BICOK207", "Indian Constitution", 2),
    ("BIDTK258", "Innovation and Design Thinking", 2),
    ("BPLCK205C", "Baasics of Java Programming", 2),
    ("BMATS201", "Mathematics for CSE Stream-II", 2),
    ("BESCK204D", "Introduction to Mechanical Engineering", 2),
    ("BPHYS202", "Physics for CSE Stream", 2),
    ("BPOPS203", "Principles of Programming Using C", 2),
    # Semester 3
    ("BCS301", "Mathematics for Computer Science", 3),
    ("BCS302", "Digital Design & Computer Organization", 3),
    ("BCS303", "Operating Systems", 3),
    ("BCS304", "Data Structures and Applications", 3),
    ("BCSL305", "Data Structures Lab", 3),
    ("BCS306B", "Object Oriented Programming with C++", 3),
    ("BSCK307", "Social Connect and Responsibility", 3),
    ("BYOK359", "Yoga", 3),
    # Semester 4
    ("BCS401", "Analysis & Design of Algorithms", 4),
    ("BCS402", "Microcontrollers", 4),
    ("BCS403", "Database Management Systems", 4),
    ("BCSL404", "Analysis & Design of Algorithms Lab", 4),
    ("BCS405A", "Discrete Mathematical Structures", 4),
    ("BCSL456D", "Technical Writing using LATEX", 4),
    ("BBOC407", "Biology for Computer Engineers", 4),
    ("BUHK408", "Universal Human Values Course", 4),
    ("BYOK459", "Yoga", 4),
    # Semester 5 (normal subjects; WebTech BCSL504 handled separately)
    ("BCS501", "Software Engineering & Project Management", 5),
    ("BCS502", "Computer Networks", 5),
    ("BCS503", "Theory of Computation", 5),
    ("BCS504", "Unix System Programming", 5),
    ("BRMK557", "Research Methodology and IPR", 5),
    ("BCS508", "Environmental Studies and E-Waste Management", 5),
]

WEBTECH_CODE = "BCSL504"
WEBTECH_FILE = "Web Technology Programs.pdf"

EXCLUDED = frozenset({"BCS515x", "BNSK559", "BPEK559", "BCS586"})


def ensure_subject(code, name, semester):
    assert code not in EXCLUDED, f"refusing to touch excluded {code}"
    row = db.session.execute(
        text("SELECT id, subject_name, semester FROM subjects "
             "WHERE subject_code = :c AND branch = :b AND scheme = :s"),
        {"c": code, "b": BRANCH, "s": SCHEME},
    ).first()
    if row:
        sid, old_name, old_sem = row[0], row[1], row[2]
        if old_name != name or old_sem != semester:
            db.session.execute(
                text("UPDATE subjects SET subject_name = :n, semester = :s, "
                     "branch = :b, scheme = :sc WHERE id = :i"),
                {"n": name, "s": semester, "b": BRANCH, "sc": SCHEME, "i": sid},
            )
            return sid, "updated"
        return sid, "ok"
    db.session.execute(
        text("INSERT INTO subjects (subject_code, subject_name, semester, "
             "branch, scheme, credits, icon, category) VALUES "
             "(:c, :n, :s, :b, :sc, 4, '📚', 'Core')"),
        {"c": code, "n": name, "s": semester, "b": BRANCH, "sc": SCHEME},
    )
    row = db.session.execute(
        text("SELECT id FROM subjects WHERE subject_code = :c"),
        {"c": code},
    ).first()
    return row[0], "inserted"


def ensure_units(subject_id, code):
    """Ensure unit_number 1-5 exist for subject. Returns (kept, inserted)."""
    existing = {
        r[0] for r in db.session.execute(
            text("SELECT unit_number FROM units WHERE subject_id = :i"),
            {"i": subject_id},
        ).fetchall()
    }
    inserted = 0
    for n in (1, 2, 3, 4, 5):
        if n in existing:
            continue
        db.session.execute(
            text("INSERT INTO units (subject_id, unit_number, unit_name) "
                 "VALUES (:i, :n, :u)"),
            {"i": subject_id, "n": n, "u": f"Module {n}"},
        )
        inserted += 1
    return 5 - inserted, inserted


with app.app_context():
    stats = {"subjects_ok": 0, "subjects_updated": 0, "subjects_inserted": 0,
             "units_kept": 0, "units_inserted": 0}
    subject_ids = {}
    for code, name, sem in REQUIRED:
        sid, status = ensure_subject(code, name, sem)
        subject_ids[code] = sid
        if status == "ok":
            stats["subjects_ok"] += 1
        elif status == "updated":
            stats["subjects_updated"] += 1
        else:
            stats["subjects_inserted"] += 1
        kept, inserted = ensure_units(sid, code)
        stats["units_kept"] += kept
        stats["units_inserted"] += inserted
        print(f"{status:8} {code} sem={sem} units kept={kept} inserted={inserted}")

    # Web Technology exception: zero units, single PDF row (report only).
    wrow = db.session.execute(
        text("SELECT id FROM subjects WHERE subject_code = :c"),
        {"c": WEBTECH_CODE},
    ).first()
    if wrow:
        wid = wrow[0]
        wn = db.session.execute(
            text("SELECT COUNT(*) FROM units WHERE subject_id = :i"), {"i": wid}
        ).scalar()
        if wn:
            db.session.execute(
                text("DELETE FROM units WHERE subject_id = :i"), {"i": wid}
            )
            print(f"webtech  {WEBTECH_CODE}: removed {wn} stray units rows (exception: no modules)")
        else:
            print(f"webtech  {WEBTECH_CODE}: 0 units rows (exception OK)")
        docs = db.session.execute(
            text("SELECT module_number, original_filename, status FROM knowledge_documents "
                 "WHERE subject_code = :c ORDER BY module_number"),
            {"c": WEBTECH_CODE},
        ).fetchall()
        print(f"webtech  docs: {[(d[0], d[1], d[2]) for d in docs]}")
    else:
        print(f"webtech  {WEBTECH_CODE}: subject row missing (left untouched)")

    # Excluded codes: verify untouched, never inserted.
    for code in sorted(EXCLUDED):
        n = db.session.execute(
            text("SELECT COUNT(*) FROM subjects WHERE subject_code = :c"), {"c": code}
        ).scalar()
        print(f"excluded {code}: rows={n} (untouched)")

    db.session.commit()

    print()
    print("Semester | Subjects | Modules")
    for sem in (1, 2, 3, 4, 5):
        n_sub = db.session.execute(
            text("SELECT COUNT(*) FROM subjects WHERE semester = :s AND subject_code = ANY(:codes)"),
            {"s": sem, "codes": [c for c, _n, s in REQUIRED if s == sem]},
        ).scalar()
        n_mod = db.session.execute(
            text("SELECT COUNT(*) FROM units u JOIN subjects s ON s.id = u.subject_id "
                 "WHERE s.semester = :s AND s.subject_code = ANY(:codes)"),
            {"s": sem, "codes": [c for c, _n, s in REQUIRED if s == sem]},
        ).scalar()
        print(f"{sem}        | {n_sub}        | {n_mod}")
    wunits = db.session.execute(
        text("SELECT COUNT(*) FROM units u JOIN subjects s ON s.id = u.subject_id "
             "WHERE s.subject_code = :c"), {"c": WEBTECH_CODE}
    ).scalar()
    print(f"WebTech  | 1 (exception) | {wunits} (must be 0)")
    print(f"DONE subjects ok={stats['subjects_ok']} updated={stats['subjects_updated']} "
          f"inserted={stats['subjects_inserted']} | units kept={stats['units_kept']} "
          f"inserted={stats['units_inserted']}")
