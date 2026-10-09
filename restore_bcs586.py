"""Re-insert the BCS586 Mini Project subject row (collateral deletion).
Its detail page reads MINI_PROJECTS docs dynamically; no knowledge touched."""
from app import app
from utils.database import db

with app.app_context():
    with db.engine.connect() as conn:
        row = conn.execute(
            db.text("SELECT id FROM subjects WHERE subject_code='BCS586'")
        ).first()
        if row:
            print(f"BCS586 already present id={row[0]}")
        else:
            conn.execute(
                db.text("""
                    INSERT INTO subjects
                        (subject_code, subject_name, semester, branch, scheme,
                         credits, icon, category)
                    VALUES ('BCS586', 'Mini Project', 5, 'CSE', '2022', 4, '📚', NULL)
                """)
            )
            conn.commit()
            print("BCS586 re-inserted")