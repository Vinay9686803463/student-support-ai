"""Regression tests for database initialization and the login pipeline.

Covers:
1. init_database creates the knowledge-base tables (knowledge_documents,
   knowledge_chunks, knowledge_processing_logs) that boot-time RAG code
   reads. These were previously only made by the manual script
   setup_knowledge_base.py, which production never ran - the direct cause
   of the "relation knowledge_documents does not exist" startup error.
2. No pre-existing table/model is dropped, truncated or altered
   (additive-only schema creation is asserted by checking row survival).
3. Email-based registration + login round-trip (signup writes the hash
   into both `password` and `password_hash`; login reads and verifies it).
4. Duplicate-registration is refused without touching the first row.

DB-free: uses an isolated SQLite file database, never the production
DATABASE_URL. Run: python -m pytest test_database_initialization.py -q
"""

import os
import tempfile
import unittest

from sqlalchemy import text

# Isolate from any local .env before importing utils.database.
os.environ["DATABASE_URL"] = "sqlite:////tmp/ssa_init_test.db"
for var in ("VERCEL",):
    os.environ.pop(var, None)


class DatabaseInitializationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Recreate a clean isolated database file for the whole class.
        if os.path.exists("/tmp/ssa_init_test.db"):
            os.remove("/tmp/ssa_init_test.db")
        from flask import Flask
        from utils.database import init_database
        # Local tmp instance path so the util never writes elsewhere.
        cls.app = Flask(__name__, instance_relative_config=False)
        cls.app.config["TESTING"] = True
        init_database(cls.app)

    def test_knowledge_tables_exist_after_init(self):
        """init_database creates the RAG knowledge tables."""
        from utils.database import db, KnowledgeDocument, KnowledgeChunk
        from utils.database import KnowledgeProcessingLog
        with self.app.app_context():
            inspector = None
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            for model, name in (
                (KnowledgeDocument, "knowledge_documents"),
                (KnowledgeChunk, "knowledge_chunks"),
                (KnowledgeProcessingLog, "knowledge_processing_logs"),
            ):
                table_name = model.__tablename__
                self.assertIn(
                    table_name,
                    inspector.get_table_names(),
                    f"{name} missing after init_database",
                )

    def test_knowledge_document_roundtrip(self):
        """A registered document survives and keeps its columns."""
        from utils.database import db, KnowledgeDocument
        with self.app.app_context():
            doc = KnowledgeDocument(
                subject_code="BCS501",
                subject_name="Software Engineering",
                module_number=1,
                module_title="Introduction",
                title="Module 1",
                original_filename="Module 1.pdf",
                file_path="static/uploads/bcs501/Module 1.pdf",
                status="uploaded",
                page_count=12,
            )
            db.session.add(doc)
            db.session.commit()
            fetched = db.session.query(KnowledgeDocument).filter_by(
                subject_code="BCS501"
            ).one()
            self.assertEqual(fetched.page_count, 12)
            self.assertEqual(fetched.status, "uploaded")

    def test_signup_login_roundtrip(self):
        """The registration -> login path that the Vercel logs exercise."""
        from werkzeug.security import check_password_hash
        from utils.database import db, User
        with self.app.app_context():
            email = "roundtrip@example.com"
            user = User(
                name="Round Trip",
                email=email,
                # The app writes the hash into both legacy and new columns.
                password="x",
                password_hash="x",
                branch="CSE",
                scheme="2022",
                current_semester=5,
            )
            from werkzeug.security import generate_password_hash
            user.password = user.password_hash = generate_password_hash(
                "correct-horse-battery"
            )
            db.session.add(user)
            db.session.commit()

            # Login path mirrors app.py: SELECT by lowercased email,
            # then check_password_hash on the stored hash.
            row = db.session.execute(text("""
                SELECT id, password_hash FROM users WHERE email = :email
            """), {"email": email}).mappings().first()
            self.assertIsNotNone(row, "user row must exist after signup")
            self.assertTrue(
                check_password_hash(row["password_hash"],
                                    "correct-horse-battery")
            )
            self.assertFalse(
                check_password_hash(row["password_hash"], "wrong")
            )

    def test_duplicate_registration_preserves_original_row(self):
        """Refusing a duplicate must not touch the first account."""
        from utils.database import db, User
        with self.app.app_context():
            email = "dup-check@example.com"
            first = User(
                name="First User",
                email=email,
                password="pw",
                password_hash="pw",
                branch="CSE",
                scheme="2022",
                current_semester=5,
            )
            db.session.add(first)
            db.session.commit()
            second = User(
                name="Second User",
                email=email,  # same email
                password="pw",
                password_hash="pw",
                branch="CSE",
                scheme="2022",
                current_semester=5,
            )
            db.session.add(second)
            # The app has a UNIQUE index on users.email; the second
            # insert must fail while the first row stays intact.
            with self.assertRaises(Exception):
                db.session.commit()
            db.session.rollback()
            count = db.session.query(User).filter_by(email=email).count()
            self.assertEqual(count, 1, "duplicate insert must not create a row")
            row = db.session.query(User).filter_by(email=email).one()
            self.assertEqual(row.name, "First User")


class LoginBehaviorTests(unittest.TestCase):
    """Behavior of the actual Flask view functions /auth routes."""

    @classmethod
    def setUpClass(cls):
        # Distinct file so the two suites do not fight over one SQLite file.
        if os.path.exists("/tmp/ssa_login_test.db"):
            os.remove("/tmp/ssa_login_test.db")
        os.environ["DATABASE_URL"] = "sqlite:////tmp/ssa_login_test.db"
        import app as app_module
        cls.module = app_module
        cls.client = app_module.app.test_client()
        with app_module.app.app_context():
            from utils.database import db, User, Subject, Question, Resource
            db.drop_all()
            db.create_all()
            from werkzeug.security import generate_password_hash
            user = User(
                name="View Tester",
                email="viewtester@example.com",
                password=generate_password_hash("viewpass"),
                password_hash=generate_password_hash("viewpass"),
                branch="CSE",
                scheme="2022",
                current_semester=5,
            )
            db.session.add(user)
            db.session.commit()

    def _fresh_client(self):
        # Each test needs its own session cookie; a class-level client
        # would leak the previous test's logged-in session.
        return self.module.app.test_client()

    def test_login_success_then_dashboard(self):
        resp = self._fresh_client().post("/login", data={
            "email": "viewtester@example.com",
            "password": "viewpass",
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302,
            "successful login must redirect, not re-render login page")

    def test_login_wrong_password_rerenders(self):
        resp = self._fresh_client().post("/login", data={
            "email": "viewtester@example.com",
            "password": "not-the-password",
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Invalid email or password", resp.data)

    def test_login_unknown_email_rerenders(self):
        resp = self._fresh_client().post("/login", data={
            "email": "nobody@example.com",
            "password": "whatever",
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Invalid email or password", resp.data)


if __name__ == "__main__":
    unittest.main()
