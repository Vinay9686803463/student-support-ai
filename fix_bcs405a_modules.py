"""Move BCS405A files from Additional Resources into Study Material.

The 5 DMS PDFs were registered under module_number=0 (Additional
Resources). This subject must show them directly under Study Material as
unnumbered file cards instead. Guarded: only ids 341-345, only if they
are still module 0 for BCS405A. No other rows touched.
Run: venv\\Scripts\\python.exe fix_bcs405a_modules.py (idempotent)
"""

from app import app
from sqlalchemy import text

from utils.database import db

IDS = [341, 342, 343, 344, 345]

with app.app_context():
    for doc_id in IDS:
        found = db.session.execute(
            text("SELECT subject_code, module_number, original_filename "
                 "FROM knowledge_documents WHERE id = :i"),
            {"i": doc_id},
        ).first()
        assert found is not None, f"doc id={doc_id} missing!"
        assert found[0] == "BCS405A", f"doc id={doc_id} is {found[0]}. Aborting."
        if found[1] != 0:
            print(f"  id={doc_id} already module {found[1]}, skipping")
            continue
        db.session.execute(
            text("UPDATE knowledge_documents SET module_number = 1, "
                 "module_title = 'Study Material' WHERE id = :i"),
            {"i": doc_id},
        )
        print(f"  id={doc_id} {found[2]!r} module 0 -> 1")

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
    print("COMMITTED. All 5 BCS405A files are Study Material now.")
