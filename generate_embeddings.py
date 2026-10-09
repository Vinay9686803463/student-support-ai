import os

import psycopg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")


MODEL_NAME = "all-MiniLM-L6-v2"


def main():

    print()
    print("=" * 60)
    print("STUDENT SUPPORT AI")
    print("KNOWLEDGE BASE EMBEDDING GENERATOR")
    print("=" * 60)
    print()

    print(f"Loading embedding model: {MODEL_NAME}")
    print("First run may take some time because the model is downloaded.")
    print()

    model = SentenceTransformer(MODEL_NAME)

    vector_size = model.get_sentence_embedding_dimension()

    print(f"[OK] Model loaded")
    print(f"[OK] Vector size: {vector_size}")
    print()

    if vector_size != 384:
        raise RuntimeError(
            f"Unexpected vector size: {vector_size}. "
            "Expected 384."
        )

    with psycopg.connect(DATABASE_URL, prepare_threshold=None) as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM knowledge_chunks
                WHERE embedding IS NULL
                """
            )

            remaining = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM knowledge_chunks
                WHERE embedding IS NOT NULL
                """
            )

            completed = cursor.fetchone()[0]

    print(f"Already embedded : {completed}")
    print(f"Remaining         : {remaining}")
    print()

    if remaining == 0:

        print("[OK] All knowledge chunks already have embeddings.")
        print()
        return

    with psycopg.connect(DATABASE_URL, prepare_threshold=None) as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    content
                FROM knowledge_chunks
                WHERE embedding IS NULL
                ORDER BY id
                """
            )

            chunks = cursor.fetchall()

    print(f"Generating embeddings for {len(chunks)} chunks...")
    print()

    total = len(chunks)
    processed = 0

    # Process in batches so memory usage stays reasonable.
    batch_size = 32

    with psycopg.connect(DATABASE_URL, prepare_threshold=None) as connection:

        with connection.cursor() as cursor:

            for start in range(0, total, batch_size):

                batch = chunks[
                    start:start + batch_size
                ]

                chunk_ids = [
                    row[0]
                    for row in batch
                ]

                texts = [
                    row[1]
                    for row in batch
                ]

                embeddings = model.encode(
                    texts,
                    batch_size=batch_size,
                    show_progress_bar=False,
                    normalize_embeddings=True,
                )

                for chunk_id, embedding in zip(
                    chunk_ids,
                    embeddings,
                ):

                    vector = embedding.tolist()

                    cursor.execute(
                        """
                        UPDATE knowledge_chunks
                        SET embedding = %s
                        WHERE id = %s
                        """,
                        (
                            vector,
                            chunk_id,
                        ),
                    )

                    processed += 1

                connection.commit()

                percentage = (
                    processed / total
                ) * 100

                print(
                    f"Progress: "
                    f"{processed}/{total} "
                    f"({percentage:.1f}%)"
                )

    print()
    print("=" * 60)
    print("EMBEDDING GENERATION COMPLETE")
    print("=" * 60)
    print()
    print(f"[OK] Chunks processed: {processed}")
    print("[OK] Embeddings saved to PostgreSQL")
    print()
    print("Your knowledge chunks are now vectorized.")
    print()


if __name__ == "__main__":
    main()