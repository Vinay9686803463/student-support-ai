"""Verify remaining-subject ingestion: docs, chunks, embeddings, pages,
PDF viewing, per-module RAG, subject purity, BCS501/502 regression."""
import re
from app import app
from utils.database import db
from utils.vector_search import search_knowledge

results = []


def check(name, condition, detail=""):
    results.append(bool(condition))
    print(f"[{'PASS' if condition else 'FAIL'}] {name} {detail}", flush=True)


STOP = {"what", "which", "with", "from", "about", "that", "this", "have"}


def keywords(text, n=10):
    words = [w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in STOP]
    seen, out = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) == n:
            break
    return out


with app.app_context():
    print("=== STEP 8: documents ===")
    docs = db.session.execute(
        db.text("""
            SELECT subject_code, module_number, COUNT(*)
            FROM knowledge_documents
            WHERE subject_code IN ('BCS503','BCS504','BCS515')
            GROUP BY 1, 2 ORDER BY 1, 2
        """)
    ).fetchall()
    got = {(r[0], r[1]): r[2] for r in docs}
    print(f"  {got}")
    expect = {(f"BCS503", m): 1 for m in (1, 2, 3, 4, 5)}
    expect.update({(f"BCS504", m): 1 for m in (1, 3, 4, 5)})
    expect.update({(f"BCS515", m): 1 for m in (1, 2, 3, 4, 5)})
    check("docs per module match expected (14 docs)", got == expect)

    wt = db.session.execute(
        db.text("""
            SELECT id, subject_code, subject_name, module_number,
                   original_filename, page_count, status
            FROM knowledge_documents
            WHERE original_filename = 'Web Technology Programs.pdf'
        """)
    ).fetchall()
    check("exactly ONE WebTech document", len(wt) == 1)
    if wt:
        print(f"  id={wt[0].id} code={wt[0].subject_code} mod={wt[0].module_number} "
              f"pages={wt[0].page_count} status={wt[0].status}")
        check("WebTech code is BCSL504", wt[0].subject_code == "BCSL504")

    print("=== STEP 9: chunks ===")
    chunks = db.session.execute(
        db.text("""
            SELECT subject_code, module_number, COUNT(*)
            FROM knowledge_chunks
            WHERE subject_code IN ('BCS503','BCS504','BCS515','BCSL504')
            GROUP BY 1, 2 ORDER BY 1, 2
        """)
    ).fetchall()
    cmap = {(r[0], r[1]): r[2] for r in chunks}
    print(f"  {cmap}")
    check("chunks>0 for all 15 expected slots",
          all(cmap.get(k, 0) > 0 for k in list(expect) + [("BCSL504", 1)]))

    print("=== STEP 10: embeddings ===")
    emb = db.session.execute(
        db.text("""
            SELECT subject_code, module_number, COUNT(*),
                   COUNT(*) - COUNT(embedding)
            FROM knowledge_chunks
            WHERE subject_code IN ('BCS503','BCS504','BCS515','BCSL504')
            GROUP BY 1, 2 ORDER BY 1, 2
        """)
    ).fetchall()
    nulls = sum(r[3] for r in emb)
    total = sum(r[2] for r in emb)
    for r in emb:
        print(f"  {r[0]} mod={r[1]} embedded={r[2] - r[3]}/{r[2]}")
    check("zero NULL embeddings in new subjects", nulls == 0, f"total={total}")

    print("=== sample chunk per module (for RAG queries) ===")
    # Use a MIDDLE chunk of each module (topical content) rather than
    # the first chunk (often shared header boilerplate).
    samples = db.session.execute(
        db.text("""
            WITH ranked AS (
                SELECT subject_code, module_number, content,
                       ROW_NUMBER() OVER (
                           PARTITION BY subject_code, module_number
                           ORDER BY id) AS rn,
                       COUNT(*) OVER (
                           PARTITION BY subject_code, module_number) AS total
                FROM knowledge_chunks
                WHERE subject_code IN ('BCS503','BCS504','BCS515','BCSL504')
            )
            SELECT subject_code, module_number, content FROM ranked
            WHERE rn = (total / 2) + 1
            ORDER BY subject_code, module_number
        """)
    ).fetchall()
    print(f"  sampled {len(samples)} module slots")

client = app.test_client()
with client.session_transaction() as sess:
    sess["user_id"] = 1

