"""Vercel startup compatibility tests (read-only app filesystem).

Regression tests for::

    OSError: [Errno 30] Read-only file system: '/var/task/instance'

raised from ``db.init_app(app)`` when Flask-SQLAlchemy resolves a
relative SQLite URI against ``app.instance_path`` and calls
``os.makedirs`` on it. Vercel's ``/var/task`` directory is read-only;
only ``/tmp`` is writable (and ephemeral).

All tests run offline: SQLite targets live under ``tmp_path`` and the
PostgreSQL cases either assert on config only or hit a
connection-refused address that ``init_database`` already tolerates.

Run: <python> -m pytest tests/test_vercel_init.py -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask

from utils import database as database_module
from utils.database import (
    _build_database_config,
    _ensure_writable_instance_path,
    _resolve_database_url,
    db,
    init_database,
)


def _fresh_app(instance_path=None):
    app = Flask(__name__)
    if instance_path is not None:
        app.instance_path = instance_path
    return app


def test_build_config_postgres_keeps_postgres_and_pool_options():
    config = _build_database_config(
        "postgresql://user:pass@host:5432/dbname")
    assert config["SQLALCHEMY_DATABASE_URI"] == \
        "postgresql://user:pass@host:5432/dbname"
    assert config["SQLALCHEMY_TRACK_MODIFICATIONS"] is False
    assert config["SQLALCHEMY_ENGINE_OPTIONS"]["pool_pre_ping"] is True


def test_build_config_sqlite_has_no_engine_options():
    config = _build_database_config("sqlite:///student_support_ai.db")
    assert config["SQLALCHEMY_DATABASE_URI"] == \
        "sqlite:///student_support_ai.db"
    assert "SQLALCHEMY_ENGINE_OPTIONS" not in config


def test_resolve_normalizes_postgres_scheme(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgres://user:pass@host:5432/dbname")
    assert _resolve_database_url() == \
        "postgresql://user:pass@host:5432/dbname"


def test_resolve_sqlite_fallback_without_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    assert _resolve_database_url() == "sqlite:///student_support_ai.db"


def test_writable_instance_path_is_noop_locally(tmp_path):
    app = _fresh_app(instance_path=str(tmp_path / "instance"))
    _ensure_writable_instance_path(app)
    # Parent (tmp_path) is writable, so Flask-SQLAlchemy can create the
    # directory itself: local development behavior is unchanged.
    assert app.instance_path == str(tmp_path / "instance")


def test_writable_instance_path_redirects_when_read_only(
        tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    # Parent does not exist / is not writable (simulates /var/task).
    app = _fresh_app(
        instance_path=str(tmp_path / "readonly-task" / "instance"))
    _ensure_writable_instance_path(app)
    assert app.instance_path == str(tmp_path / "ssa-instance")
    assert os.path.isdir(app.instance_path)


def test_init_database_sqlite_relative_succeeds_with_readonly_instance(
        tmp_path, monkeypatch):
    """The exact Vercel crash: relative sqlite + read-only app dir."""
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///vercel_crash_repro.db")
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    app = _fresh_app(
        instance_path=str(tmp_path / "readonly-task" / "instance"))
    init_database(app)  # must not raise EROFS
    assert app.config["SQLALCHEMY_DATABASE_URI"] == \
        "sqlite:///vercel_crash_repro.db"
    assert app.instance_path == str(tmp_path / "ssa-instance")
    assert os.path.isfile(
        os.path.join(app.instance_path, "vercel_crash_repro.db"))
    # Auth model untouched: both hash columns still mapped.
    assert hasattr(database_module.User, "password_hash")
    assert hasattr(database_module.User, "password")


def test_init_database_vercel_without_database_url_raises(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = _fresh_app()
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        init_database(app)


def test_init_database_vercel_with_postgres_uses_postgres(
        tmp_path, monkeypatch):
    """Postgres is preserved; refused connection is tolerated as before."""
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://u:p@127.0.0.1:1/nonexistent")
    app = _fresh_app(instance_path=str(tmp_path / "instance"))
    init_database(app)  # unreachable DB -> warning path, no raise
    assert app.config["SQLALCHEMY_DATABASE_URI"] == \
        "postgresql://u:p@127.0.0.1:1/nonexistent"
    assert "SQLALCHEMY_ENGINE_OPTIONS" in app.config


def test_init_database_preserves_local_sqlite_fallback(
        tmp_path, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    app = _fresh_app(instance_path=str(tmp_path / "instance"))
    init_database(app)  # local dev without .env still boots on sqlite
    assert app.config["SQLALCHEMY_DATABASE_URI"] == \
        "sqlite:///student_support_ai.db"
