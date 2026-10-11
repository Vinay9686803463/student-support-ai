import os
import time

from dotenv import load_dotenv

from utils.answer_cache import cache_key, get as cache_get, kb_version_from_stats, put as cache_put
from utils.rag import MODE_LIMITS, prepare_rag_request


load_dotenv()


# Mode defaults: retrieval budget + provider timeout per mode.
MODE_TIMEOUTS = {
    "fast": 15,
    "detailed": 30,
}


def normalize_mode(mode):
    mode = (mode or "").strip().lower()
    return mode if mode in MODE_LIMITS else "detailed"


def _gemini_key():
    key = (
        os.getenv("GOOGLE_GENERATIVE_AI_API_KEY")
        or ""
    ).strip()

    if not key:
        return None

    if key.upper() in {
        "YOUR_API_KEY_HERE",
        "REPLACE-ME",
        "REPLACE_ME",
        "NONE",
    }:
        return None

    return key


def gemini_available():
    """
    Check whether Gemini is configured and
    the Google Generative AI package is installed.
    """

    if not _gemini_key():
        return False

    try:
        import google.generativeai  # noqa: F401

        return True

    except Exception:
        return False


def _gemini_models():
    import google.generativeai as genai

    genai.configure(
        api_key=_gemini_key()
    )

    for model_name in (
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ):
        try:
            yield genai.GenerativeModel(model_name)
        except Exception:
            continue


def _call_gemini(prompt, timeout=30):
    """
    Send the RAG-grounded prompt to Gemini; return the full answer
    text or None. Server-side only: the API key never leaves the backend.
    """

    for model in _gemini_models():

        try:

            response = model.generate_content(
                prompt,
                request_options={
                    "timeout": timeout
                },
            )

            answer = (
                getattr(response, "text", "")
                or ""
            ).strip()

            if answer:
                return answer

        except Exception:
            continue

    return None


def _stream_gemini(prompt, timeout=30):
    """Yield Gemini answer pieces as they arrive (empty if unavailable)."""
    for model in _gemini_models():

        try:
            response = model.generate_content(
                prompt,
                stream=True,
                request_options={
                    "timeout": timeout
                },
            )
            yielded = False
            for chunk in response:
                piece = (getattr(chunk, "text", "") or "")
                if piece:
                    yielded = True
                    yield piece
            if yielded:
                return
        except Exception:
            continue


def _offline_general_explanation(question):
    """Built-in study-bank explanation for *question*, or None.

    Used only when no language model is reachable: it gives the
    student a clearly labeled general explanation instead of
    leaving them with bare excerpts. Never presented as
    document-grounded content.
    """
    try:
        from utils.ai import KNOWLEDGE_BASE, _match_topic
    except Exception:
        return None
    try:
        topic = _match_topic(question or "")
    except Exception:
        return None
    if not topic:
        return None
    return KNOWLEDGE_BASE.get(topic)


def _excerpt_block(index, result):
    """One clearly labeled retrieved passage (never the whole answer)."""
    filename = result.get("filename") or ""
    where = (
        f"{result['subject_code']}, "
        f"Module {result['module_number']}, "
        f"Page {result['page_number']}"
        + (f" ({filename})" if filename else "")
    )
    return f"\n{index}. {where}\n{result['content']}"


def _compose_no_provider_answer(question, results):
    """Honest answer text when no language model is reachable.

    States the limitation up front, adds a labeled general
    explanation when the built-in study bank covers the topic,
    then lists the retrieved passages as excerpts - never
    masquerading as a synthesized answer.
    """
    parts = [
        "Direct AI answering is currently unavailable, so I cannot "
        "synthesize a full answer right now. Please try again later "
        "for a complete explanation.\n"
    ]
    general = _offline_general_explanation(question)
    if general:
        parts.append(
            "General explanation (from the built-in study bank, "
            "not from your documents):\n\n"
            + general
        )
    else:
        parts.append(
            "The retrieved passages below may still help. If they do "
            "not cover your question, try rephrasing it or asking "
            "about a specific topic (e.g. 'Explain OSI layers')."
        )
    parts.append(
        "\nRelevant excerpts from your study materials "
        "(for reference, not a complete answer):"
    )
    for index, result in enumerate(results, start=1):
        parts.append(_excerpt_block(index, result))
    return "\n".join(parts)


