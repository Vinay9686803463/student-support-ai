import re
from app import app
from utils.database import db

results = []


def check(name, condition, detail=""):
    results.append(bool(condition))
    print(f"[{'PASS' if condition else 'FAIL'}] {name} {detail}", flush=True)


SEM1 = ["BMATS101", "BPOPS103", "BESCK104x", "BPHYS102", "BCHES102",
        "BETCK105x", "BPLCK105x", "BENGK106", "BPWSK106", "BKSKK107",
        "BKBKK107", "BICOK107", "BIDTK158", "BSFHK158"]
SEM2 = ["BMATS201", "BESCK204x", "BCHES202", "BPHYS202", "BCEDK203",
        "BPOPS203", "BETCK205x", "BPLCK205x", "BENGK206", "BPWSK206",
        "BICOK207", "BKSKK207", "BKBKK207", "BIDTK258", "BSFHK258"]
SEM3 = ["BCS301", "BCS302", "BCS303", "BCS304", "BCSL305", "BSCK307",
        "BCS306B", "BCSL358A"]
SEM4 = ["BCS401", "BCS402", "BCS403", "BCSL404", "BBOC407", "BUHK408",
        "BCS405A", "BCSL456D"]
SEM5CORE = ["BCS501", "BCS502", "BCS503", "BCS504", "BCS508", "BCS515",
            "BCS586", "BCSL504", "BRMK557"]
SEM5PROF = ["BCS515A", "BCS515B", "BCS515C", "BCS515D"]
ALL = SEM1 + SEM2 + SEM3 + SEM4 + SEM5CORE + SEM5PROF

with app.app_context():
    n = db.session.execute(
        db.text("SELECT COUNT(*) FROM subjects WHERE branch='CSE' AND scheme='2022' "
                "AND semester IN (1,2,3,4)")
    ).scalar()
    check("sem1-4 rows present", n == 48, f"count={n}")
    dupes = db.session.execute(
        db.text("SELECT subject_code, COUNT(*) FROM subjects GROUP BY 1 HAVING COUNT(*) > 1")
    ).fetchall()
    check("no duplicate subject codes", len(dupes) == 0, f"{dupes}")

client = app.test_client()
with client.session_transaction() as sess:
    sess["user_id"] = 1


def codes_on_page(path):
    r = client.get(path)
    h = r.get_data(as_text=True)
    return r.status_code, h, sorted(set(re.findall(r'href="/subjects?/([A-Z0-9x]+)"', h)))


expect = {1: SEM1, 2: SEM2, 3: SEM3, 4: SEM4}
REMOVED3 = ["Data Visualization with Python", "Project Management with Git",
            "R Programming", "Ability Enhancement Course / Skill Enhancement",
            "Object Oriented Programming with Java", "BCS306A", "BCS358x",
            "BCSL358B", "BCSL358C", "BCSL358D"]
REMOVED4 = ["UI/UX", "Capacity Planning for IT", "Green IT and Sustainability",
            "Linear Algebra", "Optimization Technique", "Graph Theory",
            "BCS405B", "BCS405C", "BCS405D", "BCS456A", "BCS456B", "BCS456C"]
for sem, codes in expect.items():
    sc, h, got = codes_on_page(f"/subjects?semester={sem}")
    check(f"sem{sem} exact code list", sc == 200 and got == sorted(codes),
          f"status={sc} got={len(got)} want={len(codes)}")
    if got != sorted(codes):
        print(f"   missing={sorted(set(codes) - set(got))} extra={sorted(set(got) - set(codes))}")
    # Semester nav: 5 boxes, only current active, back button first
    boxes = re.findall(r'class="semester-box( active)?"[^>]*>\s*(\d)(?:st|nd|rd|th)', h)
    check(f"sem{sem} nav: 5 boxes, only sem{sem} active",
          sorted(int(b[1]) for b in boxes) == [1, 2, 3, 4, 5]
          and sum(1 for b in boxes if b[0]) == 1
          and next(int(b[1]) for b in boxes if b[0]) == sem)
    bi = h.find("back-nav-row")
    ni = h.find("semester-nav")
    hi = h.find("subjects-header")
    check(f"sem{sem} order: back -> nav -> header", 0 <= bi < ni < hi)
    check(f"sem{sem} badge VTU CSE 2022",
          f"Semester {sem} \u2022 VTU CSE \u2022 2022 Scheme" in h)

for name in REMOVED3:
    check(f"sem3 removed: {name[:42]}", name not in client.get("/subjects?semester=3").get_data(as_text=True))
for name in REMOVED4:
    check(f"sem4 removed: {name[:42]}", name not in client.get("/subjects?semester=4").get_data(as_text=True))

sc, h, got = codes_on_page("/subjects")
check("sem5 core list intact",
      sc == 200 and got == sorted(SEM5CORE + SEM5PROF), f"got={got}")
check("sem5 Professional Elective section", "Professional Elective" in h
      and "BCS515A" in h and "Computer Graphics" in h)
check("sem5 placeholder still hidden",
      "Professional Elective Course" not in h and "BCS515x" not in got)
for hid in ["BNSK559", "BPEK559", "BYOK559", "BNSK359", "BPEK359", "BYOK359",
            "BCS515x", "Yoga"]:
    check(f"hidden {hid}", hid not in got)

sc3 = client.get("/subjects?semester=3").get_data(as_text=True)
check("sem3 Elective Options section",
      "Elective Options" in sc3 and "BCS306B" in sc3 and "Object Oriented Programming with C++" in sc3)
check("sem3 activity hidden", "BNSK359" not in sc3 and "National Service Scheme" not in sc3)
sc1 = client.get("/subjects?semester=1").get_data(as_text=True)
check("sem1 Selectable Alternatives section",
      "Selectable Alternatives" in sc1 and "BPHYS102" in sc1)
sc4 = client.get("/subjects?semester=4").get_data(as_text=True)
check("sem4 electives grouped", "Elective Options" in sc4 and "BCS405A" in sc4
      and "BCSL456D" in sc4)

# Detail pages for new subjects (BCS306A was user-removed -> 404 expected)
for path in ["/subjects/BCS301", "/subjects/BCS401", "/subjects/BMATS101",
             "/subjects/BCS515A", "/subjects/BCS306B", "/subjects/BRMK557"]:
    rr = client.get(path)
    check(f"detail {path}", rr.status_code == 200, f"status={rr.status_code}")
rr = client.get("/subjects/BCS306A")
check("detail /subjects/BCS306A removed (404)", rr.status_code == 404,
      f"status={rr.status_code}")

# Knowledge intact (VTU-subject docs; project docs removed externally, see report)
with app.app_context():
    kd = db.session.execute(db.text("SELECT COUNT(*) FROM knowledge_documents")).scalar()
    check("knowledge documents preserved", kd == 30, f"count={kd}")
    codes = db.session.execute(
        db.text("SELECT DISTINCT subject_code FROM knowledge_documents ORDER BY 1")
    ).fetchall()
    check("all VTU knowledge subjects intact",
          sorted(r[0] for r in codes) == ["BCS501", "BCS502", "BCS503", "BCS504",
                                          "BCS515", "BCSL504", "BRMK557"],
          f"{[r[0] for r in codes]}")

print()
print(f"TOTAL: {sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)