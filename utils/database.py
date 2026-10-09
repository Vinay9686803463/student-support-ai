import os

from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
from flask_sqlalchemy import SQLAlchemy  # pyright: ignore[reportMissingImports]
from sqlalchemy import inspect, text  # pyright: ignore[reportMissingImports]


load_dotenv()


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///student_support_ai.db")


# SQLAlchemy expects postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )


db = SQLAlchemy()


DATABASE_CONFIG = {
    "SQLALCHEMY_DATABASE_URI": DATABASE_URL,
    "SQLALCHEMY_TRACK_MODIFICATIONS": False,
}

# The deployed app uses PostgreSQL.  A local SQLite database keeps a fresh
# checkout usable without requiring a hosted database before the first run.
if DATABASE_URL.startswith("postgresql"):
    # Reuse connections across requests instead of opening a fresh
    # TCP+TLS+auth handshake per query (NullPool). pre_ping drops dead
    # connections and recycle refreshes idle ones, so hosted-DB restarts
    # and pooler idle timeouts stay safe. Same queries, same results.
    DATABASE_CONFIG["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "connect_args": {
            "connect_timeout": 10
        }
    }


# =========================================================
# USERS
# =========================================================

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(200),
        nullable=False
    )

    email = db.Column(
        db.String(200),
        unique=True,
        nullable=False,
        index=True
    )

    phone = db.Column(
        db.String(20),
        nullable=True
    )

    # Legacy plain/hash column (kept NOT NULL in existing DBs).
    # New code writes the hash into BOTH columns.
    password = db.Column(
        db.String(255),
        nullable=True
    )

    password_hash = db.Column(
        db.String(255),
        nullable=True
    )

    branch = db.Column(
        db.String(50),
        nullable=True,
        default="CSE"
    )

    scheme = db.Column(
        db.String(20),
        nullable=True,
        default="2022"
    )

    current_semester = db.Column(
        db.Integer,
        nullable=True,
        default=5
    )

    created_at = db.Column(
        db.DateTime,
        nullable=True,
        server_default=db.func.now()
    )


# =========================================================
# NOTES
# =========================================================

class Note(db.Model):
    __tablename__ = "notes"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        nullable=False,
        index=True
    )

    title = db.Column(
        db.String(200),
        nullable=False
    )

    subject_id = db.Column(
        db.Integer,
        nullable=True,
        index=True
    )

    subject = db.Column(
        db.String(100),
        nullable=True
    )

    content = db.Column(
        db.Text,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now()
    )

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now()
    )


# =========================================================
# SUBJECTS
# =========================================================

class Subject(db.Model):
    __tablename__ = "subjects"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    code = db.Column(
        "subject_code",
        db.String(50),
        unique=True,
        nullable=False,
        index=True
    )

    name = db.Column(
        "subject_name",
        db.String(200),
        nullable=False
    )

    branch = db.Column(
        db.String(50),
        nullable=False,
        default="CSE"
    )

    scheme = db.Column(
        db.String(20),
        nullable=False,
        default="2022"
    )

    semester = db.Column(
        db.Integer,
        nullable=False,
        default=5
    )

    credits = db.Column(
        db.Integer,
        nullable=False,
        default=4
    )

    icon = db.Column(
        db.String(50),
        nullable=False,
        default="📚"
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    # Subject grouping for the My Subjects list. NULL means a normal
    # core academic subject. Other values: 'Alternative' (stream/choice
    # dependent, shown under Selectable Alternatives), 'Elective'
    # (shown under Elective Options), 'Professional Elective' (shown
    # under Professional Elective), 'Activity' (mandatory/activity
    # courses, never shown as normal subject cards).
    category = db.Column(
        db.String(50),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now()
    )

    questions = db.relationship(
        "Question",
        backref="subject",
        lazy=True,
        cascade="all, delete-orphan"
    )

    resources = db.relationship(
        "Resource",
        backref="subject",
        lazy=True,
        cascade="all, delete-orphan"
    )


# =========================================================
# QUESTIONS
# =========================================================

class Question(db.Model):
    __tablename__ = "questions"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    subject_id = db.Column(
        db.Integer,
        db.ForeignKey("subjects.id"),
        nullable=False,
        index=True
    )

    question = db.Column(
        db.Text,
        nullable=False
    )

    unit = db.Column(
        db.String(50),
        nullable=True
    )

    marks = db.Column(
        db.Integer,
        nullable=True
    )

    difficulty = db.Column(
        db.String(30),
        nullable=True
    )

    answer = db.Column(
        db.Text,
        nullable=True
    )

    is_important = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now()
    )


