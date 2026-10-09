"""Seed official VTU B.E. CSE 2022-scheme subjects for semesters 1-4,
plus semester-5 professional-elective choices and activity classification.

Idempotent upsert: match on (subject_code, branch, scheme, semester);
update name/category/credits when present, insert otherwise. Uses one
fresh connection per row (Supabase pooler + prepared statements).
"""

from app import app
from sqlalchemy import text

from utils.database import db

BRANCH = "CSE"
SCHEME = "2022"

# (code, name, semester, category)
SUBJECTS = [
    # ---------------- Semester 1 ----------------
    ("BCEDK103", "Computer Aided Engineering Drawing", 1, "Core"),
    ("BCHES102", "Chemistry for CSE Stream", 1, "Core"),
    ("BESCK104C", "Electronics and Communication Engineering", 1, "Core"),
    ("BENGK106", "Communicative English", 1, "Core"),
    ("BKSKK107", "Samskrutika Kannada", 1, "Core"),
    ("BMATS101", "Mathematics for CSE-Stream-I", 1, "Core"),
    ("BSFHK158", "Scientific Foundations of Health", 1, "Core"),
    ("BETCK105F", "Waste Management", 1, "Core"),
    # ---------------- Semester 2 ----------------
    ("BPWSK206", "Professional Writing Skills in English", 2, "Core"),
    ("BICOK207", "Indian Constitution", 2, "Core"),
    ("BIDTK258", "Innovation and Design Thinking", 2, "Core"),
    ("BPLCK205C", "Baasics of Java Programming", 2, "Core"),
    ("BMATS201", "Mathematics for CSE Stream-II", 2, "Core"),
    ("BESCK204D", "Introduction to Mechanical Engineering", 2, "Core"),
    ("BPHYS202", "Physics for CSE Stream", 2, "Core"),
    ("BPOPS203", "Principles of Programming Using C", 2, "Core"),
    # ---------------- Semester 3 ----------------
    ("BCS301", "Mathematics for Computer Science", 3, "Core"),
    ("BCS302", "Digital Design & Computer Organization", 3, "Core"),
    ("BCS303", "Operating Systems", 3, "Core"),
    ("BCS304", "Data Structures and Applications", 3, "Core"),
    ("BCSL305", "Data Structures Lab", 3, "Core"),
    ("BSCK307", "Social Connect and Responsibility", 3, "Core"),
    ("BCS306B", "Object Oriented Programming with C++", 3, "Core"),
    ("BYOK359", "Yoga", 3, "Core"),
    # ---------------- Semester 4 ----------------
    ("BCS401", "Analysis & Design of Algorithms", 4, "Core"),
    ("BCS402", "Microcontrollers", 4, "Core"),
    ("BCS403", "Database Management Systems", 4, "Core"),
    ("BCSL404", "Analysis & Design of Algorithms Lab", 4, "Core"),
    ("BBOC407", "Biology for Computer Engineers", 4, "Core"),
    ("BUHK408", "Universal Human Values Course", 4, "Core"),
    ("BCS405A", "Discrete Mathematical Structures", 4, "Core"),
    ("BCSL456D", "Technical Writing using LATEX", 4, "Core"),
    ("BYOK459", "Yoga", 4, "Core"),
    # ---------------- Semester 5 additions ----------------
    ("BCS515A", "Computer Graphics", 5, "Professional Elective"),
    ("BCS515B", "Artificial Intelligence", 5, "Professional Elective"),
    ("BCS515C", "Unix System Programming", 5, "Professional Elective"),
    ("BCS515D", "Distributed Systems", 5, "Professional Elective"),
]

# Semester-5 rows reclassified as activity (list exclusion already covers them).
ACTIVITY_UPDATES = ["BNSK559", "BPEK559", "BYOK559"]

LAB_SUFFIXES = ("06", "07", "08", "58", "59")


def credits_for(code, category):
    if "L" in code[3:]:
        return 1
    if code.endswith(LAB_SUFFIXES):
        return 1
    if code.startswith(("BNSK", "BPEK", "BYOK", "BSCK", "BBOC", "BUHK")):
        return 1
    if category in ("Elective", "Professional Elective"):
        return 3
    return 4


