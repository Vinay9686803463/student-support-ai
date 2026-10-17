import os
import re
import threading
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
    "fast": 60,
    "detailed": 180,
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
        from google import genai  # noqa: F401

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
    # Verified live against the project API key (Oct 2026):
    # gemini-3.5-flash-lite has available quota and returns
    # detailed answers. The others may be rate-limited (429).
    "gemini-3.5-flash-lite",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
)


def _explicit_candidates():
    """Operator-configured models from GEMINI_MODELS/GEMINI_MODEL.

    Returns a tuple, or None when neither variable is set, so the
    caller can tell "operator chose these" apart from defaults.
    """
    raw = (os.getenv("GEMINI_MODELS") or "").strip()
    if raw:
        names = tuple(
            part.strip() for part in raw.split(",") if part.strip()
        )
        return names or None
    single = (os.getenv("GEMINI_MODEL") or "").strip()
    return (single,) if single else None


def _model_candidates():
    """Model names to try, in order.

    Overridable without a code change via GEMINI_MODELS
    ("a,b,c") or the single GEMINI_MODEL, so a retired model
    name can be rotated by the operator. Falls back to the
    built-in defaults when unset.
    """
    return _explicit_candidates() or _DEFAULT_GEMINI_MODELS


def _defaults_after(tried):
    """Verified defaults not already tried, for retired-model recovery.

    Used only when every explicitly configured model failed with
    model_not_found: the operator's choice is always tried first
    and any other error (auth, quota, network) is reported as-is
    instead of burning latency on models that would fail the same
    way.
    """
    if not _explicit_candidates():
        return ()
    tried_set = set(tried or ())
    return tuple(
        model for model in _DEFAULT_GEMINI_MODELS
        if model not in tried_set
    )


_GEMINI_CLIENTS = {}
_GEMINI_CLIENTS_LOCK = threading.Lock()


def _gemini_client(timeout):
    """Build (and reuse) a Gemini client for requests.

    Uses the installed ``google-genai`` SDK (``google.genai``).
    ``http_options`` timeout is in milliseconds.

    Clients are cached per (key, timeout): construction costs
    ~24ms (measured), and every chat question previously paid it.
    Reuse is thread-safe (one lock-guarded dict, bounded size); a
    rotated key simply gets its own entry, and keys are never logged.
    """
    from google import genai

    entry = (_gemini_key(), max(1, int(timeout * 1000)))
    with _GEMINI_CLIENTS_LOCK:
        client = _GEMINI_CLIENTS.get(entry)
        if client is None:
            if len(_GEMINI_CLIENTS) >= 8:
                _GEMINI_CLIENTS.pop(next(iter(_GEMINI_CLIENTS)))
            client = genai.Client(
                api_key=entry[0], http_options={"timeout": entry[1]}
            )
            _GEMINI_CLIENTS[entry] = client
        return client


