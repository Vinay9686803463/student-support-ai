"""Tiny in-process answer cache with KB-version invalidation.

Key = (normalized question, subject, module, mode, kb_version).
kb_version changes whenever documents/chunks change, so stale answers
are never served after an upload, delete, or re-index. Thread-safe
enough for the Flask dev server (single process, GIL-guarded dict ops
plus a lock for compound updates).
"""

import hashlib
import threading
import time


_CACHE = {}
_LOCK = threading.Lock()
_MAX_ENTRIES = 256
_TTL_SECONDS = 6 * 60 * 60


def cache_key(question, subject_code=None, module_number=None, mode="detailed",
              kb_version=""):
    normalized = (question or "").strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
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
