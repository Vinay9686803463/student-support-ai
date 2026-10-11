"""Remove duplicate BCS405A module-0 rows (any ids, not hardcoded).

A concurrent process keeps re-inserting module-0 ('Additional Resources')
duplicates of the same filenames. A row is deleted only if another BCS405A
row with the same filename, module_number=1, and byte-identical file
exists. Idempotent: safe to re-run any time.
Run: venv\\Scripts\\python.exe fix_bcs405a_dupes.py
"""

import hashlib
import pathlib
from app import app
from sqlalchemy import text

from utils.database import db

BASE = pathlib.Path(__file__).resolve().parent

with app.app_context():
    dupes = db.session.execute(
        text("SELECT id, original_filename, file_path FROM knowledge_documents "
             "WHERE subject_code = 'BCS405A' AND module_number = 0 ORDER BY id")
    ).fetchall()
    print(f"module-0 rows found: {len(dupes)}")
    for doc_id, filename, fpath in dupes:
        keeper = db.session.execute(
            text("SELECT id, file_path FROM knowledge_documents "
                 "WHERE subject_code = 'BCS405A' AND module_number = 1 "
                 "AND original_filename = :f AND id != :i"),
            {"f": filename, "i": doc_id},
        ).first()
        assert keeper is not None, f"id={doc_id} has no module-1 twin. Aborting."
        a = (BASE / fpath).read_bytes()
        b = (BASE / keeper[1]).read_bytes()
        assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest(), \
            f"id={doc_id} bytes differ from keeper {keeper[0]}. Aborting."
        db.session.execute(text("DELETE FROM knowledge_documents WHERE id = :i"),
                           {"i": doc_id})
        print(f"  deleted duplicate id={doc_id} {filename!r} (keeper id={keeper[0]})")

    left = db.session.execute(
        text("SELECT COUNT(*) FROM knowledge_documents "
             "WHERE subject_code = 'BCS405A' AND module_number = 0")
    ).scalar()
    assert left == 0, f"{left} module-0 rows remain. Aborting."
    n = db.session.execute(
        text("SELECT COUNT(*) FROM knowledge_documents WHERE subject_code = 'BCS405A'")
    ).scalar()
    assert n == 5, f"expected 5 BCS405A docs, found {n}. Aborting."
    db.session.commit()
    print("COMMITTED. BCS405A has exactly its 5 Study Material rows.")
