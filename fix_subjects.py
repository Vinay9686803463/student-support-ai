from app import app
from utils.database import db


with app.app_context():

    print()
    print("========================================")
    print("          FIXING USERS TABLE")
    print("========================================")
    print()

    columns = db.session.execute(
        db.text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'users'
            ORDER BY ordinal_position
        """)
    ).fetchall()

    existing_columns = {
        row[0]
        for row in columns
    }

    print("Current columns:")

    for column in existing_columns:
        print("  ✓", column)

    print()

    if "password_hash" not in existing_columns:

        print("Adding password_hash column...")

        db.session.execute(
            db.text("""
                ALTER TABLE public.users
                ADD COLUMN password_hash VARCHAR(255)
            """)
        )

        db.session.commit()

        print("✓ password_hash column added.")

    else:

        print("✓ password_hash already exists.")

    print()

    if "password" in existing_columns:

        print("Migrating existing password...")

        db.session.execute(
            db.text("""
                UPDATE public.users
                SET password_hash = password
                WHERE password_hash IS NULL
                  AND password IS NOT NULL
            """)
        )

        db.session.commit()

        print("✓ Existing password migrated.")

    print()

    result = db.session.execute(
        db.text("""
            SELECT
                id,
                name,
                email,
                password_hash IS NOT NULL AS password_hash_exists
            FROM public.users
            ORDER BY id
        """)
    ).mappings().fetchall()

    print("Users after migration:")
    print()

    for user in result:
        print(
            f"ID: {user['id']} | "
            f"Name: {user['name']} | "
            f"Email: {user['email']}"
        )

        print(
            f"  password_hash exists: "
            f"{user['password_hash_exists']}"
        )

        print()

    print("========================================")
    print("    FIXING NOTES AND SUBJECTS TABLES")
    print("========================================")
    print()

    subject_columns = {
        row[0]
        for row in db.session.execute(
            db.text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'subjects'
            """)
        ).fetchall()
    }

    required_subject_columns = {
        "credits": """
            ALTER TABLE public.subjects
            ADD COLUMN credits INTEGER NOT NULL DEFAULT 4
        """,
        "icon": """
            ALTER TABLE public.subjects
            ADD COLUMN icon VARCHAR(50) NOT NULL DEFAULT '📚'
        """,
        "description": """
            ALTER TABLE public.subjects
            ADD COLUMN description TEXT
        """
    }

    for column_name, statement in required_subject_columns.items():
        if column_name not in subject_columns:
            db.session.execute(db.text(statement))
            print(f"Added subjects.{column_name}.")
        else:
            print(f"subjects.{column_name} already exists.")

    note_columns = {
        row[0]
        for row in db.session.execute(
            db.text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'notes'
            """)
        ).fetchall()
    }

    if "subject" not in note_columns:
        if "subject_id" not in note_columns:
            raise RuntimeError(
                "The notes table has neither subject nor subject_id; "
                "cannot safely migrate notes."
            )

        db.session.execute(
            db.text("""
                ALTER TABLE public.notes
                ADD COLUMN subject VARCHAR(100)
            """)
        )

        db.session.execute(
            db.text("""
                UPDATE public.notes AS note
                SET subject = LEFT(
                    COALESCE(
                        (
                            SELECT subject.subject_name
                            FROM public.subjects AS subject
                            WHERE subject.id::text = note.subject_id::text
                        ),
                        note.subject_id::text,
                        'General'
                    ),
                    100
                )
                WHERE note.subject IS NULL
            """)
        )

        db.session.execute(
            db.text("""
                ALTER TABLE public.notes
                ALTER COLUMN subject SET NOT NULL
            """)
        )

        print("Added and populated notes.subject from subject_id.")
    else:
        print("notes.subject already exists.")

    db.session.commit()

    print("========================================")
    print("          DATABASE TABLES FIXED")
    print("========================================")
    print()