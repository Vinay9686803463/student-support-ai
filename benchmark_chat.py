"""Performance benchmark for Student Support AI.

Measures, without printing any secret:
  1. Cold `import app` cost (separate process, includes boot initialization)
  2. Knowledge retrieval cost for representative questions
  3. Query plans / index usage for the FTS + vector queries
  4. Provider (Gemini) generation latency, and stream time-to-first-chunk
  5. End-to-end /api/chat/stream latency via the Flask test client
  6. Follow-up suggestion engine cost

Read-only against the database (SELECT/EXPLAIN only). Run:

    venv/Scripts/python.exe benchmark_chat.py
"""

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

RESULTS = {}

QUESTIONS = {
    "osi": ("Explain the seven layers of the OSI model.", None, None),
    "normalization": ("Explain 1NF, 2NF and 3NF with examples.", None, None),
    "subnetting": ("How do you subnet a /24 network into /26 subnets?", None, None),
}


def ms(seconds):
    return int(seconds * 1000)


def cold_import():
    """Time a fresh-process `import app` (boot path incl. init + bootstrap)."""
    code = (
        "import sys, time; t = time.perf_counter(); import app; "
        "sys.stdout.write(str(round((time.perf_counter() - t) * 1000)))"
    )
    env = dict(os.environ)
    env.pop("WERKZEUG_DEBUG_PIN", None)
    times = []
    for run in ("cold-1", "cold-2"):
        started = time.perf_counter()
        finished = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
        )
        wall = ms(time.perf_counter() - started)
        out = (finished.stdout or "").strip().splitlines()
        inner = out[-1] if out and out[-1].isdigit() else "?"
        RESULTS[f"cold_import_{run}"] = f"{inner} ms (script wall {wall} ms)"


def retrieval(app_module):
    from utils.rag import prepare_rag_request
    from utils.rag_ai import MODE_LIMITS, MODE_CONTEXT_CHARS
    from utils import answer_cache

    answer_cache.invalidate_all()

    for stage in ("cold", "warm"):
        blank = "benchmark clearance query"
        prepare_rag_request(question=blank, limit=MODE_LIMITS["fast"],
                            max_chars_per_source=MODE_CONTEXT_CHARS["fast"])
        for name, (question, subject, module) in QUESTIONS.items():
            started = time.perf_counter()
            prepare_rag_request(
                question=question,
                subject_code=subject,
                module_number=module,
                limit=MODE_LIMITS["fast"],
                max_chars_per_source=MODE_CONTEXT_CHARS["fast"],
            )
            RESULTS[f"retrieval_{stage}_{name}"] = f"{ms(time.perf_counter() - started)} ms"


def query_plans(app_module):
    from utils.db_conn import get_conn

    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge_chunks")
        chunks = cur.fetchone()[0]
        cur.execute("SELECT COUNT(embedding) FROM knowledge_chunks")
        embedded = cur.fetchone()[0]
        RESULTS["knowledge_chunks"] = f"{chunks} rows, {embedded} with embeddings"

        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'knowledge_chunks'"
        )
        RESULTS["knowledge_chunks_indexes"] = [r[0] for r in cur.fetchall()]

        cur.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'knowledge_chunks' AND column_name = 'embedding'"
        )
        row = cur.fetchone()
        RESULTS["embedding_column"] = f"{row[0] if row else 'MISSING'}"

        cur.execute(
            "SELECT extname FROM pg_extension WHERE extname = 'vector'"
        )
        RESULTS["pgvector_extension"] = bool(cur.fetchall())

        tsquery = "'osi' | 'layers' | 'reference' | 'model'"
        cur.execute(
            "EXPLAIN (ANALYZE, BUFFERS) SELECT kc.id, kc.content, "
            "ts_rank_cd(to_tsvector('english', kc.content), "
            "to_tsquery('english', %s)) AS similarity, "
            "d.original_filename AS filename, d.title AS doc_title "
            "FROM knowledge_chunks kc JOIN knowledge_documents d "
            "ON d.id = kc.document_id "
            "WHERE to_tsvector('english', kc.content) @@ to_tsquery('english', %s) "
            "ORDER BY similarity DESC LIMIT 12",
            (tsquery, tsquery),
        )
        plan = "\n".join(r[0] for r in cur.fetchall())
        RESULTS["fts_plan"] = [
            line for line in plan.splitlines()
            if ("Execution Time" in line or "Index" in line or "Seq Scan" in line)]

        cur.execute(
            "EXPLAIN (ANALYZE) SELECT id, content, "
            "1 - (embedding <=> embedding) AS similarity "
            "FROM knowledge_chunks WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> embedding LIMIT 12"
        )
        plan = "\n".join(r[0] for r in cur.fetchall())
        RESULTS["vector_plan"] = [
            line for line in plan.splitlines()
            if ("Execution Time" in line or "Index" in line or "Seq Scan" in line)]


