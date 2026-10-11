"""Additive migration: full-text search index for knowledge chunks.

Creates a GIN expression index so keyword search over chunk content is
fast without any ML model. Safe to re-run (IF NOT EXISTS). Does not
touch existing data, embeddings, or tables.

Run: <python> migrate_fts_index.py
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
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_content_fts
                ON knowledge_chunks
                USING gin (to_tsvector('english', content))
                """
            )
        connection.commit()
    print("[OK] FTS GIN index ready: idx_knowledge_chunks_content_fts")


if __name__ == "__main__":
    main()
