"""Tests for the chat "+" menu (attachments, library picker, payload).

Two layers:
1. DB-free pipeline tests — the RAG prompt carries attachment excerpts
   and rag_ai passes attachments_text through to the prompt builder.
2. Endpoint tests on an isolated SQLite app (real app.py routes) —
   upload validation/with extraction, library listing, payload
   normalisation and backward compatibility without attachments.

Run: python -m pytest tests/test_chat_plus_menu.py -q
"""

import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Isolate from the local .env BEFORE importing utils.database / app.
_TMPDIR = tempfile.mkdtemp(prefix="ssa_plus_menu_")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMPDIR, "ssa_plus.sqlite")
for var in ("VERCEL",):
    os.environ.pop(var, None)


# ===============================================================
# Part 1 — pipeline (DB-free)
# ===============================================================

class PromptContextTests(unittest.TestCase):

    def test_prompt_contains_attachment_block(self):
        from utils.rag import build_rag_prompt

        prompt = build_rag_prompt(
            "Summarise the attached notes",
            [],
            attachments_text="--- notes.txt ---\nOSI has seven layers.",
        )
        self.assertIn("ATTACHED MATERIAL EXCERPTS", prompt)
        self.assertIn("--- notes.txt ---", prompt)
        self.assertIn("OSI has seven layers.", prompt)
        self.assertIn("Summarise the attached notes", prompt)

    def test_prompt_without_attachments_has_no_block(self):
        from utils.rag import build_rag_prompt

        prompt = build_rag_prompt("Explain binary search", [])
        self.assertNotIn(
            "ATTACHED MATERIAL EXCERPTS (files the student added):", prompt
        )

    def test_no_attachments_keeps_backward_compatible_prompt(self):
        from utils.rag import build_rag_prompt

        old_prompt = build_rag_prompt("Explain binary search", [])
        new_prompt = build_rag_prompt(
            "Explain binary search", [], attachments_text=None
        )
        self.assertEqual(old_prompt, new_prompt)

        very_old_prompt = build_rag_prompt(
            "Explain binary search", [], history=None,
        )
        self.assertEqual(old_prompt, very_old_prompt)

    def test_prepare_rag_request_passes_attachments(self):
        import utils.rag as rag

        captured = {}

        def fake_build(question, results, max_chars_per_source=None,
                       history=None, attachments_text=None):
            captured["attachments_text"] = attachments_text
            return "PROMPT"

        with patch.object(rag, "rerank_by_coverage",
                          side_effect=lambda r, q: r), \
             patch.object(rag, "retrieve_knowledge", return_value=[]), \
             patch.object(rag, "build_rag_prompt",
                          side_effect=fake_build):
            rag.prepare_rag_request(
                "q", attachments_text="EXCERPT"
            )
        self.assertEqual(captured["attachments_text"], "EXCERPT")

    def test_answer_with_rag_forwards_attachments(self):
        import utils.rag_ai as rag_ai
        from utils.answer_cache import invalidate_all

        captured = {}

        def fake_prepare(**kwargs):
            captured.update(kwargs)
            return {"question": "q", "results": [], "prompt": "P"}

        invalidate_all()
        with patch.object(rag_ai, "prepare_rag_request",
                          side_effect=fake_prepare), \
             patch.object(rag_ai, "current_kb_version",
                          return_value="t1"), \
             patch.object(rag_ai, "gemini_available", return_value=False), \
             patch.object(rag_ai, "active_provider", return_value=None), \
             patch.object(rag_ai, "get_last_provider_error",
                          return_value={}):
            rag_ai.answer_with_rag(
                "Explain OSI", mode="fast", attachments_text="NOTE"
            )
        self.assertEqual(captured.get("attachments_text"), "NOTE")

    def test_stream_answer_forwards_attachments(self):
        import utils.rag_ai as rag_ai

        captured = {}

        def fake_prepare(**kwargs):
            captured.update(kwargs)
            return {"question": "q", "results": [], "prompt": "P"}

        with patch.object(rag_ai, "prepare_rag_request",
                          side_effect=fake_prepare), \
             patch.object(rag_ai, "MODE_LIMITS", {"fast": 3}), \
             patch.object(rag_ai, "active_provider", return_value=None):
            events = list(rag_ai.stream_answer(
                "Explain OSI", mode="fast",
                attachments_text="NOTE"
            ))
        self.assertEqual(captured.get("attachments_text"), "NOTE")
        self.assertEqual(events[-1]["event"], "done")

    def test_answer_with_rag_does_not_crash_on_cache_lookup(self):
        """Regression: the cache lookup previously received kwargs the
        cache_key() function never accepted, which crashed every
        attachment-free request too. It must not raise."""
        import utils.rag_ai as rag_ai
        from utils.answer_cache import invalidate_all

        invalidate_all()
        with patch.object(rag_ai, "prepare_rag_request",
                          return_value={
                              "question": "q", "results": [],
                              "prompt": "P"}), \
             patch.object(rag_ai, "current_kb_version",
                          return_value="t1"), \
             patch.object(rag_ai, "gemini_available", return_value=False), \
             patch.object(rag_ai, "active_provider", return_value=None), \
             patch.object(rag_ai, "get_last_provider_error",
                          return_value={}):
            out = rag_ai.answer_with_rag(
                "plain question", mode="fast", history=[{"role": "user",
                                                         "content": "h"}]
            )
        self.assertFalse(out["used_ai"])

    def test_attachment_requests_bypass_shared_cache(self):
        """An attachment-muted request must neither read nor write the
        shared question cache, poisoning later attachment-free asks."""
        import utils.rag_ai as rag_ai
        from utils.answer_cache import (
            cache_key, put as cache_put, get as cache_get, invalidate_all
        )

        invalidate_all()
        fake_results = [
            {"document_id": 1, "subject_code": "BCS502", "module_number": 1,
             "page_number": 1, "content": "OSI model passage.",
             "similarity": 0.5, "filename": "m1.pdf", "doc_title": "m1.pdf"},
        ]
        shared_key = cache_key(
            "Cache bypass question", None, None, "fast", "t1"
        )

        def fake_prepare(**kwargs):
            return {"question": "q", "results": [dict(fake_results[0])],
                    "prompt": "P"}

        # Pre-seed the shared key with an ACTIVE cached value: an
        # attachment call must NOT serve it.
        cache_put(shared_key, {
            "answer": "CACHED SHARED ANSWER", "sources": [],
            "used_rag": True, "used_ai": False,
            "answer_kind": "fallback_excerpts", "error_code": None,
            "mode": "fast", "latency_ms": 5, "cached": False,
            "suggestions": [],
        })

        with patch.object(rag_ai, "prepare_rag_request",
                          side_effect=fake_prepare), \
             patch.object(rag_ai, "current_kb_version",
                          return_value="t1"), \
             patch.object(rag_ai, "active_provider", return_value=None), \
             patch.object(rag_ai, "get_last_provider_error",
                          return_value={}):
            with_att = rag_ai.answer_with_rag(
                "Cache bypass question", mode="fast",
                attachments_text="NOTE"
            )
            self.assertNotEqual("CACHED SHARED ANSWER",
                                with_att["answer"])
            # The pre-seeded value survives untouched.
            self.assertEqual(
                "CACHED SHARED ANSWER",
                cache_get(shared_key)["answer"]
            )
            # And the attachment call must not have overwritten it.
            without = rag_ai.answer_with_rag(
                "Cache bypass question", mode="fast"
            )
        self.assertEqual("CACHED SHARED ANSWER", without["answer"])