def _call_gemini(prompt, timeout=30):
    """
    Send the RAG-grounded prompt to Gemini; return the full answer
    text or None. Server-side only: the API key never leaves the backend.
    """

    try:
        client = _gemini_client(timeout)
    except Exception as error:
        _record_provider_error(_classify_provider_error(error))
        return None

    tried = []
    only_not_found = True

    for model_name in _model_candidates():
        tried.append(model_name)
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )

            answer = (
                getattr(response, "text", "")
                or ""
            ).strip()

            if answer:
                print(f"GEMINI OK model={model_name} chars={len(answer)}")
                return answer

            only_not_found = False

        except Exception as error:
            code = _classify_provider_error(error)
            _record_provider_error(code, model=model_name)
            if code != "model_not_found":
                only_not_found = False
            # Stop immediately on auth errors - trying more models
            # with the same invalid key is pointless.
            if code in ("auth_invalid", "auth_missing"):
                return None
            continue

    # Same retired-model recovery as before: only when every
    # explicitly configured model said model_not_found.
    if only_not_found:
        for model_name in _defaults_after(tried):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
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
    try:
        client = _gemini_client(timeout)
    except Exception as error:
        _record_provider_error(_classify_provider_error(error))
        return
    tried = []
    only_not_found = True
    for model_name in _model_candidates():
        tried.append(model_name)
        try:
            response = client.models.generate_content_stream(
                model=model_name,
                contents=prompt,
            )
            yielded = False
            for chunk in response:
                piece = (getattr(chunk, "text", "") or "")
                if piece:
                    yielded = True
                    yield piece
            if yielded:
                return
            only_not_found = False
        except Exception as error:
            code = _classify_provider_error(error)
            _record_provider_error(code, model=model_name)
            if code != "model_not_found":
                only_not_found = False
            # Stop immediately on auth errors.
            if code in ("auth_invalid", "auth_missing"):
                return
            continue
    # Same retired-model recovery as _call_gemini: only when every
    # explicitly configured model said model_not_found.
    if only_not_found:
        for model_name in _defaults_after(tried):
            try:
                response = client.models.generate_content_stream(
                    model=model_name,
                    contents=prompt,
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
    """User-safe answer text when no language model is reachable.

    When a general explanation is available from the built-in study
    bank, return it as the answer (clearly labeled as a general
    explanation) without the "temporarily unavailable" notice or raw
    excerpts.  Otherwise show a friendly notice plus clearly labeled
    study-bank content - never raw error codes, model names, setup
    instructions, or stack traces. Those stay in the backend log
    (see the AI UNAVAILABLE print at the call site) and in the
    machine-readable ``error_code`` field of the response.
    """
    general = _offline_general_explanation(question)
    if general:
        # A valid fallback answer exists: present it cleanly without
        # the scary "temporarily unavailable" notice or raw excerpts.
        return (
            "General explanation (from the built-in study bank, "
            "not from your documents):\n\n"
            + general
        )
    # No general explanation available: be honest and point to excerpts.
    parts = [
        "The AI assistant is temporarily unavailable. "
        "Please try again shortly.\n"
    ]
    if results:
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
    else:
        parts.append(
            "I couldn't find relevant material in the knowledge base "
            "for that question. Try rephrasing, or ask about a "
            "specific topic (e.g. 'Explain OSI layers')."
        )
    return "\n".join(parts)


def _log_rag_timing(label, started):
    """One backend timing line per answer.

    Label carries only the answer kind, provider name, error code,
    and counts - never prompts, questions, keys, or document text.
    """
    ms = int((time.monotonic() - started) * 1000)
    print(f"RAG TIMING {label} ms={ms}")


def answer_with_rag(
    question,
    subject_code=None,
    module_number=None,
    limit=5,
    mode="detailed",
    history=None,
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
        _log_rag_timing("kind=cached", started)
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
        history=history,
    )

    results = rag_data["results"]
    prompt = rag_data["prompt"]

    timeout = MODE_TIMEOUTS[mode]
    max_tokens = {"fast": 1200, "detailed": 3000}[mode]

    provider = active_provider()

    # Try the configured model provider (gemini by default).
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
                    "suggestions": generate_followup_suggestions(question, answer),
                }
                cache_put(
                    cache_key(question, subject_code, module_number, mode, kb_version),
                    response,
                )
                _log_rag_timing(
                    "kind=ai_generated provider=" + response["provider"],
                    started)
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
                    "suggestions": generate_followup_suggestions(question, answer),
                }
                cache_put(
                    cache_key(question, subject_code, module_number, mode, kb_version),
                    response,
                )
                _log_rag_timing(
                    "kind=ai_generated provider=" + response["provider"],
                    started)
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
                    "suggestions": generate_followup_suggestions(question, answer),
                }
                cache_put(
                    cache_key(question, subject_code, module_number, mode, kb_version),
                    response,
                )
                _log_rag_timing(
                    "kind=ai_generated provider=" + response["provider"],
                    started)
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
        effective_provider = provider or configured_provider()
        # Developer-facing diagnostic only (backend log): the setup
        # hint names env vars and local URLs but never secrets, and
        # the user-facing text above carries no technical details.
        print(
            f"AI UNAVAILABLE provider={effective_provider} "
            f"error={error_code} "
            f"hint={_provider_hint(effective_provider, error_code)}"
        )
        fallback_answer = _compose_no_provider_answer(
            question, results, provider=effective_provider,
            error_code=error_code)

        # Determine if a general explanation was provided (so the
        # frontend can avoid showing "AI temporarily unavailable").
        _has_general = _offline_general_explanation(question) is not None

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
            "suggestions": generate_followup_suggestions(question, fallback_answer),
            "has_general_explanation": _has_general,
        }
        # Deliberately NOT cached: a failed answer must never be
        # re-served for hours (6h TTL) after the provider recovers.
        # Success responses above are cached; failures always retry.
        _log_rag_timing(
            f"kind=fallback error={error_code} "
            f"results={len(results)}",
            started)
        return response

    _log_rag_timing("kind=no_results", started)
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
                  mode="detailed", limit=None, history=None):
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
        history=history,
    )
    results = rag_data["results"]
    prompt = rag_data["prompt"]

    yield {"event": "sources", "data": {"sources": results}}

    timeout = MODE_TIMEOUTS[mode]
    max_tokens = {"fast": 1200, "detailed": 3000}[mode]
    provider = active_provider()
    streamed = False
    stream_provider = None
    full_text_parts = []  # accumulated answer text (for suggestions)

    from utils import ollama_provider as _ollama
    from utils import openai_provider as _openai

    if provider == "openai":
        try:
            for piece in _openai.stream_pieces(
                prompt, timeout=timeout, max_tokens=max_tokens
            ):
                streamed = True
                stream_provider = "openai"
                full_text_parts.append(piece)
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
                full_text_parts.append(piece)
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
                full_text_parts.append(piece)
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
        full_text_parts.append(composed)
        for start in range(0, len(composed), 1200):
            yield {"event": "token",
                   "data": {"text": composed[start:start + 1200]}}

    full_answer = "".join(full_text_parts)
    answer_kind = ("ai_generated" if streamed else
                   ("fallback_excerpts" if results else "no_results"))

    done_data = {
        "used_rag": bool(results),
        "used_ai": streamed,
        "provider": stream_provider,
        "answer_kind": answer_kind,
        "error_code": None if streamed else (
            get_last_provider_error().get("code") or "provider_not_configured"
        ) if results else None,
        "mode": mode,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }

    # Attach suggestions for every non-empty answer. For successful AI
    # answers they are topic-specific; for fallback answers they are
    # generic follow-ups so the chat stays useful even when the
    # provider is unavailable. Skip only for empty/no-results answers.
    if full_answer.strip():
        done_data["suggestions"] = generate_followup_suggestions(
            question, full_answer)
        # Tell the frontend whether a general explanation was provided
        # so it can avoid showing "AI temporarily unavailable".
        done_data["has_general_explanation"] = (
            _offline_general_explanation(question) is not None
            and not streamed
        )

    yield {"event": "done", "data": done_data}


