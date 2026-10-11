"""Register BCS306B (OOP with C++) module + additional PDFs (reusable pattern).

Convention (matches Chemistry/ECE implementations):
  knowledge_base/BCS306B/module<N>/<file>.pdf      -> Study Material Modules 1-5
  knowledge_base/BCS306B/additional/<file>.pdf     -> Additional Resources
  (module_number = 0, module_title = 'Additional Resources')

Every source file is verified to be a genuine PDF (magic bytes + page
count) before its link is created. Idempotent: existing
(subject_code, original_filename) rows are skipped, and an existing row
mapped to a different module aborts instead of duplicating.
Run: venv\\Scripts\\python.exe ingest_bcs306b_resources.py
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

SUBJECT_CODE = "BCS306B"
SUBJECT_NAME = "Object Oriented Programming with C++"
SOURCE_DIR = Path(r"E:\1DI24CS087\3rd Sem Notes\C++ Notes")

# (module_number, filename, subdir, module_title)
ENTRIES = [
    (1, "Module 1.pdf", "module1", "Module 1"),
    (2, "Module 2.pdf", "module2", "Module 2"),
    (3, "Module 3.pdf", "module3", "Module 3"),
    (4, "BCS306B-module-4-pdf.pdf", "module4", "Module 4"),
    (5, "BCS306B-module-5-pdf.pdf", "module5", "Module 5"),
    (0, "C ++ previous year question papers.pdf", "additional", "Additional Resources"),
    (0, "C++ Assignent Module 4 and 5.pdf", "additional", "Additional Resources"),
    (0, "C++ Assignment  Module 1.pdf", "additional", "Additional Resources"),
    (0, "C++ Assignment Module 2.pdf", "additional", "Additional Resources"),
    (0, "cpplab.pdf", "additional", "Additional Resources"),
]


def assert_real_pdf(path):
    with open(path, "rb") as fh:
        assert fh.read(5) == b"%PDF-", f"not a PDF (bad magic): {path}"
    pages = len(PdfReader(str(path)).pages)
    assert pages > 0, f"empty/unreadable PDF: {path}"
    return pages


def main():
    conn = psycopg.connect(DATABASE_URL, prepare_threshold=None)
    try:
        for number, filename, subdir, mod_title in ENTRIES:
            src = SOURCE_DIR / filename
            assert src.is_file(), f"source PDF missing: {src}"
            pages = assert_real_pdf(src)

            dest_dir = PROJECT_ROOT / "knowledge_base" / SUBJECT_CODE / subdir
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / filename
            if not dest.is_file():
                shutil.copy2(src, dest)
                print(f"[COPIED] {subdir}/{filename} ({pages} pages)")
            else:
                print(f"[EXISTS] {subdir}/{filename}")

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
                    print(f"  row id={row[0]} already mapped (module {number}), skipping")
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
                    (SUBJECT_CODE, SUBJECT_NAME, number, mod_title,
                     Path(filename).stem, filename, rel, pages),
                )
                print(f"  registered id={cur.fetchone()[0]} -> module {number}")
            conn.commit()
    finally:
        conn.close()
    print("DONE.")


if __name__ == "__main__":
    main()
