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
    print("          USERS TABLE FIXED")
    print("========================================")
    print()