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
    print("VERIFYING KNOWLEDGE BASE EMBEDDINGS")
    print("=" * 60)
    print()

    with psycopg.connect(DATABASE_URL) as connection:

        with connection.cursor() as cursor:

            # Total chunks
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM knowledge_chunks
                """
            )

            total_chunks = cursor.fetchone()[0]

            # Chunks with embeddings
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM knowledge_chunks
                WHERE embedding IS NOT NULL
                """
            )

            embedded_chunks = cursor.fetchone()[0]

            # Chunks without embeddings
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM knowledge_chunks
                WHERE embedding IS NULL
                """
            )

            missing_embeddings = cursor.fetchone()[0]

            # Check vector dimension
            cursor.execute(
                """
                SELECT
                    vector_dims(embedding)
                FROM knowledge_chunks
                WHERE embedding IS NOT NULL
                LIMIT 1
                """
            )

            dimension_result = cursor.fetchone()

            vector_dimension = (
                dimension_result[0]
                if dimension_result
                else None
            )

    print(f"Total chunks       : {total_chunks}")
    print(f"Embedded chunks    : {embedded_chunks}")
    print(f"Missing embeddings : {missing_embeddings}")
    print(f"Vector dimension   : {vector_dimension}")
    print()

    if total_chunks == 0:

        print("✗ No knowledge chunks found.")
        return

    if missing_embeddings > 0:

        print(
            "⚠ Some chunks do not have embeddings yet."
        )

        print(
            "Run: python generate_embeddings.py"
        )

        return

    if vector_dimension != 384:

        print(
            "✗ Unexpected vector dimension."
        )

        print(
            "Expected: 384"
        )

        return

    print("✓ All chunks have embeddings.")
    print("✓ Vector dimension is 384.")
    print("✓ Knowledge base is ready for semantic search.")
    print()


if __name__ == "__main__":
    main()
