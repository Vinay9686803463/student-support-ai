"""Verify VTU 2022 subject codes for semesters 1-4 (14 acceptance points)."""
import html
import re

from app import app
from utils.database import db

results = []


def check(name, condition, detail=""):
    results.append(bool(condition))
    print(f"[{'PASS' if condition else 'FAIL'}] {name} {detail}", flush=True)


SPEC = {
    1: [("BCEDK103", "Computer Aided Engineering Drawing"),
        ("BCHES102", "Chemistry for CSE Stream"),
        ("BESCK104C", "Electronics and Communication Engineering"),
        ("BENGK106", "Communicative English"),
        ("BKSKK107", "Samskrutika Kannada"),
        ("BMATS101", "Mathematics for CSE-Stream-I"),
        ("BSFHK158", "Scientific Foundations of Health"),
        ("BETCK105F", "Waste Management")],
    2: [("BPWSK206", "Professional Writing Skills in English"),
        ("BICOK207", "Indian Constitution"),
        ("BIDTK258", "Innovation and Design Thinking"),
        ("BPLCK205C", "Baasics of Java Programming"),
        ("BMATS201", "Mathematics for CSE Stream-II"),
        ("BESCK204D", "Introduction to Mechanical Engineering"),
        ("BPHYS202", "Physics for CSE Stream"),
        ("BPOPS203", "Principles of Programming Using C")],
    3: [("BCS301", "Mathematics for Computer Science"),
        ("BCS302", "Digital Design & Computer Organization"),
        ("BCS303", "Operating Systems"),
        ("BCS304", "Data Structures and Applications"),
        ("BCSL305", "Data Structures Lab"),
        ("BCS306B", "Object Oriented Programming with C++"),
        ("BSCK307", "Social Connect and Responsibility"),
        ("BYOK359", "Yoga")],
    4: [("BCS401", "Analysis & Design of Algorithms"),
        ("BCS402", "Microcontrollers"),
        ("BCS403", "Database Management Systems"),
        ("BCSL404", "Analysis & Design of Algorithms Lab"),
        ("BCS405A", "Discrete Mathematical Structures"),
        ("BCSL456D", "Technical Writing using LATEX"),
        ("BBOC407", "Biology for Computer Engineers"),
        ("BUHK408", "Universal Human Values Course"),
        ("BYOK459", "Yoga")],
}

with app.app_context():
    counts = dict(db.session.execute(
        db.text("SELECT semester, COUNT(*) FROM subjects GROUP BY semester ORDER BY semester")
    ).fetchall())
    check("counts 8/8/8/9", {k: counts.get(k) for k in (1, 2, 3, 4)} == {1: 8, 2: 8, 3: 8, 4: 9},
          str(counts))

    for sem, pairs in SPEC.items():
        rows = db.session.execute(
            db.text("SELECT subject_code, subject_name, branch, scheme, category "
                    "FROM subjects WHERE semester = :s ORDER BY subject_code"),
            {"s": sem},
        ).mappings().all()
        got = sorted((r["subject_code"], r["subject_name"]) for r in rows)
        check(f"sem{sem} exact code+name list", got == sorted(pairs),
              str([c for c, _n in got]) if got != sorted(pairs) else f"{len(got)} rows")
        check(f"sem{sem} all CSE/2022/Core",
              all(r["branch"] == "CSE" and r["scheme"] == "2022"
                  and r["category"] == "Core" for r in rows))

    all_codes = {r[0] for r in db.session.execute(
        db.text("SELECT subject_code FROM subjects")
    ).fetchall()}
    for code in ["BESCK104x", "BETCK105x", "BCEDK203", "BPLCK205x", "BESCK204x",
                 "BCS306A", "BCS358x", "BCSL358A", "BCSL358B", "BCSL358C", "BCSL358D",
                 "BCS405B", "BCS405C", "BCS405D", "BCS456A", "BCS456B", "BCS456C",
                 "BNSK359", "BPEK359", "BCS586"]:
        check(f"excluded {code} absent", code not in all_codes)

    dupes = db.session.execute(
        db.text("SELECT subject_code, COUNT(*) FROM subjects GROUP BY 1 HAVING COUNT(*) > 1")
    ).fetchall()
    check("no duplicate codes", not dupes, str(dupes))

    doc_counts = dict(db.session.execute(
        db.text("SELECT subject_code, COUNT(*) FROM knowledge_documents GROUP BY 1")
    ).fetchall())
    for code, expected in [("BCS501", 5), ("BCS502", 5), ("BCS503", 5),
                           ("BCS504", 4), ("BCS515", 5), ("BCSL504", 1), ("BRMK557", 5)]:
        check(f"VTU docs intact: {code}", doc_counts.get(code) == expected,
              f"docs={doc_counts.get(code)}")

