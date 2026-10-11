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
        self.assertIn("Direct AI answering is currently unavailable",
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
        self.assertIn("Direct AI answering is currently unavailable",
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
        self.assertIn("Direct AI answering is currently unavailable", body)
        self.assertIn("Relevant excerpts", body)
        done = events[-1]["data"]
        self.assertTrue(done["used_rag"])
        self.assertFalse(done["used_ai"])

    def test_stream_model_pieces_pass_through(self):
        pieces = ["## Binary", " Search\n", "O(log n)"]
        with patch.object(rag_ai, "prepare_rag_request",
                          return_value=_rag_data()), \
             patch.object(rag_ai, "gemini_available", return_value=True), \
             patch.object(rag_ai, "_stream_gemini", return_value=iter(pieces)):
            events = list(rag_ai.stream_answer(question=QUESTION + " q6"))
        body = "".join(e["data"]["text"] for e in events
                       if e["event"] == "token")
        self.assertEqual(body, "".join(pieces))
        self.assertTrue(events[-1]["data"]["used_ai"])


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
            "answer": "Direct AI answering is currently unavailable...",
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
