import os

import psycopg
from dotenv import load_dotenv


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")


def main():
    print()
    print("=" * 60)
    print("CHECKING PGVECTOR")
    print("=" * 60)
    print()

    with psycopg.connect(DATABASE_URL) as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT extname
                FROM pg_extension
                WHERE extname = 'vector'
                """
            )

            result = cursor.fetchone()

    if result:
        print("✓ pgvector is installed.")
        print("  Extension: vector")
    else:
        print("✗ pgvector is NOT installed.")

    print()


if __name__ == "__main__":
    main()