# ===============================================================
# Part 2 — endpoints on an isolated SQLite app
# ===============================================================

@pytest.fixture(scope="module")
def ssa_app():
    import app as app_module   # heavy but self-contained on SQLite
    app_module.app.config["TESTING"] = True
    return app_module


@pytest.fixture()
def client(ssa_app):
    from utils.database import db, User
    with ssa_app.app.app_context():
        from werkzeug.security import generate_password_hash
        existing = db.session.execute(
            db.text("SELECT id FROM users WHERE email = :e"),
            {"e": "plusmenu@test.local"},
        ).first()
        if not existing:
            import sqlalchemy as sa
            db.session.execute(
                sa.text("""
                    INSERT INTO users
                        (name, email, password, password_hash, branch,
                         current_semester)
                    VALUES
                        ('Plus Menu', 'plusmenu@test.local', :pw, :pw,
                         'CSE', 5)
                """),
                {"pw": generate_password_hash("test-only-not-real")},
            )
            db.session.commit()
            user_id = db.session.execute(
                db.text(
                    "SELECT id FROM users WHERE email = 'plusmenu@test.local'"
                )
            ).scalar()
        else:
            user_id = existing[0]
    client = ssa_app.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Plus Menu"
    return client


class TestAttachmentEndpoints:

    def test_txt_upload_extracts_text(self, client):
        data = {
            "file": (io.BytesIO(b"ACID properties explained here."),
                     "notes.txt")
        }
        res = client.post("/api/chat/attachments", data=data)
        assert res.status_code == 200
        body = res.get_json()
        assert body["ok"] is True
        assert body["attachment"]["text"].startswith("ACID")
        assert body["attachment"]["name"] == "notes.txt"

    def test_image_upload_gets_clear_unavailable_message(self, client):
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
            "1f15c4890000000d49444154789c6300010000050001"
            "0d0a2db40000000049454e44ae426082"
        )
        data = {"file": (io.BytesIO(png), "photo.png")}
        res = client.post("/api/chat/attachments", data=data)
        assert res.status_code == 415
        body = res.get_json()
        assert body["ok"] is False
        assert "text only" in body["error"].lower()
        assert "image" in body["error"].lower()

    def test_unsupported_extension_rejected(self, client):
        data = {"file": (io.BytesIO(b"MZ\x90\x00"), "virus.exe")}
        res = client.post("/api/chat/attachments", data=data)
        assert res.status_code == 400
        assert res.get_json()["ok"] is False

    def test_missing_file_rejected(self, client):
        res = client.post("/api/chat/attachments", data={})
        assert res.status_code == 400

    def test_filename_never_used_for_paths(self, client):
        payload = b"Path traversal label kept as display only."
        data = {
            "file": (io.BytesIO(payload), "../../tmp/evil/notes.txt")
        }
        res = client.post("/api/chat/attachments", data=data)
        assert res.status_code == 200
        name = res.get_json()["attachment"]["name"]
        assert "/" not in name and ".." not in name
        assert name.endswith("notes.txt")

    def test_garbage_pdf_fails_gracefully_not_500(self, client):
        data = {"file": (io.BytesIO(b"not a real pdf at all"), "fake.pdf")}
        res = client.post("/api/chat/attachments", data=data)
        assert res.status_code in (200, 415, 400)
        body = res.get_json()
        assert body is not None
        if body.get("ok"):
            assert body["attachment"]["text"] == ""

    def test_unauthenticated_upload_rejected(self, ssa_app):
        blank = ssa_app.app.test_client()
        data = {"file": (io.BytesIO(b"hello"), "notes.txt")}
        res = blank.post("/api/chat/attachments", data=data)
        assert res.status_code in (302, 401)


