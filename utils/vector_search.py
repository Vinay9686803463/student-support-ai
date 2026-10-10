import os

import psycopg
from dotenv import load_dotenv
from functools import lru_cache
from sentence_transformers import SentenceTransformer


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")


MODEL_NAME = "all-MiniLM-L6-v2"


_model = None


def get_model():

    global _model

    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)

    return _model


def create_query_embedding(question):

    # Identical questions reuse the cached vector instead of re-running
    # the transformer (inference is deterministic, so results match
    # exactly). Retried / popular questions skip ~100ms+ of CPU work.
    return list(_cached_embedding((question or "").strip()))


@lru_cache(maxsize=128)
def _cached_embedding(normalized_question):

    model = get_model()

    embedding = model.encode(
        normalized_question,
        normalize_embeddings=True,
    )

    # lru_cache needs a hashable return value; callers get a fresh list.
    return tuple(embedding.tolist())


def search_knowledge(
    question,
    subject_code=None,
    module_number=None,
    limit=5,
):

    if not question or not question.strip():
        return []

    # Guard the LIMIT: non-positive values would mean "no limit" in
    # Postgres and dump the table; garbage falls back to the default.
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5

    if limit < 1:
        limit = 5

    query_embedding = create_query_embedding(
        question.strip()
    )

    filters = []
    final_parameters = [query_embedding]

    if subject_code:

        filters.append(
            "subject_code = %s"
        )

        final_parameters.append(
            subject_code
        )

    if module_number:

        filters.append(
            "module_number = %s"
        )

        final_parameters.append(
            module_number
        )

    where_clause = ""

    if filters:

        where_clause = (
            "WHERE "
            + " AND ".join(filters)
            + " AND embedding IS NOT NULL"
        )

    else:

        where_clause = "WHERE embedding IS NOT NULL"

    sql = f"""
        SELECT
            id,
            document_id,
            subject_code,
            module_number,
            page_number,
            chunk_number,
            content,

            1 - (
                embedding <=> %s::vector
            ) AS similarity

        FROM knowledge_chunks

        {where_clause}

        ORDER BY
            embedding <=> %s::vector

        LIMIT %s
    """

    # The query vector is required twice:
    # once for similarity calculation
    # and once for ordering.
    final_parameters.append(
        query_embedding
    )

    final_parameters.append(
        limit
    )

    # prepare_threshold=None keeps pooled/proxied connections working
    # (same reason as knowledge_ingest.get_connection); connect_timeout
    # fails fast instead of hanging a chat request on a dead database.
    with psycopg.connect(
        DATABASE_URL,
        connect_timeout=10,
        prepare_threshold=None,
    ) as connection:

        with connection.cursor() as cursor:

            cursor.execute(
                sql,
                final_parameters,
            )

            rows = cursor.fetchall()

    results = []

    for row in rows:

        results.append(
            {
                "id": row[0],
                "document_id": row[1],
                "subject_code": row[2],
                "module_number": row[3],
                "page_number": row[4],
                "chunk_number": row[5],
                "content": row[6],
                "similarity": float(row[7]),
            }
        )

    return results