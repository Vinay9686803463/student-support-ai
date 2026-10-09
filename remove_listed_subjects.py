"""Delete the 11 user-rejected elective seed rows (verified unreferenced:
no questions, units, resources, or knowledge documents)."""
from app import app
from utils.database import db

CODES = ["BCSL358D", "BCSL358C", "BCSL358B", "BCS358x", "BCS306A",
         "BCS456C", "BCS456B", "BCS456A", "BCS405D", "BCS405C", "BCS405B"]

with app.app_context():
    for code in CODES:
        with db.engine.connect() as conn:
            row = conn.execute(
                db.text("SELECT id, semester FROM subjects WHERE subject_code=:c"),
                {"c": code},
            ).first()
            if not row:
                print(f"absent {code}")
                continue
            for table, col in (("questions", "subject_id"), ("units", "subject_id"),
                               ("resources", "subject_id")):
                n = conn.execute(
                    db.text(f"SELECT COUNT(*) FROM {table} WHERE {col}=:i"),
                    {"i": row[0]},
                ).scalar()
                assert n == 0, f"{code} referenced by {table}"
            k = conn.execute(
                db.text("SELECT COUNT(*) FROM knowledge_documents WHERE subject_code=:c"),
                {"c": code},
            ).scalar()
            assert k == 0, f"{code} has knowledge docs"
            conn.execute(db.text("DELETE FROM subjects WHERE id=:i"), {"i": row[0]})
            conn.commit()
            print(f"deleted {code} (was sem {row[1]})")
print("DONE")