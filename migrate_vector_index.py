"""Additive migration: vector (HNSW) index for chunk embeddings.

Creates an approximate-nearest-neighbour index (HNSW, cosine distance)
over ``knowledge_chunks.embedding`` so semantic search stops scanning
every embedded row on each question (measured: 146ms seq scan for ~1k
embedded chunks, growing linearly as more chunks get embeddings).
Safe to re-run (IF NOT EXISTS). Adds no columns and changes no data.

Older pgvector (<0.5) falls back to IVFFlat with lists=32.

Run: <python> migrate_vector_index.py
"""

import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")


def main():
    with psycopg.connect(DATABASE_URL, prepare_threshold=None) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )
            row = cursor.fetchone()
            if not row:
                print(
                    "pgvector is not installed; nothing to do "
                    "(vector search stays model-based / disabled)."
                )
                return
            version = tuple(int(part) for part in row[0].split(".")[:2])
            print(f"pgvector {row[0]}")
            if version >= (0, 5):
                statement = (
                    "CREATE INDEX IF NOT EXISTS "
                    "idx_knowledge_chunks_embedding_hnsw "
                    "ON knowledge_chunks "
                    "USING hnsw (embedding vector_cosine_ops)"
                )
            else:
                statement = (
                    "CREATE INDEX IF NOT EXISTS "
                    "idx_knowledge_chunks_embedding "
                    "ON knowledge_chunks "
                    "USING ivfflat (embedding vector_cosine_ops) "
                    "WITH (lists = 32)"
                )
            cursor.execute(statement)
        connection.commit()
    print("Vector index ready (HNSW cosine on knowledge_chunks.embedding).")


if __name__ == "__main__":
    main()
