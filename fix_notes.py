from app import app
from utils.database import db


with app.app_context():

    print()
    print("========================================")
    print("          CHECKING USERS TABLE")
    print("========================================")
    print()

    columns = db.session.execute(
        db.text("""
            SELECT
                column_name,
                data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'users'
            ORDER BY ordinal_position
        """)
    ).fetchall()

    if not columns:
        print("ERROR: users table was not found.")
    else:

        print("Users table columns:")
        print()

        for column_name, data_type in columns:
            print(
                f"  ✓ {column_name} ({data_type})"
            )

        print()

        print("Existing users:")

        users = db.session.execute(
            db.text("""
                SELECT *
                FROM public.users
                ORDER BY id
            """)
        ).mappings().fetchall()

        if not users:
            print("  No users found.")
        else:

            for user in users:
                print()
                for key, value in user.items():

                    # Don't print the actual password hash
                    if "password" in key.lower():
                        print(
                            f"  {key}: [HIDDEN]"
                        )
                    else:
                        print(
                            f"  {key}: {value}"
                        )

    print()
    print("========================================")
    print("          CHECK COMPLETE")
    print("========================================")
    print()