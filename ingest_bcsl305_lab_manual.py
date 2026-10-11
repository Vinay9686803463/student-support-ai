"""Register the DS Lab Manual text file for BCSL305 (reusable pattern).

Convention (matches module-PDF implementations):
  knowledge_base/<SUBJECT_CODE>/module<N>/<file>  +  one
  knowledge_documents row (module_number = N).

The existing /knowledge/document/<id> route serves non-PDF files as
downloads; the subject page renders a View File button generically.
Idempotent: an existing (subject_code, original_filename) row is skipped.
Run: venv\\Scripts\\python.exe ingest_bcsl305_lab_manual.py
"""

import os
import shutil
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")

SUBJECT_CODE = "BCSL305"
SUBJECT_NAME = "Data Structures Lab"
SOURCE = Path(r"C:\Users\vinay\Downloads\DS Lab Manual.txt")
FILENAME = "DS Lab Manual.txt"
MODULE_NUMBER = 1


def main():
    dest_dir = PROJECT_ROOT / "knowledge_base" / SUBJECT_CODE / f"module{MODULE_NUMBER}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / FILENAME

    if SOURCE.is_file():
        raw = SOURCE.read_bytes()
        assert raw, f"source file is empty: {SOURCE}"
        raw.decode("utf-8", errors="strict")
        print(f"[OK] source genuine UTF-8 text, {len(raw)} bytes")
        if not dest.is_file():
            shutil.copy2(SOURCE, dest)
            print(f"[COPIED] {dest.relative_to(PROJECT_ROOT).as_posix()}")
        else:
            print("[EXISTS] destination file already present")
    elif dest.is_file():
        # One-time source was removed from Downloads after a prior
        # successful ingest; the project copy is the canonical file now.
        print(f"[SOURCE GONE] {SOURCE} no longer in Downloads; "
              f"using project copy ({dest.stat().st_size} bytes)")
    else:
        raise FileNotFoundError(
            f"Neither source nor project copy exists: {SOURCE} / {dest}"
        )

    conn = psycopg.connect(DATABASE_URL, prepare_threshold=None)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, module_number FROM knowledge_documents
                WHERE subject_code = %s AND original_filename = %s
                """,
                (SUBJECT_CODE, FILENAME),
            )
            row = cur.fetchone()
            if row:
                assert row[1] == MODULE_NUMBER, (
                    f"{FILENAME} registered under module {row[1]}. Aborting."
                )
                print(f"  row id={row[0]} already mapped, skipping")
            else:
                rel = dest.relative_to(PROJECT_ROOT).as_posix()
                cur.execute(
                    """
                    INSERT INTO knowledge_documents
                        (subject_code, subject_name, module_number, module_title,
                         title, original_filename, file_path, page_count, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 'uploaded')
                    RETURNING id
                    """,
                    (SUBJECT_CODE, SUBJECT_NAME, MODULE_NUMBER, "Module 1",
                     Path(FILENAME).stem, FILENAME, rel),
                )
                print(f"  registered id={cur.fetchone()[0]} -> module {MODULE_NUMBER}")
        conn.commit()
    finally:
        conn.close()
    print("DONE.")


if __name__ == "__main__":
    main()
