from pathlib import Path
import os
import psycopg
from dotenv import load_dotenv
from utils.knowledge_ingest import extract_document_pages, split_text

ROOT = Path.cwd().resolve()
KB = (ROOT / "knowledge_base").resolve()
load_dotenv(ROOT / ".env")

EXPECTED = {
    446: (1, 7, "EVS-BCS508 Mod1@azdocuments.in.pdf"),
    447: (2, 20, "EVS-BCS508 Mod2@azdocuments.in.pdf"),
    448: (3, 42, "EVS-BCS508 Mod3@azdocuments.in.pdf"),
    449: (4, 31, "EVS-BCS508 Mod4@azdocuments.in.pdf"),
    450: (5, 43, "EVS-BCS508 Mod5@azdocuments.in.pdf"),
}

url = os.getenv("DATABASE_URL")
if not url:
    raise SystemExit("STOP: DATABASE_URL is missing.")

# Prepare all text locally before touching the database.
prepared = []
for doc_id, (module, expected_pages, filename) in EXPECTED.items():
    path = (KB / "BCS508" / f"module{module}" / filename).resolve(strict=True)
    path.relative_to(KB)
    pages, reason = extract_document_pages(path)

    if reason or len(pages) != expected_pages:
        raise SystemExit(
            f"STOP: extraction mismatch for ID {doc_id}; "
            f"pages={len(pages)}, reason={reason!r}"
        )

    chunks = []
    number = 0
    for page in pages:
        for content in split_text(page.get("text", "")):
            content = content.strip()
            if content:
                number += 1
                chunks.append((
                    doc_id, "BCS508", module, int(page["page_number"]),
                    number, content, len(content), len(content.split())
                ))

    if not chunks:
        raise SystemExit(f"STOP: no chunks extracted for ID {doc_id}.")
    prepared.append((doc_id, module, expected_pages, filename, chunks))

print("\nPrepared:")
for doc_id, module, pages, filename, chunks in prepared:
    print(f"ID {doc_id}, module {module}: {pages} pages, {len(chunks)} chunks")
print("Total:", sum(len(x[4]) for x in prepared), "chunks")
print("Embeddings will remain NULL. Only BCS508 IDs 446-450 are targeted.")

answer = input("\nType APPLY to continue, or anything else to cancel: ").strip()
if answer != "APPLY":
    raise SystemExit("Cancelled. No database changes made.")

# Writes are atomic: an exception before commit rolls back the transaction.
with psycopg.connect(url, connect_timeout=10) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, subject_code, module_number, status,
                   file_path, original_filename
            FROM knowledge_documents
            WHERE id = ANY(%s)
            ORDER BY id FOR UPDATE
        """, (list(EXPECTED),))
        records = cur.fetchall()

        if len(records) != 5:
            raise RuntimeError("STOP: expected exactly five records.")

        for r in records:
            doc_id, subject, module, status, stored_path, filename = r
            exp_module, _, exp_filename = EXPECTED[doc_id]
            exp_path = (
                f"knowledge_base/BCS508/module{exp_module}/{exp_filename}"
            )
            if (
                subject != "BCS508" or module != exp_module
                or status != "uploaded" or filename != exp_filename
                or str(stored_path).replace("\\", "/") != exp_path
            ):
                raise RuntimeError(f"STOP: record validation failed for ID {doc_id}.")

            cur.execute(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE document_id=%s",
                (doc_id,)
            )
            if cur.fetchone()[0] != 0:
                raise RuntimeError(f"STOP: ID {doc_id} already has chunks.")

        for doc_id, module, pages, filename, chunks in prepared:
            cur.executemany("""
                INSERT INTO knowledge_chunks
                (document_id, subject_code, module_number, page_number,
                 chunk_number, content, character_count, word_count)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, chunks)

            cur.execute("""
                UPDATE knowledge_documents
                SET page_count=%s, status='processed', updated_at=NOW()
                WHERE id=%s AND subject_code='BCS508' AND status='uploaded'
            """, (pages, doc_id))
            if cur.rowcount != 1:
                raise RuntimeError(f"STOP: update failed for ID {doc_id}.")

            cur.execute("""
                INSERT INTO knowledge_processing_logs
                    (document_id, action, status, message)
                VALUES (%s, %s, %s, %s)
            """, (
                doc_id, "pdf_ingestion", "success",
                f"Recovered PDF text; inserted {len(chunks)} chunks; embeddings not generated."
            ))

        for doc_id, module, pages, filename, chunks in prepared:
            cur.execute(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE document_id=%s",
                (doc_id,)
            )
            if cur.fetchone()[0] != len(chunks):
                raise RuntimeError(f"STOP: chunk verification failed for ID {doc_id}.")

            cur.execute("""
                SELECT COUNT(*) FROM knowledge_chunks
                WHERE document_id=%s
                  AND length(to_tsvector('english', content)::text) > 0
            """, (doc_id,))
            if cur.fetchone()[0] == 0:
                raise RuntimeError(f"STOP: text-search verification failed for ID {doc_id}.")

    conn.commit()

print("\nSUCCESS: database changes committed.")
for doc_id, module, pages, filename, chunks in prepared:
    print(f"ID {doc_id}: {len(chunks)} chunks verified")
