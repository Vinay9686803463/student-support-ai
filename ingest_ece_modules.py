"""Register ECE module PDFs (reusable pattern).

Convention (matches Chemistry/Modules implementation):
  knowledge_base/<SUBJECT_CODE>/module<N>/<file>.pdf  +  one
  knowledge_documents row per module (module_number = N).

Module 1 already exists and is preserved; only missing modules are added.
Every source file is verified to be a genuine PDF (magic bytes + page
count) before its link is created, so no button can point at a broken file.
Idempotent: existing (subject_code, original_filename) rows are skipped.
Run: venv\\Scripts\\python.exe ingest_ece_modules.py
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

SUBJECT_CODE = "BESCK104C"
SUBJECT_NAME = "Electronics and Communication Engineering"
SOURCE_DIR = Path(r"E:\1DI24CS087\1st Sem Notes\ECE Notes")

# module_number -> source filename (Module 1 already registered; kept here
# for completeness but skipped as a duplicate).
MODULE_FILES = {
    1: "ECE Module 1.pdf",
    2: "ECE Module 2.pdf",
    3: "ECE Module 3.pdf",
    4: "ECE Module 4.pdf",
    5: "ECE Module 5.pdf",
}


def assert_real_pdf(path):
    with open(path, "rb") as fh:
        assert fh.read(5) == b"%PDF-", f"not a PDF (bad magic): {path}"
    pages = len(PdfReader(str(path)).pages)
    assert pages > 0, f"empty/unreadable PDF: {path}"
    return pages


def main():
    conn = psycopg.connect(DATABASE_URL, prepare_threshold=None)
    try:
        for number in sorted(MODULE_FILES):
            filename = MODULE_FILES[number]
            src = SOURCE_DIR / filename
            assert src.is_file(), f"source PDF missing: {src}"
            pages = assert_real_pdf(src)

            dest_dir = PROJECT_ROOT / "knowledge_base" / SUBJECT_CODE / f"module{number}"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / filename
            if not dest.is_file():
                shutil.copy2(src, dest)
                print(f"[COPIED] module{number}/{filename} ({pages} pages)")
            else:
                print(f"[EXISTS] module{number}/{filename}")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, module_number FROM knowledge_documents
                    WHERE subject_code = %s AND original_filename = %s
                    """,
                    (SUBJECT_CODE, filename),
                )
                row = cur.fetchone()
                if row:
                    assert row[1] == number, (
                        f"{filename} registered under module {row[1]}, "
                        f"expected {number}. Aborting."
                    )
                    print(f"  row id={row[0]} already mapped to module {number}, skipping")
                    continue
                rel = dest.relative_to(PROJECT_ROOT).as_posix()
                cur.execute(
                    """
                    INSERT INTO knowledge_documents
                        (subject_code, subject_name, module_number, module_title,
                         title, original_filename, file_path, page_count, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'uploaded')
                    RETURNING id
                    """,
                    (SUBJECT_CODE, SUBJECT_NAME, number, f"Module {number}",
                     Path(filename).stem, filename, rel, pages),
                )
                print(f"  registered id={cur.fetchone()[0]} -> module {number}")
            conn.commit()
    finally:
        conn.close()
    print("DONE.")


if __name__ == "__main__":
    main()
