"""Register Analysis & Design of Algorithms Lab (BCSL404) manual.

Thin strict wrapper around utils.bootstrap (single source of truth for
the file list): validates the PDF, then runs the same idempotent
ensure the app runs on every boot. The manual renders as an
unnumbered file card under Study Material (BCSL404 is in the
unnumbered-file list in app.py:subject_detail, same as the BCSL305
lab) - no Module sections, no Additional Resources section.

- Only SELECT + INSERT missing knowledge_documents rows keyed by
  (subject_code, original_filename, module_number). Never
  UPDATE/DELETE subjects, units, knowledge_documents, or chunks.
- Fails loudly (no silent skips) when the subject row or the file is
  missing/unreadable.

Run: venv\\Scripts\\python.exe seed_adalab.py
Runs against DATABASE_URL (.env) - local SQLite or production Postgres.
"""

from pathlib import Path

from importlib import import_module

try:
    PdfReader = import_module("pypdf").PdfReader
except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment.
    raise RuntimeError(
        "pypdf is required to validate the study-material PDF. "
        "Install it in the project virtual environment."
    ) from exc

try:
    from sqlalchemy import text  # type: ignore[reportMissingImports]
except ImportError:  # pragma: no cover - project venv normally provides this.
    def text(_statement):
        raise RuntimeError(
            "SQLAlchemy is required to run this seeder. "
            "Activate the project virtual environment and install dependencies."
        )

from app import app
from utils.bootstrap import (
    STUDY_MATERIALS,
    STUDY_MATERIAL_SUBDIRS,
    ensure_canonical_subjects,
    ensure_study_materials,
)
from utils.database import db

SUBJECT_CODE = "BCSL404"
ENTRIES = list(STUDY_MATERIALS[SUBJECT_CODE])
BASE_DIR = Path(__file__).resolve().parent / "knowledge_base" / SUBJECT_CODE
SUBDIRS = STUDY_MATERIAL_SUBDIRS[SUBJECT_CODE]


def _path_for(filename, module_number):
    subdir = SUBDIRS.get(module_number, "")
    if subdir:
        return BASE_DIR / subdir / filename
    return BASE_DIR / filename


def main():
    assert len(ENTRIES) == 1, "the single ADA lab manual must be listed"

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

    for filename, module_number in ENTRIES:
        key = (filename, module_number)
        status = "EXISTS" if key in before else "REGISTERED"
        print(f"[{status}] id={after[key]} mod={module_number} {filename}")

    print("DONE: ADA lab manual registered.")


if __name__ == "__main__":
    main()
