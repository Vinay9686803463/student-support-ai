"""Verify Semester 1/2 subject update; confirm sem 3-5 + KB untouched."""
import re

from app import app
from utils.database import db

results = []


def check(name, condition, detail=""):
    results.append(bool(condition))
    print(f"[{'PASS' if condition else 'FAIL'}] {name} {detail}", flush=True)


SEM1_EXPECTED = [
    "Computer Aided Engineering Drawing",
    "Chemistry for CSE Stream",
    "Electronics and Communication Engineering",
    "Communicative English",
    "Samskrutika Kannada",
    "Mathematics for CSE-Stream-I",
    "Scientific Foundations of Health",
    "Waste Management",
]
SEM2_EXPECTED = [
    "Professional Writing Skills in English",
    "Indian Constitution",
    "Innovation and Design Thinking",
    "Baasics of Java Programming",
    "Mathematics for CSE Stream-II",
    "Introduction to Mechanical Engineering",
    "Physics for CSE Stream",
    "Principles of Programming Using C",
]

with app.app_context():
    counts = dict(db.session.execute(
        db.text("SELECT semester, COUNT(*) FROM subjects GROUP BY semester ORDER BY semester")
    ).fetchall())
    check("sem counts 8/8/16/14/16", counts == {1: 8, 2: 8, 3: 16, 4: 14, 5: 16}, str(counts))

    dupes = db.session.execute(
        db.text("SELECT subject_code, COUNT(*) c FROM subjects GROUP BY 1 HAVING COUNT(*) > 1")
    ).fetchall()
    check("no duplicate subject codes", not dupes, str(dupes))

    sem1 = db.session.execute(
        db.text("SELECT subject_code, subject_name, branch, scheme, category FROM subjects "
                "WHERE semester = 1 ORDER BY subject_code")
    ).mappings().all()
    sem1_names = sorted(r["subject_name"] for r in sem1)
    check("sem1 exactly the 8 names", sem1_names == sorted(SEM1_EXPECTED), str(sem1_names))
    check("sem1 all CSE/2022/Core",
          all(r["branch"] == "CSE" and r["scheme"] == "2022" and r["category"] == "Core" for r in sem1))
    check("sem1 codes preserved",
          sorted(r["subject_code"] for r in sem1) == sorted(
              ["BCEDK203", "BCHES102", "BESCK104x", "BENGK106",
               "BKSKK107", "BMATS101", "BSFHK158", "BETCK105x"]))
    check("sem1 exact new names",
          "Mathematics for CSE-Stream-I" in sem1_names
          and "Chemistry for CSE Stream" in sem1_names
          and "Samskrutika Kannada" in sem1_names
          and "Mathematics" not in sem1_names
          and [n for n in sem1_names if n == "Chemistry"] == []
          and [n for n in sem1_names if n == "Kannada"] == [])

    sem2 = db.session.execute(
        db.text("SELECT subject_code, subject_name, branch, scheme, category FROM subjects "
                "WHERE semester = 2 ORDER BY subject_code")
    ).mappings().all()
    sem2_names = sorted(r["subject_name"] for r in sem2)
    check("sem2 exactly the 8 names", sem2_names == sorted(SEM2_EXPECTED), str(sem2_names))
    check("sem2 all CSE/2022/Core",
          all(r["branch"] == "CSE" and r["scheme"] == "2022" and r["category"] == "Core" for r in sem2))

    # unwanted subjects gone (single query: avoids pg prepared-stmt reuse issue)
    all_codes = {r[0] for r in db.session.execute(
        db.text("SELECT subject_code FROM subjects")
    ).fetchall()}
    for code in ["BICOK107", "BIDTK158", "BKBKK107", "BPHYS102", "BPLCK105x",
                 "BPOPS103", "BPWSK106", "BCHES202", "BENGK206", "BETCK205x",
                 "BKBKK207", "BKSKK207", "BSFHK258"]:
        check(f"unwanted {code} removed", code not in all_codes)

    # knowledge base: VTU docs untouched; Mini Project data fully removed.
    for code, expected in [("BCS501", 5), ("BCS502", 5), ("BCS503", 5),
                           ("BCS504", 4), ("BCS515", 5), ("BCSL504", 1), ("BRMK557", 5)]:
        n = db.session.execute(
            db.text("SELECT COUNT(*) FROM knowledge_documents WHERE subject_code = :c"),
            {"c": code},
        ).scalar()
        check(f"VTU docs intact: {code}", n == expected, f"docs={n}")
    check("BCS586 subject row removed",
          db.session.execute(
              db.text("SELECT COUNT(*) FROM subjects WHERE subject_code = 'BCS586'")
          ).scalar() == 0)
    check("MINI_PROJECTS docs removed",
          db.session.execute(
              db.text("SELECT COUNT(*) FROM knowledge_documents "
                      "WHERE subject_code = 'MINI_PROJECTS'")
          ).scalar() == 0)
    check("MINI_PROJECTS chunks removed",
          db.session.execute(
              db.text("SELECT COUNT(*) FROM knowledge_chunks "
                      "WHERE subject_code = 'MINI_PROJECTS'")
          ).scalar() == 0)

