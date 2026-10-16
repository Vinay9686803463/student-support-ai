"""Automated tests for the chat answer pipeline (Issue 1 & 3 backend).

Covers, with retrieval and the language model stubbed:
1. Retrieved passages + working model -> synthesized answer verbatim.
2. Citations refer only to actually retrieved documents.
3. No provider + passages -> honest notice + labeled excerpts (never a
   raw dump masquerading as the answer).
4. No provider + known topic -> clearly labeled general explanation.
5. No provider + no passages -> honest insufficient-sources message.
6. Model error -> visible honest fallback, never an exception or fake.
7. RAG prompt instructs direct answering and carries question+context.
8. Streaming no-provider path yields the honest text, same protocol.

Run: venv\\Scripts\\python.exe -m pytest test_chat_answers.py -q
(DB-free: retrieval, model, cache-version and clock are stubbed.)
"""

import os
import unittest
from unittest.mock import patch

from utils import rag_ai
from utils.answer_cache import invalidate_all
from utils.rag import build_rag_prompt

RESULTS = [
    {
        "document_id": 11,
        "subject_code": "BCS304",
        "module_number": 1,
        "page_number": 3,
        "similarity": 0.91,
        "content": "Binary search works on a sorted array by repeatedly halving it.",
        "filename": "Module 1.pdf",
        "doc_title": "Module 1.pdf",
    },
    {
        "document_id": 12,
        "subject_code": "BCS304",
        "module_number": 1,
        "page_number": 4,
        "similarity": 0.83,
        "content": "Time complexity is O(log n); space is O(1) iterative.",
        "filename": "Module 1.pdf",
        "doc_title": "Module 1.pdf",
    },
]

QUESTION = "Explain binary search and give its algorithm"


def _rag_data(results=RESULTS):
    return {
        "question": QUESTION,
        "results": [dict(r) for r in results],
        "prompt": "PROMPT",
    }


