"""Verify BCS502 PDF display, PDF route, sidebars, and page health."""
from app import app
from utils.database import db
from sqlalchemy import text

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name} {detail}")


with app.app_context():
    n = db.session.execute(
        text("SELECT COUNT(*) FROM knowledge_documents WHERE subject_code='BCS502'")
    ).scalar()
    check("no duplicate BCS502 docs (expect 5)", n == 5, f"count={n}")

client = app.test_client()

# Log in as user 1
with client.session_transaction() as sess:
    sess["user_id"] = 1
    sess["user_name"] = "Test"

# 1. Subject detail BCS502
r = client.get("/subjects/BCS502")
check("GET /subjects/BCS502 = 200", r.status_code == 200, f"status={r.status_code}")
html = r.get_data(as_text=True)
for m in ["Module 1", "Module 2", "Module 3", "Module 4", "Module 5"]:
    check(f"BCS502 page shows {m}", m in html)
for f in ["BCS502 Module 1.pdf", "BCS502 Module 2.pdf", "BCS502 Module 4.pdf",
          "BCS502 Module 5.pdf", "BCS502 Module 3.pdf"]:
    check(f"BCS502 page shows {f}", f in html)
check("BCS502 page has View PDF buttons", "View PDF" in html)
check("BCS502 page links /knowledge/pdf/", "/knowledge/pdf/" in html)
check("View PDF opens new tab", 'target="_blank"' in html and 'rel="noopener"' in html)

# 2. PDF route
r = client.get("/knowledge/pdf/1")
check("GET /knowledge/pdf/1 = 200 pdf",
      r.status_code == 200 and r.content_type == "application/pdf",
      f"status={r.status_code} type={r.content_type} bytes={len(r.data)}")
r = client.get("/knowledge/pdf/999999")
check("GET /knowledge/pdf/999999 = 404", r.status_code == 404,
      f"status={r.status_code}")

# 3. Other subject still works (generic, not hardcoded)
r = client.get("/subjects/BCS501")
check("GET /subjects/BCS501 = 200", r.status_code == 200, f"status={r.status_code}")

# 4. Sidebar on subjects page matches canonical
r = client.get("/subjects")
shtml = r.get_data(as_text=True)
check("GET /subjects = 200", r.status_code == 200, f"status={r.status_code}")
nav_start = shtml.find("<nav>")
nav_end = shtml.find("</nav>")
nav = shtml[nav_start:nav_end] if nav_start >= 0 and nav_end > nav_start else ""
check("subjects sidebar: AI Assistant label", "AI Assistant" in nav)
check("subjects sidebar: no 'Ask AI' label", "Ask AI" not in nav)
check("subjects sidebar: My Subjects active",
      'href="/subjects" class="nav-link active"' in nav)
order = ["Dashboard", "AI Assistant", "My Subjects", "My Notes",
         "Important Questions", "Resources"]
positions = [nav.find(x) for x in order]
check("subjects sidebar: correct item order",
      all(p >= 0 for p in positions) and positions == sorted(positions),
      f"positions={positions}")
check("subjects sidebar: Settings+Logout present",
      "Settings" in shtml and "Logout" in shtml)

# 5. All main pages healthy
for path in ["/dashboard", "/chat", "/subjects", "/notes", "/questions",
             "/resources", "/settings"]:
    rr = client.get(path)
    check(f"GET {path} = 200", rr.status_code == 200, f"status={rr.status_code}")

# 6. Unauthenticated PDF access redirects to login
client2 = app.test_client()
r = client2.get("/knowledge/pdf/1", follow_redirects=False)
check("unauth PDF redirects to login",
      r.status_code in (301, 302) and "/login" in (r.headers.get("Location") or ""),
      f"status={r.status_code}")

# 7. Back navigation on every major page
backs = {
    "/subjects/BCS501": ("subjects", "Back to My Subjects"),
    "/subjects/BCS502": ("subjects", "Back to My Subjects"),
    "/subjects": ("dashboard", "Back to Dashboard"),
    "/notes": ("dashboard", "Back to Dashboard"),
    "/questions": ("dashboard", "Back to Dashboard"),
    "/resources": ("dashboard", "Back to Dashboard"),
    "/settings": ("dashboard", "Back to Dashboard"),
    "/chat": ("dashboard", "Back to Dashboard"),
}
for path, (route, label) in backs.items():
    rr = client.get(path)
    h = rr.get_data(as_text=True)
    href = f'href="/{route}"'
    has_link = label in h and 'class="back-link"' in h and href in h
    check(f"back arrow {path} -> /{route}", rr.status_code == 200 and has_link,
          f"status={rr.status_code}")

# 8. Subject detail topbar matches dashboard pattern
r = client.get("/subjects/BCS501")
h = r.get_data(as_text=True)
check("subject topbar: no in-topbar back link", "back-subject-link" not in h)
check("subject topbar: no topbar-user block", "topbar-user" not in h)
check("subject topbar: dashboard profile block", 'class="profile"' in h)
check("subject topbar: small-title present", "small-title" in h)
ti = h.find("<header class=\"topbar\">")
bi = h.find("back-nav-row")
hi = h.find("subject-detail-hero")
check("subject order: topbar -> back -> hero",
      0 <= ti < bi < hi, f"topbar={ti} back={bi} hero={hi}")

# 9. Back arrow round-trip: BCS501 -> My Subjects
r = client.get("/subjects/BCS501")
check("BCS501 back href points at /subjects",
      'href="/subjects"' in r.get_data(as_text=True))
r = client.get("/subjects")
check("round-trip lands on My Subjects",
      r.status_code == 200 and "Your semester subjects" in r.get_data(as_text=True))

failed = [n for n, ok, _ in results if not ok]
print()
print(f"TOTAL: {len(results) - len(failed)}/{len(results)} passed")
if failed:
    print("FAILED:", failed)
    raise SystemExit(1)