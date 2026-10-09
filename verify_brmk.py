"""Verify BRMK557 integration: records, page, PDF view, per-module
RAG, subject purity, full regression."""
from app import app
from utils.database import db
from utils.vector_search import search_knowledge

results = []


def check(name, condition, detail=""):
    results.append(bool(condition))
    print(f"[{'PASS' if condition else 'FAIL'}] {name} {detail}", flush=True)


with app.app_context():
    docs = db.session.execute(
        db.text("""SELECT id, module_number, original_filename, page_count, status
                   FROM knowledge_documents WHERE subject_code='BRMK557'
                   ORDER BY module_number""")
    ).fetchall()
    check("BRMK557 documents == 5 (no dupes)", len(docs) == 5, f"count={len(docs)}")
    for d in docs:
        print(f"  id={d.id} mod={d.module_number} {d.original_filename!r} "
              f"pages={d.page_count} status={d.status}", flush=True)

    ch = db.session.execute(
        db.text("""SELECT module_number, COUNT(*), COUNT(*)-COUNT(embedding)
                   FROM knowledge_chunks WHERE subject_code='BRMK557'
                   GROUP BY 1 ORDER BY 1""")
    ).fetchall()
    for r in ch:
        print(f"  mod {r[0]}: chunks={r[1]} null_emb={r[2]}", flush=True)
    check("chunks all 5 modules, 0 NULL embeddings",
          len(ch) == 5 and sum(r[2] for r in ch) == 0,
          f"total={sum(r[1] for r in ch)}")

client = app.test_client()
with client.session_transaction() as sess:
    sess["user_id"] = 1

r = client.get("/subjects/BRMK557")
h = r.get_data(as_text=True)
check("GET /subjects/BRMK557 200", r.status_code == 200, f"status={r.status_code}")
for m in (1, 2, 3, 4, 5):
    check(f"page Module {m}", f"Module {m}" in h)
    check(f"page file module-{m}", f"BRMK557-module-{m}-pdf.pdf" in h)
check("View PDF buttons + new-tab", "View PDF" in h and 'target="_blank"' in h)

with app.app_context():
    ids = [d.id for d in db.session.execute(
        db.text("SELECT id FROM knowledge_documents WHERE subject_code='BRMK557' ORDER BY id")
    ).fetchall()]
for doc_id in ids:
    rr = client.get(f"/knowledge/pdf/{doc_id}")
    check(f"PDF {doc_id} 200", rr.status_code == 200 and rr.content_type == "application/pdf",
          f"bytes={len(rr.data)}")

print("=== per-module RAG ===")
natural = [
    (1, "meaning of research motivation engineering research ethics"),
    (2, "literature review technical reading citations bibliography"),
    (3, "intellectual property rights patents patenting process"),
    (4, "copyrights trademarks infringement ownership"),
    (5, "industrial design geographical indications design rights"),
]
for mod, q in natural:
    res = search_knowledge(q, subject_code="BRMK557", limit=3)
    mods = [(x["subject_code"], x["module_number"]) for x in res]
    ok = len(res) > 0 and ("BRMK557", mod) in mods and res[0]["page_number"] is not None
    check(f"RAG BRMK557 mod {mod}", ok, f"hits={mods} sim={res[0]['similarity']:.4f}" if res else "")

print("=== purity ===")
for code, q in [("BRMK557", "patent copyright research"),
                ("BCS501", "normalization"), ("BCS502", "OSI model"),
                ("BCS503", "finite automaton"), ("BCS504", "system call"),
                ("BCS515", "e-waste"), ("BCSL504", "HTML")]:
    res = search_knowledge(q, subject_code=code, limit=5)
    check(f"purity {code}", all(x["subject_code"] == code for x in res), f"n={len(res)}")

print("=== regression ===")
for path, marker in [("/subjects/BCS501", "SEPM Module 1.pdf"),
                     ("/subjects/BCS502", "BCS502 Module 1.pdf"),
                     ("/subjects/BCS503", "BCS503 Mod1@azdocuments.in.pdf"),
                     ("/subjects/BCS504", "Unix Module 1.pdf"),
                     ("/subjects/BCS515", "M1.pdf"),
                     ("/subjects/BCSL504", "Web Technology Programs.pdf")]:
    rr = client.get(path)
    check(f"regression {path}", rr.status_code == 200 and marker in rr.get_data(as_text=True),
          f"status={rr.status_code}")

print()
print(f"TOTAL: {sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)