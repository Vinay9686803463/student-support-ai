"""Tiny in-process answer cache with KB-version invalidation.

Key = (normalized question, subject, module, mode, kb_version) plus
fingerprints of any private prompt context (conversation history /
attachments), so a cached answer can never be reused with different
context — e.g. one user's answer leaking to another user.
kb_version changes whenever documents/chunks change, so stale answers
are never served after an upload, delete, or re-index. Thread-safe
enough for the Flask dev server (single process, GIL-guarded dict ops
plus a lock for compound updates).
"""

import hashlib
import json
import threading
import time
import uuid


_CACHE = {}
_LOCK = threading.Lock()
_MAX_ENTRIES = 256
_TTL_SECONDS = 6 * 60 * 60


def _context_item(item):
    """JSON-safe projection of one history message (full content kept)."""
    if isinstance(item, dict):
        return {str(key): str(value) for key, value in sorted(item.items())}
    return str(item)


def _context_digest(value):
    """Fingerprint one piece of user-private prompt context.

    The RAG prompt is built from the question PLUS conversation history
    and attachment text, so a cache key that ignored them could serve
    one user's answer to someone else. Fingerprinting makes reuse safe:
    a hit can only occur when the effective prompt context is identical.
    Un-digestable objects get a unique fingerprint (never reused).
    """
    try:
        if isinstance(value, (list, tuple)):
            payload = json.dumps([_context_item(item) for item in value],
                                 sort_keys=True, default=str)
        else:
            payload = str(value)
    except Exception:
        return uuid.uuid4().hex
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def cache_key(question, subject_code=None, module_number=None, mode="detailed",
              kb_version="", history=None, attachments_text=None):
    normalized = (question or "").strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
    if history:
        digest += ":" + _context_digest(history)
    if attachments_text:
        digest += ":" + _context_digest(attachments_text)
    return (digest, subject_code or "", module_number or 0, mode, kb_version)


def kb_version_from_stats(doc_count, chunk_count, embedded_count, max_updated_at):
    """Build an opaque version string from cheap aggregate stats."""
    return f"{doc_count}:{chunk_count}:{embedded_count}:{max_updated_at or ''}"


def get(key):
    now = time.time()
    with _LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        if now - entry["at"] > _TTL_SECONDS:
            _CACHE.pop(key, None)
            return None
        return entry["value"]


def put(key, value):
    with _LOCK:
        if len(_CACHE) >= _MAX_ENTRIES:
            oldest = min(_CACHE.items(), key=lambda item: item[1]["at"])[0]
            _CACHE.pop(oldest, None)
        _CACHE[key] = {"at": time.time(), "value": value}


def invalidate_all():
    with _LOCK:
        _CACHE.clear()


def stats():
    with _LOCK:
        return {"entries": len(_CACHE), "max_entries": _MAX_ENTRIES}
