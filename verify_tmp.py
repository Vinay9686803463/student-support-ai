import hashlib
import html
import pathlib
import re
from app import app
from jinja2 import Environment, FileSystemLoader

Environment(loader=FileSystemLoader("templates")).get_template("subject_detail.html")
print("TEMPLATE PARSE: OK")

client = app.test_client()
with client.session_transaction() as sess:
    sess["user_id"] = 1

results = []
def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}", flush=True)

h = html.unescape(client.get("/subjects/BCS401").get_data(as_text=True))
check("200, no error", "Something went wrong" not in h)
study = h.split("Study Material</h2>")[1].split("QUICK ACTIONS")[0]
order = [m.group(1) for m in re.finditer(r"Module\s+([1-5])\s*</h3>", study)]
check("Modules 1-5 in order, no placeholder", order == ["1", "2", "3", "4", "5"]
      and "No PDF uploaded yet." not in study, str(order))
check("Module 1 shows exact filename", "BCS401-module-1-written.pdf" in study)

m = re.search(r"Module\s+1\s*</h3>.*?/knowledge/pdf/(\d+)", study, re.DOTALL)
check("Module 1 button present", m is not None)
if m:
    r = client.get(f"/knowledge/pdf/{m.group(1)}")
    body = r.data
    src = pathlib.Path(r"C:\Users\vinay\Downloads\BCS401-module-1-writtten.pdf").read_bytes()
    check("Module 1 serves the actual PDF (byte-identical to source)",
          r.status_code == 200 and r.content_type == "application/pdf"
          and hashlib.sha256(body).hexdigest() == hashlib.sha256(src).hexdigest(),
          f"{r.status_code} {len(body)} bytes")

links = sorted(set(re.findall(r"/knowledge/pdf/(\d+)", h)), key=int)
check("24 total PDF buttons", len(links) == 24, str(links))
for code in ["BCS402", "BCS403"]:
    hx = client.get(f"/subjects/{code}").get_data(as_text=True)
    check(f"{code} intact", "Something went wrong" not in hx)

print()
print(f"TOTAL: {sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