class AnswerPipelineTest(unittest.TestCase):
    def setUp(self):
        invalidate_all()

    def test_prompt_instructs_direct_answer(self):
        prompt = build_rag_prompt(QUESTION, RESULTS)
        self.assertIn(QUESTION, prompt)
        self.assertIn("Binary search works on a sorted array", prompt)
        lowered = prompt.lower()
        self.assertIn("answer the student's actual question directly", lowered)
        self.assertIn("never return only filenames", lowered)
        self.assertNotIn("return only", lowered.replace("never return only", ""))

    def test_model_answer_returned_verbatim_with_sources(self):
        synth = ("## Binary Search\nBinary search halves a sorted array. "
                 "Complexity O(log n). [Source 1]")
        with patch.object(rag_ai, "prepare_rag_request",
                          return_value=_rag_data()), \
             patch.dict("os.environ", {"AI_PROVIDER": "gemini"}), \
             patch.object(rag_ai, "gemini_available", return_value=True), \
             patch.object(rag_ai, "_call_gemini", return_value=synth):
            out = rag_ai.answer_with_rag(question=QUESTION + " q1")
        self.assertEqual(out["answer"], synth)
        self.assertTrue(out["used_ai"])
        self.assertTrue(out["used_rag"])
        self.assertEqual(len(out["sources"]), 2)
        # Citations refer only to retrieved documents.
        self.assertEqual(
            {s["document_id"] for s in out["sources"]}, {11, 12})
        self.assertTrue(
            all(s["filename"] == "Module 1.pdf" for s in out["sources"]))

    def test_no_provider_gives_honest_notice_not_dump(self):
        with patch.object(rag_ai, "prepare_rag_request",
                          return_value=_rag_data()), \
             patch.object(rag_ai, "gemini_available", return_value=False):
            out = rag_ai.answer_with_rag(question=QUESTION + " q2")
        self.assertFalse(out["used_ai"])
        self.assertTrue(out["used_rag"])
        self.assertIn("The AI assistant is temporarily unavailable",
                      out["answer"])
        self.assertIn("Relevant excerpts", out["answer"])
        # Excerpts labeled, sources intact for the citations UI.
        self.assertIn("BCS304", out["answer"])
        self.assertEqual(len(out["sources"]), 2)
        # Must not be a bare dump.
        self.assertFalse(out["answer"].startswith("Binary search works"))

    def test_no_provider_known_topic_labels_general_explanation(self):
        seen = "Explain the seven layers of the OSI model and each function"
        with patch.object(rag_ai, "prepare_rag_request",
                          return_value=_rag_data()), \
             patch.object(rag_ai, "gemini_available", return_value=False):
            out = rag_ai.answer_with_rag(question=seen)
        self.assertIn("built-in study bank", out["answer"])
        self.assertIn("OSI", out["answer"])

    def test_no_provider_no_results_is_honest(self):
        with patch.object(rag_ai, "prepare_rag_request",
                          return_value=_rag_data(results=[])), \
             patch.object(rag_ai, "gemini_available", return_value=False):
            out = rag_ai.answer_with_rag(question="zzz qqq xxx 4")
        self.assertEqual(out["sources"], [])
        self.assertFalse(out["used_ai"])
        self.assertFalse(out["used_rag"])
        self.assertIn("couldn't find relevant material", out["answer"])

    def test_model_error_falls_back_visibly(self):
        with patch.object(rag_ai, "prepare_rag_request",
                          return_value=_rag_data()), \
             patch.object(rag_ai, "gemini_available", return_value=True), \
             patch.object(rag_ai, "_call_gemini",
                          side_effect=RuntimeError("boom")):
            out = rag_ai.answer_with_rag(question=QUESTION + " q3")
        # The raise is caught inside answer_with_rag, which falls
        # through to the honest no-provider fallback.
        self.assertFalse(out["used_ai"])
        self.assertIn("The AI assistant is temporarily unavailable",
                      out["answer"])

    def test_stream_no_provider_yields_honest_text(self):
        with patch.object(rag_ai, "prepare_rag_request",
                          return_value=_rag_data()), \
             patch.object(rag_ai, "gemini_available", return_value=False):
            events = list(rag_ai.stream_answer(question=QUESTION + " q5"))
        kinds = [e["event"] for e in events]
        self.assertEqual(kinds[0], "sources")
        self.assertEqual(kinds[-1], "done")
        body = "".join(e["data"]["text"] for e in events
                       if e["event"] == "token")
        self.assertIn("The AI assistant is temporarily unavailable", body)
        self.assertIn("Relevant excerpts", body)
        done = events[-1]["data"]
        self.assertTrue(done["used_rag"])
        self.assertFalse(done["used_ai"])

    def test_stream_model_pieces_pass_through(self):
        pieces = ["## Binary", " Search\n", "O(log n)"]
        with patch.object(rag_ai, "prepare_rag_request",
                          return_value=_rag_data()), \
             patch.dict("os.environ", {"AI_PROVIDER": "gemini"}), \
             patch.object(rag_ai, "gemini_available", return_value=True), \
             patch.object(rag_ai, "_stream_gemini", return_value=iter(pieces)):
            events = list(rag_ai.stream_answer(question=QUESTION + " q6"))
        body = "".join(e["data"]["text"] for e in events
                       if e["event"] == "token")
        self.assertEqual(body, "".join(pieces))
        self.assertTrue(events[-1]["data"]["used_ai"])

    def test_stream_model_failure_records_error(self):
        from utils.rag_ai import get_last_provider_error
        with patch.object(rag_ai, "prepare_rag_request",
                          return_value=_rag_data()), \
             patch.dict("os.environ", {"AI_PROVIDER": "gemini"}), \
             patch.object(rag_ai, "gemini_available", return_value=True), \
             patch.object(rag_ai, "_stream_gemini",
                          side_effect=RuntimeError("429 rate limit exceeded")):
            events = list(rag_ai.stream_answer(question=QUESTION + " q7"))
        done = events[-1]["data"]
        self.assertFalse(done["used_ai"])
        self.assertEqual(done["error_code"], "rate_limited")
        self.assertEqual(get_last_provider_error()["code"], "rate_limited")
        body = "".join(e["data"]["text"] for e in events
                       if e["event"] == "token")
        self.assertIn("The AI assistant is temporarily unavailable", body)


