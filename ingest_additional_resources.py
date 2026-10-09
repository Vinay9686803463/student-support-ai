"""Register Additional-Resources PDFs for a subject (reusable).

Convention (no code changes needed for future PDFs):
  1. Put the PDF under  knowledge_base/<SUBJECT_CODE>/additional/
  2. Register one knowledge_documents row with module_number = 0 and
     module_title = 'Additional Resources'.
  3. The subject page automatically renders an "Additional Resources"
     section below Modules 1-5; each file opens via the existing
     /knowledge/pdf/<id> route. To add more PDFs later, extend FILES
     below (or point SOURCE_DIR at the new files) and re-run.

Idempotent: existing (subject_code, original_filename) rows are skipped.
Run: venv\\Scripts\\python.exe ingest_additional_resources.py
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

SUBJECT_CODE = "BCHES102"
SUBJECT_NAME = "Chemistry for CSE Stream"
SOURCE_DIR = Path(r"E:\1DI24CS087\1st Sem Notes\Chemistry Notes")
DEST_SUBDIR = "additional"
FILES = [
    # NOTE: 'Aug-2022.pdf' from the Chemistry Notes folder is NOT a PDF
    # (its bytes are an HTML page), so it is deliberately excluded until
    # a genuine Aug-2022.pdf is provided.
    "Chemistry Polymer.pdf",
    "chemistry..pdf",
    "Corrosion.pdf",
]


def main():
    dest_dir = PROJECT_ROOT / "knowledge_base" / SUBJECT_CODE / DEST_SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    conn = psycopg.connect(DATABASE_URL, prepare_threshold=None)
    try:
        for filename in FILES:
            src = SOURCE_DIR / filename
            assert src.is_file(), f"source PDF missing: {src}"
            reader = PdfReader(str(src))
            pages = len(reader.pages)
            assert pages > 0, f"empty/unreadable PDF: {src}"

            dest = dest_dir / filename
            if not dest.is_file():
                shutil.copy2(src, dest)
                print(f"[COPIED] {dest.name} ({pages} pages)")
            else:
                print(f"[EXISTS] {dest.name}")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM knowledge_documents
                    WHERE subject_code = %s AND original_filename = %s
                    """,
                    (SUBJECT_CODE, filename),
                )
                if cur.fetchone():
                    print(f"  row exists, skipping: {filename}")
                    continue
                rel = dest.relative_to(PROJECT_ROOT).as_posix()
                cur.execute(
                    """
                    INSERT INTO knowledge_documents
                        (subject_code, subject_name, module_number, module_title,
                         title, original_filename, file_path, page_count, status)
                    VALUES (%s, %s, 0, 'Additional Resources', %s, %s, %s, %s, 'uploaded')
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
