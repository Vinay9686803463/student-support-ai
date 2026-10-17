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

_ISOLATED_DB_URL = None


def _isolated_test_database():
    """One shared sqlite DATABASE_URL for every app-importing test class.

    The Flask engine is created the FIRST time app is imported, so an
    os.environ change in a later setUpClass cannot rebind it. All route
    classes therefore share this module's single isolated DB
    (production Postgres is never touched).
    """
    global _ISOLATED_DB_URL
    if _ISOLATED_DB_URL is None:
        import tempfile
        t = tempfile.mkdtemp(prefix="chatqa_")
        _ISOLATED_DB_URL = (
            "sqlite:///" + os.path.join(t, "r.db").replace("\\", "/"))
    os.environ["DATABASE_URL"] = _ISOLATED_DB_URL
    return _ISOLATED_DB_URL


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
            # When a general explanation is available, it is shown
            # cleanly without the "temporarily unavailable" notice.
            self.assertIn(
                "General explanation", text)
            for forbidden in ("provider_not_configured",
                              "model_not_found", "auth_invalid",
                              "auth_missing", "quota_exceeded",
                              "rate_limited", "server_error",
                              "gemini-", "OPENAI", "GOOGLE_",
                              "Traceback", "AIza"):
                self.assertNotIn(forbidden, text)
            # Study-bank content still labeled, never AI-claimed.
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
        # ...but friendly for users. A general explanation is available
        # for this question, so it is shown instead of the scary notice.
        self.assertIn(
            "General explanation", out["answer"])
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
            "General explanation", out["answer"])
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

    def test_prepare_returns_only_relevant_bounded(self):
        from unittest.mock import patch as mock_patch

        def chunk(code, content):
            return {"id": code, "document_id": code,
                    "subject_code": code, "module_number": 1,
                    "page_number": 1, "chunk_number": 1,
                    "content": content, "similarity": 0.5}

        mixed = [
            chunk("BCS403", "DBMS data models and normalization."),
            chunk("BCS501", "Agile sprints deliver increments; "
                             "the spiral model adds risk analysis."),
            chunk("BCS402", "Microcontroller timers and interrupts."),
            chunk("BCS501", "Waterfall phases run sequentially."),
            chunk("BPWSK206", "English grammar tenses and articles."),
        ]
        with mock_patch("utils.rag.search_hybrid",
                        return_value=list(mixed)):
            from utils.rag import prepare_rag_request
            out = prepare_rag_request(
                question="Agile vs Waterfall vs Spiral", limit=8)
        codes = [r["subject_code"] for r in out["results"]]
        self.assertEqual(codes, ["BCS501", "BCS501"])
        self.assertLessEqual(len(out["results"]), 8)


class ModelCandidatesTest(unittest.TestCase):
    def test_defaults_when_unset(self):
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("GEMINI_MODELS", None)
            os.environ.pop("GEMINI_MODEL", None)
            from utils.rag_ai import _model_candidates
            self.assertEqual(_model_candidates(),
                             ("gemini-3.5-flash-lite",
                              "gemini-3.7-flash",
                              "gemini-3.6-flash",
                              "gemini-3.8-flash",
                              "gemini-3.5-flash"))

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
                             ("gemini-3.5-flash-lite",
                              "gemini-3.7-flash",
                              "gemini-3.6-flash",
                              "gemini-3.8-flash",
                              "gemini-3.5-flash"))

    def test_classify_retired_and_overloaded_models(self):
        from utils.rag_ai import _classify_provider_error
        self.assertEqual(
            _classify_provider_error(Exception("404 model not found")), "model_not_found")
        self.assertEqual(
            _classify_provider_error(Exception("504 Bad Gateway")), "server_error")
        self.assertEqual(
            _classify_provider_error(Exception("504 Deadline expired")), "timeout")
        self.assertEqual(
            _classify_provider_error(Exception(
                "429 RESOURCE_EXHAUSTED You exceeded your current quota")),
            "quota_exceeded")


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
            ["gemini-2.5-flash", "gemini-3.5-flash-lite"])

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

    def test_latency_reported_as_int(self):
        from unittest.mock import MagicMock, patch as mock_patch
        resp = MagicMock()
        resp.text = "timed answer"
        client = MagicMock()
        client.models.generate_content.return_value = resp
        with patch.dict("os.environ", {"GEMINI_MODELS": "m1"}):
            with mock_patch("google.genai.Client",
                            return_value=client):
                from utils.rag_ai import _call_gemini  # noqa: F401
                from utils.answer_cache import invalidate_all
                invalidate_all()
                try:
                    with patch.object(
                            rag_ai, "prepare_rag_request",
                            return_value={"question": "q",
                                          "results": [],
                                          "prompt": "P"}), \
                         patch.object(rag_ai, "current_kb_version",
                                      return_value="v-lat"), \
                         patch.object(rag_ai, "gemini_available",
                                      return_value=True), \
                         patch.object(rag_ai, "active_provider",
                                      return_value="gemini"):
                        out = rag_ai.answer_with_rag(
                            "Explain latency", mode="fast")
                finally:
                    invalidate_all()
        self.assertTrue(out["used_ai"])
        self.assertIsInstance(out["latency_ms"], int)
        self.assertGreaterEqual(out["latency_ms"], 0)

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
            if model in ("gemini-2.5-flash", "gemini-3.5-flash-lite"):
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
             "gemini-3.5-flash-lite", "gemini-3.7-flash"])

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


