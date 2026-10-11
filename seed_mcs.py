"""Register Mathematics for Computer Science (BCS301) files.

Thin strict wrapper around utils.bootstrap (single source of truth for
the file list): validates every file, then runs the same idempotent
ensure the app runs on every boot. Documents render as unnumbered
file cards; JPEGs open inline via /knowledge/document/<id>.

- Only SELECT + INSERT missing knowledge_documents rows keyed by
  (subject_code, original_filename, module_number). Never
  UPDATE/DELETE subjects, units, knowledge_documents, or chunks.
- Fails loudly (no silent skips) when the subject row or a file is
  missing/unreadable.

Run: venv\\Scripts\\python.exe seed_mcs.py
Runs against DATABASE_URL (.env) - local SQLite or production Postgres.
"""

from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import text

from app import app
from utils.bootstrap import (
    STUDY_MATERIALS,
    ensure_canonical_subjects,
    ensure_study_materials,
)
from utils.database import db

SUBJECT_CODE = "BCS301"
FILES = [f for f, _m in STUDY_MATERIALS[SUBJECT_CODE]]
SOURCE_DIR = Path(__file__).resolve().parent / "knowledge_base" / SUBJECT_CODE

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def main():
    assert len(FILES) == 12, "all twelve Maths-CS files must be listed"

    for filename in FILES:
        pdf_path = SOURCE_DIR / filename
        if not pdf_path.is_file():
            raise SystemExit(f"source file missing: {pdf_path}")
        suffix = pdf_path.suffix.lower()
        if suffix == ".pdf":
            pages = len(PdfReader(str(pdf_path)).pages)
            if pages < 1:
                raise SystemExit(f"empty/unreadable PDF: {pdf_path}")
        elif suffix in IMAGE_SUFFIXES:
            with open(pdf_path, "rb") as fh:
                if len(fh.read()) < 1:
                    raise SystemExit(f"empty image: {pdf_path}")
        else:
            raise SystemExit(f"unsupported type: {pdf_path}")

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

    print("DONE: 12 Maths-CS files registered.")


if __name__ == "__main__":
    main()
