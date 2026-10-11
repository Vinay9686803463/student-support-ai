"""Register UHV (BUHK408) study PDFs as unnumbered file cards (reusable pattern).

The two UHV files (general notes + MCQ bank) are not module-wise, so they
render as individual file cards via the existing unnumbered-collection
branch in subject_detail (same as BCEDK103/BCS301/etc.). No Module 1-5
placeholders are created.
Idempotent: existing (subject_code, original_filename) rows are skipped.
Run: venv\\Scripts\\python.exe ingest_buhk408_resources.py
"""

import os
import shutil
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from pypdf import PdfReader

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")

SUBJECT_CODE = "BUHK408"
SUBJECT_NAME = "Universal Human Values Course"
SOURCE_DIR = Path(r"C:\Users\vinay\Downloads")
FILES = [
    "Universal Human Values Notes 2025-26.pdf",
    "MCQs UHV Module 1 & 2_2025-26.pdf",
]


def assert_real_pdf(path):
    with open(path, "rb") as fh:
        assert fh.read(5) == b"%PDF-", f"not a PDF (bad magic): {path}"
    pages = len(PdfReader(str(path)).pages)
    assert pages > 0, f"empty/unreadable PDF: {path}"
    return pages


def main():
    dest_dir = PROJECT_ROOT / "knowledge_base" / SUBJECT_CODE
    dest_dir.mkdir(parents=True, exist_ok=True)

    conn = psycopg.connect(DATABASE_URL, prepare_threshold=None)
    try:
        for filename in FILES:
            src = SOURCE_DIR / filename
            assert src.is_file(), f"source PDF missing: {src}"
            pages = assert_real_pdf(src)

            dest = dest_dir / filename
            if not dest.is_file():
                shutil.copy2(src, dest)
                print(f"[COPIED] {filename} ({pages} pages)")
            else:
                print(f"[EXISTS] {filename}")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM knowledge_documents
                    WHERE subject_code = %s AND original_filename = %s
                    """,
                    (SUBJECT_CODE, filename),
                )
                row = cur.fetchone()
                if row:
                    print(f"  row id={row[0]} already registered, skipping")
                    continue
                rel = dest.relative_to(PROJECT_ROOT).as_posix()
                cur.execute(
                    """
                    INSERT INTO knowledge_documents
                        (subject_code, subject_name, module_number, module_title,
                         title, original_filename, file_path, page_count, status)
                    VALUES (%s, %s, 1, 'Study Material', %s, %s, %s, %s, 'uploaded')
                    RETURNING id
                    """,
                    (SUBJECT_CODE, SUBJECT_NAME, Path(filename).stem,
                     filename, rel, pages),
                )
                print(f"  registered id={cur.fetchone()[0]}: {filename}")
            conn.commit()
    finally:
        conn.close()
    print("DONE.")


if __name__ == "__main__":
    main()
