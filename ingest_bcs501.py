"""Copy SEPM PDFs into knowledge_base/BCS501 and ingest with the
existing utils.knowledge_ingest pipeline (idempotent: skips PDFs
already registered in knowledge_documents)."""
import os
import shutil
from pathlib import Path

from utils.knowledge_ingest import process_pdf

PROJECT_ROOT = Path(__file__).resolve().parent

# Resolve the Windows Downloads folder dynamically.
downloads = Path(os.path.expandvars("%USERPROFILE%")) / "Downloads"
if not downloads.is_dir():
    downloads = Path.home() / "Downloads"

SUBJECT_CODE = "BCS501"
SUBJECT_NAME = "Software Engineering & Project Management"

MODULES = {
    1: "SEPM Module 1.pdf",
    2: "SEPM Module 2.pdf",
    3: "SEPM Module 3.pdf",
    4: "SEPM Module 4.pdf",
    5: "SEPM Module 5.pdf",
}

print(f"Downloads folder: {downloads}")
print(f"Project knowledge base: {PROJECT_ROOT / 'knowledge_base'}")
print()

results = {}
for module_number in sorted(MODULES):
    filename = MODULES[module_number]
    print("=" * 60)
    print(f"Module {module_number}: {filename}")

    src = downloads / filename
    if not src.is_file():
        print(f"  [MISSING] not found in Downloads: {src}")
        results[module_number] = "missing-source"
        continue
    print(f"  [FOUND] {src} ({src.stat().st_size} bytes)")

    dest_dir = PROJECT_ROOT / "knowledge_base" / SUBJECT_CODE / f"module{module_number}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    if not dest.is_file():
        shutil.copy2(src, dest)
        print(f"  [COPIED] -> {dest}")
    else:
        print(f"  [EXISTS] already in knowledge base: {dest}")

    try:
        document_id = process_pdf(
            pdf_path=dest,
            subject_code=SUBJECT_CODE,
            subject_name=SUBJECT_NAME,
            module_number=module_number,
            module_title=f"Module {module_number}",
            source="local-downloads",
        )
        print(f"  [REGISTERED] document id={document_id}")
        results[module_number] = f"document-{document_id}"
    except Exception as error:
        print(f"  [ERROR] {error}")
        results[module_number] = f"error: {error}"

print()
print("=" * 60)
print("INGEST SUMMARY")
for module_number in sorted(MODULES):
    print(f"  Module {module_number}: {results[module_number]}")
print("=" * 60)