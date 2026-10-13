import os
import time

from dotenv import load_dotenv

from utils.answer_cache import cache_key, get as cache_get, kb_version_from_stats, put as cache_put
from utils import openai_provider
from utils.rag import MODE_CONTEXT_CHARS, MODE_LIMITS, prepare_rag_request


load_dotenv()


# Mode defaults: retrieval budget + provider timeout per mode.
# Full grounded answers take ~15-30s to generate; budgets reflect
# measured latency (fast streams, so time-to-first-token stays low).
MODE_TIMEOUTS = {
    "fast": 45,
    "detailed": 120,
}


def normalize_mode(mode):
    mode = (mode or "").strip().lower()
    return mode if mode in MODE_LIMITS else "detailed"


def configured_provider():
    """Active model provider, selected via AI_PROVIDER.

    'gemini' (default, free-tier eligible key), 'openai' (paid API),
    or 'ollama' (free local inference, no key). Unknown values fall
    back to the default; only the selected provider is ever required.
    """
    name = (os.getenv("AI_PROVIDER") or "gemini").strip().lower()
    return name if name in ("openai", "gemini", "ollama") else "gemini"


def active_provider():
    """Provider to actually call: the configured one, if usable."""
    from utils import ollama_provider as _ollama
    from utils import openai_provider as _openai

    if configured_provider() == "gemini":
        return "gemini" if gemini_available() else None
    if configured_provider() == "ollama":
        return "ollama" if _ollama.ollama_available() else None
    return "openai" if _openai.openai_available() else None


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


def _classify_provider_error(error):
    """Map a provider exception to a stable, loggable error code.

    Only the code (plus model/latency context) is ever logged or sent
    to the client — never the key, and never raw messages that could
    echo credentials.
    """
    text = f"{type(error).__name__}: {error}".lower()

    if "api key" in text or "api_key" in text or "unauthenticated" in text:
        if "valid" in text or "invalid" in text or "incorrect" in text:
            return "auth_invalid"
        return "auth_missing"
    if "401" in text or "403" in text or "permission" in text:
        return "auth_invalid"
    if "quota" in text or "exhausted" in text:
        return "quota_exceeded"
    if "429" in text or "rate" in text and "limit" in text:
        return "rate_limited"
    if "404" in text or "not found" in text or "notfound" in text:
        return "model_not_found"
    if "timeout" in text or "timed out" in text or "deadline" in text:
        return "timeout"
    if ("connect" in text or "dns" in text or "resolve" in text
            or "network" in text or "unreachable" in text):
        return "network"
    if "500" in text or "502" in text or "503" in text or "504" in text or "server" in text:
        return "server_error"
    return "unknown"


_LAST_PROVIDER_ERROR = {"code": None, "at": None, "model": None}


def get_last_provider_error():
    """Last classified provider failure (operator diagnostics, no secrets)."""
    return dict(_LAST_PROVIDER_ERROR)


def _record_provider_error(code, model=None):
    _LAST_PROVIDER_ERROR.update(
        {"code": code, "model": model, "at": time.time()}
    )
    print(f"PROVIDER ERROR [{code}] model={model or 'unknown'}")


_DEFAULT_GEMINI_MODELS = (
    # Live-verified 2026-10-11: 1.5/2.0/2.5-flash return 404 "no longer
    # available"; gemini-flash-latest times out. 3.8-flash (provider
    # recommendation) and 3.5-flash both returned real generations,
    # so both stay: a transient 504 on the first falls through to
    # the second instead of the fallback message.
    "gemini-3.8-flash",
    "gemini-3.5-flash",
)


def _model_candidates():
    """Model names to try, in order.

    Overridable without a code change via GEMINI_MODELS
    ("a,b,c") so a retired model name can be rotated by the
    operator. Falls back to the built-in defaults when unset.
    """
    raw = (os.getenv("GEMINI_MODELS") or "").strip()
    if not raw:
        return _DEFAULT_GEMINI_MODELS
    names = tuple(part.strip() for part in raw.split(",") if part.strip())
    return names or _DEFAULT_GEMINI_MODELS


