"""Register Data Structures and Applications (BCS304) files.

Thin strict wrapper around utils.bootstrap (single source of truth for
the file list): validates every file, then runs the same idempotent
ensure the app runs on every boot.

- Module PDFs (slots 1, 3, 4, 5) -> Module 1/3/4/5 cards under Study
  Material. Module 2 has no file ('Module 2.pdf' is absent from
  Downloads) and renders the existing empty-slot placeholder.
- 9 files with module_number 0 -> Additional Resources section,
  including 'code raiders.txt' (inline text) and 2 Word documents
  (downloads) via /knowledge/document/<id>.
- Only SELECT + INSERT missing knowledge_documents rows keyed by
  (subject_code, original_filename, module_number). Never
  UPDATE/DELETE subjects, units, knowledge_documents, or chunks.
- Fails loudly (no silent skips) when the subject row or a file is
  missing/unreadable.

Run: venv\\Scripts\\python.exe seed_ds.py
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

SUBJECT_CODE = "BCS304"
ENTRIES = list(STUDY_MATERIALS[SUBJECT_CODE])
BASE_DIR = Path(__file__).resolve().parent / "knowledge_base" / SUBJECT_CODE
SUBDIRS = STUDY_MATERIAL_SUBDIRS[SUBJECT_CODE]

OFFICE_SUFFIXES = (".docx", ".doc", ".ppt", ".pptx", ".xlsx")


def _path_for(filename, module_number):
    subdir = SUBDIRS.get(module_number, "")
    if subdir:
        return BASE_DIR / subdir / filename
    return BASE_DIR / filename


def main():
    assert len(ENTRIES) == 13, "all thirteen DS entries must be listed"

    for filename, module_number in ENTRIES:
        pdf_path = _path_for(filename, module_number)
        if not pdf_path.is_file():
            raise SystemExit(f"source file missing: {pdf_path}")
        suffix = pdf_path.suffix.lower()
        if suffix == ".pdf":
            pages = len(PdfReader(str(pdf_path)).pages)
            if pages < 1:
                raise SystemExit(f"empty/unreadable PDF: {pdf_path}")
        elif suffix in OFFICE_SUFFIXES:
            if pdf_path.stat().st_size < 1:
                raise SystemExit(f"empty document: {pdf_path}")
        elif suffix == ".txt":
            text_content = pdf_path.read_text(encoding="utf-8")
            if not text_content.strip():
                raise SystemExit(f"empty text file: {pdf_path}")
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

    modules = sum(1 for _f, m in after if m in (1, 3, 4, 5))
    additional = sum(1 for _f, m in after if m == 0)
    assert modules == 4, f"expected 4 module rows, got {modules}"
    assert additional == 9, f"expected 9 additional rows, got {additional}"

    for filename, module_number in ENTRIES:
        key = (filename, module_number)
        status = "EXISTS" if key in before else "REGISTERED"
        print(f"[{status}] id={after[key]} mod={module_number} {filename}")

    print("DONE: 13 DS files registered (4 modules + 9 additional).")


if __name__ == "__main__":
    main()
