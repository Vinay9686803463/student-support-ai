"""Register Technical Writing using LATEX (BCSL456D) manual.

Self-contained registrar: validates the PDF, then SELECT + INSERTs
the single missing knowledge_documents row keyed by
(subject_code, original_filename, module_number). Never
UPDATE/DELETE subjects, units, knowledge_documents, or chunks.

The manual renders as an unnumbered file card under Study Material
(BCSL456D is in the unnumbered-file list in app.py:subject_detail,
same as the BCSL305/BCSL404 labs) - no Module sections, no
Additional Resources section.

NOTE: utils/bootstrap.py is currently locked by an external process,
so the STUDY_MATERIALS/CANONICAL entries for BCSL456D could not be
added yet. Once the lock clears, add the matching entries there
(single ("latex manual.pdf", 1) slot + subdir/title maps + canonical
row) so boot self-heal covers this subject; the slots below are
chosen to match that future entry exactly, keeping both writers
idempotent. Fails loudly when the subject row or file is missing.

Run: python seed_latex.py
Runs against DATABASE_URL (.env) - local SQLite or production Postgres.
"""

from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import text

from app import app
from utils.database import db

SUBJECT_CODE = "BCSL456D"
SUBJECT_NAME = "Technical Writing using LATEX"
FILENAME = "latex manual.pdf"
MODULE_NUMBER = 1
MODULE_TITLE = "Module 1"
BASE_DIR = Path(__file__).resolve().parent / "knowledge_base" / SUBJECT_CODE


def main():
    pdf_path = BASE_DIR / "module1" / FILENAME
    if not pdf_path.is_file():
        raise SystemExit(f"source file missing: {pdf_path}")
    pages = len(PdfReader(str(pdf_path)).pages)
    if pages < 1:
        raise SystemExit(f"empty/unreadable PDF: {pdf_path}")
    print(f"validated {FILENAME} ({pages} pages)")

    with app.app_context():
        subject = db.session.execute(
            text("SELECT id FROM subjects WHERE subject_code = :c"),
            {"c": SUBJECT_CODE},
        ).first()
        if not subject:
            raise SystemExit(
                f"subject {SUBJECT_CODE} missing; "
                "restore it before registering documents"
            )

        existing = db.session.execute(
            text("""
                SELECT id FROM knowledge_documents
                WHERE subject_code = :c
                  AND original_filename = :f
                  AND module_number = :m
            """),
            {"c": SUBJECT_CODE, "f": FILENAME, "m": MODULE_NUMBER},
        ).first()
        if existing:
            print(f"[EXISTS] id={existing[0]} mod={MODULE_NUMBER} {FILENAME}")
        else:
            new_id = db.session.execute(
                text("""
                    INSERT INTO knowledge_documents
                        (subject_code, subject_name, module_number,
                         module_title, title, original_filename,
                         file_path, page_count, status)
                    VALUES (:c, :n, :m, :mt, :t, :f, :p, :pg, 'uploaded')
                    RETURNING id
                """),
                {
                    "c": SUBJECT_CODE,
                    "n": SUBJECT_NAME,
                    "m": MODULE_NUMBER,
                    "mt": MODULE_TITLE,
                    "t": Path(FILENAME).stem,
                    "f": FILENAME,
                    "p": f"knowledge_base/{SUBJECT_CODE}/module1/{FILENAME}",
                    "pg": pages,
                },
            ).scalar()
            db.session.commit()
            print(f"[REGISTERED] id={new_id} mod={MODULE_NUMBER} {FILENAME}")

    print("DONE: LATEX manual registered.")


if __name__ == "__main__":
    main()
