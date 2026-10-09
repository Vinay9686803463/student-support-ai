from app import app
from utils.database import db

with app.app_context():
    print("=== subjects table (all) ===")
    subs = db.session.execute(
        db.text("SELECT subject_code, subject_name FROM subjects ORDER BY subject_code")
    ).fetchall()
    for s in subs:
        print(f"  {s.subject_code}: {s.subject_name}")

    print()
    print("=== knowledge_documents for BCS503/BCS504/BCS515 ===")
    rows = db.session.execute(
        db.text("""
            SELECT id, subject_code, subject_name, module_number, module_title,
                   title, original_filename, file_path, page_count, status
            FROM knowledge_documents
            WHERE subject_code IN ('BCS503','BCS504','BCS515')
            ORDER BY subject_code, module_number, id
        """)
    ).fetchall()
    print(f"count={len(rows)}")
    for r in rows:
        print(f"  id={r.id} {r.subject_code} mod={r.module_number} "
              f"orig={r.original_filename!r} pages={r.page_count} status={r.status}")

    print()
    print("=== Web Technology search ===")
    w = db.session.execute(
        db.text("""
            SELECT id, subject_code, subject_name, module_number, title,
                   original_filename, file_path, page_count, status
            FROM knowledge_documents
            WHERE subject_name ILIKE '%Web Technology%'
               OR original_filename = 'Web Technology Programs.pdf'
            ORDER BY id
        """)
    ).fetchall()
    print(f"count={len(w)}")
    for r in w:
        print(f"  id={r.id} {r.subject_code} mod={r.module_number} "
              f"orig={r.original_filename!r} status={r.status}")