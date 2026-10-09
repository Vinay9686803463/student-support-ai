"""Seed 5th-semester VTU CSE (2022 scheme) subjects (idempotent).

Run:  venv\\Scripts\\python.exe seed_subjects.py
Skips subjects that already exist, so it is safe to run many times.
"""

from app import app
from sqlalchemy import text

from utils.database import db


SUBJECTS = [
    ("BCS501", "Software Engineering & Project Management", 5, "CSE", "2022"),
    ("BCS502", "Computer Networks", 5, "CSE", "2022"),
    ("BCS503", "Theory of Computation", 5, "CSE", "2022"),
    ("BCS508", "Environmental Studies and E-Waste Management", 5, "CSE", "2022"),
    ("BCS515x", "Professional Elective Course", 5, "CSE", "2022"),
    ("BCSL504", "Web Technology Lab", 5, "CSE", "2022"),
    ("BNSK559", "National Service Scheme (NSS)", 5, "CSE", "2022"),
    ("BPEK559", "Physical Education (PE) (Sports and Athletics)", 5, "CSE", "2022"),
    ("BRMK557", "Research Methodology and IPR", 5, "CSE", "2022"),
    ("BYOK559", "Yoga", 5, "CSE", "2022"),
]


with app.app_context():
    added = 0
    for code, name, semester, branch, scheme in SUBJECTS:
        # Use a separate connection to avoid psycopg prepared statement cache
        bind = db.engine.connect()
        try:
            exists = bind.execute(
                text("SELECT id FROM subjects WHERE subject_code = :code"),
                {"code": code}
            ).first()
            if exists:
                continue
            bind.execute(
                text("""
                    INSERT INTO subjects
                        (subject_code, subject_name, semester, branch, scheme, credits, icon)
                    VALUES
                        (:code, :name, :semester, :branch, :scheme, 4, '📚')
                """),
                {
                    "code": code, "name": name, "semester": semester,
                    "branch": branch, "scheme": scheme
                }
            )
            added += 1
        finally:
            bind.close()
    db.session.commit()
    print(f"Subjects added: {added}")