"""Copy + ingest BRMK557 (Research Methodology and IPR) modules 1-5
with the existing pipeline. Idempotent via process_pdf's guard."""
import os
import shutil
from pathlib import Path

from utils.knowledge_ingest import process_pdf

PROJECT_ROOT = Path(__file__).resolve().parent
downloads = Path(os.path.expandvars("%USERPROFILE%")) / "Downloads"
if not downloads.is_dir():
    downloads = Path.home() / "Downloads"

CODE = "BRMK557"
NAME = "Research Methodology and IPR"

for mod in (1, 2, 3, 4, 5):
    filename = f"BRMK557-module-{mod}-pdf.pdf"
    print(f"--- {CODE} module {mod}: {filename}")
    src = downloads / filename
    if not src.is_file():
        print("    [MISSING SOURCE]")
        continue
    dest_dir = PROJECT_ROOT / "knowledge_base" / CODE / f"module{mod}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    if not dest.is_file():
        shutil.copy2(src, dest)
        print(f"    [COPIED] {dest}")
    else:
        print("    [EXISTS in knowledge base]")
    try:
        doc_id = process_pdf(
            pdf_path=dest, subject_code=CODE, subject_name=NAME,
            module_number=mod, module_title=f"Module {mod}",
            source="local-downloads",
        )
        print(f"    [REGISTERED] id={doc_id}")
    except Exception as error:
        print(f"    [ERROR] {error}")
print("DONE")