class FallbackUserSafeTextTest(unittest.TestCase):
    """Fallback answers stay friendly: no codes, models, or secrets.

    All provider calls are mocked (no network, no credentials).
    """

    def _results(self):
        return [{
            "document_id": 1, "subject_code": "BCS403",
            "module_number": 1, "page_number": 2,
            "chunk_number": 1,
            "content": "Normal forms reduce redundancy.",
            "similarity": 0.5, "filename": "M1.pdf",
            "doc_title": "M1.pdf",
        }]

    def test_friendly_notice_without_technical_details(self):
        from utils.rag_ai import _compose_no_provider_answer
        for code in ("provider_not_configured", "model_not_found",
                     "auth_invalid", "auth_missing", "quota_exceeded",
                     "rate_limited", "timeout", "network",
                     "server_error", "unknown", None):
            text = _compose_no_provider_answer(
                "Explain normalization", self._results(),
                provider="gemini", error_code=code)
            self.assertIn(
                "The AI assistant is temporarily unavailable", text)
            for forbidden in ("provider_not_configured",
                              "model_not_found", "auth_invalid",
                              "auth_missing", "quota_exceeded",
                              "rate_limited", "server_error",
                              "gemini-", "OPENAI", "GOOGLE_",
                              "Traceback", "AIza"):
                self.assertNotIn(forbidden, text)
            # Study-bank content still labeled, never AI-claimed.
            self.assertIn("Relevant excerpts", text)
            self.assertNotIn("AI-generated", text)

    def test_quota_error_keeps_code_in_payload_only(self):
        from utils.answer_cache import invalidate_all
        invalidate_all()
        try:
            with patch.object(rag_ai, "prepare_rag_request",
                              return_value={
                                  "question": "q",
                                  "results": self._results(),
                                  "prompt": "P"}), \
                 patch.object(rag_ai, "current_kb_version",
                              return_value="v-quota"), \
                 patch.object(rag_ai, "gemini_available",
                              return_value=True), \
                 patch.object(rag_ai, "active_provider",
                              return_value="gemini"), \
                 patch.object(rag_ai, "_call_gemini",
                              side_effect=RuntimeError(
                                  "429 rate limit exceeded")):
                out = rag_ai.answer_with_rag(
                    "Explain normalization", mode="fast")
        finally:
            invalidate_all()
        self.assertFalse(out["used_ai"])
        self.assertEqual(out["answer_kind"], "fallback_excerpts")
        # Distinguished for developers...
        self.assertEqual(out["error_code"], "rate_limited")
        # ...but friendly for users.
        self.assertIn(
            "The AI assistant is temporarily unavailable",
            out["answer"])
        self.assertNotIn("rate_limited", out["answer"])
        self.assertNotIn("429", out["answer"])

    def test_missing_configuration_is_friendly(self):
        from utils.answer_cache import invalidate_all
        invalidate_all()
        try:
            with patch.object(rag_ai, "prepare_rag_request",
                              return_value={
                                  "question": "q",
                                  "results": self._results(),
                                  "prompt": "P"}), \
                 patch.object(rag_ai, "current_kb_version",
                              return_value="v-nokey"), \
                 patch.object(rag_ai, "gemini_available",
                              return_value=False), \
                 patch.object(rag_ai, "active_provider",
                              return_value=None):
                rag_ai._LAST_PROVIDER_ERROR.update(
                    {"code": None, "at": None, "model": None})
                out = rag_ai.answer_with_rag(
                    "Explain normalization", mode="fast")
        finally:
            invalidate_all()
        self.assertEqual(out["error_code"], "provider_not_configured")
        self.assertIn(
            "The AI assistant is temporarily unavailable",
            out["answer"])
        self.assertNotIn("provider_not_configured", out["answer"])


