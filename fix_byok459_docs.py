"""Re-register the 3 missing BYOK459 Study Material rows (guarded).

Row id=323 (23.69.docx, module 1) survived; ids 324-326 were deleted by an
outside process. This re-adds exactly the missing filenames — no duplicate
subject, no duplicate rows (an existing filename row is never re-inserted).
Each file is byte-verified against Downloads before registration.
Run: venv\\Scripts\\python.exe fix_byok459_docs.py (idempotent)
"""

import hashlib
import pathlib
from app import app
from sqlalchemy import text

from utils.database import db

BASE = pathlib.Path(__file__).resolve().parent
DOWNLOADS = pathlib.Path(r"C:\Users\vinay\Downloads")

# (filename, module_number) — original mapping; 23.69.docx already present.
NEEDED = [
    ("ACKNOWLEDGEMENT of yoga.docx", 2),
    ("Certificate yoga.docx", 3),
    ("CONTENTS.docx", 4),
]

with app.app_context():
    subj = db.session.execute(
        text("SELECT id, semester FROM subjects WHERE subject_code = 'BYOK459'")
    ).first()
    assert subj is not None and subj[1] == 4, f"BYOK459 unexpected: {subj}. Aborting."
    print(f"subject OK: id={subj[0]} sem=4 (no duplicate created)")

    for filename, mod in NEEDED:
        src = DOWNLOADS / filename
        assert src.is_file(), f"missing in Downloads: {filename}. Aborting."
        digest = hashlib.sha256(src.read_bytes()).hexdigest()

        have = db.session.execute(
            text("SELECT id, module_number, file_path FROM knowledge_documents "
                 "WHERE subject_code = 'BYOK459' AND original_filename = :f"),
            {"f": filename},
        ).first()
        if have:
            disk = BASE / have[2]
            assert disk.is_file() and hashlib.sha256(disk.read_bytes()).hexdigest() == digest, \
                f"existing row id={have[0]} content mismatch. Aborting."
            print(f"  row id={have[0]} {filename!r} already registered, skipping")
            continue

        dest = BASE / "knowledge_base" / "BYOK459" / filename
        if dest.is_file():
            assert hashlib.sha256(dest.read_bytes()).hexdigest() == digest, \
                f"disk copy of {filename!r} differs from Downloads. Aborting."
            print(f"  disk copy verified: {filename!r}")
        else:
            import shutil
            shutil.copy2(src, dest)
            print(f"  copied: {filename!r}")

        with open(dest, "rb") as fh:
            assert fh.read(4) == b"PK\x03\x04", f"{filename!r} is not a DOCX. Aborting."
        rel = dest.relative_to(BASE).as_posix()
        new_id = db.session.execute(
            text("INSERT INTO knowledge_documents (subject_code, subject_name, module_number, "
                 "module_title, title, original_filename, file_path, page_count, status) "
                 "VALUES ('BYOK459', 'Yoga', :m, 'Study Material', :t, :f, :p, 0, 'uploaded') "
                 "RETURNING id"),
            {"m": mod, "t": pathlib.Path(filename).stem, "f": filename, "p": rel},
        ).scalar()
        print(f"  registered id={new_id} {filename!r} -> module {mod}")

    rows = db.session.execute(
        text("SELECT original_filename FROM knowledge_documents "
             "WHERE subject_code = 'BYOK459' ORDER BY module_number")
    ).fetchall()
    assert [r[0] for r in rows] == ["23.69.docx", "ACKNOWLEDGEMENT of yoga.docx",
                                    "Certificate yoga.docx", "CONTENTS.docx"], rows
    db.session.commit()
    print("COMMITTED. BYOK459 has exactly its 4 Study Material files.")
