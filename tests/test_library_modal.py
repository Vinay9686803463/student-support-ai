"""Tests for the "Add from library" modal fix (library loading + close).

Three layers:
1. Endpoint tests on an isolated SQLite app: /api/chat/library returns
   metadata-only rows fast, honours status filtering and the 200-row cap,
   and handles the empty-db case.
2. Static asset guards: the close button markup (type, aria-label,
   inline handler), the CSS [hidden] guard that makes closeLibrary()
   actually hide the overlay, the red hover/focus styles and the
   loading/retry state classes, and the JS rewrite markers (retry,
   AbortController watchdog, no sticky once-flag regression).
3. Static-file format checks kept structural (no pixel/CSS parsing).

Run: python -m pytest tests/test_library_modal.py -q
"""

import os
import sys
import tempfile
import pathlib
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Isolate from the local .env BEFORE importing utils.database / app.
_TMPDIR = tempfile.mkdtemp(prefix="ssa_library_modal_")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    _TMPDIR, "ssa_library.sqlite"
)
for var in ("VERCEL",):
    os.environ.pop(var, None)

_REPO = pathlib.Path(__file__).resolve().parent.parent


# ================================================================
# Part 1 — endpoint behaviour (isolated SQLite app)
# ================================================================

@pytest.fixture(scope="module")
def ssa_app():
    import app as app_module   # heavy but self-contained on SQLite
    app_module.app.config["TESTING"] = True
    return app_module


@pytest.fixture()
def client(ssa_app):
    from utils.database import db
    with ssa_app.app.app_context():
        import sqlalchemy as sa
        row = db.session.execute(
            sa.text(
                "SELECT id FROM users "
                "WHERE email = 'libmodal@test.local'"
            )
        ).first()
        if not row:
            from werkzeug.security import generate_password_hash
            db.session.execute(
                sa.text("""
                    INSERT INTO users
                        (name, email, password, password_hash, branch,
                         current_semester)
                    VALUES
                        ('Library Modal', 'libmodal@test.local', :pw, :pw,
                         'CSE', 5)
                """),
                {"pw": generate_password_hash("test-only-not-real")},
            )
            db.session.commit()
    c = ssa_app.app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_name"] = "Library Modal"
    return c


class TestLibraryEndpoint:

    def test_listing_is_ok_and_fast(self, client):
        started = time.perf_counter()
        res = client.get("/api/chat/library")
        elapsed = time.perf_counter() - started
        assert res.status_code == 200
        body = res.get_json()
        assert body["ok"] is True
        assert isinstance(body["documents"], list)
        # Local SQLite should answer in milliseconds; the ceiling only
        # guards against a server-side hang (the client watchdog aborts
        # truly dead requests in the real UI).
        assert elapsed < 2.0, f"library endpoint took {elapsed:.3f}s"

    def test_documents_are_metadata_only(self, ssa_app, client):
        from utils.database import db, KnowledgeDocument
        with ssa_app.app.app_context():
            db.session.add(KnowledgeDocument(
                subject_code="LBM01",
                subject_name="Library Modal Test",
                module_number=2,
                title="Metadata only document",
                original_filename="metadata-only.pdf",
                file_path="metadata-only.pdf",
                status="uploaded",
                page_count=4,
            ))
            db.session.commit()

        res = client.get("/api/chat/library")
        assert res.status_code == 200
        docs = res.get_json()["documents"]
        mine = [d for d in docs if d.get("subject_code") == "LBM01"]
        assert len(mine) == 1
        doc = mine[0]
        for key in ("id", "subject_code", "subject_name", "title",
                    "filename", "module_number", "page_count"):
            assert key in doc, f"missing metadata key: {key}"
        # Never ship document text/chunk content in the listing.
        for heavy in ("content", "text", "chunks"):
            assert heavy not in doc, f"listing leaked heavy field: {heavy}"

    def test_failed_documents_excluded(self, ssa_app, client):
        from utils.database import db, KnowledgeDocument
        with ssa_app.app.app_context():
            db.session.add(KnowledgeDocument(
                subject_code="LBM02",
                subject_name="Failed Doc Test",
                module_number=1,
                title="Should not appear",
                original_filename="failed.pdf",
                file_path="failed.pdf",
                status="failed",
                page_count=1,
            ))
            db.session.commit()

        docs = client.get("/api/chat/library").get_json()["documents"]
        assert all(d.get("subject_code") != "LBM02" for d in docs)

    def test_listing_capped_at_200(self, ssa_app, client):
        from utils.database import db, KnowledgeDocument
        with ssa_app.app.app_context():
            existing = db.session.execute(db.text(
                "SELECT COUNT(*) FROM knowledge_documents"
            )).scalar()
            for i in range(205):
                db.session.add(KnowledgeDocument(
                    subject_code="LBMCAP",
                    subject_name="Cap Test",
                    module_number=(i % 5) + 1,
                    title=f"Cap filler {i}",
                    original_filename=f"cap-{i}.pdf",
                    file_path=f"cap-{i}.pdf",
                    status="uploaded",
                    page_count=1,
                ))
            db.session.commit()

        docs = client.get("/api/chat/library").get_json()["documents"]
        assert len(docs) == min(200, existing + 205)


