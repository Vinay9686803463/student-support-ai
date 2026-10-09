"""Verify BCS501 ingestion: DB state, page display, PDF view, RAG."""
from app import app
from utils.database import db

results = []


def check(name, condition, detail=""):
    results.append(bool(condition))
    print(f"[{'PASS' if condition else 'FAIL'}] {name} {detail}")


with app.app_context():
    docs = db.session.execute(
        db.text("""
            SELECT id, module_number, original_filename, file_path,
                   page_count, status
            FROM knowledge_documents
            WHERE subject_code = 'BCS501'
            ORDER BY module_number
        """)
    ).fetchall()
    check("BCS501 documents == 5", len(docs) == 5, f"count={len(docs)}")
    for d in docs:
        print(f"  id={d.id} mod={d.module_number} file={d.original_filename!r} "
              f"pages={d.page_count} status={d.status}")

    per_mod = db.session.execute(
        db.text("""
            SELECT module_number, COUNT(*) FROM knowledge_documents
            WHERE subject_code='BCS501' GROUP BY 1 ORDER BY 1
        """)
    ).fetchall()
    check("one doc per module 1-5",
          [(r[0], r[1]) for r in per_mod] == [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1)])

    chunks = db.session.execute(
        db.text("""
            SELECT module_number, COUNT(*) FROM knowledge_chunks
            WHERE subject_code='BCS501' GROUP BY 1 ORDER BY 1
        """)
    ).fetchall()
    print("chunks per module:", [(r[0], r[1]) for r in chunks])
    check("chunks exist for all 5 modules",
          len(chunks) == 5 and all(r[1] > 0 for r in chunks))

    emb = db.session.execute(
        db.text("""SELECT COUNT(*) FROM knowledge_chunks
                   WHERE subject_code='BCS501' AND embedding IS NOT NULL""")
    ).scalar()
    null_emb = db.session.execute(
        db.text("""SELECT COUNT(*) FROM knowledge_chunks
                   WHERE subject_code='BCS501' AND embedding IS NULL""")
    ).scalar()
    total = db.session.execute(
        db.text("SELECT COUNT(*) FROM knowledge_chunks WHERE subject_code='BCS501'")
    ).scalar()
    check("all BCS501 chunks embedded", null_emb == 0 and emb == total,
          f"embedded={emb} null={null_emb} total={total}")

    bcs502 = db.session.execute(
        db.text("SELECT COUNT(*) FROM knowledge_documents WHERE subject_code='BCS502'")
    ).scalar()
    check("BCS502 docs untouched (5)", bcs502 == 5, f"count={bcs502}")

client = app.test_client()
with client.session_transaction() as sess:
    sess["user_id"] = 1

r = client.get("/subjects/BCS501")
h = r.get_data(as_text=True)
check("GET /subjects/BCS501 = 200", r.status_code == 200, f"status={r.status_code}")
for m in ["Module 1", "Module 2", "Module 3", "Module 4", "Module 5"]:
    check(f"BCS501 page: {m}", m in h)
for f in ["SEPM Module 1.pdf", "SEPM Module 2.pdf", "SEPM Module 3.pdf",
          "SEPM Module 4.pdf", "SEPM Module 5.pdf"]:
    check(f"BCS501 page: {f}", f in h)

doc_id = docs[0].id
r = client.get(f"/knowledge/pdf/{doc_id}")
check(f"PDF view doc {doc_id} = 200 pdf",
      r.status_code == 200 and r.content_type == "application/pdf",
      f"status={r.status_code} bytes={len(r.data)}")

# RAG retrieval for BCS501 (two modules)
from utils.vector_search import search_knowledge
res1 = search_knowledge("Explain software engineering and its characteristics",
                        subject_code="BCS501", limit=3)
check("RAG BCS501 Q1 returns BCS501 chunks",
      len(res1) > 0 and all(x["subject_code"] == "BCS501" for x in res1),
      f"n={len(res1)}")
if res1:
    print(f"  top: mod={res1[0]['module_number']} page={res1[0]['page_number']} "
          f"sim={res1[0]['similarity']:.4f}")
    print(f"  text: {res1[0]['content'][:160]!r}")

res2 = search_knowledge("Explain Agile methodology and Scrum",
                        subject_code="BCS501", limit=3)
check("RAG BCS501 Q2 (agile) returns BCS501 chunks",
      len(res2) > 0 and all(x["subject_code"] == "BCS501" for x in res2),
      f"n={len(res2)}")
if res2:
    print(f"  top: mod={res2[0]['module_number']} page={res2[0]['page_number']} "
          f"sim={res2[0]['similarity']:.4f}")

# Subject filtering: BCS502 query must not leak BCS501 and vice versa
res502 = search_knowledge("What are the seven layers of the OSI model?",
                          subject_code="BCS502", limit=3)
check("BCS502 retrieval still pure BCS502",
      len(res502) > 0 and all(x["subject_code"] == "BCS502" for x in res502),
      f"n={len(res502)}")

# BCS502 page regression
r = client.get("/subjects/BCS502")
h2 = r.get_data(as_text=True)
check("BCS502 page regression 200 + PDFs",
      r.status_code == 200 and "BCS502 Module 1.pdf" in h2,
      f"status={r.status_code}")

print()
print(f"TOTAL: {sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)