class ProviderDiagnosticsTest(unittest.TestCase):
    """Startup banner must not demand an AIza key prefix."""

    def _report_with_key(self, key):
        _isolated_test_database()
        with patch.dict("os.environ",
                        {"AI_PROVIDER": "gemini",
                         "GOOGLE_GENERATIVE_AI_API_KEY": key}):
            from app import provider_diagnostics
            return provider_diagnostics()

    def test_non_aiza_long_key_is_accepted(self):
        report = self._report_with_key("sk-test-key-1234567890abcdef")
        self.assertTrue(report["key_present"])
        self.assertTrue(report["key_format_ok"])

    def test_placeholder_key_is_rejected(self):
        report = self._report_with_key("YOUR_API_KEY_HERE")
        self.assertTrue(report["key_present"])
        self.assertFalse(report["key_format_ok"])

    def test_short_key_is_rejected(self):
        report = self._report_with_key("abc123")
        self.assertFalse(report["key_format_ok"])


class ApiChatRouteTest(unittest.TestCase):
    """POST /api/chat passes the pipeline answer through untouched."""

    @classmethod
    def setUpClass(cls):
        _isolated_test_database()
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


class PromptCitationRuleTest(unittest.TestCase):
    """The RAG prompt must not ask the model to emit [Source N] markers.

    Sources stay hidden from the user; markers the model was told to
    produce would leak into answers if the prompt still requested them.
    """

    def test_prompt_has_no_inline_citation_rule(self):
        from utils.rag import build_rag_prompt

        prompt = build_rag_prompt(
            "Explain OSI layers", results=[], max_chars_per_source=100)
        # The old instruction ("cite it as [Source N] where N matches
        # the SOURCE number") must be gone — rule 6 now forbids it.
        self.assertNotIn("cite it as", prompt)
        self.assertIn("Do not add inline citation markers", prompt)
        # Sources still travel structurally for auditability.
        from utils.rag_ai import format_sources
        src = format_sources([{
            "document_id": 1, "subject_code": "BCS502",
            "module_number": 1, "page_number": 3, "similarity": 0.5,
        }])
        self.assertEqual(src[0]["subject_code"], "BCS502")


