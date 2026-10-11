"""Backfill text extraction + chunking for every registered document.

Covers ALL knowledge_documents with zero chunks: PDFs, DOCX/DOC, PPT/PPTX,
XLSX, TXT across every semester/subject. Embeddings are NOT generated here
(run generate_embeddings.py afterwards); keyword search works immediately
via the FTS index.

- Skips documents that already have chunks (no duplicate indexing).
- Missing disk files, scanned/empty PDFs, and unsupported types are
  recorded in knowledge_processing_logs and printed in the final report
  instead of being silently ignored.
- Original files are never modified; file-serving routes untouched.

Run: <python> index_all_documents.py [--limit N] [--subject CODE]
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")

PROJECT_ROOT = Path(__file__).resolve().parent


def main():
    only_subject = None
    max_docs = None
    offset = 0
    args = sys.argv[1:]
    for index, arg in enumerate(args):
        if arg == "--subject" and index + 1 < len(args):
            only_subject = args[index + 1]
        if arg == "--limit" and index + 1 < len(args):
            max_docs = int(args[index + 1])
        if arg == "--offset" and index + 1 < len(args):
            offset = int(args[index + 1])

    from utils.knowledge_ingest import extract_document_pages, split_text

    conn = psycopg.connect(DATABASE_URL, prepare_threshold=None)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.id, d.subject_code, d.subject_name, d.module_number,
                       d.module_title, d.original_filename, d.file_path,
                       COUNT(c.id) AS chunks
                FROM knowledge_documents d
                LEFT JOIN knowledge_chunks c ON c.document_id = d.id
                GROUP BY d.id, d.subject_code, d.subject_name, d.module_number,
                         d.module_title, d.original_filename, d.file_path
                HAVING COUNT(c.id) = 0
                ORDER BY d.subject_code, d.module_number, d.id
                """
            )
            pending = cur.fetchall()
    finally:
        conn.close()

    if only_subject:
        pending = [row for row in pending if row[1] == only_subject]
    if offset:
        pending = pending[offset:]
    if max_docs:
        pending = pending[:max_docs]

    print(f"Documents without chunks: {len(pending)}")

    report = {"indexed": [], "empty": [], "missing": [], "failed": [],
              "duplicate": [], "skipped_type": []}

    conn = psycopg.connect(DATABASE_URL, prepare_threshold=None)
    try:
        for doc_id, code, _name, module, _mtitle, filename, file_path, _n in pending:
            # Duplicate-filename guard: another row with the same file
            # already indexed means this row is a redundant re-registration.
            # Skip it (report only) — never double-index the same content.
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.id, COUNT(c.id)
                    FROM knowledge_documents d
                    LEFT JOIN knowledge_chunks c ON c.document_id = d.id
                    WHERE d.subject_code = %s AND d.original_filename = %s
                      AND d.id != %s
                    GROUP BY d.id
                    """,
                    (code, filename, doc_id),
                )
                twins = cur.fetchall()

            if any(count > 0 for _tid, count in twins):
                keeper = next(tid for tid, count in twins if count > 0)
                report["duplicate"].append((code, filename, doc_id, keeper))
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO knowledge_processing_logs
                        (document_id, action, status, message)
                        VALUES (%s, 'index_backfill', 'skipped', %s)
                        """,
                        (doc_id, f"duplicate of document {keeper}; already indexed"),
                    )
                conn.commit()
                print(f"  [DUPE] {code} :: {filename} (indexed as id={keeper})")
                continue

            stored = Path(file_path or "")
            stored = Path(file_path or "")
            if not stored.is_absolute():
                stored = PROJECT_ROOT / stored

            if not stored.is_file():
                report["missing"].append((code, filename))
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO knowledge_processing_logs
                        (document_id, action, status, message)
                        VALUES (%s, 'index_backfill', 'failed', %s)
                        """,
                        (doc_id, f"disk file missing: {file_path}"),
                    )
                conn.commit()
                print(f"  [MISSING] {code} :: {filename}")
                continue

            try:
                pages, skipped = extract_document_pages(stored)
            except Exception as error:
                report["failed"].append((code, filename, str(error)[:120]))
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO knowledge_processing_logs
                        (document_id, action, status, message)
                        VALUES (%s, 'index_backfill', 'failed', %s)
                        """,
                        (doc_id, f"extraction failed: {error}"),
                    )
                conn.commit()
                print(f"  [FAIL] {code} :: {filename} :: {error}")
                continue

            texts = [(p["page_number"], p["text"]) for p in pages if p["text"]]
            if not texts:
                report["empty"].append((code, filename, skipped))
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO knowledge_processing_logs
                        (document_id, action, status, message)
                        VALUES (%s, 'index_backfill', 'skipped', %s)
                        """,
                        (doc_id, f"no indexable text: {skipped}"),
                    )
                conn.commit()
                print(f"  [EMPTY] {code} :: {filename} :: {skipped}")
                continue

            total = 0
            batch = []
            for page_number, text in texts:
                for chunk_number, chunk in enumerate(split_text(text), start=1):
                    batch.append((
                        doc_id, code, module, page_number, chunk_number,
                        chunk, len(chunk), len(chunk.split()),
                    ))
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO knowledge_chunks
                    (document_id, subject_code, module_number,
                     page_number, chunk_number, content,
                     character_count, word_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    batch,
                )
                total = len(batch)
                cur.execute(
                    """
                    UPDATE knowledge_documents
                    SET page_count = %s, status = 'processed', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (len(pages), doc_id),
                )
                cur.execute(
                    """
                    INSERT INTO knowledge_processing_logs
                    (document_id, action, status, message)
                    VALUES (%s, 'index_backfill', 'success', %s)
                    """,
                    (doc_id, f"indexed {len(pages)} units into {total} chunks"),
                )
            conn.commit()
            report["indexed"].append((code, filename, total))
            print(f"  [OK] {code} :: {filename} -> {total} chunks")
    finally:
        conn.close()

    print()
    print("=" * 60)
    print("BACKFILL REPORT")
    print("=" * 60)
    for key in ("indexed", "duplicate", "empty", "missing", "failed", "skipped_type"):
        print(f"  {key:12}: {len(report[key])}")
    for key in ("duplicate", "empty", "missing", "failed"):
        for entry in report[key][:60]:
            print(f"    [{key}] {' :: '.join(str(p) for p in entry)}")
    print()
    print("Next: run generate_embeddings.py for vector search on new chunks.")
    return report


if __name__ == "__main__":
    main()