print("=== STEP 11/12: subject pages ===")
page_expect = {
    "/subjects/BCS503": ["BCS503 Mod1@azdocuments.in.pdf", "BCS503 Mod5@azdocuments.in.pdf"],
    "/subjects/BCS504": ["Unix Module 1.pdf", "Unix Module 5.pdf"],
    "/subjects/BCS515": ["M1.pdf", "M5.pdf"],
    "/subjects/BCSL504": ["Web Technology Programs.pdf"],
}
for path, files in page_expect.items():
    r = client.get(path)
    h = r.get_data(as_text=True)
    mods_ok = True
    if "BCSL504" not in path:
        mods_ok = all(f"Module {m}" in h for m in (1, 2, 3, 4, 5))
    else:
        mods_ok = "Module 1" not in h and "Module 5" not in h
    check(f"page {path} 200 + modules + files",
          r.status_code == 200 and mods_ok and all(f in h for f in files),
          f"status={r.status_code}")

r = client.get("/subjects/BCS504")
check("BCS504 module 2 shows 'No PDF uploaded yet' (not hidden)",
      "No PDF uploaded yet" in r.get_data(as_text=True))

print("=== STEP 13: PDF viewing ===")
with app.app_context():
    pdf_ids = db.session.execute(
        db.text("""SELECT id, subject_code FROM knowledge_documents
                   WHERE subject_code IN ('BCS503','BCS504','BCS515','BCSL504')
                   ORDER BY id LIMIT 4""")
    ).fetchall()
for doc_id, code in pdf_ids:
    r = client.get(f"/knowledge/pdf/{doc_id}")
    check(f"PDF {doc_id} ({code}) 200 pdf",
          r.status_code == 200 and r.content_type == "application/pdf",
          f"bytes={len(r.data)}")

print("=== STEP 14: per-module RAG retrieval ===")
rag_n = 0
for s in samples:
    code, mod, content = s
    q = " ".join(keywords(content))
    res = search_knowledge(q, subject_code=code, limit=3)
    mods = [(x["subject_code"], x["module_number"]) for x in res]
    ok = (len(res) > 0 and all(x["subject_code"] == code for x in res)
          and res[0]["page_number"] is not None
          and res[0]["similarity"] > 0.2 and len(res[0]["content"]) > 0)
    rag_n += 1
    check(f"RAG {code} mod {mod} indexed+retrievable", ok,
          f"top3={mods} best_sim={res[0]['similarity']:.4f}" if res else "no results")

# Module discrimination with distinctive questions (curricula overlap,
# so only genuinely distinctive topics can isolate a single module).
distinct = [
    ("BCS504", 4, "multiplexed I/O select and poll IPC message queues", 1),
    ("BCS515", 3, "Extended Producer Responsibility PRO recycling obligations", 1),
    ("BCS515", 4, "e-waste collection centres dismantling refurbishing handling facilities", 5),
]
for code, mod, q, limit in distinct:
    res = search_knowledge(q, subject_code=code, limit=limit)
    mods = [(x["subject_code"], x["module_number"]) for x in res]
    ok = (code, mod) in mods
    rag_n += 1
    check(f"RAG discrimination {code} mod {mod} (top-{limit})", ok,
          f"hits={mods}" if res else "no results")

natural = [
    ("BCS503", "What is a finite automaton and DFA"),
    ("BCS504", "Explain system calls in Unix"),
    ("BCS515", "What is e-waste and how is it managed"),
    ("BCSL504", "HTML programs and web forms"),
]
for code, q in natural:
    res = search_knowledge(q, subject_code=code, limit=3)
    ok = len(res) > 0 and all(x["subject_code"] == code for x in res)
    rag_n += 1
    check(f"RAG natural {code}: {q[:38]}", ok,
          f"n={len(res)} sim={res[0]['similarity']:.4f}" if res else "")
print(f"retrieval tests run: {rag_n}")

print("=== STEP 15: subject purity ===")
for code, q in [("BCS503", "finite automaton"), ("BCS504", "unix inode"),
                ("BCS515", "e-waste"), ("BCS501", "normalization"),
                ("BCS502", "OSI model")]:
    res = search_knowledge(q, subject_code=code, limit=5)
    check(f"purity {code}", all(x["subject_code"] == code for x in res),
          f"n={len(res)}")

print("=== STEP 16: BCS501/502 regression ===")
for path, marker in [("/subjects/BCS501", "SEPM Module 1.pdf"),
                     ("/subjects/BCS502", "BCS502 Module 1.pdf")]:
    r = client.get(path)
    check(f"regression {path}",
          r.status_code == 200 and marker in r.get_data(as_text=True),
          f"status={r.status_code}")

print()
print(f"TOTAL: {sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)