"""Register the Module 1 PDF for BCS401 (one-shot fix + idempotent).

Root cause of the missing Module 1: the source file in Downloads carries a
typo ('writtten', triple-t), so exact-name matching never found
'BCS401-module-1-written.pdf'. The fix copies those exact bytes into
knowledge_base/BCS401/module1/ under the CORRECT name and registers that
row. Contents are preserved byte-for-byte (SHA-256 asserted).
Run: venv\\Scripts\\python.exe ingest_bcs401_module1.py (idempotent)
"""

import hashlib
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

SRC = Path(r"C:\Users\vinay\Downloads\BCS401-module-1-writtten.pdf")
FILENAME = "BCS401-module-1-written.pdf"


def main():
    assert SRC.is_file(), f"typo'd source gone: {SRC}"
    raw = SRC.read_bytes()
    assert raw[:5] == b"%PDF-", "source is not a PDF"
    pages = len(PdfReader(str(SRC)).pages)
    assert pages > 0, "source PDF has no pages"
    digest = hashlib.sha256(raw).hexdigest()
    print(f"[OK] source {SRC.name} ({len(raw)} bytes, {pages} pages)")

    dest = PROJECT_ROOT / "knowledge_base" / "BCS401" / "module1" / FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        assert hashlib.sha256(dest.read_bytes()).hexdigest() == digest, \
            "existing destination bytes differ from source. Aborting."
        print("[EXISTS] destination already matches source bytes")
    else:
        shutil.copy2(SRC, dest)
        print(f"[COPIED] module1/{FILENAME}")

    conn = psycopg.connect(DATABASE_URL, prepare_threshold=None)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, module_number FROM knowledge_documents
                WHERE subject_code = 'BCS401' AND original_filename = %s
                """,
                (FILENAME,),
            )
            row = cur.fetchone()
            if row:
                assert row[1] == 1, f"registered under module {row[1]}. Aborting."
                print(f"  row id={row[0]} already mapped to module 1, skipping")
            else:
                rel = dest.relative_to(PROJECT_ROOT).as_posix()
                cur.execute(
                    """
                    INSERT INTO knowledge_documents
                        (subject_code, subject_name, module_number, module_title,
                         title, original_filename, file_path, page_count, status)
                    VALUES ('BCS401', 'Analysis & Design of Algorithms', 1, 'Module 1',
                            'BCS401-module-1-written', %s, %s, %s, 'uploaded')
                    RETURNING id
                    """,
                    (FILENAME, rel, pages),
                )
                print(f"  registered id={cur.fetchone()[0]} -> module 1")
        conn.commit()
    finally:
        conn.close()
    print("DONE.")


if __name__ == "__main__":
    main()
