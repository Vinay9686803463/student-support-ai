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
    print("KNOWLEDGE BASE STATUS")
    print("=" * 60)

    with psycopg.connect(DATABASE_URL) as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM knowledge_documents
                """
            )

            document_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM knowledge_chunks
                """
            )

            chunk_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT
                    subject_code,
                    module_number,
                    COUNT(*)
                FROM knowledge_documents
                GROUP BY subject_code, module_number
                ORDER BY subject_code, module_number
                """
            )

            module_rows = cursor.fetchall()

    print()
    print(f"Documents : {document_count}")
    print(f"Chunks    : {chunk_count}")

    print()
    print("Documents by module:")
    print("-" * 40)

    for subject_code, module_number, count in module_rows:
        print(
            f"{subject_code} | "
            f"Module {module_number} | "
            f"{count} documents"
        )

    print()
    print("=" * 60)
    print("DATABASE CHECK COMPLETE")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()