class SemesterAwareRetrievalTest(unittest.TestCase):
    """Semester scoping stays explicit and global where intended.

    Retrieval itself never filters by semester; only an explicit
    subject/module scope narrows it. All calls are mocked.
    """

    def test_prepare_passes_subject_scope_through(self):
        from unittest.mock import MagicMock, patch as mock_patch
        fake = MagicMock(return_value=[])
        with mock_patch("utils.rag.search_hybrid", fake):
            from utils.rag import prepare_rag_request
            prepare_rag_request(
                question="Explain normalization",
                subject_code="BCS403", module_number=2, limit=5)
        _, kwargs = fake.call_args
        self.assertEqual(kwargs.get("subject_code"), "BCS403")
        self.assertEqual(kwargs.get("module_number"), 2)

    def test_subject_detected_without_semester_filter(self):
        from utils.rag import detect_query_subject
        known = {"BMATS201": "Mathematics for CSE Stream-II",
                 "BCS501": "Software Engineering"}
        self.assertEqual(
            detect_query_subject("Explain BMATS201", known), "BMATS201")
        self.assertIsNone(detect_query_subject("Explain cooking", known))

    def test_general_question_without_pdf_uses_ai(self):
        from utils.answer_cache import invalidate_all
        invalidate_all()
        try:
            with patch.object(rag_ai, "prepare_rag_request",
                              return_value={
                                  "question": "q", "results": [],
                                  "prompt": "P"}), \
                 patch.object(rag_ai, "current_kb_version",
                              return_value="v-general"), \
                 patch.object(rag_ai, "gemini_available",
                              return_value=True), \
                 patch.object(rag_ai, "active_provider",
                              return_value="gemini"), \
                 patch.object(rag_ai, "_call_gemini",
                              return_value="General AI answer."):
                out = rag_ai.answer_with_rag(
                    "What is software engineering?", mode="fast")
        finally:
            invalidate_all()
        self.assertTrue(out["used_ai"])
        self.assertEqual(out["answer_kind"], "ai_generated")
        self.assertEqual(out["answer"], "General AI answer.")
        self.assertIsNone(out["error_code"])

    def test_missing_documents_is_not_a_provider_error(self):
        from utils.answer_cache import invalidate_all
        invalidate_all()
        try:
            with patch.object(rag_ai, "prepare_rag_request",
                              return_value={
                                  "question": "q", "results": [],
                                  "prompt": "P"}), \
                 patch.object(rag_ai, "current_kb_version",
                              return_value="v-missing"), \
                 patch.object(rag_ai, "gemini_available",
                              return_value=False), \
                 patch.object(rag_ai, "active_provider",
                              return_value=None):
                rag_ai._LAST_PROVIDER_ERROR.update(
                    {"code": None, "at": None, "model": None})
                out = rag_ai.answer_with_rag(
                    "zzz qqq xxx 9", mode="fast")
        finally:
            invalidate_all()
        self.assertEqual(out["answer_kind"], "no_results")
        self.assertFalse(out["used_ai"])
        self.assertFalse(out["used_rag"])
        self.assertIsNone(out["error_code"])
        self.assertIn("couldn't find relevant material", out["answer"])


class ModelCandidatesTest(unittest.TestCase):
    def test_defaults_when_unset(self):
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("GEMINI_MODELS", None)
            os.environ.pop("GEMINI_MODEL", None)
            from utils.rag_ai import _model_candidates
            self.assertEqual(_model_candidates(),
                             ("gemini-3.5-flash", "gemini-3.6-flash"))

    def test_single_model_env_honored(self):
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("GEMINI_MODELS", None)
            os.environ["GEMINI_MODEL"] = "gemini-2.5-flash"
            from utils.rag_ai import _model_candidates
            self.assertEqual(_model_candidates(),
                             ("gemini-2.5-flash",))
            os.environ.pop("GEMINI_MODEL", None)

    def test_override_parsed(self):
        with patch.dict("os.environ",
                        {"GEMINI_MODELS": " gemini-3.5-flash ,, gemini-3.8-flash "}):
            from utils.rag_ai import _model_candidates
            self.assertEqual(_model_candidates(),
                             ("gemini-3.5-flash", "gemini-3.8-flash"))

    def test_blank_override_falls_back(self):
        with patch.dict("os.environ", {"GEMINI_MODELS": " , "}):
            from utils.rag_ai import _model_candidates
            self.assertEqual(_model_candidates(),
                             ("gemini-3.5-flash", "gemini-3.6-flash"))

    def test_classify_retired_and_overloaded_models(self):
        from utils.rag_ai import _classify_provider_error
        self.assertEqual(
            _classify_provider_error(Exception("404 model not found")), "model_not_found")
        self.assertEqual(
            _classify_provider_error(Exception("504 Bad Gateway")), "server_error")
        self.assertEqual(
            _classify_provider_error(Exception("504 Deadline expired")), "timeout")