def _gemini_models():
    import google.generativeai as genai

    genai.configure(
        api_key=_gemini_key()
    )

    for model_name in _model_candidates():
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

        model_name = getattr(model, "model_name", None) or getattr(
            model, "_model_name", "unknown"
        )

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
                print(f"GEMINI OK model={model_name} chars={len(answer)}")
                return answer

        except Exception as error:
            _record_provider_error(
                _classify_provider_error(error), model=model_name
            )
            continue

    return None


def _stream_gemini(prompt, timeout=30):
    """Yield Gemini answer pieces as they arrive (empty if unavailable)."""
    for model in _gemini_models():
        model_name = getattr(model, "model_name", None) or getattr(
            model, "_model_name", "unknown"
        )
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
        except Exception as error:
            _record_provider_error(
                _classify_provider_error(error), model=model_name
            )
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


def _provider_hint(provider, error_code):
    """One actionable setup hint for the failed provider (or empty).

    Shown after the limitation notice so the operator knows exactly
    what to fix. Contains no secrets: only env-var names, the local
    daemon URL, and the model name.
    """
    from utils import ollama_provider as _ollama

    # Specific error codes first: they say what actually failed.
    # Provider setup lines are the fallback when the code alone
    # does not prescribe an action.
    if error_code == "quota_exhausted":
        return ("The AI account has no free quota remaining; switch "
                "AI_PROVIDER to a free option (gemini free-tier or "
                "local ollama) and restart.")
    if error_code == "auth_invalid":
        return ("The configured AI key was rejected; check the key and "
                "restart the backend.")
    if provider == "ollama":
        return (
            "Setup: install Ollama, run `ollama serve`, pull a model "
            f"(`ollama pull {_ollama.configured_model()}`), set "
            "AI_PROVIDER=ollama, and restart the backend. "
            f"(Tried {_ollama.configured_url()}: {error_code}.)"
        )
    if provider == "gemini":
        return (
            "Setup: set GOOGLE_GENERATIVE_AI_API_KEY in the backend "
            "environment and restart."
            + (f" ({error_code}.)" if error_code else "")
        )
    return ""


