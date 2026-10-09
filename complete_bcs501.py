"""Complete BCS501 chunk ingestion. Uses fresh psycopg connections with
automatic server-side prepared statements disabled (prepare_threshold=None)
to avoid DuplicatePreparedStatement errors on the pooled connection.
Creates NO new documents."""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from utils.knowledge_ingest import extract_pdf_pages, split_text

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parent


def connect():
    return psycopg.connect(DATABASE_URL, prepare_threshold=None)


with connect() as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, module_number, original_filename, file_path, status
            FROM knowledge_documents
            WHERE subject_code = 'BCS501'
            ORDER BY module_number
        """)
        docs = cur.fetchall()

for doc_id, module_number, original_filename, file_path, status in docs:
    print(f"--- document {doc_id} (module {module_number}, status={status})", flush=True)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE document_id=%s",
                        (doc_id,))
            existing_chunks = cur.fetchone()[0]
    print(f"    chunks present: {existing_chunks}", flush=True)

    rel = os.path.relpath(
        PROJECT_ROOT / "knowledge_base" / "BCS501" / f"module{module_number}" / original_filename,
        PROJECT_ROOT,
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE knowledge_documents SET file_path=%s WHERE id=%s",
                        (rel, doc_id))
        conn.commit()
    print(f"    file_path -> {rel}", flush=True)

    if status == "processed" and existing_chunks > 0:
        print("    already complete, skipping", flush=True)
        continue

    pdf_path = PROJECT_ROOT / rel
    pages = extract_pdf_pages(pdf_path)
    print(f"    pages={len(pages)}", flush=True)
    total_chunks = 0
    pages_with_text = 0
    with connect() as conn:
        with conn.cursor() as cur:
            for page in pages:
                if not page["text"]:
                    continue
                pages_with_text += 1
                for cn, chunk in enumerate(split_text(page["text"]), start=1):
                    cur.execute("""
                        INSERT INTO knowledge_chunks
                        (document_id, subject_code, module_number, page_number,
                         chunk_number, content, character_count, word_count)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (doc_id, "BCS501", module_number, page["page_number"],
                          cn, chunk, len(chunk), len(chunk.split())))
                    total_chunks += 1
            cur.execute("""
                UPDATE knowledge_documents
                SET page_count=%s, status='processed', updated_at=NOW()
                WHERE id=%s
            """, (len(pages), doc_id))
            cur.execute("""
                INSERT INTO knowledge_processing_logs
                (document_id, action, status, message)
                VALUES (%s,'pdf_ingestion','success',%s)
            """, (doc_id, f"Processed {len(pages)} pages, {total_chunks} chunks (completed)."))
        conn.commit()
    print(f"    [OK] text_pages={pages_with_text} chunks={total_chunks} status=processed",
          flush=True)

print("COMPLETE")