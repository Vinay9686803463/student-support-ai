"""Ingest the single Web Technology PDF under the existing BCSL504
subject (Web Technology Lab). ONE document, no module structure."""
import os
import shutil
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from utils.knowledge_ingest import process_pdf

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
downloads = Path(os.path.expandvars("%USERPROFILE%")) / "Downloads"
if not downloads.is_dir():
    downloads = Path.home() / "Downloads"

FILENAME = "Web Technology Programs.pdf"
CODE = "BCSL504"
NAME = "Web Technology Lab"

src = downloads / FILENAME
print(f"source: {src} exists={src.is_file()}")
assert src.is_file(), "Web Technology Programs.pdf not found in Downloads"

dest_dir = PROJECT_ROOT / "knowledge_base" / CODE
dest_dir.mkdir(parents=True, exist_ok=True)
dest = dest_dir / FILENAME
if not dest.is_file():
    shutil.copy2(src, dest)
    print(f"[COPIED] {dest}")
else:
    print(f"[EXISTS] {dest}")

db_url = os.getenv("DATABASE_URL")
with psycopg.connect(db_url, prepare_threshold=None) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, status FROM knowledge_documents
            WHERE original_filename = %s
        """, (FILENAME,))
        row = cur.fetchone()
print(f"existing record: {row}")
if row and row[1] == "processed":
    print("already fully processed, skipping")
else:
    doc_id = process_pdf(
        pdf_path=dest, subject_code=CODE, subject_name=NAME,
        module_number=1, module_title=None, source="local-downloads",
    )
    print(f"[REGISTERED] id={doc_id}")