from app import app
from utils.database import db


with app.app_context():

    print()
    print("========================================")
    print("          USERS TABLE CHECK")
    print("========================================")
    print()

    # Check users table
    table = db.session.execute(
        db.text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'users'
            )
        """)
    ).scalar()

    print("Users table exists:", table)
    print()

    if not table:
        print("ERROR: users table does not exist.")
        print()
        exit()

    # Get columns
    columns = db.session.execute(
        db.text("""
            SELECT
                column_name,
                data_type,
                is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'users'
            ORDER BY ordinal_position
        """)
    ).fetchall()

    print("USERS TABLE COLUMNS")
    print("----------------------------------------")

    for column_name, data_type, nullable in columns:
        print(
            f"{column_name} | {data_type} | nullable={nullable}"
        )

    print()

    # Count users
    count = db.session.execute(
        db.text("""
            SELECT COUNT(*)
            FROM public.users
        """)
    ).scalar()

    print("Number of users:", count)
    print()

    # Show user information without passwords
    users = db.session.execute(
        db.text("""
            SELECT *
            FROM public.users
            ORDER BY id
        """)
    ).mappings().fetchall()

    if users:

        print("USERS")
        print("----------------------------------------")

        for user in users:

            print()

            for key, value in user.items():

                if "password" in key.lower():
                    print(f"{key}: [HIDDEN]")
                else:
                    print(f"{key}: {value}")

    else:
        print("No users found.")

    print()
    print("========================================")
    print("          CHECK FINISHED")
    print("========================================")
    print()