client = app.test_client()
with client.session_transaction() as sess:
    sess["user_id"] = 1


def cards(path):
    h = html.unescape(client.get(path).get_data(as_text=True))
    codes = sorted(set(re.findall(r'href="/subjects?/([A-Z0-9x]+)"', h)))
    return h, codes, h.count("View Subject")


for sem in (1, 2, 3, 4):
    h, codes, ncards = cards(f"/subjects?semester={sem}")
    want = sorted(c for c, _n in SPEC[sem])
    check(f"sem{sem} page: {len(want)} cards with exact codes",
          ncards == len(want) and codes == want, f"cards={ncards} codes={codes}")
    for _code, name in SPEC[sem]:
        if name not in h:
            check(f"sem{sem} card shows {name!r}", False)
            break
    else:
        check(f"sem{sem} cards show exact names", True)
    check(f"sem{sem} no alt/elective sections",
          "Selectable Alternatives" not in h and "Elective Options" not in h)

# Yoga in both semesters with distinct codes.
h3, codes3, _n = cards("/subjects?semester=3")
h4, codes4, _n = cards("/subjects?semester=4")
check("Yoga BYOK359 in sem3", "BYOK359" in codes3 and "Yoga" in h3)
check("Yoga BYOK459 in sem4", "BYOK459" in codes4 and "Yoga" in h4)

# Every sem1-4 card opens its detail page showing the DB code.
all_codes = [c for sem in (1, 2, 3, 4) for c, _n in SPEC[sem]]
check("33 sem1-4 subjects", len(all_codes) == 33, f"count={len(all_codes)}")
bad = 0
for code in all_codes:
    r = client.get(f"/subjects/{code}")
    h = r.get_data(as_text=True)
    if r.status_code != 200 or code not in h or "Something went wrong" in h:
        check(f"detail /subjects/{code}", False, f"status={r.status_code}")
        bad += 1
if not bad:
    check("all 33 detail pages show DB code", True)

# Sem5 + journey + preserved areas.
r = client.get("/subjects?semester=5")
h5 = r.get_data(as_text=True)
for c in ["BCS501", "BCS502", "BCS503", "BCSL504", "BRMK557", "BCS508", "BCS515"]:
    if c not in h5:
        check(f"sem5 keeps {c}", False)
        break
else:
    check("sem5 keeps working subjects", True)
check("sem5 excludes Mini Project/elective/NSS/PE",
      "BCS586" not in h5 and "BCS515x" not in h5
      and "BNSK559" not in h5 and "BPEK559" not in h5)
for path in ["/subjects/BCS502", "/subjects/BCSL504", "/subjects/BRMK557"]:
    check(f"detail {path} 200", client.get(path).status_code == 200)
h = client.get("/dashboard").get_data(as_text=True)
check("journey links sem1-4", all(f"semester={n}" in h for n in (1, 2, 3, 4)))

# RAG still grounded in sem-5 knowledge.
r = client.post("/api/chat", json={"message": "Explain DBMS normalization"})
d = r.get_json() or {}
check("chat/RAG answers", r.status_code == 200 and len(d.get("reply", "")) > 20,
      f"engine={d.get('engine')}")

print()
print(f"TOTAL: {sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
