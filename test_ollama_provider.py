"""Tests for the Ollama local provider + dispatch (free operation).

Ollama's HTTP API is stubbed (no daemon needed): availability,
generation, streaming, error mapping, answer_with_rag dispatch in
both modes, and the actionable fallback when the daemon is down.

Run: <python> -m pytest test_ollama_provider.py -q
"""

import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from utils import ollama_provider as ollama
from utils import rag_ai
from utils.answer_cache import invalidate_all

RESULTS = [
    {
        "document_id": 7,
        "subject_code": "BCS403",
        "module_number": 3,
        "page_number": 9,
        "similarity": 0.9,
        "content": "First normal form 1NF eliminates repeating groups.",
        "filename": "dbms-module-3-notes (1) (1) (2).pdf",
        "doc_title": "dbms-module-3-notes (1) (1) (2).pdf",
    },
]


def _rag_data():
    return {"question": "What is 1NF?", "results": [dict(r) for r in RESULTS],
            "prompt": "PROMPT"}


class FakeReply:
    """Minimal urlopen context manager yielding canned bytes lines."""

    def __init__(self, payload_bytes=None, lines=None):
        self._payload = payload_bytes
        self._lines = lines or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._payload

    def __iter__(self):
        return iter(self._lines)


def _tags_reply(*names):
    return FakeReply(payload_bytes=json.dumps(
        {"models": [{"name": n} for n in names]}).encode())


class OllamaConfigTest(unittest.TestCase):
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ollama.configured_model(), "llama3.1:8b")
            self.assertEqual(ollama.configured_url(), "http://localhost:11434")

    def test_overrides(self):
        with patch.dict(os.environ, {"OLLAMA_MODEL": "mistral:7b",
                                     "OLLAMA_URL": "http://gpu:11434"}):
            self.assertEqual(ollama.configured_model(), "mistral:7b")
            self.assertEqual(ollama.configured_url(), "http://gpu:11434")

    def test_provider_selection(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "ollama"}):
            self.assertEqual(rag_ai.configured_provider(), "ollama")
        with patch.dict(os.environ, {"AI_PROVIDER": "bogus"}):
            self.assertEqual(rag_ai.configured_provider(), "gemini")

    def test_active_provider_ollama(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "ollama"}), \
             patch.object(ollama, "ollama_available", return_value=True):
            self.assertEqual(rag_ai.active_provider(), "ollama")
        with patch.dict(os.environ, {"AI_PROVIDER": "ollama"}), \
             patch.object(ollama, "ollama_available", return_value=False):
            self.assertIsNone(rag_ai.active_provider())


class OllamaHttpTest(unittest.TestCase):
    def test_available_when_model_pulled(self):
        with patch("utils.ollama_provider.urllib.request.urlopen",
                   return_value=_tags_reply("llama3.1:8b", "mistral:7b")):
            self.assertTrue(ollama.ollama_available())

    def test_unavailable_when_model_missing(self):
        with patch("utils.ollama_provider.urllib.request.urlopen",
                   return_value=_tags_reply("mistral:7b")):
            self.assertFalse(ollama.ollama_available())

    def test_unavailable_when_daemon_down(self):
        with patch("utils.ollama_provider.urllib.request.urlopen",
                   side_effect=urllib.error.URLError("refused")):
            self.assertFalse(ollama.ollama_available())

    def test_generate_answer_parses_response(self):
        body = json.dumps({"response": "  1NF means atomic values.  "}).encode()
        with patch("utils.ollama_provider.urllib.request.urlopen",
                   return_value=FakeReply(payload_bytes=body)):
            self.assertEqual(ollama.generate_answer("Q", timeout=5),
                             "1NF means atomic values.")

    def test_stream_pieces_yields_ndjson(self):
        lines = [json.dumps({"response": "Hello "}).encode(),
                 json.dumps({"response": "there", "done": True}).encode()]
        with patch("utils.ollama_provider.urllib.request.urlopen",
                   return_value=FakeReply(lines=lines)):
            self.assertEqual(list(ollama.stream_pieces("Q", timeout=5)),
                             ["Hello ", "there"])

    def test_classify(self):
        self.assertEqual(
            ollama.classify_ollama_error(ollama._HttpStatusError(404, "x")),
            "model_not_found")
        self.assertEqual(
            ollama.classify_ollama_error(ollama._HttpStatusError(500, "x")),
            "server_error")
        self.assertEqual(
            ollama.classify_ollama_error(urllib.error.URLError("refused")),
            "network")
        self.assertEqual(
            ollama.classify_ollama_error(TimeoutError("timed out")), "timeout")
        self.assertEqual(ollama.classify_ollama_error(Exception("weird")),
                         "unknown")