def provider(app_module, prompt):
    from utils.rag_ai import _stream_gemini

    started = time.perf_counter()
    first = None
    total = 0
    for piece in _stream_gemini(prompt, timeout=40):
        if first is None:
            first = time.perf_counter() - started
        total += len(piece)
    RESULTS["provider_stream"] = (
        f"TTFC {ms(first or 0)} ms, answer {total} chars, "
        f"total {ms(time.perf_counter() - started)} ms")


def followups(app_module):
    from utils.rag_ai import generate_followup_suggestions

    started = time.perf_counter()
    out = generate_followup_suggestions(
        "Explain the seven layers of the OSI model.", "answer text")
    RESULTS["suggestions_query"] = (
        f"{ms(time.perf_counter() - started)} ms ({len(out)} suggestions)")


def sse_endpoint(app_module, question):
    from utils import answer_cache

    answer_cache.invalidate_all()
    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 1
        session["user_name"] = "Student"

    started = time.perf_counter()
    first_token = None
    ttfc_ok = False
    response = client.post(
        "/api/chat/stream",
        json={"message": question, "mode": "fast"},
        buffered=False,
    )
    try:
        for line in response.response:
            text = line.decode("utf-8", "replace") if isinstance(line, bytes) else line
            if text.startswith("event: token") and first_token is None:
                first_token = time.perf_counter() - started
            if text.startswith("event: done"):
                ttfc_ok = True
        RESULTS["sse_endpoint"] = (
            f"TTFC {ms(first_token or 0)} ms, total {ms(time.perf_counter() - started)} ms, "
            f"done_received={ttfc_ok}")
    except Exception as error:
        RESULTS["sse_endpoint"] = f"FAILED after {ms(time.perf_counter() - started)} ms: {error}"


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    print(f"BENCHMARK PHASE: {phase}")

    if phase in ("all", "boot", "before", "after"):
        cold_import()

    phase_db = phase in ("all", "db", "before", "after")
    if phase_db or phase == "provider":
        started = time.perf_counter()
        from app import db  # noqa: F401  (warm imports, before timing starts)
        import app as app_module

        RESULTS["warm_import_app"] = f"{ms(time.perf_counter() - started)} ms"

    if phase_db or phase in ("all", "db"):
        retrieval(app_module)
        query_plans(app_module)

    if phase in ("all", "provider", "before", "after"):
        from utils.rag import prepare_rag_request
        from utils.rag_ai import MODE_LIMITS, MODE_CONTEXT_CHARS
        from utils import answer_cache

        answer_cache.invalidate_all()
        prepped = prepare_rag_request(
            question=QUESTIONS["osi"][0],
            limit=MODE_LIMITS["fast"],
            max_chars_per_source=MODE_CONTEXT_CHARS["fast"],
        )
        provider(app_module, prepped["prompt"])
        followups(app_module)
        sse_endpoint(app_module, QUESTIONS["osi"][0])

    print(json.dumps(RESULTS, indent=2, default=str))


if __name__ == "__main__":
    main()
