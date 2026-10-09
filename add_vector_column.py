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
    print("ADDING VECTOR STORAGE")
    print("=" * 60)
    print()

    with psycopg.connect(DATABASE_URL) as connection:

        with connection.cursor() as cursor:

            # Make sure pgvector is enabled
            cursor.execute(
                """
                CREATE EXTENSION IF NOT EXISTS vector
                """
            )

            # Add embedding column
            cursor.execute(
                """
                ALTER TABLE knowledge_chunks
                ADD COLUMN IF NOT EXISTS embedding vector(384)
                """
            )

            # Index will be created later after embeddings
            # are generated.

        connection.commit()

    print("✓ pgvector extension enabled.")
    print("✓ embedding column added.")
    print()
    print("Column:")
    print("  knowledge_chunks.embedding")
    print("  vector dimension: 384")
    print()
    print("Vector storage is ready.")
    print()


if __name__ == "__main__":
    main()