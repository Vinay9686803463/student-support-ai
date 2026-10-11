"""Register Yoga (BYOK459, 4th Semester) Study Material documents.

Thin strict wrapper around utils.bootstrap (single source of truth for
the file list): validates every file, then runs the same idempotent
ensure the app runs on every boot. Documents render as unnumbered
file cards directly under the Study Material heading (BYOK459 is in
the unnumbered-file list in app.py:subject_detail) - no Module
sections, no Additional Resources section.

- Only SELECT + INSERT missing knowledge_documents rows keyed by
  (subject_code, original_filename, module_number). Never
  UPDATE/DELETE subjects, units, knowledge_documents, or chunks.
- Fails loudly (no silent skips) when the subject row or a file is
  missing/unreadable.

Run: venv\\Scripts\\python.exe seed_yoga459.py
Runs against DATABASE_URL (.env) - local SQLite or production Postgres.
"""

from pathlib import Path

from sqlalchemy import text

from app import app
from utils.bootstrap import (
    STUDY_MATERIALS,
    ensure_canonical_subjects,
    ensure_study_materials,
)
from utils.database import db

SUBJECT_CODE = "BYOK459"
FILES = [f for f, _m in STUDY_MATERIALS[SUBJECT_CODE]]
SOURCE_DIR = Path(__file__).resolve().parent / "knowledge_base" / SUBJECT_CODE


def main():
    assert len(FILES) == 4, "all four Yoga documents must be listed"

    for filename in FILES:
        doc_path = SOURCE_DIR / filename
        if not doc_path.is_file():
            raise SystemExit(f"source file missing: {doc_path}")
        if doc_path.suffix.lower() != ".docx":
            raise SystemExit(f"unexpected non-Word file: {doc_path}")
        with open(doc_path, "rb") as fh:
            if fh.read(2) != b"PK":
                raise SystemExit(f"not a valid .docx (bad zip magic): {doc_path}")
        if doc_path.stat().st_size < 1:
            raise SystemExit(f"empty document: {doc_path}")

    with app.app_context():
        subject = db.session.execute(
            text("SELECT id FROM subjects WHERE subject_code = :c"),
            {"c": SUBJECT_CODE},
        ).first()
        if not subject:
            raise SystemExit(
                f"subject {SUBJECT_CODE} missing; "
                "ensure_canonical_subjects() should have restored it"
            )

        before = {
            (row[0], row[1]) for row in db.session.execute(
                text("""
                    SELECT original_filename, module_number
                    FROM knowledge_documents
                    WHERE subject_code = :c
                """),
                {"c": SUBJECT_CODE},
            ).fetchall()
        }

        ensure_canonical_subjects()
        ensure_study_materials()

        after = {
            (row[0], row[1]): row[2] for row in db.session.execute(
                text("""
                    SELECT original_filename, module_number, id
                    FROM knowledge_documents
                    WHERE subject_code = :c
                """),
                {"c": SUBJECT_CODE},
            ).fetchall()
        }

    for filename, module_number in STUDY_MATERIALS[SUBJECT_CODE]:
        key = (filename, module_number)
        status = "EXISTS" if key in before else "REGISTERED"
        print(f"[{status}] id={after[key]} mod={module_number} {filename}")

    print("DONE: 4 Yoga (4th sem) documents registered.")


if __name__ == "__main__":
    main()
