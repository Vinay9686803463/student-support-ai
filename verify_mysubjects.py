import re
from app import app
from utils.database import db

results = []


def check(name, condition, detail=""):
    results.append(bool(condition))
    print(f"[{'PASS' if condition else 'FAIL'}] {name} {detail}", flush=True)


with app.app_context():
    total = db.session.execute(db.text("SELECT COUNT(*) FROM subjects")).scalar()
    check("no subjects deleted from DB", total >= 13, f"count={total}")
    for code in ["BCS501", "BCS502", "BCS503", "BCS504", "BCS508", "BCS515",
                "BCS515x", "BCS586", "BCSL504", "BNSK559", "BPEK559",
                "BRMK557", "BYOK559"]:
        n = db.session.execute(
            db.text("SELECT COUNT(*) FROM subjects WHERE subject_code=:c"), {"c": code}
        ).scalar()
        check(f"DB row {code} still exists", n == 1)

client = app.test_client()
with client.session_transaction() as sess:
    sess["user_id"] = 1

r = client.get("/subjects")
h = r.get_data(as_text=True)
codes = sorted(set(re.findall(r'href="/subjects?/([A-Z0-9x]+)"', h)))
print(f"cards: {codes}")
check("GET /subjects 200", r.status_code == 200)
check("Research Methodology and IPR visible",
      "Research Methodology" in h and "BRMK557" in codes)
check("Professional Elective absent", "Professional Elective Course" not in h and "BCS515x" not in codes)
check("NSS absent", "National Service Scheme" not in h and "BNSK559" not in codes)
check("PE absent", "Physical Education" not in h and "BPEK559" not in codes)
check("Yoga hidden (activity rule)", "BYOK559" not in codes)
for c in ["BCS501", "BCS502", "BCS503", "BCS504", "BCS515", "BRMK557",
          "BCS515A", "BCS515B", "BCS515C", "BCS515D"]:
    check(f"relevant subject {c} visible", c in codes)

# Detail links still work (visible + hidden-direct)
for path in ["/subjects/BRMK557", "/subjects/BCS501", "/subjects/BCS515x"]:
    rr = client.get(path)
    check(f"detail {path} loads", rr.status_code == 200, f"status={rr.status_code}")

# UI unchanged: sidebar/topbar/back-arrow intact
check("sidebar canonical", "AI Assistant" in h and "My Subjects" in h)
check("back arrow present", "Back to Dashboard" in h and 'class="back-link"' in h)
check("topbar intact", 'class="topbar"' in h and 'class="profile-menu"' in h
      and 'class="avatar"' in h)

print()
print(f"TOTAL: {sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)