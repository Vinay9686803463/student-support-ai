"""Ollama provider for free local AI-generated study answers.

Configuration (server-side environment only, never frontend/Git):
  AI_PROVIDER=ollama - select this provider in utils/rag_ai.py.
  OLLAMA_URL     - optional; default "http://localhost:11434".
  OLLAMA_MODEL   - optional override; default "llama3.1:8b".
                   Pull it first:  ollama pull llama3.1:8b
                   (needs a running daemon:  ollama serve)

Uses only the Python standard library (urllib) against Ollama's
local HTTP API, so no extra dependency is required. Nothing secret
is ever logged or returned to the client (there is no API key;
only the local server URL, which is not sensitive).
"""

import json
import os
import urllib.error
import urllib.request

DEFAULT_MODEL = "llama3.1:8b"
DEFAULT_URL = "http://localhost:11434"
_AVAILABILITY_TIMEOUT = 3


def configured_model():
    """Model name from env, defaulting to the documented default."""
    name = (os.getenv("OLLAMA_MODEL") or "").strip()
    return name or DEFAULT_MODEL


def configured_url():
    """Ollama base URL from env, defaulting to local."""
    return (os.getenv("OLLAMA_URL") or "").strip() or DEFAULT_URL


def _tags():
    """Parsed /api/tags payload, or raise the connection error."""
    request = urllib.request.Request(
        configured_url().rstrip("/") + "/api/tags",
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=_AVAILABILITY_TIMEOUT) as reply:
        return json.loads(reply.read().decode("utf-8"))


def ollama_available():
    """True when the Ollama daemon answers AND the model is pulled."""
    try:
        models = _tags().get("models", [])
        names = {str(m.get("name", "")).split(":")[0] for m in models}
        want = configured_model().split(":")[0]
        if want and want not in names and configured_model() not in {
                str(m.get("name", "")) for m in models}:
            return False
        return True
    except Exception:
        return False


def _post(path, payload, timeout):
    """POST JSON to Ollama; return the parsed response or raise."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        configured_url().rstrip("/") + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise _HttpStatusError(error.code, error.reason)


class _HttpStatusError(Exception):
    def __init__(self, status, reason=""):
        super().__init__(f"ollama HTTP {status} {reason}".strip())
        self.status_code = status


def classify_ollama_error(error):
    """Map an Ollama failure to a stable error code (no secrets)."""
    status = getattr(error, "status_code", None)
    if status == 404:
        return "model_not_found"
    if isinstance(status, int) and status >= 500:
        return "server_error"
    if isinstance(status, int) and status >= 400:
        return "bad_request"

    name = type(error).__name__
    text = f"{name}: {error}".lower()
    if "timed out" in text or "timeout" in text or "deadline" in text:
        return "timeout"
    # Connection refused / DNS / unreachable daemon.
    if ("urlerror" in text or "connection refused" in text
            or "connect" in text or "dns" in text or "resolve" in text
            or "network" in text or "unreachable" in text
            or "no route" in text or "name or service" in text):
        return "network"
    return "unknown"


def generate_answer(prompt, timeout=60, max_tokens=1200, model=None):
    """Full generated answer text, or raise the connection/HTTP error."""
    data = _post("/api/generate", {
        "model": model or configured_model(),
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens},
    }, timeout=timeout)
    return (data.get("response") or "").strip()


def stream_pieces(prompt, timeout=120, max_tokens=1800, model=None):
    """Yield generated text pieces as Ollama streams NDJSON lines."""
    body = json.dumps({
        "model": model or configured_model(),
        "prompt": prompt,
        "stream": True,
        "options": {"num_predict": max_tokens},
    }).encode("utf-8")
    request = urllib.request.Request(
        configured_url().rstrip("/") + "/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        reply = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        raise _HttpStatusError(error.code, error.reason)
    with reply:
        for raw_line in reply:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            piece = event.get("response") or ""
            if piece:
                yield piece
            if event.get("done"):
                break