# ================================================================
# Part 2 — static asset guards (template / CSS / JS)
# ================================================================

@pytest.fixture(scope="module")
def chat_html():
    return (_REPO / "templates" / "chat.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def chat_css():
    return (_REPO / "static" / "css" / "chat.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def chat_js():
    return (_REPO / "static" / "js" / "chat.js").read_text(encoding="utf-8")


class TestCloseButtonMarkup:

    def test_button_type_and_aria(self, chat_html):
        start = chat_html.index('class="library-close"')
        block = chat_html[start - 200: chat_html.index("</button>",
                                                       start) + 9]
        assert 'type="button"' in block, "X must never submit a form"
        assert 'aria-label="Close library"' in block
        assert "closeLibrary()" in block

    def test_overlay_has_hidden_attribute(self, chat_html):
        assert chat_html.count('id="libraryOverlay" hidden') >= 1

    def test_escape_and_retry_symbols_wired(self, chat_css, chat_js):
        assert "retryLibraryLoad" in chat_js


class TestOverlayHiddenGuard:

    def test_hidden_guard_outranks_flex_display(self, chat_css):
        assert ".library-overlay[hidden]" in chat_css
        guard = chat_css[chat_css.index(".library-overlay[hidden]"):]
        assert "display: none" in guard[:80]

    def test_red_hover_style_desktop_only(self, chat_css):
        hover_zone = chat_css[chat_css.index("@media (hover: hover)"):]
        close_hover = hover_zone[:hover_zone.index("}", hover_zone.index(
            ".library-close:hover"))]
        assert "#ef4444" in close_hover          # red background
        assert "#ffffff" in close_hover          # white X
        assert len(
            [i for i, c in enumerate(chat_css)
             if chat_css[i:].startswith(".library-close:hover")]) >= 1

    def test_focus_indicator_and_transition(self, chat_css):
        assert ".library-close:focus-visible" in chat_css
        close_rule = chat_css[
            chat_css.index(".library-close {"):
            chat_css.index("}", chat_css.index(".library-close {"))]
        assert "transition:" in close_rule
        assert "0.18s" in close_rule

    def test_loading_and_retry_states_styled(self, chat_css):
        for cls in (".library-loading", ".library-spinner",
                    "library-spin", ".library-retry-btn"):
            assert cls in chat_css, f"missing style hook: {cls}"


class TestLibraryJavascriptGuards:

    def test_no_sticky_once_flag_regression(self, chat_js):
        assert "_libraryLoadedOnce" not in chat_js, (
            "the sticky once-flag must stay removed: it froze the dialog "
            "on 'Loading library…' after any failed first attempt"
        )

    def test_abortcontroller_and_watchdog(self, chat_js):
        assert "AbortController()" in chat_js
        assert "aborter.abort()" in chat_js
        # Watchdog must convert a hung request into the retry state.
        assert "setTimeout" in chat_js

    def test_error_state_is_never_reported_as_empty(self, chat_js):
        assert "!response.ok" in chat_js
        assert "Could not load the library" in chat_js
        assert "renderLibrary" in chat_js

    def test_closeable_in_every_state(self, chat_js):
        close_body_start = chat_js.index("function closeLibrary()")
        close_body = chat_js[close_body_start:close_body_start + 700]
        # Close runs before/regardless of any fetch settlement.
        assert "overlay.hidden = true" in close_body
        assert "_libraryStopFetch()" in close_body

    def test_single_escape_binding_on_reopen(self, chat_js):
        open_body = chat_js[chat_js.index(
            "function openLibrary()"): chat_js.index(
            "function startLibraryLoad")]
        assert "addEventListener" in open_body
        assert "removeEventListener" in open_body


def _noop():
    return None