class OllamaDispatchTest(unittest.TestCase):
    def setUp(self):
        invalidate_all()

    def _patched_rag(self, **kwargs):
        return patch.object(rag_ai, "prepare_rag_request",
                            return_value=_rag_data()), kwargs

    def test_generate_path_fast_and_detailed(self):
        for mode in ("fast", "detailed"):
            with self.subTest(mode=mode):
                invalidate_all()
                p1, _ = self._patched_rag()
                with p1, \
                     patch.dict(os.environ, {"AI_PROVIDER": "ollama"}), \
                     patch.object(ollama, "ollama_available",
                                  return_value=True), \
                     patch.object(ollama, "generate_answer",
                                  return_value="## 1NF\nAtomic values."):
                    out = rag_ai.answer_with_rag(
                        question=f"What is 1NF? {mode} m", mode=mode)
                self.assertEqual(out["answer"], "## 1NF\nAtomic values.")
                self.assertTrue(out["used_ai"])
                self.assertEqual(out["provider"], "ollama")
                self.assertEqual(out["answer_kind"], "ai_generated")
                self.assertEqual(len(out["sources"]), 1)

    def test_stream_path(self):
        p1, _ = self._patched_rag()
        with p1, \
             patch.dict(os.environ, {"AI_PROVIDER": "ollama"}), \
             patch.object(ollama, "ollama_available", return_value=True), \
             patch.object(ollama, "stream_pieces",
                          return_value=iter(["## 1", "NF"])):
            events = list(rag_ai.stream_answer(
                question="What is 1NF? stream m"))
        body = "".join(e["data"]["text"] for e in events
                       if e["event"] == "token")
        self.assertEqual(body, "## 1NF")
        done = events[-1]["data"]
        self.assertTrue(done["used_ai"])
        self.assertEqual(done["provider"], "ollama")

    def test_daemon_down_gives_actionable_fallback(self):
        p1, _ = self._patched_rag()
        with p1, \
             patch.dict(os.environ, {"AI_PROVIDER": "ollama"}), \
             patch.object(ollama, "ollama_available", return_value=False):
            out = rag_ai.answer_with_rag(question="What is 1NF? down m")
        self.assertFalse(out["used_ai"])
        self.assertEqual(out["answer_kind"], "fallback_excerpts")
        self.assertIn("Direct AI answering is currently unavailable",
                      out["answer"])
        # Actionable, never a fake answer; sources intact for citations.
        self.assertIn("ollama serve", out["answer"])
        self.assertIn("AI_PROVIDER=ollama", out["answer"])
        self.assertNotIn("sk-", out["answer"])
        self.assertEqual(len(out["sources"]), 1)

    def test_ollama_error_recorded_not_swallowed(self):
        p1, _ = self._patched_rag()
        with p1, \
             patch.dict(os.environ, {"AI_PROVIDER": "ollama"}), \
             patch.object(ollama, "ollama_available", return_value=True), \
             patch.object(ollama, "generate_answer",
                          side_effect=urllib.error.URLError("refused")):
            out = rag_ai.answer_with_rag(question="What is 1NF? err m")
        self.assertFalse(out["used_ai"])
        self.assertEqual(out["error_code"], "network")
        self.assertEqual(rag_ai.get_last_provider_error()["code"], "network")


if __name__ == "__main__":
    unittest.main()