client = app.test_client()
with client.session_transaction() as sess:
    sess["user_id"] = 1


def subject_cards(path):
    """Normal subject cards only (have a View Subject link; excludes promo banner)."""
    h = client.get(path).get_data(as_text=True)
    codes = sorted(set(re.findall(r'href="/subjects?/([A-Z0-9x]+)"', h)))
    names = sorted(set(re.findall(r"<h3>\s*([^<]+?)\s*</h3>", h)) - {"Mini Projects"})
    return h, codes, names, h.count("View Subject")


SEM1_CODES = sorted(["BCEDK103", "BCHES102", "BESCK104C", "BENGK106",
                     "BKSKK107", "BMATS101", "BSFHK158", "BETCK105F"])
SEM2_CODES = sorted(["BPWSK206", "BICOK207", "BIDTK258", "BPLCK205C",
                     "BMATS201", "BESCK204D", "BPHYS202", "BPOPS203"])

h1, codes1, names1, cards1 = subject_cards("/subjects?semester=1")
check("GET /subjects?semester=1 200", "Computer Aided Engineering Drawing" in h1)
check("sem1 exactly 8 normal subject cards", cards1 == 8 and codes1 == SEM1_CODES,
      f"cards={cards1} codes={codes1}")
check("sem1 page shows exactly the 8 names", names1 == sorted(SEM1_EXPECTED), str(names1))
check("sem1 no alternative/elective sections",
      "Selectable Alternatives" not in h1 and "Elective Options" not in h1)

h2, codes2, names2, cards2 = subject_cards("/subjects?semester=2")
check("sem2 exactly 8 normal subject cards", cards2 == 8 and codes2 == SEM2_CODES,
      f"cards={cards2} codes={codes2}")
check("sem2 page shows exactly the 8 names", names2 == sorted(SEM2_EXPECTED), str(names2))
check("sem2 English exact", "Professional Writing Skills in English" in h2
      and "Communicative English" not in h2)
check("sem1 English exact",
      "Communicative English" in h1 and "Professional Writing Skills" not in h1)

for path, label in [("/subjects?semester=3", "sem3"), ("/subjects?semester=4", "sem4"),
                    ("/subjects", "sem5")]:
    r = client.get(path)
    h = r.get_data(as_text=True)
    check(f"{label} page loads", r.status_code == 200, f"status={r.status_code}")

# every sem1/2 card opens its detail page
with app.app_context():
    codes = [r[0] for r in db.session.execute(
        db.text("SELECT subject_code FROM subjects WHERE semester IN (1, 2) ORDER BY semester, subject_code")
    ).fetchall()]
check("16 sem1/2 subjects found", len(codes) == 16, f"count={len(codes)}")
for code in codes:
    r = client.get(f"/subjects/{code}")
    check(f"detail /subjects/{code}", r.status_code == 200, f"status={r.status_code}")

# dashboard journey links intact
h = client.get("/dashboard").get_data(as_text=True)
check("dashboard journey links",
      all(f"semester={n}" in h for n in (1, 2, 3, 4)))

# --- Mini Project section fully removed from UI ---
for bad_path, label in [("/mini-projects", "page route"),
                        ("/api/mini-projects/search", "search API"),
                        ("/subjects/BCS586", "old project subject page")]:
    r = client.get(bad_path)
    check(f"removed {label} -> 404", r.status_code == 404, f"status={r.status_code}")

for page in ["/dashboard", "/subjects", "/subjects?semester=1",
             "/subjects?semester=2", "/subjects?semester=5", "/chat"]:
    h = client.get(page).get_data(as_text=True)
    check(f"no Mini Project traces on {page}",
          "Mini Projects" not in h and "mini-projects" not in h
          and "BCS586" not in h)

# --- preserved sections still work ---
for code, name in [("BCSL504", "Web Technology"), ("BRMK557", "Research Methodology")]:
    r = client.get(f"/subjects/{code}")
    h = r.get_data(as_text=True)
    check(f"{name} ({code}) detail works", r.status_code == 200 and name in h,
          f"status={r.status_code}")
h5 = client.get("/subjects?semester=5").get_data(as_text=True)
check("Web Technology card present (sem5)", "BCSL504" in h5)
check("RMIP card present (sem5)", "BRMK557" in h5)
check("no Mini Project card (sem5)", "BCS586" not in h5 and "Mini Project" not in h5)

print()
print(f"TOTAL: {sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