class SuggestionsRouteTest(unittest.TestCase):
    """GET /api/chat/suggestions: balanced across supported subjects."""

    @classmethod
    def setUpClass(cls):
        _isolated_test_database()
        from werkzeug.security import generate_password_hash
        from sqlalchemy import text
        from app import app as flask_app
        from utils.database import db as _db
        flask_app.config["TESTING"] = True
        cls.app = flask_app
        with flask_app.app_context():
            _db.create_all()
            h = generate_password_hash("password123")
            # Distinct email from ApiChatRouteTest's user: pytest shares
            # one sqlite DB across classes (app is imported once), so
            # both users must coexist.
            _db.session.execute(text(
                "INSERT INTO users (name,email,password,password_hash,"
                "branch,scheme,current_semester) VALUES ('T','sug@e.com',"
                ":h,:h,'CSE','2022',5)"), {"h": h})
            # Ensure the semester-5 support set exists exactly like the
            # real DB (bootstrap may already have restored some rows).
            wanted = [
                ("BCS501", "Software Engineering & Project Management"),
                ("BCS502", "Computer Networks"),
                ("BCS503", "Theory of Computation"),
                ("BCS505", "Professional Elective ???"),
            ]
            rows = _db.session.execute(text(
                "SELECT id, subject_code FROM subjects")).mappings().all()
            id_by_code = {r["subject_code"]: r["id"] for r in rows}
            for code, name in wanted:
                if code not in id_by_code:
                    _db.session.execute(text(
                        "INSERT INTO subjects (subject_code,subject_name,"
                        "branch,scheme,semester,credits,icon) VALUES"
                        "(:c,:n,'CSE','2022',5,3,'*')"), {"c": code, "n": name})
            if "BCS401" not in id_by_code:
                _db.session.execute(text(
                    "INSERT INTO subjects (subject_code,subject_name,"
                    "branch,scheme,semester,credits,icon) VALUES"
                    "('BCS401','Algorithms','CSE','2022',4,3,'*')"))
            _db.session.commit()
            # Attach 4 questions per supported subject via subject ids.
            rows = _db.session.execute(text(
                "SELECT id, subject_code FROM subjects")).mappings().all()
            id_by_code = {r["subject_code"]: r["id"] for r in rows}
            for code in ("BCS501", "BCS502", "BCS503"):
                for n in (1, 2, 3, 4):
                    _db.session.execute(text(
                        "INSERT INTO questions (subject_id, question,"
                        " unit, marks, difficulty, is_important)"
                        " VALUES (:sid, :q, 'U1', 10, 'Medium', 1)"),
                        {"sid": id_by_code[code], "q": f"Q {code} {n}"})
            _db.session.commit()

        cls.client = flask_app.test_client()
        cls.client.post("/login",
                        data={"email": "sug@e.com",
                              "password": "password123"})

    def test_mix_spans_all_supported_subjects(self):
        rv = self.client.get("/api/chat/suggestions")
        data = rv.get_json()
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(data["semester"], 5)
        mix = {c["subject_code"] for c in data["suggestions"]}
        self.assertTrue(mix <= {"BCS501", "BCS502", "BCS503"},
                        f"only supported subjects: {mix}")
        self.assertGreaterEqual(
            len(mix), 3,
            f"must span all supported subjects, got: {mix}")

    def test_rotation_varies_across_loads(self):
        import random as random_module
        seen_orders = set()
        from unittest.mock import patch

        def identity(seq):
            return seq

        def reverse(seq):
            seq.reverse()
            return seq

        for shuffler in (identity, reverse):
            with patch.object(random_module, "shuffle", shuffler):
                rv = self.client.get("/api/chat/suggestions")
            data = rv.get_json()
            seen_orders.add(tuple(c["text"] for c in data["suggestions"]))
        self.assertEqual(
            len(seen_orders), 2,
            f"suggestions must rotate across loads, got: {seen_orders}")

    def test_selected_subject_prioritized(self):
        rv = self.client.get("/api/chat/suggestions?subject_code=BCS503")
        data = rv.get_json()
        codes = {c["subject_code"] for c in data["suggestions"]}
        self.assertEqual(codes, {"BCS503"},
                         f"subject selection wins: {codes}")

    def test_unknown_subject_never_invented(self):
        rv = self.client.get("/api/chat/suggestions?subject_code=BCS999")
        data = rv.get_json()
        # BCS999 has no DB rows: fallback fills from supported subjects
        # only, never fabricated codes.
        for chip in data["suggestions"]:
            self.assertIn(chip["subject_code"],
                          {"BCS501", "BCS502", "BCS503"})


if __name__ == "__main__":
    unittest.main()