# ---------------------------------------------------------------------------
# Dynamic follow-up suggestions
# ---------------------------------------------------------------------------

# Each entry: (keywords that match the question/answer, [suggestions]).
# Used as a lightweight, on-topic fallback when the AI provider does not
# return structured suggestions alongside its answer. Suggestion sets are
# drawn from the examples in the product requirements and cover the most
# common VTU CSE topics.
FOLLOWUP_TOPICS = (
    (
        ["halting", "undecidable", "decidable", "computability",
         "turing machine", "reduction", "recursively enumerable"],
        [
            "Explain decidable and undecidable problems.",
            "State the pumping lemma for regular languages.",
            "Explain the difference between DFA and NFA.",
            "Give an example of a reduction used to prove undecidability.",
        ],
    ),
    (
        ["csma", "cdma", "access control", "medium access", "ethernet",
         "collision", "carrier sense", "mac protocol", "aluha", "slotted"],
        [
            "Explain CSMA/CD and CSMA/CA access methods.",
            "What is the difference between CSMA/CD and CSMA/CA?",
            "Explain the binary exponential backoff algorithm.",
            "How does Ethernet handle collisions?",
        ],
    ),
    (
        ["waterfall", "agile", "scrum", "spiral", "sdlc",
         "software engineering", "development model"],
        [
            "What are the advantages and disadvantages of Waterfall?",
            "Explain the phases of the Waterfall Model with an example.",
            "Compare Waterfall and Agile in a table.",
        ],
    ),
    (
        ["osi", "layers of", "reference model", "seven layers", "7 layers",
         "physical layer", "data link", "network layer", "transport layer",
         "session layer", "presentation layer", "application layer"],
        [
            "Explain the functions of each OSI layer.",
            "What is the difference between TCP and UDP?",
            "Give important OSI model exam questions.",
        ],
    ),
    (
        ["tcp", "udp", "tcp/ip", "tcp ip", "handshake", "datagram",
         "transport layer"],
        [
            "Explain the TCP 3-way handshake with an example.",
            "What is the difference between TCP and UDP?",
            "When would you use UDP instead of TCP?",
        ],
    ),
    (
        ["dfa", "nfa", "finite automata", "automata", "epsilon",
         "regular language", "pumping", "subset construction"],
        [
            "Convert an NFA into an equivalent DFA.",
            "Explain epsilon transitions with an example.",
            "Compare DFA and NFA in a table.",
        ],
    ),
    (
        ["normalization", "1nf", "2nf", "3nf", "bcnf",
         "functional dependency", "database", "dbms"],
        [
            "What is the difference between 3NF and BCNF?",
            "Explain normalization with an example.",
            "What are transitive and partial dependencies?",
        ],
    ),
    (
        ["scheduling", "fcfs", "sjf", "round robin", "gantt",
         "cpu scheduling", "waiting time", "process"],
        [
            "Explain Round Robin scheduling with a Gantt chart.",
            "What is the difference between SJF and SRTF?",
            "Compare CPU scheduling algorithms in a table.",
        ],
    ),
    (
        ["acid", "transaction", "isolation", "durability",
         "atomicity", "consistency"],
        [
            "What are the ACID properties of a transaction?",
            "Explain transaction isolation levels.",
            "What is the difference between commit and rollback?",
        ],
    ),
    (
        ["computer network", "types of networks", "lan wan man",
         "networking", "hub", "switch", "router"],
        [
            "What is the difference between LAN, MAN, and WAN?",
            "Explain network devices: hub, switch, and router.",
            "What is TCP/IP and how does it work?",
        ],
    ),
    (
        ["ip address", "subnet", "subnetting", "cidr", "ipv4",
         "classful", "mask"],
        [
            "How does subnetting work with an example?",
            "What is the difference between IPv4 and IPv6?",
            "Explain CIDR notation with examples.",
        ],
    ),
    (
        ["testing", "black-box", "white box", "unit test",
         "integration test", "boundary value", "software testing"],
        [
            "What is the difference between black-box and white-box testing?",
            "Explain boundary value analysis with an example.",
            "What are the levels of software testing?",
        ],
    ),
    (
        ["cocomo", "cost estimation", "effort estimation", "kloc",
         "software cost"],
        [
            "What are the three COCOMO modes?",
            "Explain COCOMO with a worked example.",
            "What is the difference between basic and intermediate COCOMO?",
        ],
    ),
)