def upsert(code, name, semester, category):
    # subject_code is globally unique: match on code (+branch/scheme)
    # and reconcile every field to the spec, healing any drift.
    with db.engine.connect() as conn:
        existing = conn.execute(
            text("""
                SELECT id FROM subjects
                WHERE subject_code = :code
                  AND branch = :branch
                  AND scheme = :scheme
            """),
            {"code": code, "branch": BRANCH, "scheme": SCHEME},
        ).first()
        if existing:
            conn.execute(
                text("""
                    UPDATE subjects
                    SET subject_name = :name,
                        semester = :semester,
                        category = :category,
                        credits = :credits
                    WHERE id = :sid
                """),
                {"name": name, "semester": semester, "category": category,
                 "credits": credits_for(code, category), "sid": existing[0]},
            )
            conn.commit()
            return "updated"
        conn.execute(
            text("""
                INSERT INTO subjects
                    (subject_code, subject_name, semester, branch, scheme,
                     credits, icon, category)
                VALUES
                    (:code, :name, :semester, :branch, :scheme,
                     :credits, '📚', :category)
            """),
            {"code": code, "name": name, "semester": semester,
             "branch": BRANCH, "scheme": SCHEME,
             "credits": credits_for(code, category), "category": category},
        )
        conn.commit()
        return "inserted"


# Subject codes the user rejected from the normal listing. They are
# never (re)seeded, and any row found with these codes is removed
# (only when unreferenced: no questions/units/resources/knowledge).
REMOVED_CODES = frozenset({
    "BCS306A", "BCS358x", "BCSL358A", "BCSL358B", "BCSL358C", "BCSL358D",
    "BCS405B", "BCS405C", "BCS405D", "BCS456A", "BCS456B", "BCS456C",
    "BNSK359", "BPEK359",
    # Superseded Semester 1/2 bucket codes (replaced by exact VTU codes).
    "BESCK104x", "BETCK105x", "BCEDK203", "BPLCK205x", "BESCK204x",
    # Resurrected Semester 1/2 rows from older seed lists.
    "BPOPS103", "BPHYS102", "BPLCK105x", "BPWSK106", "BKBKK107",
    "BICOK107", "BIDTK158", "BCHES202", "BETCK205x", "BENGK206",
    "BKSKK207", "BKBKK207", "BSFHK258",
})


def purge_removed():
    with db.engine.connect() as conn:
        for code in sorted(REMOVED_CODES):
            row = conn.execute(
                db.text("SELECT id FROM subjects WHERE subject_code = :code"),
                {"code": code},
            ).first()
            if not row:
                continue
            refs = 0
            for table, col in (("questions", "subject_id"),
                               ("units", "subject_id"),
                               ("resources", "subject_id")):
                refs += conn.execute(
                    db.text(f"SELECT COUNT(*) FROM {table} WHERE {col} = :i"),
                    {"i": row[0]},
                ).scalar()
            refs += conn.execute(
                db.text("SELECT COUNT(*) FROM knowledge_documents "
                        "WHERE subject_code = :code"),
                {"code": code},
            ).scalar()
            if refs:
                print(f"kept {code} (referenced {refs}x)")
                continue
            conn.execute(db.text("DELETE FROM subjects WHERE id = :i"),
                         {"i": row[0]})
            conn.commit()
            print(f"purged {code}")


with app.app_context():
    purge_removed()
    stats = {"inserted": 0, "updated": 0}
    for code, name, semester, category in SUBJECTS:
        result = upsert(code, name, semester, category)
        stats[result] += 1
        print(f"{result:8} {code} sem={semester} cat={category}")
    for code in ACTIVITY_UPDATES:
        with db.engine.connect() as conn:
            conn.execute(
                text("UPDATE subjects SET category = 'Activity' "
                     "WHERE subject_code = :code"),
                {"code": code},
            )
            conn.commit()
        print(f"activity  {code}")
    print(f"DONE inserted={stats['inserted']} updated={stats['updated']}")
