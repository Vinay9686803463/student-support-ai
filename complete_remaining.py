"""Complete chunk ingestion for documents stuck in 'processing'.
Reuses extract_pdf_pages/split_text and process_pdf's SQL shapes.
Creates NO new documents; skips docs that already have chunks."""
import os
from pathlib import Path

from utils.knowledge_ingest import get_connection, extract_pdf_pages, split_text

PROJECT_ROOT = Path(__file__).resolve().parent

conn = get_connection()
try:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, subject_code, module_number, original_filename,
                   file_path, status
            FROM knowledge_documents
            WHERE subject_code IN ('BCS503','BCS504','BCS515')
            ORDER BY subject_code, module_number
        """)
        docs = cur.fetchall()
    print(f"candidate documents: {len(docs)}")

    for doc_id, code, mod, orig, fpath, status in docs:
        print(f"--- {code} module {mod} (id={doc_id}, status={status})", flush=True)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE document_id=%s",
                        (doc_id,))
            have = cur.fetchone()[0]
        print(f"    chunks present: {have}", flush=True)

        # Normalize to the relative convention.
        if fpath and Path(fpath).is_absolute():
            try:
                rel = os.path.relpath(fpath, PROJECT_ROOT)
            except ValueError:
                rel = fpath
        else:
            rel = fpath
        if rel != fpath:
            with conn.cursor() as cur:
                cur.execute("UPDATE knowledge_documents SET file_path=%s WHERE id=%s",
                            (rel, doc_id))
            conn.commit()
            print(f"    file_path -> {rel}", flush=True)

        if status == "processed" and have > 0:
            print("    already complete, skipping", flush=True)
            continue

        pdf_path = PROJECT_ROOT / rel if not Path(rel).is_absolute() else Path(rel)
        pages = extract_pdf_pages(pdf_path)
        total = 0
        text_pages = 0
        with conn.cursor() as cur:
            # Remove any partial chunks from the failed attempt first
            # (same document only), then insert the full set.
            if have > 0:
                cur.execute("DELETE FROM knowledge_chunks WHERE document_id=%s",
                            (doc_id,))
            for page in pages:
                if not page["text"]:
                    continue
                text_pages += 1
                for cn, chunk in enumerate(split_text(page["text"]), start=1):
                    cur.execute("""
                        INSERT INTO knowledge_chunks
                        (document_id, subject_code, module_number, page_number,
                         chunk_number, content, character_count, word_count)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (doc_id, code, mod, page["page_number"],
                          cn, chunk, len(chunk), len(chunk.split())))
                    total += 1
            cur.execute("""
                UPDATE knowledge_documents
                SET page_count=%s, status='processed', updated_at=NOW()
                WHERE id=%s
            """, (len(pages), doc_id))
            cur.execute("""
                INSERT INTO knowledge_processing_logs
                (document_id, action, status, message)
                VALUES (%s,'pdf_ingestion','success',%s)
            """, (doc_id, f"Processed {len(pages)} pages, {total} chunks (completed)."))
        conn.commit()
        print(f"    [OK] pages={len(pages)} text_pages={text_pages} chunks={total}",
              flush=True)
finally:
    conn.close()
print("COMPLETE")