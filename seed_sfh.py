"""Register Scientific Foundations of Health (BSFHK158) PDFs.

Thin strict wrapper around utils.bootstrap (single source of truth for
the file list): validates every PDF with pypdf, then runs the same
idempotent ensure the app runs on every boot.

- Only SELECT + INSERT missing knowledge_documents rows keyed by
  (subject_code, original_filename). Never UPDATE/DELETE subjects,
  units, knowledge_documents, or knowledge_chunks.
- Fails loudly (no silent skips) when the subject row or a PDF is
  missing/unreadable.

Run: venv\\Scripts\\python.exe seed_sfh.py
Runs against DATABASE_URL (.env) - local SQLite or production Postgres.
"""

from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import text

from app import app
from utils.bootstrap import (
    CANONICAL_SUBJECTS,
    STUDY_MATERIALS,
    ensure_canonical_subjects,
    ensure_study_materials,
)
from utils.database import db

SUBJECT_CODE = "BSFHK158"
SUBJECT_NAME = dict((c, n) for c, n, _s, _b, _sc, _cat in CANONICAL_SUBJECTS)[SUBJECT_CODE]
FILES = [f for f, _m in STUDY_MATERIALS[SUBJECT_CODE]]
SOURCE_DIR = Path(__file__).resolve().parent / "knowledge_base" / SUBJECT_CODE


def main():
    assert len(FILES) == 14, "all fourteen SFH PDFs must be listed"

    for filename in FILES:
        pdf_path = SOURCE_DIR / filename
        if not pdf_path.is_file():
            raise SystemExit(f"source PDF missing: {pdf_path}")
        pages = len(PdfReader(str(pdf_path)).pages)
        if pages < 1:
            raise SystemExit(f"empty/unreadable PDF: {pdf_path}")

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
            row[0] for row in db.session.execute(
                text("""
                    SELECT original_filename FROM knowledge_documents
                    WHERE subject_code = :c
                """),
                {"c": SUBJECT_CODE},
            ).fetchall()
        }

        ensure_canonical_subjects()
        ensure_study_materials()

        after = {
            row[0]: row[1] for row in db.session.execute(
                text("""
                    SELECT original_filename, id FROM knowledge_documents
                    WHERE subject_code = :c
                """),
                {"c": SUBJECT_CODE},
            ).fetchall()
        }

    for filename in FILES:
        if filename in before:
            print(f"[EXISTS] id={after[filename]} {filename}")
        else:
            assert filename in after, f"registration failed: {filename}"
            print(f"[REGISTERED] id={after[filename]} {filename}")

    print("DONE: 14 Scientific Foundations of Health PDFs registered.")


if __name__ == "__main__":
    main()