GENERAL_FOLLOWUPS = [
    "Explain this topic with an example.",
    "Give important exam questions on this topic.",
    "Compare related concepts in a table.",
]


def _keyword_in_text(keyword, lowered):
    """Match *keyword* in *lowered* text.

    Short single-word keywords (like "osi", "tcp", "dfa") are matched
    with word boundaries so they don't fire inside unrelated words
    ("decomposing" contains "osi", "process" contains... well, not
    "osi", but the point stands). Multi-word phrases and longer
    keywords keep the simpler substring match.
    """
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return False
    if " " in keyword:
        return keyword in lowered
    if len(keyword) < 5:
        return bool(re.search(
            r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])",
            lowered,
        ))
    return keyword in lowered


def _match_followup_topic(text):
    """Return a suggestion list for *text* when a topic keyword matches."""
    lowered = (text or "").lower()
    for _keywords, suggestions in FOLLOWUP_TOPICS:
        if any(_keyword_in_text(k, lowered) for k in _keywords):
            return suggestions
    return None


def generate_followup_suggestions(question, answer):
    """Return 3-4 on-topic follow-up suggestions for *question* + *answer*.

    Falls back to generic suggestions when no topic matches. Never raises.
    """
    combined = f"{question or ''} {answer or ''}"
    specific = _match_followup_topic(combined)
    if specific:
        return list(specific[:4])
    return list(GENERAL_FOLLOWUPS[:3])


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