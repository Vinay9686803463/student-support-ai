"""Boot self-heal for BCSL456D (Technical Writing using LATEX).

utils/bootstrap.py is currently unreadable (OS-level permission lock
on that single file), so the BCSL456D entries cannot live there yet.
This supplement provides the identical idempotent ensure for the one
LATEX manual and is called from app.py right after
ensure_study_content(). Once the lock on utils/bootstrap.py clears,
fold these entries into STUDY_MATERIALS / CANONICAL_SUBJECTS /
STUDY_MATERIAL_SUBDIRS / STUDY_MATERIAL_TITLES there (same slots:
single ("latex manual.pdf", 1) entry, module1 subdir, "Module 1"
title, 1-credit lab-style canonical row) and delete this module +
its app.py hook - both writers key rows by
(subject_code, original_filename, module_number), so the handover is
idempotent and registers nothing twice.

Never raises: failures roll back and log, matching the convention in
utils.bootstrap.ensure_study_materials.
"""

from pathlib import Path

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SUBJECT_CODE = "BCSL456D"
SUBJECT_NAME = "Technical Writing using LATEX"
# (filename, module_number slot, subdir, module_title, page_count via pypdf)
ENTRIES = [
    ("latex manual.pdf", 1, "module1", "Module 1"),
]


def ensure_latex_materials(db):
    """Register the on-disk LATEX manual if its document row is missing."""
    try:
        from pypdf import PdfReader
    except ImportError as error:
        print(f"  ! latex materials skipped (pypdf unavailable): {error}")
        return
    try:
        for filename, module_number, subdir, module_title in ENTRIES:
            pdf_path = PROJECT_ROOT / "knowledge_base" / SUBJECT_CODE / subdir / filename
            if not pdf_path.is_file():
                print(f"  ! file missing, skipping: {SUBJECT_CODE}/{filename}")
                continue
            try:
                pages = len(PdfReader(str(pdf_path)).pages)
            except Exception as error:
                print(f"  ! unreadable PDF, skipping {filename}: {error}")
                continue
            if pages < 1:
                print(f"  ! empty PDF, skipping: {filename}")
                continue
            existing = db.session.execute(
                text("""
                    SELECT id FROM knowledge_documents
                    WHERE subject_code = :c
                      AND original_filename = :f
                      AND module_number = :m
                """),
                {"c": SUBJECT_CODE, "f": filename, "m": module_number},
            ).first()
            if existing:
                continue
            db.session.execute(
                text("""
                    INSERT INTO knowledge_documents
                        (subject_code, subject_name, module_number,
                         module_title, title, original_filename,
                         file_path, page_count, status)
                    VALUES (:c, :n, :m, :mt, :t, :f, :p, :pg, 'uploaded')
                """),
                {
                    "c": SUBJECT_CODE,
                    "n": SUBJECT_NAME,
                    "m": module_number,
                    "mt": module_title,
                    "t": Path(filename).stem,
                    "f": filename,
                    "p": f"knowledge_base/{SUBJECT_CODE}/{subdir}/{filename}",
                    "pg": pages,
                },
            )
            db.session.commit()
            print(f"  + study material: {SUBJECT_CODE} mod={module_number} "
                  f"{filename} ({pages} pages)")
    except Exception as error:
        db.session.rollback()
        print(f"  ! latex materials skipped: {error}")
