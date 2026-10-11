"""Shared thread-local database connections for retrieval paths.

The chat pipeline used to open a brand-new pooled connection per query
(version check + keyword search + vector search + subject lookup), and
each fresh connection can queue behind other writers on the hosted
pooler. One reused connection per thread removes that overhead.
Connections carry a statement timeout so a saturated database fails
fast into the fallback path instead of hanging the UI.
"""

import os
import threading

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")

STATEMENT_TIMEOUT_MS = 15000

_state = threading.local()


def _new_connection():
    import psycopg

    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=10,
        prepare_threshold=None,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )


def get_conn():
    """Return the current thread's shared connection (reconnect if dead)."""
    conn = getattr(_state, "conn", None)
    try:
        if conn is not None and not conn.closed:
            return conn
    except Exception:
        pass
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass
    conn = _new_connection()
    _state.conn = conn
    return conn


def close_conn():
    """Drop the current thread's shared connection (request teardown)."""
    conn = getattr(_state, "conn", None)
    _state.conn = None
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