# =========================================================
# RESOURCES
# =========================================================

class Resource(db.Model):
    __tablename__ = "resources"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    subject_id = db.Column(
        db.Integer,
        db.ForeignKey("subjects.id"),
        nullable=True,
        index=True
    )

    title = db.Column(
        db.String(200),
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    category = db.Column(
        db.String(100),
        nullable=False
    )

    resource_type = db.Column(
        db.String(50),
        nullable=False
    )

    url = db.Column(
        "resource_url",
        db.Text,
        nullable=True
    )

    is_featured = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now()
    )


# =========================================================
# AI CONVERSATIONS
# =========================================================

class Conversation(db.Model):
    __tablename__ = "conversations"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        nullable=False,
        index=True
    )

    title = db.Column(
        db.String(200),
        nullable=False,
        default="New Conversation"
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now()
    )

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now()
    )

    messages = db.relationship(
        "Message",
        backref="conversation",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="Message.created_at"
    )


# =========================================================
# AI MESSAGES
# =========================================================

class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(
        db.Integer,
            primary_key=True
    )

    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversations.id"),
        nullable=False,
        index=True
    )

    role = db.Column(
        db.String(30),
        nullable=False
    )

    content = db.Column(
        db.Text,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now()
    )


# =========================================================
# USER PREFERENCES
# =========================================================

class UserPreference(db.Model):
    __tablename__ = "user_preferences"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        unique=True,
        nullable=False,
        index=True
    )

    study_reminders = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    ai_suggestions = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    dark_mode = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now()
    )

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now()
    )


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def _migrate_legacy_schema():
    """Add fields introduced after the first hosted database was created.

    ``create_all`` only creates missing tables; it intentionally does not
    alter existing ones.  These additive migrations make older databases
    compatible with the current models without changing or deleting data.
    """
    required_columns = {
        "users": {
            "phone": "VARCHAR(20)",
        },
        "subjects": {
            "credits": "INTEGER NOT NULL DEFAULT 4",
            "icon": "VARCHAR(50) NOT NULL DEFAULT '📚'",
            "description": "TEXT",
            "category": "VARCHAR(50)",
        },
        "resources": {
            "category": "VARCHAR(100) NOT NULL DEFAULT 'General'",
            "is_featured": "BOOLEAN NOT NULL DEFAULT FALSE",
        },
    }

    try:
        inspector = inspect(db.engine)
        with db.engine.begin() as connection:
            for table_name, columns in required_columns.items():
                existing_columns = {
                    column["name"]
                    for column in inspector.get_columns(table_name)
                }
                for column_name, definition in columns.items():
                    if column_name not in existing_columns:
                        connection.execute(
                            text(
                                f"ALTER TABLE {table_name} "
                                f"ADD COLUMN {column_name} {definition}"
                            )
                        )
                        print(f"  + {table_name}.{column_name} column added.")
    except Exception as error:
        # Never crash the app over a migration hiccup (e.g. a readonly
        # replica or a transient network blip). The raw-SQL fallbacks in
        # app.py keep every page working; the error is logged instead.
        print(f"  ! schema migration skipped: {error}")


def init_database(app):
    app.config.update(DATABASE_CONFIG)

    db.init_app(app)

    try:
        with app.app_context():
            db.create_all()
            _migrate_legacy_schema()
    except Exception as error:
        # The database may be temporarily unreachable (network/VPN).
        # Start anyway so /database-test can report the problem and the
        # app can serve friendly error pages instead of crashing on boot.
        print("=" * 60)
        print("  WARNING: database unreachable at startup.")
        print(f"  {error}")
        print("  The app will start; pages needing data will show an")
        print("  error page until the database is reachable again.")
        print("=" * 60)