class GeminiRetiredModelFallbackTest(unittest.TestCase):
    """A retired first model must fall through instead of giving up.

    All provider calls are mocked (no network, no credentials).
    The client cache is cleared per test so each mocked Client
    is actually constructed (see _gemini_client).
    """

    def setUp(self):
        rag_ai._GEMINI_CLIENTS.clear()

    def tearDown(self):
        rag_ai._GEMINI_CLIENTS.clear()

    def _client_failing_then_ok(self, fail_text, ok_text="recovered"):
        from unittest.mock import MagicMock
        ok = MagicMock()
        ok.text = ok_text
        client = MagicMock()
        client.models.generate_content.side_effect = [
            Exception(fail_text), ok,
        ]
        return client

    def test_first_model_not_found_second_succeeds(self):
        from unittest.mock import patch as mock_patch
        client = self._client_failing_then_ok(
            "404 models/retired-x is not found")
        with patch.dict("os.environ",
                        {"GEMINI_MODELS": "retired-x, fresh-y"}):
            with mock_patch("google.genai.Client",
                            return_value=client):
                from utils.rag_ai import _call_gemini
                self.assertEqual(
                    _call_gemini("PROMPT", timeout=5), "recovered")
        tried = [call.kwargs.get("model")
                 for call in client.models.generate_content.call_args_list]
        self.assertEqual(tried, ["retired-x", "fresh-y"])

    def test_explicit_retired_model_recovers_with_defaults(self):
        from unittest.mock import MagicMock, patch as mock_patch

        def fake_generate(*args, **kwargs):
            model = kwargs.get("model")
            if model == "gemini-2.5-flash":
                raise Exception(
                    "404 models/gemini-2.5-flash is not found")
            ok = MagicMock()
            ok.text = "via default"
            return ok

        client = MagicMock()
        client.models.generate_content.side_effect = fake_generate
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("GEMINI_MODELS", None)
            os.environ["GEMINI_MODEL"] = "gemini-2.5-flash"
            try:
                with mock_patch("google.genai.Client",
                                return_value=client):
                    from utils.rag_ai import _call_gemini
                    self.assertEqual(
                        _call_gemini("PROMPT", timeout=5),
                        "via default")
            finally:
                os.environ.pop("GEMINI_MODEL", None)
        tried = [call.kwargs.get("model")
                 for call in client.models.generate_content.call_args_list]
        # Recovery stops at the first working default model.
        self.assertEqual(
            tried,
            ["gemini-2.5-flash", "gemini-3.5-flash"])

    def test_auth_error_does_not_try_defaults(self):
        from unittest.mock import MagicMock, patch as mock_patch
        client = MagicMock()
        client.models.generate_content.side_effect = Exception(
            "401 API key not valid")
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("GEMINI_MODELS", None)
            os.environ["GEMINI_MODEL"] = "custom-model"
            try:
                with mock_patch("google.genai.Client",
                                return_value=client):
                    from utils.rag_ai import _call_gemini
                    self.assertIsNone(
                        _call_gemini("PROMPT", timeout=5))
            finally:
                os.environ.pop("GEMINI_MODEL", None)
        self.assertEqual(
            client.models.generate_content.call_count, 1)
        from utils.rag_ai import get_last_provider_error
        self.assertEqual(
            get_last_provider_error().get("code"), "auth_invalid")

    def test_client_reused_across_questions(self):
        from unittest.mock import MagicMock, patch as mock_patch
        resp = MagicMock()
        resp.text = "cached-client answer"
        client = MagicMock()
        client.models.generate_content.return_value = resp
        with patch.dict("os.environ",
                        {"GEMINI_MODELS": "m1"}):
            with mock_patch("google.genai.Client",
                            return_value=client) as made:
                from utils.rag_ai import _call_gemini
                self.assertEqual(
                    _call_gemini("PROMPT", timeout=5),
                    "cached-client answer")
                self.assertEqual(
                    _call_gemini("PROMPT", timeout=5),
                    "cached-client answer")
                # Built once, reused for the second question.
                self.assertEqual(made.call_count, 1)
            with mock_patch("google.genai.Client",
                            return_value=client) as made2:
                from utils.rag_ai import _call_gemini as call2
                call2("PROMPT", timeout=9)
                # A different timeout gets its own client.
                self.assertEqual(made2.call_count, 1)

    def test_stream_recovers_after_not_found(self):
        from unittest.mock import MagicMock, patch as mock_patch
        first, second = MagicMock(), MagicMock()
        first.text = "Hello "
        second.text = "world"
        client = MagicMock()
        client.models.generate_content_stream.side_effect = [
            Exception("404 models/old is not found"),
            iter([first, second]),
        ]
        with patch.dict("os.environ",
                        {"GEMINI_MODELS": "old, new"}):
            with mock_patch("google.genai.Client",
                            return_value=client):
                from utils.rag_ai import _stream_gemini
                self.assertEqual(
                    list(_stream_gemini("PROMPT", timeout=5)),
                    ["Hello ", "world"])

    def test_recovery_tries_second_default_when_first_fails(self):
        from unittest.mock import MagicMock, patch as mock_patch

        def fake_generate(*args, **kwargs):
            model = kwargs.get("model")
            if model in ("gemini-2.5-flash", "gemini-3.5-flash"):
                raise Exception(
                    f"404 models/{model} is not found")
            ok = MagicMock()
            ok.text = "via second default"
            return ok

        client = MagicMock()
        client.models.generate_content.side_effect = fake_generate
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("GEMINI_MODELS", None)
            os.environ["GEMINI_MODEL"] = "gemini-2.5-flash"
            try:
                with mock_patch("google.genai.Client",
                                return_value=client):
                    from utils.rag_ai import _call_gemini
                    self.assertEqual(
                        _call_gemini("PROMPT", timeout=5),
                        "via second default")
            finally:
                os.environ.pop("GEMINI_MODEL", None)
        tried = [call.kwargs.get("model")
                 for call in client.models.generate_content.call_args_list]
        self.assertEqual(
            tried,
            ["gemini-2.5-flash",
             "gemini-3.5-flash", "gemini-3.6-flash"])

    def test_fallback_response_is_not_cached(self):
        from unittest.mock import MagicMock, patch as mock_patch
        from utils.answer_cache import invalidate_all
        invalidate_all()
        fake_results = [{
            "document_id": 1, "subject_code": "BCS403",
            "module_number": 1, "page_number": 2,
            "chunk_number": 1,
            "content": "Normal forms reduce redundancy.",
            "similarity": 0.5, "filename": "M1.pdf",
            "doc_title": "M1.pdf",
        }]
        prepare = MagicMock(return_value={
            "question": "q", "results": fake_results, "prompt": "P"})
        with mock_patch("utils.rag_ai.prepare_rag_request", prepare), \
            mock_patch("utils.rag_ai.current_kb_version",
                       return_value="v-nocache"), \
            mock_patch.object(rag_ai, "gemini_available",
                              return_value=False), \
            mock_patch.object(rag_ai, "active_provider",
                              return_value=None):
            from utils.rag_ai import answer_with_rag
            first = answer_with_rag("Explain normalization",
                                    mode="fast")
            second = answer_with_rag("Explain normalization",
                                     mode="fast")
        self.assertFalse(first["used_ai"])
        self.assertFalse(second["used_ai"])
        self.assertFalse(second.get("cached", False))
        # Retrieval ran again: the failed answer was not served
        # from cache.
        self.assertEqual(prepare.call_count, 2)
        invalidate_all()