def _compose_no_provider_answer(question, results,
                                provider=None, error_code=None):
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
    hint = _provider_hint(provider, error_code)
    if hint:
        parts.append(hint)
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
            "answer_kind": "no_results",
            "error_code": None,
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
        max_chars_per_source=MODE_CONTEXT_CHARS[mode],
    )

    results = rag_data["results"]
    prompt = rag_data["prompt"]

    timeout = MODE_TIMEOUTS[mode]
    max_tokens = {"fast": 800, "detailed": 1800}[mode]

    provider = active_provider()

    # Try the configured model provider (OpenAI by default).
    if provider == "openai":

        try:

            answer = openai_provider.generate_answer(
                prompt,
                timeout=timeout,
                max_tokens=max_tokens,
            )

            if answer:

                response = {
                    "answer": answer,
                    "sources": results,
                    "used_rag": bool(results),
                    "used_ai": True,
                    "provider": "openai",
                    "answer_kind": "ai_generated",
                    "error_code": None,
                    "mode": mode,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "cached": False,
                }
                cache_put(
                    cache_key(question, subject_code, module_number, mode, kb_version),
                    response,
                )
                return response

        except Exception as error:
            _record_provider_error(
                openai_provider.classify_openai_error(error),
                model=openai_provider.configured_model(),
            )

    elif provider == "ollama":

        from utils import ollama_provider as _ollama

        try:

            answer = _ollama.generate_answer(
                prompt,
                timeout=timeout,
                max_tokens=max_tokens,
            )

            if answer:

                response = {
                    "answer": answer,
                    "sources": results,
                    "used_rag": bool(results),
                    "used_ai": True,
                    "provider": "ollama",
                    "answer_kind": "ai_generated",
                    "error_code": None,
                    "mode": mode,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "cached": False,
                }
                cache_put(
                    cache_key(question, subject_code, module_number, mode, kb_version),
                    response,
                )
                return response

        except Exception as error:
            _record_provider_error(
                _ollama.classify_ollama_error(error),
                model=_ollama.configured_model(),
            )

    elif provider == "gemini" and gemini_available():

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
                    "provider": "gemini",
                    "answer_kind": "ai_generated",
                    "error_code": None,
                    "mode": mode,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "cached": False,
                }
                cache_put(
                    cache_key(question, subject_code, module_number, mode, kb_version),
                    response,
                )
                return response

        except Exception as error:
            _record_provider_error(_classify_provider_error(error))

    # No AI provider available. Never present raw excerpts as the
    # answer: say so honestly, add a labeled general explanation
    # when the study bank covers the topic, then list the passages
    # as excerpts. Sources travel separately in "sources" for the
    # citations UI.
    if results:

        last_error = get_last_provider_error()
        error_code = last_error.get("code") or "provider_not_configured"
        fallback_answer = _compose_no_provider_answer(
            question, results, provider=provider or configured_provider(),
            error_code=error_code)

        response = {
            "answer": fallback_answer,
            "sources": results,
            "used_rag": True,
            "used_ai": False,
            "provider": provider,
            "answer_kind": "fallback_excerpts",
            "error_code": error_code,
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
        "answer_kind": "no_results",
        "error_code": None,
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
        max_chars_per_source=MODE_CONTEXT_CHARS[mode],
    )
    results = rag_data["results"]
    prompt = rag_data["prompt"]

    yield {"event": "sources", "data": {"sources": results}}

    timeout = MODE_TIMEOUTS[mode]
    max_tokens = {"fast": 800, "detailed": 1800}[mode]
    provider = active_provider()
    streamed = False
    stream_provider = None

    from utils import ollama_provider as _ollama
    from utils import openai_provider as _openai

    if provider == "openai":
        try:
            for piece in _openai.stream_pieces(
                prompt, timeout=timeout, max_tokens=max_tokens
            ):
                streamed = True
                stream_provider = "openai"
                yield {"event": "token", "data": {"text": piece}}
        except Exception as stream_error:
            _record_provider_error(
                _openai.classify_openai_error(stream_error),
                model=_openai.configured_model(),
            )
    elif provider == "ollama":
        try:
            for piece in _ollama.stream_pieces(
                prompt, timeout=timeout, max_tokens=max_tokens
            ):
                streamed = True
                stream_provider = "ollama"
                yield {"event": "token", "data": {"text": piece}}
        except Exception as stream_error:
            _record_provider_error(
                _ollama.classify_ollama_error(stream_error),
                model=_ollama.configured_model(),
            )
    elif provider == "gemini":
        try:
            for piece in _stream_gemini(prompt, timeout=timeout):
                streamed = True
                stream_provider = "gemini"
                yield {"event": "token", "data": {"text": piece}}
        except Exception as stream_error:
            _record_provider_error(_classify_provider_error(stream_error))

    if not streamed:
        # No language model reachable: stream the same honest
        # no-provider text as answer_with_rag (limitation notice,
        # labeled general explanation when available, then excerpts).
        # Same SSE protocol: token pieces, then the done event below.
        stream_error_code = (
            get_last_provider_error().get("code") or "provider_not_configured"
        )
        composed = (
            _compose_no_provider_answer(
                question, results, provider=provider or configured_provider(),
                error_code=stream_error_code)
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
        "used_ai": streamed,
        "provider": stream_provider,
        "answer_kind": ("ai_generated" if streamed else
                        ("fallback_excerpts" if results else "no_results")),
        "error_code": None if streamed else (
            get_last_provider_error().get("code") or "provider_not_configured"
        ) if results else None,
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