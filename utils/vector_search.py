import os

import psycopg
from dotenv import load_dotenv
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

    model = get_model()

    embedding = model.encode(
        question,
        normalize_embeddings=True,
    )

    return embedding.tolist()


def search_knowledge(
    question,
    subject_code=None,
    module_number=None,
    limit=5,
):

    if not question or not question.strip():
        return []

    query_embedding = create_query_embedding(
        question.strip()
    )

    filters = []
    parameters = [query_embedding]

    if subject_code:

        filters.append(
            "subject_code = %s"
        )

        parameters.append(
            subject_code
        )

    if module_number:

        filters.append(
            "module_number = %s"
        )

        parameters.append(
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

    parameters.append(limit)

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

    parameters_for_query = [
        query_embedding
    ]

    if subject_code:
        parameters_for_query.append(
            subject_code
        )

    if module_number:
        parameters_for_query.append(
            module_number
        )

    parameters_for_query.append(
        query_embedding
    )

    parameters_for_query.append(
        limit
    )

    # Rebuild SQL parameters cleanly.
    final_parameters = [
        query_embedding
    ]

    if subject_code:
        final_parameters.append(
            subject_code
        )

    if module_number:
        final_parameters.append(
            module_number
        )

    final_parameters.append(
        query_embedding
    )

    final_parameters.append(
        limit
    )

    with psycopg.connect(
        DATABASE_URL
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