class ApiChatRouteTest(unittest.TestCase):
    """POST /api/chat passes the pipeline answer through untouched."""

    @classmethod
    def setUpClass(cls):
        import os
        import tempfile
        t = tempfile.mkdtemp(prefix="chatrout_")
        os.environ["DATABASE_URL"] = (
            "sqlite:///" + os.path.join(t, "r.db").replace("\\", "/"))
        from werkzeug.security import generate_password_hash
        from sqlalchemy import text
        from app import app as flask_app
        from utils.database import db as _db
        flask_app.config["TESTING"] = True
        cls.app = flask_app
        with flask_app.app_context():
            _db.create_all()
            h = generate_password_hash("password123")
            _db.session.execute(text(
                "INSERT INTO users (name,email,password,password_hash,"
                "branch,scheme,current_semester) VALUES ('T','t@e.com',"
                ":h,:h,'CSE','2022',3)"), {"h": h})
            _db.session.commit()
        cls.client = flask_app.test_client()
        cls.client.post("/login",
                        data={"email": "t@e.com", "password": "password123"})

    def test_synthesized_answer_passes_through(self):
        payload = {
            "answer": "## Binary Search\nHalves a sorted array. [Source 1]",
            "sources": RESULTS,
            "used_rag": True,
            "used_ai": True,
            "mode": "detailed",
            "latency_ms": 5,
            "cached": False,
        }
        with patch.object(rag_ai, "answer_with_rag", return_value=payload):
            rv = self.client.post("/api/chat", json={"message": "Explain x"})
        data = rv.get_json()
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(data["answer"], payload["answer"])
        self.assertTrue(data["used_ai"])
        self.assertEqual(len(data["sources"]), 2)

    def test_honest_fallback_passes_through_not_emptied(self):
        payload = {
            "answer": "The AI assistant is temporarily unavailable...",
            "sources": RESULTS,
            "used_rag": True,
            "used_ai": False,
            "mode": "fast",
            "latency_ms": 5,
            "cached": False,
        }
        with patch.object(rag_ai, "answer_with_rag", return_value=payload):
            rv = self.client.post("/api/chat", json={"message": "Explain y"})
        data = rv.get_json()
        self.assertEqual(rv.status_code, 200)
        self.assertIn("unavailable", data["answer"])
        self.assertFalse(data["used_ai"])


if __name__ == "__main__":
    unittest.main()
