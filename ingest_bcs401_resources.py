"""Register BCS401 (ADA) module + additional PDFs (reusable pattern).

Sources: Modules 2-5 from Downloads; all 19 additional files from the
ADA Notes folder (absent from Downloads). NOTE: BCS401-module-1-written.pdf
is missing everywhere — it is NOT registered/invented; its Module 1 slot
renders the standard empty placeholder until the real file is provided.

Convention: knowledge_base/BCS401/module<N>/... (modules 1-5) and
knowledge_base/BCS401/additional/... (module_number=0). Every file is
verified genuine PDF (magic + pages) before registration. Idempotent.
Run: venv\\Scripts\\python.exe ingest_bcs401_resources.py
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

SUBJECT_CODE = "BCS401"
SUBJECT_NAME = "Analysis & Design of Algorithms"
DL = Path(r"C:\Users\vinay\Downloads")
NOTES = Path(r"E:\1DI24CS087\4th Sem Notes\ADA Notes")

# (module_number, filename, source_dir, subdir)
ENTRIES = [
    (2, "BCS401-module-2-written.pdf", DL, "module2"),
    (3, "BCS401-module-3-written.pdf", DL, "module3"),
    (4, "BCS401-module-4-written.pdf", DL, "module4"),
    (5, "BCS401-module-5-written.pdf", DL, "module5"),
    (0, "tsp.pdf", NOTES, "additional"),
    (0, "module2-6.pdf", NOTES, "additional"),
    (0, "module2-4.pdf", NOTES, "additional"),
    (0, "module2-3.pdf", NOTES, "additional"),
    (0, "module2-2.pdf", NOTES, "additional"),
    (0, "module2-1.pdf", NOTES, "additional"),
    (0, "knapsack.pdf", NOTES, "additional"),
    (0, "Important_question ADA.pdf", NOTES, "additional"),
    (0, "binary_tree_traversal.pdf", NOTES, "additional"),
    (0, "BCS401-ADA-m2-notes.pdf", NOTES, "additional"),
    (0, "BCS401-ADA-m1-notes.pdf", NOTES, "additional"),
    (0, "ass2(ADA) (2).pdf", NOTES, "additional"),
    (0, "ADA_LAB_MANUAL_BCSL404_2026.pdf", NOTES, "additional"),
    (0, "Ada very importatnt questions for IA 2.pdf", NOTES, "additional"),
    (0, "ADA Very Important Question  CSE.pdf", NOTES, "additional"),
    (0, "ADA Previous question papers.pdf", NOTES, "additional"),
    (0, "ADA Mod 1.pdf", NOTES, "additional"),
    (0, "ADA assignment 1.pdf", NOTES, "additional"),
    (0, "ACSEDAA Assignmen_2_20264thsem.pdf", NOTES, "additional"),
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
        for number, filename, srcdir, subdir in ENTRIES:
            src = srcdir / filename
            assert src.is_file(), f"source missing: {src}"
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
                        f"{filename} under module {row[1]}, expected {number}. Aborting."
                    )
                    print(f"  row id={row[0]} already mapped, skipping")
                    continue
                mod_title = f"Module {number}" if number else "Additional Resources"
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
    print("DONE. (BCS401-module-1-written.pdf missing everywhere — not registered.)")


if __name__ == "__main__":
    main()
