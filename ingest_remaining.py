"""Copy + ingest remaining subjects with the existing pipeline.
Idempotent: process_pdf skips PDFs already registered (subject_code,
module_number, original_filename). WebTech single doc pre-checked by
original_filename."""
import os
import shutil
from pathlib import Path

from utils.knowledge_ingest import process_pdf

PROJECT_ROOT = Path(__file__).resolve().parent
downloads = Path(os.path.expandvars("%USERPROFILE%")) / "Downloads"
if not downloads.is_dir():
    downloads = Path.home() / "Downloads"

JOBS = [
    # (subject_code, subject_name, module_number, filename, dest_subdir, module_title)
    ("BCS503", "Theory of Computation", 1, "BCS503 Mod1@azdocuments.in.pdf", "module1", "Module 1"),
    ("BCS503", "Theory of Computation", 2, "BCS503 Mod2@azdocuments.in.pdf", "module2", "Module 2"),
    ("BCS503", "Theory of Computation", 3, "BCS503 Mod3@azdocuments.in.pdf", "module3", "Module 3"),
    ("BCS503", "Theory of Computation", 4, "BCS503 Mod4@azdocuments.in.pdf", "module4", "Module 4"),
    ("BCS503", "Theory of Computation", 5, "BCS503 Mod5@azdocuments.in.pdf", "module5", "Module 5"),
    ("BCS504", "Unix System Programming", 1, "Unix Module 1.pdf", "module1", "Module 1"),
    ("BCS504", "Unix System Programming", 3, "Unix Module 3.pdf", "module3", "Module 3"),
    ("BCS504", "Unix System Programming", 4, "Unix Module 4.pdf", "module4", "Module 4"),
    ("BCS504", "Unix System Programming", 5, "Unix Module 5.pdf", "module5", "Module 5"),
    ("BCS515", "Environmental Studies and E-waste", 1, "M1.pdf", "module1", "Module 1"),
    ("BCS515", "Environmental Studies and E-waste", 2, "M2.pdf", "module2", "Module 2"),
    ("BCS515", "Environmental Studies and E-waste", 3, "M3.pdf", "module3", "Module 3"),
    ("BCS515", "Environmental Studies and E-waste", 4, "M4.pdf", "module4", "Module 4"),
    ("BCS515", "Environmental Studies and E-waste", 5, "M5.pdf", "module5", "Module 5"),
]

print(f"Downloads: {downloads}")
results = []
for code, name, mod, filename, subdir, mod_title in JOBS:
    print(f"--- {code} module {mod}: {filename}")
    src = downloads / filename
    if not src.is_file():
        print("    [MISSING SOURCE]")
        results.append((code, mod, "missing-source"))
        continue
    dest_dir = PROJECT_ROOT / "knowledge_base" / code / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    if not dest.is_file():
        shutil.copy2(src, dest)
        print(f"    [COPIED] {dest}")
    else:
        print("    [EXISTS in knowledge base]")
    try:
        doc_id = process_pdf(
            pdf_path=dest, subject_code=code, subject_name=name,
            module_number=mod, module_title=mod_title, source="local-downloads",
        )
        print(f"    [REGISTERED] id={doc_id}")
        results.append((code, mod, f"document-{doc_id}"))
    except Exception as error:
        print(f"    [ERROR] {error}")
        results.append((code, mod, f"error: {error}"))

# NOTE: BCS504 module 2 (Unix Module 2.pdf) was not found anywhere.
print()
print("SUMMARY")
for code, mod, status in results:
    print(f"  {code} module {mod}: {status}")
