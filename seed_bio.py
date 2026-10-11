"""Register Biology for Computer Engineers (BBOC407) files.

Thin strict wrapper around utils.bootstrap (single source of truth for
the file list): validates every PDF, then runs the same idempotent
ensure the app runs on every boot.

- 5 module PDFs (slots 1-5) -> Module 1-5 cards under Study Material.
- 9 PDFs with module_number 0 -> Additional Resources section.
- Only SELECT + INSERT missing knowledge_documents rows keyed by
  (subject_code, original_filename, module_number). Never
  UPDATE/DELETE subjects, units, knowledge_documents, or chunks.
- Fails loudly (no silent skips) when the subject row or a file is
  missing/unreadable.

Run: venv\\Scripts\\python.exe seed_bio.py
Runs against DATABASE_URL (.env) - local SQLite or production Postgres.
"""

from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import text

from app import app
from utils.bootstrap import (
    STUDY_MATERIALS,
    STUDY_MATERIAL_SUBDIRS,
    ensure_canonical_subjects,
    ensure_study_materials,
)
from utils.database import db

SUBJECT_CODE = "BBOC407"
ENTRIES = list(STUDY_MATERIALS[SUBJECT_CODE])
BASE_DIR = Path(__file__).resolve().parent / "knowledge_base" / SUBJECT_CODE
SUBDIRS = STUDY_MATERIAL_SUBDIRS[SUBJECT_CODE]


def _path_for(filename, module_number):
    subdir = SUBDIRS.get(module_number, "")
    if subdir:
        return BASE_DIR / subdir / filename
    return BASE_DIR / filename


def main():
    assert len(ENTRIES) == 14, "all fourteen Biology entries must be listed"

    for filename, module_number in ENTRIES:
        pdf_path = _path_for(filename, module_number)
        if not pdf_path.is_file():
            raise SystemExit(f"source file missing: {pdf_path}")
        if pdf_path.suffix.lower() != ".pdf":
            raise SystemExit(f"unexpected non-PDF: {pdf_path}")
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

    modules = sum(1 for _f, m in after if m in (1, 2, 3, 4, 5))
    additional = sum(1 for _f, m in after if m == 0)
    assert modules == 5, f"expected 5 module rows, got {modules}"
    assert additional == 9, f"expected 9 additional rows, got {additional}"

    for filename, module_number in ENTRIES:
        key = (filename, module_number)
        status = "EXISTS" if key in before else "REGISTERED"
        print(f"[{status}] id={after[key]} mod={module_number} {filename}")

    print("DONE: 14 Biology files registered (5 modules + 9 additional).")


if __name__ == "__main__":
    main()
