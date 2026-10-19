import os
import time

from dotenv import load_dotenv

from utils.answer_cache import cache_key, get as cache_get, kb_version_from_stats, put as cache_put
from utils import openai_provider
from utils.rag import MODE_CONTEXT_CHARS, MODE_LIMITS, prepare_rag_request


load_dotenv()


# Mode defaults: retrieval budget + provider timeout per mode.
# Timeouts are ceilings: a healthy answer streams in ~4-15s, so a
# hung provider must bail well before the user is left waiting a
# minute+. Overridable via PROVIDER_TIMEOUT_FAST / PROVIDER_TIMEOUT_DETAILED.
def _env_timeout(name, default):
    """Provider ceiling from env (seconds), bounded to at least 5s."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return max(float(raw), 5)
    except ValueError:
        return default


MODE_TIMEOUTS = {
    "fast": _env_timeout("PROVIDER_TIMEOUT_FAST", 30.0),
    "detailed": _env_timeout("PROVIDER_TIMEOUT_DETAILED", 75.0),
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


# ----------------------------------------------------------------------------
# Provider cooldown (bounded fallback strategy)
#
# Known-fatal provider states — a rejected key, an exhausted quota — cannot
# change between two attempts inside one message, and historically re-attempting
# them on every message added full provider timeouts to every answer (the
# "thinking for minutes" symptom). After such a failure the provider is parked
# briefly; meanwhile answers still work instantly through the honest study-bank
# fallback path. Purely time-based: service resumes automatically, and any
# successful generation clears it immediately. Never prints or stores secrets.
# ----------------------------------------------------------------------------

_COOLDOWN_CODES = frozenset({
    "auth_invalid", "quota_exceeded", "quota_exhausted",
})
_PROVIDER_COOLDOWN = {"provider": None, "code": None, "until": 0.0}


def _provider_cooldown_seconds():
    return _env_timeout("PROVIDER_COOLDOWN_SECONDS", 300.0)


def _start_provider_cooldown(code, provider=None):
    seconds = _provider_cooldown_seconds()
    if seconds <= 0:
        return
    if code in _COOLDOWN_CODES:
        _PROVIDER_COOLDOWN.update(
            {
                "provider": provider or "unknown",
                "code": code,
                "until": time.monotonic() + seconds,
            }
        )


def _provider_cooldown_code(provider=None):
    """Active cooldown code for *provider*, or None when retry is OK.

    Scoped per provider: an exhausted local Ollama or a bad OpenAI key
    must not park Gemini, and vice versa.
    """
    if _PROVIDER_COOLDOWN["until"] <= time.monotonic():
        return None
    if provider and _PROVIDER_COOLDOWN["provider"] not in (None, provider):
        return None
    return _PROVIDER_COOLDOWN["code"]


def _clear_provider_cooldown():
    _PROVIDER_COOLDOWN.update(
        {"provider": None, "code": None, "until": 0.0}
    )


def _record_provider_error(code, model=None, provider=None):
    _LAST_PROVIDER_ERROR.update(
        {"code": code, "model": model, "at": time.time()}
    )
    print(f"PROVIDER ERROR [{code}] model={model or 'unknown'}")
    _start_provider_cooldown(code, provider=provider)


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


_GENAI_STATE = {"key": None}
_GENAI_MODEL_CACHE = {}


def _ensure_genai():
    """Configure the Google SDK once per key change (not per message)."""
    import google.generativeai as genai

    key = _gemini_key()
    if key and _GENAI_STATE["key"] != key:
        genai.configure(api_key=key)
        _GENAI_STATE["key"] = key
        _GENAI_MODEL_CACHE.clear()
    return genai


def _gemini_models():
    """Reusable GenerativeModel objects, in candidate order.

    Model objects are cached for the life of the process — building
    them inside the request path is pure per-message overhead.
    """
    genai = _ensure_genai()

    for model_name in _model_candidates():
        model = _GENAI_MODEL_CACHE.get(model_name)
        if model is None:
            try:
                model = genai.GenerativeModel(model_name)
            except Exception:
                continue
            _GENAI_MODEL_CACHE[model_name] = model
        yield model


# Errors that cannot improve by switching model name/account-side state:
# one attempt is always enough before falling back honestly.
_NO_FALLBACK_CODES = frozenset({
    "timeout", "auth_invalid", "auth_missing", "quota_exceeded",
    "rate_limited",
})


def _call_gemini(prompt, timeout=30):
    """
    Send the RAG-grounded prompt to Gemini; return the full answer
    text or None. Server-side only: the API key never leaves the backend.

    Bounded by design: a timeout is never paid twice (one wait is
    already the user-visible worst case), and quick failures rotate to
    the next configured model at most once.
    """
    tried = 0

    for model in _gemini_models():
        tried += 1

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
                _clear_provider_cooldown()
                return answer

        except Exception as error:
            code = _classify_provider_error(error)
            _record_provider_error(code, model=model_name, provider="gemini")
            if code in _NO_FALLBACK_CODES or tried > 1:
                break

    return None


def _stream_gemini(prompt, timeout=30):
    """Yield Gemini answer pieces as they arrive (empty if unavailable).

    Bounded by design: at most one fallback candidate, no second
    timeout wait, and — critically — an answer that already emitted
    pieces is never restarted by another model (that would duplicate
    the streamed text).
    """
    emitted = False
    tried = 0

    for model in _gemini_models():
        tried += 1
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
            for chunk in response:
                piece = (getattr(chunk, "text", "") or "")
                if piece:
                    emitted = True
                    yield piece
            if emitted:
                _clear_provider_cooldown()
                return
        except Exception as error:
            code = _classify_provider_error(error)
            _record_provider_error(code, model=model_name, provider="gemini")
            if emitted:
                break
            if code in _NO_FALLBACK_CODES or tried > 1:
                break


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
    if error_code in ("quota_exhausted", "quota_exceeded"):
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
    # Sources are kept internally (passed to the AI as context) but
    # never displayed in the chat UI.
    return "\n".join(parts)


def answer_with_rag(
    question,
    subject_code=None,
    module_number=None,
    limit=5,
    mode="detailed",
    history=None,
    recent_topics=None,
    recent_suggestions=None,
    semester=None,
    attachments_text=None,
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

    # Attached material changes the answer, so requests carrying
    # attachments bypass the shared cache instead of widening the
    # cache key (attachment-modified answers must never be served to
    # a later attachment-free ask of the same question).
    if cached is not None and not attachments_text:

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
        history=history,
        attachments_text=attachments_text,
    )

    results = rag_data["results"]
    prompt = rag_data["prompt"]

    timeout = MODE_TIMEOUTS[mode]
    max_tokens = {"fast": 800, "detailed": 1800}[mode]

    provider = active_provider()

    # Bounded fallback strategy: while a fatal provider state (bad key /
    # exhausted quota) is parked, skip straight to the honest study-bank
    # fallback instead of paying a network timeout on every message.
    if provider and _provider_cooldown_code(provider):
        provider = None

    # Try the configured model provider (OpenAI by default).
    if provider == "openai":

        try:

            answer = openai_provider.generate_answer(
                prompt,
                timeout=timeout,
                max_tokens=max_tokens,
            )

            if answer:

                _clear_provider_cooldown()
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
                    "suggestions": generate_followup_suggestions(
                        question, answer, recent_topics,
                        recent_suggestions=recent_suggestions,
                        subject_code=subject_code,
                        semester=semester),
                }
                if not attachments_text:
                    cache_put(
                        cache_key(question, subject_code, module_number, mode, kb_version),
                        response,
                    )
                return response

        except Exception as error:
            _record_provider_error(
                openai_provider.classify_openai_error(error),
                model=openai_provider.configured_model(),
                provider="openai",
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

                _clear_provider_cooldown()
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
                    "suggestions": generate_followup_suggestions(
                        question, answer, recent_topics,
                        recent_suggestions=recent_suggestions,
                        subject_code=subject_code,
                        semester=semester),
                }
                if not attachments_text:
                    cache_put(
                        cache_key(question, subject_code, module_number, mode, kb_version),
                        response,
                    )
                return response

        except Exception as error:
            _record_provider_error(
                _ollama.classify_ollama_error(error),
                model=_ollama.configured_model(),
                provider="ollama",
            )

    elif provider == "gemini" and gemini_available():

        try:

            answer = _call_gemini(
                prompt,
                timeout=timeout,
            )

            if answer:

                _clear_provider_cooldown()
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
                    "suggestions": generate_followup_suggestions(
                        question, answer, recent_topics,
                        recent_suggestions=recent_suggestions,
                        subject_code=subject_code,
                        semester=semester),
                }
                if not attachments_text:
                    cache_put(
                        cache_key(question, subject_code, module_number, mode, kb_version),
                        response,
                    )
                return response

        except Exception as error:
            _record_provider_error(_classify_provider_error(error),
                                   provider="gemini")

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
            "suggestions": generate_followup_suggestions(
                question, fallback_answer, recent_topics,
                recent_suggestions=recent_suggestions,
                subject_code=subject_code,
                semester=semester),
        }
        if not attachments_text:
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
        "suggestions": generate_followup_suggestions(
            question, "", recent_topics,
            recent_suggestions=recent_suggestions,
            subject_code=subject_code,
            semester=semester),
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
                  mode="detailed", limit=None, history=None,
                  recent_topics=None,
                  recent_suggestions=None,
                  semester=None,
                  attachments_text=None):
    """Yield SSE-ready dicts: context event, answer pieces, done event.

    Uses Gemini streaming when configured; otherwise streams the
    composed study-bank answer in pieces (real content, no fake delays).
    """
    mode = normalize_mode(mode)
    started = time.monotonic()

    question = (question or "").strip()

    if limit in (None, 0):
        limit = MODE_LIMITS[mode]

    # Instant cache reuse for the streaming path: the key includes the
    # knowledge-base version AND fingerprints of any private context
    # (conversation history / attachments), so a hit can only serve the
    # answer computed from byte-identical context. Chunks stream in big
    # honest pieces — no artificial typing delay.
    kb_version = current_kb_version()
    cache_key_value = cache_key(
        question, subject_code, module_number, mode, kb_version,
        history=history, attachments_text=attachments_text,
    )
    cached = cache_get(cache_key_value)
    if cached is not None:
        cached = dict(cached)
        answer_text = cached.get("answer") or ""
        for start in range(0, len(answer_text), 1200):
            yield {"event": "token",
                   "data": {"text": answer_text[start:start + 1200]}}
        yield {"event": "done", "data": {
            "used_rag": bool(cached.get("sources")),
            "used_ai": bool(cached.get("used_ai")),
            "provider": cached.get("provider"),
            "answer_kind": cached.get("answer_kind"),
            "error_code": cached.get("error_code"),
            "mode": mode,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "suggestions": (cached.get("suggestions")
                            or generate_followup_suggestions(
                                question, answer_text, recent_topics,
                                recent_suggestions=recent_suggestions,
                                subject_code=subject_code,
                                semester=semester)),
            "cached": True,
        }}
        return

    rag_data = prepare_rag_request(
        question=question,
        subject_code=subject_code,
        module_number=module_number,
        limit=limit,
        max_chars_per_source=MODE_CONTEXT_CHARS[mode],
        history=history,
        attachments_text=attachments_text,
    )
    results = rag_data["results"]
    prompt = rag_data["prompt"]

    yield {"event": "sources", "data": {"sources": results}}

    timeout = MODE_TIMEOUTS[mode]
    max_tokens = {"fast": 800, "detailed": 1800}[mode]
    provider = active_provider()

    # Bounded fallback strategy (same as answer_with_rag): skip the
    # provider while a fatal state (bad key / exhausted quota) is parked,
    # so repeat questions cannot re-pay the network wait.
    if provider and _provider_cooldown_code(provider):
        provider = None

    streamed = False
    stream_provider = None
    answer_parts = []

    from utils import ollama_provider as _ollama
    from utils import openai_provider as _openai

    if provider == "openai":
        try:
            for piece in _openai.stream_pieces(
                prompt, timeout=timeout, max_tokens=max_tokens
            ):
                streamed = True
                stream_provider = "openai"
                answer_parts.append(piece)
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
                answer_parts.append(piece)
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
                answer_parts.append(piece)
                yield {"event": "token", "data": {"text": piece}}
        except Exception as stream_error:
            _record_provider_error(_classify_provider_error(stream_error),
                                   provider="gemini")

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
        answer_parts.append(composed)
        for start in range(0, len(composed), 1200):
            yield {"event": "token",
                   "data": {"text": composed[start:start + 1200]}}

    full_answer = "".join(answer_parts)
    suggestions = generate_followup_suggestions(
        question, full_answer, recent_topics,
        recent_suggestions=recent_suggestions,
        subject_code=subject_code,
        semester=semester,
    )
    if streamed and full_answer:
        # Remember AI-generated answers for instant reuse. Only real
        # generated answers are cached here; fallback/limitation texts
        # always regenerate fresh so recovered provider state is
        # reflected immediately.
        cache_put(cache_key_value, {
            "answer": full_answer,
            "sources": results,
            "used_rag": bool(results),
            "used_ai": True,
            "provider": stream_provider,
            "answer_kind": "ai_generated",
            "error_code": None,
            "mode": mode,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "cached": False,
            "suggestions": suggestions,
        })
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
        "suggestions": suggestions,
        "cached": False,
    }}


# ---------------------------------------------------------------------------
# Dynamic follow-up suggestions
# ---------------------------------------------------------------------------

FOLLOWUP_TOPICS = (
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
        ["tcp", "udp", "tcp/ip", "tcp ip", "handshake", "datagram"],
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
        ["csma", "cdma", "access control", "medium access", "ethernet",
         "collision", "carrier sense", "mac protocol"],
        [
            "Explain CSMA/CD and CSMA/CA access methods.",
            "What is the difference between CSMA/CD and CSMA/CA?",
            "Explain the binary exponential backoff algorithm.",
        ],
    ),
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
    import re
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
    lowered = (text or "").lower()
    for _keywords, suggestions in FOLLOWUP_TOPICS:
        if any(_keyword_in_text(k, lowered) for k in _keywords):
            return suggestions
    return None


def _is_similar(q1, q2):
    import re
    words1 = set(re.findall(r"[a-z]{4,}", (q1 or "").lower()))
    words2 = set(re.findall(r"[a-z]{4,}", (q2 or "").lower()))
    if not words1 or not words2:
        return False
    overlap = len(words1 & words2)
    return overlap >= 2 and overlap / min(len(words1), len(words2)) > 0.5


def generate_followup_suggestions(question, answer, recent_topics=None, **kwargs):
    """Backward-compatible entry point.

    Accepts the legacy positional ``recent_topics`` plus a flexible set of
    keyword arguments (recent questions/suggestions, subject/semester filters,
    subject lists, ...) used by the newer implementation.
    """
    if "recent_topics" not in kwargs or kwargs.get("recent_topics") is None:
        kwargs["recent_topics"] = recent_topics
    try:
        return _generate_followup_suggestions_impl(question, answer, **kwargs)
    except Exception:
        try:
            return [s for s in GENERAL_FOLLOWUPS]
        except Exception:
            return ["Explain this topic with an example."]


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

    return sources# ---------------------------------------------------------------------------
# Subject-aware follow-up suggestion engine (appended)
# ---------------------------------------------------------------------------

NON_LISTED_SUBJECT_CODES = frozenset({"BCS515x", "BNSK559", "BPEK559"})


def _normalize_text(value):
    return " ".join(str(value or "").strip().lower().split())


def _normalize_subject_entry(entry):
    if isinstance(entry, dict):
        code = (entry.get("code") or entry.get("subject_code")
                or entry.get("id") or entry.get("subject"))
        name = (entry.get("name") or entry.get("subject_name")
                or entry.get("title") or entry.get("subject"))
    elif isinstance(entry, (tuple, list)):
        code = entry[0] if len(entry) > 0 else None
        name = entry[1] if len(entry) > 1 else code
    else:
        code = entry
        name = entry
    code = str(code).strip().upper() if code is not None else ""
    name = str(name).strip() if name is not None else code
    if not name:
        name = code
    return {"code": code, "name": name}


def _dedupe_subjects(subjects):
    seen = set()
    result = []
    for entry in subjects or []:
        subj = _normalize_subject_entry(entry)
        if not subj["code"] and not subj["name"]:
            continue
        key = _normalize_text(subj["name"]) or subj["code"]
        if key in seen:
            continue
        seen.add(key)
        result.append(subj)
    return result


FALLBACK_SUPPORTED_SUBJECTS = [
    ("BCS501", "Software Engineering & Project Management"),
    ("BCS502", "Computer Networks"),
    ("BCS503", "Theory of Computation"),
    ("BCS504", "Web Technology Lab"),
    ("BCS508", "Environmental Studies and E-Waste Management"),
    ("BCS515C", "Unix System Programming"),
    ("BRMK557", "Research Methodology and IPR"),
]


SUBJECT_QUESTION_TEMPLATES = {
    "BCS501": [
        "What are the advantages and disadvantages of the Waterfall model?",
        "Explain the phases of the Agile software development life cycle.",
        "What is the difference between black-box and white-box testing?",
        "Explain COCOMO cost estimation with a worked example.",
        "Compare Waterfall and Agile in a table.",
    ],
    "BCS502": [
        "Explain the functions of each OSI layer.",
        "What is the difference between TCP and UDP?",
        "Explain CSMA/CD and CSMA/CA access methods.",
        "How does routing work in a computer network?",
        "Give important Computer Networks exam questions.",
    ],
    "BCS503": [
        "Convert an NFA into an equivalent DFA.",
        "Explain decidable and undecidable problems.",
        "State the pumping lemma for regular languages.",
        "What is the difference between DFA and NFA?",
        "Explain Turing machines with an example.",
    ],
    "BCS504": [
        "Explain the difference between HTML, CSS, and JavaScript.",
        "What is the Document Object Model (DOM)?",
        "Explain client-side versus server-side scripting.",
        "How do forms and validation work in web pages?",
        "Give important Web Technology lab viva questions.",
    ],
    "BCS508": [
        "What are the 3 R's of waste management?",
        "Explain e-waste management and its environmental impact.",
        "What are the effects of pollution on the environment?",
        "Explain sustainable development with examples.",
        "Give important Environmental Studies exam questions.",
    ],
    "BCS515": [
        "What are the 3 R's of waste management?",
        "Explain e-waste management and its environmental impact.",
        "What are the effects of pollution on the environment?",
    ],
    "BCS515C": [
        "Explain process creation and termination in Unix.",
        "What are system calls in Unix? Give examples.",
        "Explain inter-process communication in Unix.",
        "How does the Unix shell handle pipes and redirection?",
        "Give important Unix System Programming exam questions.",
    ],
    "BRMK557": [
        "What are the steps of the research process?",
        "Explain different types of intellectual property rights.",
        "What is the difference between a patent and a copyright?",
        "Explain research methodology with an example.",
        "Give important Research Methodology and IPR exam questions.",
    ],
}


def _collect_strings(values):
    result = []
    if not values:
        return result
    if isinstance(values, str):
        result.append(values)
        return result
    if isinstance(values, dict):
        for key in ("questions", "recent_questions", "recent_topics",
                    "suggestions", "recent_suggestions", "displayed_suggestions",
                    "shown_suggestions", "previous_suggestions", "content",
                    "question", "text"):
            if key in values:
                result.extend(_collect_strings(values[key]))
        return result
    if isinstance(values, (list, tuple, set)):
        for item in values:
            result.extend(_collect_strings(item))
        return result
    result.append(str(values))
    return result


# Memoized subject-catalog read: follow-up suggestions asked the
# database twice per chat message (subjects + knowledge_documents).
# The catalog changes rarely, so a short TTL keeps results honest
# while removing the per-message round trips.
_SUBJECTS_CACHE = {"key": None, "at": 0.0, "value": None}
_SUBJECTS_TTL_SECONDS = 120.0


def get_supported_subjects(semester=None, subject_code=None, branch=None,
                           scheme=None, db_session=None,
                           include_materials=True):
    sem = 5 if semester is None else semester
    try:
        sem = int(sem)
    except (TypeError, ValueError):
        sem = 5

    cache_key_value = (sem, str(subject_code or "").strip(),
                       str(branch or "").strip(), str(scheme or "").strip(),
                       bool(include_materials)) if db_session is None else None
    now = time.monotonic()
    if cache_key_value is not None:
        hit = _SUBJECTS_CACHE
        if (hit["key"] == cache_key_value
                and now - hit["at"] < _SUBJECTS_TTL_SECONDS
                and hit["value"] is not None):
            return list(hit["value"])

    session = db_session
    if session is None:
        try:
            from utils.database import db as _db
            session = _db.session
        except Exception:
            session = None

    subjects = []
    knowledge_codes = set()
    knowledge_names = {}

    if session is not None:
        try:
            from sqlalchemy import text as _text
            rows = session.execute(_text(
                "SELECT subject_code, subject_name, semester, branch, scheme, "
                "category FROM subjects"
            )).mappings().all()
            for row in rows:
                row = dict(row)
                try:
                    row_sem = int(row.get("semester"))
                except (TypeError, ValueError):
                    row_sem = None
                if sem is not None and row_sem is not None and row_sem != sem:
                    continue
                if branch:
                    if str(row.get("branch", "")).strip().upper() not in ("", str(branch).strip().upper()):
                        continue
                if scheme:
                    if str(row.get("scheme", "")).strip() not in ("", str(scheme).strip()):
                        continue
                code = str(row.get("subject_code") or "").strip().upper()
                if not code or code in NON_LISTED_SUBJECT_CODES:
                    continue
                category = row.get("category")
                if category and str(category).strip().lower() == "activity":
                    continue
                name = str(row.get("subject_name") or code).strip()
                subjects.append({"code": code, "name": name})
        except Exception:
            subjects = []

        try:
            from sqlalchemy import text as _text
            kd_rows = session.execute(_text(
                "SELECT DISTINCT subject_code, subject_name FROM knowledge_documents"
            )).mappings().all()
            for row in kd_rows:
                row = dict(row)
                code = str(row.get("subject_code") or "").strip().upper()
                name = str(row.get("subject_name") or code).strip()
                if code:
                    knowledge_codes.add(code)
                    knowledge_names[code] = name
        except Exception:
            knowledge_codes = set()

    if subjects and include_materials and knowledge_codes:
        material_subjects = [
            {"code": s["code"],
             "name": knowledge_names.get(s["code"], s["name"])}
            for s in subjects if s["code"] in knowledge_codes
        ]
        if material_subjects:
            subjects = material_subjects

    if include_materials and knowledge_codes:
        existing_codes = {s["code"] for s in subjects}
        for code, name in knowledge_names.items():
            if code in existing_codes:
                continue
            if sem == 5 and not (code.startswith("BCS5") or code.startswith("BRMK5") or code.startswith("BCSL5")):
                continue
            subjects.append({"code": code, "name": name})

    if subject_code:
        wanted = str(subject_code).strip()
        filtered = [s for s in subjects
                    if s["code"] == wanted.upper()
                    or s["name"].strip().lower() == wanted.lower()]
        if filtered:
            subjects = filtered

    subjects = _dedupe_subjects(subjects)

    if not subjects and sem == 5:
        subjects = _dedupe_subjects(
            [{"code": c, "name": n} for c, n in FALLBACK_SUPPORTED_SUBJECTS]
        )
        if subject_code:
            wanted = str(subject_code).strip()
            filtered = [s for s in subjects
                        if s["code"] == wanted.upper()
                        or s["name"].strip().lower() == wanted.lower()]
            if filtered:
                subjects = filtered

    if cache_key_value is not None:
        _SUBJECTS_CACHE.update(
            {"key": cache_key_value, "at": now, "value": subjects}
        )

    return subjects


def get_supported_fifth_semester_subjects(*args, **kwargs):
    kwargs.setdefault("semester", 5)
    return get_supported_subjects(*args, **kwargs)


def get_subjects_for_semester(semester=5, *args, **kwargs):
    return get_supported_subjects(semester=semester, *args, **kwargs)


def list_supported_subjects(*args, **kwargs):
    return get_supported_subjects(*args, **kwargs)


def supported_subjects(*args, **kwargs):
    return get_supported_subjects(*args, **kwargs)


def _templates_for_subject(subj):
    code = subj["code"]
    name = subj["name"]
    if code in SUBJECT_QUESTION_TEMPLATES:
        return list(SUBJECT_QUESTION_TEMPLATES[code])
    for key, value in SUBJECT_QUESTION_TEMPLATES.items():
        if key.lower() == name.lower():
            return list(value)
    return [
        "What are the core concepts of %s?" % name,
        "Explain an important topic in %s with an example." % name,
        "Give important exam questions on %s." % name,
        "Compare two key concepts in %s." % name,
    ]


def _generate_followup_suggestions_impl(question, answer, **kwargs):
    recent_questions = _collect_strings(
        kwargs.get("recent_questions") or kwargs.get("recentQuestions"))
    recent_questions += _collect_strings(kwargs.get("recent_topics"))
    if question:
        recent_questions.append(str(question))

    recent_suggestions = []
    for key in ("recent_suggestions", "displayed_suggestions",
                "shown_suggestions", "previous_suggestions",
                "recent_displayed_suggestions", "displayed"):
        recent_suggestions += _collect_strings(kwargs.get(key))

    subject_code = (kwargs.get("subject_code") or kwargs.get("subject")
                    or kwargs.get("selected_subject")
                    or kwargs.get("current_subject"))
    semester = (kwargs.get("semester") or kwargs.get("semester_number")
                or kwargs.get("selected_semester")
                or kwargs.get("current_semester"))
    subjects_arg = (kwargs.get("subjects") or kwargs.get("supported_subjects")
                    or kwargs.get("subject_list")
                    or kwargs.get("available_subjects")
                    or kwargs.get("subjects_list"))

    if subjects_arg:
        if isinstance(subjects_arg, (str, dict)):
            subjects_arg = [subjects_arg]
        all_subjects = _dedupe_subjects(
            [_normalize_subject_entry(x) for x in subjects_arg]
        )
    else:
        all_subjects = get_supported_subjects(
            semester=semester, subject_code=None, branch=kwargs.get("branch"),
            scheme=kwargs.get("scheme"), db_session=kwargs.get("db_session"),
            include_materials=kwargs.get("include_materials", True),
        )

    if not all_subjects and semester is None:
        all_subjects = get_supported_subjects(semester=5)

    banned = recent_questions + recent_suggestions

    selected_subjects = None
    if subject_code:
        wanted = str(subject_code).strip()
        selected_subjects = [s for s in all_subjects
                             if s["code"] == wanted.upper()
                             or s["name"].strip().lower() == wanted.lower()]
        if not selected_subjects:
            selected_subjects = [{"code": wanted.upper(), "name": wanted}]
    pool_subjects = selected_subjects if selected_subjects else all_subjects

    if not pool_subjects:
        pool_subjects = [{"code": "GENERAL", "name": "your studies"}]

    if subject_code:
        max_count = min(4, max(1, len(_templates_for_subject(pool_subjects[0]))))
    else:
        max_count = len(pool_subjects)
        if max_count < 3:
            max_count = min(4, max_count + 1)
        if max_count > 12:
            max_count = 12

    def is_banned(candidate):
        cand = _normalize_text(candidate)
        if not cand:
            return True
        if _normalize_text(question) and cand == _normalize_text(question):
            return True
        for item in banned:
            if _is_similar(candidate, item):
                return True
        return False

    suggestions = []
    used = set()
    max_rounds = max((len(_templates_for_subject(s)) for s in pool_subjects), default=1)
    for rnd in range(max_rounds):
        for subj in pool_subjects:
            templates = _templates_for_subject(subj)
            if rnd >= len(templates):
                continue
            candidate = templates[rnd]
            key = _normalize_text(candidate)
            if key in used:
                continue
            if is_banned(candidate):
                continue
            used.add(key)
            suggestions.append(candidate)
            if len(suggestions) >= max_count:
                break
        if len(suggestions) >= max_count:
            break

    if len(suggestions) < max_count:
        for candidate in GENERAL_FOLLOWUPS:
            key = _normalize_text(candidate)
            if key in used or is_banned(candidate):
                continue
            used.add(key)
            suggestions.append(candidate)
            if len(suggestions) >= max_count:
                break

    if len(suggestions) < max_count:
        for subj in pool_subjects:
            name = subj["name"]
            for candidate in (
                "Explain a core concept of %s." % name,
                "Give important exam questions on %s." % name,
            ):
                key = _normalize_text(candidate)
                if key in used or is_banned(candidate):
                    continue
                used.add(key)
                suggestions.append(candidate)
                if len(suggestions) >= max_count:
                    break
            if len(suggestions) >= max_count:
                break

    if not suggestions:
        suggestions = [g for g in GENERAL_FOLLOWUPS if not is_banned(g)] or list(GENERAL_FOLLOWUPS)

    final = []
    seen_final = set()
    for s in suggestions:
        key = _normalize_text(s)
        if key in seen_final:
            continue
        seen_final.add(key)
        final.append(s)

    return final[:max_count if max_count > 0 else 4]


def generate_follow_up_suggestions(*args, **kwargs):
    return generate_followup_suggestions(*args, **kwargs)


def get_fifth_semester_subjects(*args, **kwargs):
    kwargs.setdefault("semester", 5)
    return get_supported_subjects(*args, **kwargs)


def get_5th_semester_subjects(*args, **kwargs):
    kwargs.setdefault("semester", 5)
    return get_supported_subjects(*args, **kwargs)


def get_subjects_for_5th_semester(*args, **kwargs):
    kwargs.setdefault("semester", 5)
    return get_supported_subjects(*args, **kwargs)


def fifth_semester_subjects(*args, **kwargs):
    kwargs.setdefault("semester", 5)
    return get_supported_subjects(*args, **kwargs)


def _lazy_fifth_semester_subjects(name):
    value = get_supported_subjects(semester=5)
    globals()[name] = value
    return value


def __getattr__(name):
    """(PEP 562) Legacy fifth-semester subject constants, on demand.

    These used to run two database queries at module import — charging
    every worker boot / serverless instance (and, via app.py's boot
    banner, the first chat request) for data the suggestion engine
    already fetches lazily. Resolving them on first access keeps the
    names compatible with any external caller while making imports free.
    """
    if name in ("SUPPORTED_FIFTH_SEMESTER_SUBJECTS",
                "SUPPORTED_5TH_SEMESTER_SUBJECTS"):
        return _lazy_fifth_semester_subjects(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
