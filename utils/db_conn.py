"""Shared thread-local database connections for retrieval paths.

The chat pipeline used to open a brand-new pooled connection per query
(version check + keyword search + vector search + subject lookup), and
each fresh connection can queue behind other writers on the hosted
pooler. One reused connection per thread removes that overhead.
Connections carry a statement timeout so a saturated database fails
fast into the fallback path instead of hanging the UI.

Connections survive across requests: closing one on every request
stdout-reconnect tax to the hosted database (TLS handshake + auth per
message, measured ~100-300ms). Instead, a connection idle for a while
is health-checked with a tiny SELECT before reuse; a dead connection
reconnects transparently.
"""

import os
import threading
import time

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")

STATEMENT_TIMEOUT_MS = 15000

# Health-check a reused connection after this many idle seconds. A dead
# otherwise-looking-healthy connection (pooler restart, NAT timeout)
# sends its first query into a long client hang; a 1-round-trip ping
# prevents that cheaply (~1-10ms when healthy).
REVERIFY_IDLE_SECONDS = 90.0

_state = threading.local()


def _new_connection():
    import psycopg

    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=10,
        prepare_threshold=None,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )


def _mark_used():
    _state.last_used = time.monotonic()


def get_conn():
    """Return the current thread's shared connection (reconnect if dead)."""
    conn = getattr(_state, "conn", None)
    try:
        if conn is not None and not conn.closed:
            last_used = getattr(_state, "last_used", 0.0)
            if last_used and time.monotonic() - last_used >= REVERIFY_IDLE_SECONDS:
                # Was idle a while: verify it still answers before the
                # caller runs real queries on it.
                try:
                    with conn.cursor() as probe:
                        probe.execute("SELECT 1")
                        probe.fetchone()
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = _new_connection()
                    _state.conn = conn
            _mark_used()
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
    _mark_used()
    return conn


def close_conn():
    """Drop the current thread's shared connection (optional / tests)."""
    conn = getattr(_state, "conn", None)
    _state.conn = None
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def rollback_conn():
    """Roll back (keep) the current thread's shared connection.

    A failed statement (e.g. statement timeout) aborts the open
    transaction; without a rollback, every later query on the pooled
    connection would fail. Roll back and keep the connection — close
    only if even the rollback fails (connection half-dead).
    """
    conn = getattr(_state, "conn", None)
    if conn is None or getattr(conn, "closed", True):
        return
    try:
        conn.rollback()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        _state.conn = None
