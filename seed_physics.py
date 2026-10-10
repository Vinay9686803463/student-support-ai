"""Register Physics for CSE Stream (BPHYS202) PDFs.

Thin strict wrapper around utils.bootstrap (single source of truth for
the file list): validates every PDF with pypdf, then runs the same
idempotent ensure the app runs on every boot.

- 5 module PDFs -> Module 1-5 cards under Study Material.
- 21 entries with module_number 0 -> Additional Resources section.
- 'BPHYS102_202 MODULE 5.pdf' is intentionally registered TWICE
  (slots 5 and 0) referencing the single stored file, so it is
  available in both sections. Rows are keyed by
  (subject_code, original_filename, module_number).
- Only SELECT + INSERT missing rows. Never UPDATE/DELETE subjects,
  units, knowledge_documents, or knowledge_chunks.
- Fails loudly (no silent skips) when the subject row or a file is
  missing/unreadable.

Run: venv\\Scripts\\python.exe seed_physics.py
Runs against DATABASE_URL (.env) - local SQLite or production Postgres.
"""

from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import text

from app import app
from utils.bootstrap import (
    STUDY_MATERIALS,
    STUDY_MATERIAL_SUBDIRS,
    _safename,
    ensure_canonical_subjects,
    ensure_study_materials,
)
from utils.database import db

SUBJECT_CODE = "BPHYS202"
ENTRIES = list(STUDY_MATERIALS[SUBJECT_CODE])
BASE_DIR = Path(__file__).resolve().parent / "knowledge_base" / SUBJECT_CODE
SUBDIRS = STUDY_MATERIAL_SUBDIRS[SUBJECT_CODE]


def _entry_path(entry):
    """Resolve an entry honoring an explicit subdir override."""
    filename, module_number = entry[0], entry[1]
    subdir = entry[2] if len(entry) > 2 else SUBDIRS.get(module_number, "")
    if subdir:
        return BASE_DIR / subdir / filename
    return BASE_DIR / filename


def _path_for(filename, module_number):
    return _entry_path((filename, module_number))


def main():
    assert len(ENTRIES) == 26, "all 26 physics entries must be listed"

    seen_files = set()
    for entry in ENTRIES:
        filename, module_number = entry[0], entry[1]
        pdf_path = _entry_path(entry)
        if not pdf_path.is_file():
            raise SystemExit(f"source PDF missing: {_safename(pdf_path)}")
        pages = len(PdfReader(str(pdf_path)).pages)
        if pages < 1:
            raise SystemExit(f"empty/unreadable PDF: {_safename(pdf_path)}")
        seen_files.add(filename)
    assert len(seen_files) == 25, "expected 25 distinct files (Module 5 dup)"

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
    assert additional == 21, f"expected 21 additional rows, got {additional}"

    for entry in ENTRIES:
        filename, module_number = entry[0], entry[1]
        key = (filename, module_number)
        status = "EXISTS" if key in before else "REGISTERED"
        print(f"[{status}] id={after[key]} mod={module_number} {_safename(filename)}")

    print("DONE: 26 physics rows registered (5 modules + 21 additional).")


if __name__ == "__main__":
    main()