class TestLibraryEndpoints:

    def test_library_lists_documents(self, client):
        res = client.get("/api/chat/library")
        assert res.status_code == 200
        body = res.get_json()
        assert body["ok"] is True
        assert isinstance(body["documents"], list)
        for doc in body["documents"]:
            assert "id" in doc and "subject_code" in doc

    def test_library_requires_login(self, ssa_app):
        blank = ssa_app.app.test_client()
        res = blank.get("/api/chat/library")
        assert res.status_code in (302, 401)


class TestAttachmentPayloadResolution:

    def test_resolve_caps_to_three(self, ssa_app):
        with ssa_app.app.app_context():
            many = [
                {"type": "file", "name": f"n{i}.txt",
                 "text": f"excerpt {i}"}
                for i in range(6)
            ]
            error, text = ssa_app._resolve_chat_attachments(
                {"attachments": many}
            )
        assert error is None
        assert text.count("--- n") == 3

    def test_resolve_drops_empty_and_invalid(self, ssa_app):
        with ssa_app.app.app_context():
            error, text = ssa_app._resolve_chat_attachments({
                "attachments": [
                    "junk-string",
                    {"type": "file", "name": "a.txt", "text": "   "},
                    {"type": "file", "name": "b.txt", "text": None},
                ]
            })
        assert error is None
        assert text == ""

    def test_resolve_library_pulls_text_from_db(self, ssa_app):
        from utils.database import db, KnowledgeDocument, KnowledgeChunk
        with ssa_app.app.app_context():
            doc = KnowledgeDocument(
                subject_code="TST99",
                subject_name="Test Subject",
                module_number=1,
                title="Payload test document",
                original_filename="payload-test.pdf",
                file_path="payload-test.pdf",
                status="uploaded",
                page_count=1,
            )
            db.session.add(doc)
            db.session.flush()
            db.session.add(KnowledgeChunk(
                document_id=doc.id,
                subject_code="TST99",
                module_number=1,
                page_number=1,
                chunk_number=1,
                content="Pipeline grounding passage for payload test.",
                character_count=48,
                word_count=7,
            ))
            db.session.commit()
            doc_id = doc.id

            error, text = ssa_app._resolve_chat_attachments({
                "attachments": [
                    {"type": "library", "document_id": doc_id,
                     "name": "payload-test.pdf"},
                    {"type": "library", "document_id": 999999,
                     "name": "ghost.pdf"},
                ]
            })
        assert error is None
        assert "Pipeline grounding passage" in text
        assert "999999" not in text or "ghost" not in text

    def test_resolve_truncates_overlong_file_text(self, ssa_app):
        with ssa_app.app.app_context():
            long_text = "x" * (ssa_app._CHAT_ATTACHMENT_TEXT_LIMIT + 500)
            error, text = ssa_app._resolve_chat_attachments({
                "attachments": [
                    {"type": "file", "name": "big.txt", "text": long_text},
                ]
            })
        assert error is None
        assert len(text) <= ssa_app._CHAT_ATTACHMENT_TEXT_LIMIT + 200


