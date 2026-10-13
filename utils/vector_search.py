import os
import re

import psycopg
from dotenv import load_dotenv
from functools import lru_cache


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")


MODEL_NAME = "all-MiniLM-L6-v2"


_model = None

# Circuit breaker: when the embedding model fails (e.g. torch missing),
# skip vector attempts for a while instead of paying the failed-import
# cost on every single question.
_model_failed_until = 0.0
_MODEL_RETRY_SECONDS = 300.0


def _verdict_path():
    import tempfile

    return os.path.join(
        tempfile.gettempdir(), "ssa_vector_available.json"
    )


def _read_verdict():
    import json as _json
    import time as _time

    try:
        # A negative verdict expires after a day so a later torch
        # install/repair re-enables vectors automatically.
        if _time.time() - os.path.getmtime(_verdict_path()) > 86400:
            return None
        with open(_verdict_path(), "r", encoding="utf-8") as handle:
            data = _json.load(handle)
        if isinstance(data, dict) and data.get("available") is False:
            return False
    except Exception:
        pass
    return None


def _write_verdict(available):
    import json as _json

    try:
        with open(_verdict_path(), "w", encoding="utf-8") as handle:
            _json.dump({"available": bool(available)}, handle)
    except Exception:
        pass


def vector_available():
    """True when a vector attempt is worth making in this process."""
    import time as _time

    if _time.monotonic() < _model_failed_until:
        return False
    if _read_verdict() is False:
        return False
    return True


def _mark_vector_failed():
    import time as _time

    global _model_failed_until
    _model_failed_until = _time.monotonic() + _MODEL_RETRY_SECONDS
    _write_verdict(False)


def get_model():

    global _model

    if _model is None:
        # Imported lazily so keyword search keeps working on machines
        # without torch installed; only vector search needs the model.
        from sentence_transformers import SentenceTransformer

        try:
            _model = SentenceTransformer(MODEL_NAME)
        except Exception:
            _mark_vector_failed()
            raise

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
    # Uses the thread-local shared connection: no per-query connect cost.
    from utils.db_conn import get_conn

    with get_conn().cursor() as cursor:

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


# ---------------------------------------------------------
# FULL-TEXT SEARCH (Postgres tsvector, no model needed)
# ---------------------------------------------------------

def sanitize_fts_query(question):
    """Reduce a question to plain searchable words for tsquery."""
    words = re.findall(r"[A-Za-z0-9]+", question or "")
    # Drop single letters and pure numbers-only noise; keep the rest.
    kept = [word for word in words if len(word) > 1]
    return " ".join(kept[:40])


def fts_tsquery(question):
    """OR-joined tsquery string: any matching study term recalls a chunk.

    plainto_tsquery ANDs every word (a question like "Explain DBMS
    normalization" would miss chunks lacking any one word), which kills
    recall for natural-language questions. OR + ts_rank ordering is the
    right trade-off for a study assistant.
    """
    words = re.findall(r"[A-Za-z0-9]+", sanitize_fts_query(question))
    # Quote each term so punctuation inside words can't break the query.
    terms = [f"'{word}'" for word in words if word]
    return " | ".join(terms[:40])


def search_fts(
    question,
    subject_code=None,
    module_number=None,
    limit=5,
):
    """Keyword retrieval over chunk content with filename metadata.

    Needs no ML model: works for every indexed chunk, including ones
    whose embeddings are not generated yet. Returns the same result
    shape as search_knowledge plus filename/doc_title, with ts_rank
    as similarity.
    """

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5

    if limit < 1:
        limit = 5

    query_text = sanitize_fts_query(question)

    if not query_text:
        return []

    tsquery = fts_tsquery(question)

    if not tsquery:
        return []

    filters = []
    parameters = [tsquery]

    if subject_code:
        filters.append("kc.subject_code = %s")
        parameters.append(subject_code)

    if module_number:
        filters.append("kc.module_number = %s")
        parameters.append(module_number)

    where_clause = ""
    if filters:
        where_clause = "AND " + " AND ".join(filters)

    parameters.append(limit)

    sql = f"""
        SELECT
            kc.id,
            kc.document_id,
            kc.subject_code,
            kc.module_number,
            kc.page_number,
            kc.chunk_number,
            kc.content,
            ts_rank_cd(
                to_tsvector('english', kc.content),
                to_tsquery('english', %s)
            ) AS similarity,
            d.original_filename AS filename,
            d.title AS doc_title
        FROM knowledge_chunks kc
        JOIN knowledge_documents d ON d.id = kc.document_id
        WHERE to_tsvector('english', kc.content)
              @@ to_tsquery('english', %s)
        {where_clause}
        ORDER BY similarity DESC
        LIMIT %s
    """

    # The tsquery value is needed twice (rank + match).
    final_parameters = [tsquery, tsquery] + parameters[1:]

    # Shared thread-local connection: no per-query connect cost and a
    # statement timeout so pooler saturation fails fast, not silent-hang.
    from utils.db_conn import get_conn

    with get_conn().cursor() as cursor:
        cursor.execute(sql, final_parameters)
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
                "filename": row[8],
                "doc_title": row[9],
            }
        )

    return results


def search_hybrid(
    question,
    subject_code=None,
    module_number=None,
    limit=5,
):
    """Reciprocal-rank fusion of keyword (FTS) + vector search.

    FTS guarantees recall over every indexed chunk; vectors add
    semantic ranking where embeddings exist. If the embedding model
    is unavailable, degrades gracefully to pure FTS.
    """
    fts_results = []
    vector_results = []

    try:
        fts_results = search_fts(
            question,
            subject_code=subject_code,
            module_number=module_number,
            limit=max(limit * 3, 10),
        )
    except Exception as fts_error:
        print("FTS SEARCH ERROR:", fts_error)

    import time as _time

    if not vector_available():
        vector_results = []
    else:
        try:
            vector_results = search_knowledge(
                question,
                subject_code=subject_code,
                module_number=module_number,
                limit=max(limit * 3, 10),
            )
        except Exception as vector_error:
            print("VECTOR SEARCH ERROR:", vector_error)
            _mark_vector_failed()

    if not fts_results:
        return vector_results[:limit]

    if not vector_results:
        return fts_results[:limit]

    fused = {}
    order = {}

    for rank, result in enumerate(fts_results, start=1):
        key = result["id"]
        fused[key] = fused.get(key, 0.0) + 1.0 / (60 + rank)
        order[key] = result

    for rank, result in enumerate(vector_results, start=1):
        key = result["id"]
        fused[key] = fused.get(key, 0.0) + 1.0 / (60 + rank)
        if key not in order:
            merged = dict(result)
            merged["filename"] = result.get("filename")
            merged["doc_title"] = result.get("doc_title")
            order[key] = merged

    ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)

    combined = []
    for key, score in ranked[:limit]:
        result = dict(order[key])
        result["similarity"] = float(score)
        combined.append(result)

    return combined