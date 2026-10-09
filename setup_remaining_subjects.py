"""Insert BCS504/BCS515 subject rows (idempotent) so their subject
pages resolve. BCS503 and BCSL504 already exist."""
from app import app
from utils.database import db

NEEDED = [
    ("BCS504", "Unix System Programming", 5, "CSE", "2022"),
    ("BCS515", "Environmental Studies and E-waste", 5, "CSE", "2022"),
]

with app.app_context():
    for code, name, semester, branch, scheme in NEEDED:
        exists = db.session.execute(
            db.text("SELECT id FROM subjects WHERE subject_code = :code"),
            {"code": code},
        ).first()
        if exists:
            print(f"EXISTS {code} id={exists[0]}")
            continue
        db.session.execute(
            db.text("""
                INSERT INTO subjects
                    (subject_code, subject_name, semester, branch, scheme, credits, icon)
                VALUES (:code, :name, :semester, :branch, :scheme, 4, '📚')
            """),
            {"code": code, "name": name, "semester": semester,
             "branch": branch, "scheme": scheme},
        )
        print(f"ADDED {code}")
    db.session.commit()
print("DONE")