import os

from dotenv import load_dotenv
import psycopg

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id BIGSERIAL PRIMARY KEY,

    subject_code VARCHAR(50) NOT NULL,
    subject_name VARCHAR(200) NOT NULL,

    module_number INTEGER NOT NULL,
    module_title VARCHAR(200),

    title VARCHAR(300) NOT NULL,
    original_filename VARCHAR(500) NOT NULL,

    file_path TEXT NOT NULL,
    source VARCHAR(500),

    page_count INTEGER DEFAULT 0,

    status VARCHAR(30) NOT NULL DEFAULT 'uploaded',

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE INDEX IF NOT EXISTS idx_knowledge_documents_subject
ON knowledge_documents(subject_code);


CREATE INDEX IF NOT EXISTS idx_knowledge_documents_module
ON knowledge_documents(subject_code, module_number);


CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id BIGSERIAL PRIMARY KEY,

    document_id BIGINT NOT NULL
        REFERENCES knowledge_documents(id)
        ON DELETE CASCADE,

    subject_code VARCHAR(50) NOT NULL,
    module_number INTEGER NOT NULL,

    page_number INTEGER,
    chunk_number INTEGER NOT NULL,

    content TEXT NOT NULL,

    character_count INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document
ON knowledge_chunks(document_id);


CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_subject_module
ON knowledge_chunks(subject_code, module_number);


CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_page
ON knowledge_chunks(document_id, page_number);


CREATE TABLE IF NOT EXISTS knowledge_processing_logs (
    id BIGSERIAL PRIMARY KEY,

    document_id BIGINT
        REFERENCES knowledge_documents(id)
        ON DELETE CASCADE,

    action VARCHAR(100) NOT NULL,

    status VARCHAR(30) NOT NULL,

    message TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def main():
    print()
    print("=" * 60)
    print("STUDENT SUPPORT AI - KNOWLEDGE BASE SETUP")
    print("=" * 60)
    print()

    print("Connecting to PostgreSQL...")

    with psycopg.connect(DATABASE_URL) as connection:

        with connection.cursor() as cursor:
            cursor.execute(SCHEMA_SQL)

        connection.commit()

    print("✓ Knowledge base tables created successfully.")
    print()
    print("Created tables:")
    print("  ✓ knowledge_documents")
    print("  ✓ knowledge_chunks")
    print("  ✓ knowledge_processing_logs")
    print()
    print("Knowledge base is ready.")
    print()


if __name__ == "__main__":
    main()