class TestChatEndpointCompatibility:

    SIMPLERAG = {
        "answer": "Grounded answer with attachment context.",
        "sources": [],
        "used_rag": True,
        "used_ai": False,
        "answer_kind": "fallback_excerpts",
        "error_code": None,
        "mode": "fast",
        "latency_ms": 5,
        "cached": False,
    }

    def test_chat_endpoint_works_without_attachments(self, client):
        with patch("utils.rag_ai.answer_with_rag",
                   return_value=dict(self.SIMPLERAG)):
            res = client.post(
                "/api/chat",
                json={"message": "Explain OSI", "mode": "fast"},
            )
        assert res.status_code == 200
        assert "Grounded answer" in res.get_json()["answer"]

    def test_chat_endpoint_forwards_attachment_context(self, client):
        captured = {}

        def fake_answer(**kwargs):
            captured.update(kwargs)
            return dict(self.SIMPLERAG)

        with patch("utils.rag_ai.answer_with_rag",
                   side_effect=fake_answer):
            res = client.post(
                "/api/chat",
                json={
                    "message": "Explain what I attached",
                    "mode": "fast",
                    "attachments": [
                        {"type": "file", "name": "n.txt",
                         "text": "Seven layer note."}
                    ],
                },
            )
        assert res.status_code == 200
        assert captured.get("attachments_text") and(
            "Seven layer note." in captured["attachments_text"])

    def test_stream_endpoint_without_attachments(self, client):
        from utils.answer_cache import invalidate_all
        invalidate_all()
        res = client.post(
            "/api/chat/stream",
            json={"message": "plain question", "mode": "fast"},
        )
        assert res.status_code == 200
        body = res.get_data(as_text=True)
        assert "event:" in body   # SSE still well-formed

    def test_stream_endpoint_with_attachments(self, client):
        from utils.answer_cache import invalidate_all
        captured = {}

        def fake_stream(**kwargs):
            captured.update(kwargs)
            yield {"event": "token", "data": {"text": "ok"}}
            yield {"event": "done", "data": {}}

        invalidate_all()
        with patch("utils.rag_ai.stream_answer", side_effect=fake_stream):
            res = client.post(
                "/api/chat/stream",
                json={
                    "message": "Explain my attachment",
                    "mode": "fast",
                    "attachments": [
                        {"type": "file", "name": "n.txt",
                         "text": "Attachment excerpt."}
                    ],
                },
            )
        assert res.status_code == 200
        assert "Attachment excerpt." in captured.get("attachments_text", "")

    def test_stream_rejects_forged_attachment_shapes(self, client):
        from utils.answer_cache import invalidate_all
        invalidate_all()
        res = client.post(
            "/api/chat/stream",
            json={
                "message": "question here",
                "attachments": ["just", "strings"],
            },
        )
        assert res.status_code == 200
        body = res.get_data(as_text=True)
        assert "event:" in body   # malformed attachments never 500 the stream