def answer_with_rag(
    question,
    subject_code=None,
    module_number=None,
    limit=5,
    mode="detailed",
):
    """
    Main RAG-powered answer function.

    Flow:

    Question
        ↓
    Hybrid search (keyword + vector)
        ↓
    Relevant study-material chunks (all semesters)
        ↓
    RAG prompt
        ↓
    Gemini (or study-bank fallback)
        ↓
    Grounded answer + sources + timings

    Modes: "fast" (small retrieval budget, short timeout) or
    "detailed" (larger budget). Results are cached per question +
    knowledge-base version.
    """

    mode = normalize_mode(mode)

    question = (
        question or ""
    ).strip()

    if not question:

        return {
            "answer": (
                "Please enter a question."
            ),
            "sources": [],
            "used_rag": False,
            "used_ai": False,
            "mode": mode,
            "latency_ms": 0,
            "cached": False,
        }

    started = time.monotonic()

    # The KB version is memoized (30s TTL), so this is ~free and the
    # cache-hit path below performs zero database work.
    kb_version = current_kb_version()

    cached = cache_get(
        cache_key(question, subject_code, module_number, mode, kb_version)
    )

    if cached is not None:

        cached = dict(cached)
        cached["cached"] = True
        cached["latency_ms"] = int((time.monotonic() - started) * 1000)
        return cached

    if limit in (None, 5):
        limit = MODE_LIMITS[mode]

    # Retrieve relevant study material across all semesters unless
    # the caller scoped the search to one subject/module.
    rag_data = prepare_rag_request(
        question=question,
        subject_code=subject_code,
        module_number=module_number,
        limit=limit,
    )

    results = rag_data["results"]
    prompt = rag_data["prompt"]

    timeout = MODE_TIMEOUTS[mode]

    # Try Gemini first.
    if gemini_available():

        try:

            answer = _call_gemini(
                prompt,
                timeout=timeout,
            )

            if answer:

                response = {
                    "answer": answer,
                    "sources": results,
                    "used_rag": bool(results),
                    "used_ai": True,
                    "mode": mode,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "cached": False,
                }
                cache_put(
                    cache_key(question, subject_code, module_number, mode, kb_version),
                    response,
                )
                return response

        except Exception:
            pass

    # No AI provider available. Never present raw excerpts as the
    # answer: say so honestly, add a labeled general explanation
    # when the study bank covers the topic, then list the passages
    # as excerpts. Sources travel separately in "sources" for the
    # citations UI.
    if results:

        fallback_answer = _compose_no_provider_answer(question, results)

        response = {
            "answer": fallback_answer,
            "sources": results,
            "used_rag": True,
            "used_ai": False,
            "mode": mode,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "cached": False,
        }
        cache_put(
            cache_key(question, subject_code, module_number, mode, kb_version),
            response,
        )
        return response

    return {
        "answer": (
            "I couldn't find relevant material "
            "in the knowledge base for "
            "that question."
        ),
        "sources": [],
        "used_rag": False,
        "used_ai": False,
        "mode": mode,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "cached": False,
    }


_KB_VERSION = {"at": 0.0, "value": ""}
_KB_VERSION_TTL = 30.0


def current_kb_version():
    """Cheap knowledge-base version for cache invalidation.

    Memoized for a few seconds: the underlying aggregates scan the
    whole chunks table, which would otherwise dominate fast answers.
    """
    now = time.monotonic()
    if now - _KB_VERSION["at"] < _KB_VERSION_TTL and _KB_VERSION["value"]:
        return _KB_VERSION["value"]
    try:
        from utils.db_conn import get_conn

        with get_conn().cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM knowledge_documents),
                    (SELECT COUNT(*) FROM knowledge_chunks),
                    (SELECT COUNT(embedding) FROM knowledge_chunks),
                    (SELECT COALESCE(MAX(updated_at)::text, '')
                     FROM knowledge_documents)
                """
            )
            row = cursor.fetchone()
        version = kb_version_from_stats(*row)
        _KB_VERSION["at"] = now
        _KB_VERSION["value"] = version
        return version
    except Exception:
        return _KB_VERSION["value"]


def stream_answer(question, subject_code=None, module_number=None,
                  mode="detailed", limit=None):
    """Yield SSE-ready dicts: context event, answer pieces, done event.

    Uses Gemini streaming when configured; otherwise streams the
    composed study-bank answer in pieces (real content, no fake delays).
    """
    mode = normalize_mode(mode)
    started = time.monotonic()

    if limit in (None, 0):
        limit = MODE_LIMITS[mode]

    rag_data = prepare_rag_request(
        question=(question or "").strip(),
        subject_code=subject_code,
        module_number=module_number,
        limit=limit,
    )
    results = rag_data["results"]
    prompt = rag_data["prompt"]

    yield {"event": "sources", "data": {"sources": results}}

    timeout = MODE_TIMEOUTS[mode]
    streamed = False

    if gemini_available():
        try:
            for piece in _stream_gemini(prompt, timeout=timeout):
                streamed = True
                yield {"event": "token", "data": {"text": piece}}
        except Exception as stream_error:
            print("GEMINI STREAM ERROR:", stream_error)

    if not streamed:
        # No language model reachable: stream the same honest
        # no-provider text as answer_with_rag (limitation notice,
        # labeled general explanation when available, then excerpts).
        # Same SSE protocol: token pieces, then the done event below.
        composed = (
            _compose_no_provider_answer(question, results)
            if results
            else ("I couldn't find relevant material "
                  "in the knowledge base for that question. "
                  "Try rephrasing, or ask about a specific topic "
                  "(e.g. 'Explain OSI layers').")
        )
        for start in range(0, len(composed), 1200):
            yield {"event": "token",
                   "data": {"text": composed[start:start + 1200]}}

    yield {"event": "done", "data": {
        "used_rag": bool(results),
        "used_ai": streamed and gemini_available(),
        "mode": mode,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }}


def format_sources(results):
    """
    Convert retrieved chunks into simple
    source information for the chat UI.
    """

    sources = []

    seen = set()

    for result in results:

        key = (
            result["document_id"],
            result["page_number"],
        )

        if key in seen:
            continue

        seen.add(key)

        sources.append(
            {
                "document_id": result[
                    "document_id"
                ],
                "subject_code": result[
                    "subject_code"
                ],
                "module_number": result[
                    "module_number"
                ],
                "page_number": result[
                    "page_number"
                ],
                "similarity": result[
                    "similarity"
                ],
                "filename": result.get("filename"),
                "doc_title": result.get("doc_title"),
            }
        )

    return sources