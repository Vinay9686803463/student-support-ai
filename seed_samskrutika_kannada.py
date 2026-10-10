"""Register Samskrutika Kannada (BKSKK107) Study Material PDFs.

Thin strict wrapper over utils.bootstrap (single source of truth for the
file list): validates every PDF with pypdf, then runs the same idempotent
ensure the app runs on every boot, and reports per-file status.

- Only SELECT + INSERT missing knowledge_documents rows keyed by
  (subject_code, original_filename). Never UPDATE/DELETE subjects,
  units, knowledge_documents, or knowledge_chunks.
- Fails loudly on a missing/unreadable PDF (no silent skips).

Run: venv\\Scripts\\python.exe seed_samskrutika_kannada.py
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

SUBJECT_CODE = "BKSKK107"
FILES = [f for f, _m in STUDY_MATERIALS[SUBJECT_CODE]]
SOURCE_DIR = Path(__file__).resolve().parent / "knowledge_base" / SUBJECT_CODE


def main():
    assert len(FILES) == 8, "all eight Kannada PDFs must be listed"

    for filename in FILES:
        pdf_path = SOURCE_DIR / filename
        if not pdf_path.is_file():
            raise SystemExit(f"source PDF missing: {pdf_path}")
        if len(PdfReader(str(pdf_path)).pages) < 1:
            raise SystemExit(f"empty/unreadable PDF: {pdf_path}")

    with app.app_context():
        subject = db.session.execute(
            text("SELECT id FROM subjects WHERE subject_code = :c"),
            {"c": SUBJECT_CODE},
        ).first()
        if not subject:
            raise SystemExit(
                f"subject {SUBJECT_CODE} missing and boot self-heal did "
                "not restore it; aborting"
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
            print(f"[REGISTERED] id={after[filename]} {filename}")

    print("DONE: 8 Samskrutika Kannada PDFs registered.")


if __name__ == "__main__":
    main()
