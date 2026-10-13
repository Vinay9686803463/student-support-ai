"""OpenAI provider tests: mocked success/errors/streaming + config.

Run: <python> -m pytest tests/test_openai_provider.py -q
Live-billing test is NOT included: the suite must pass without spending
credits or requiring network (all API calls are mocked).
"""

import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import openai_provider as provider


def test_config_defaults_and_placeholders(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert provider.configured_model() == "gpt-4o-mini"
    assert provider.openai_key_present() is False
    monkeypatch.setenv("OPENAI_API_KEY", "YOUR_API_KEY_HERE")
    assert provider.openai_key_present() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-looking-key")
    assert provider.openai_key_present() is True
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    assert provider.configured_model() == "gpt-4o"


def _fake_error(name, status=None, text="boom"):
    cls = type(name, (Exception,), {})
    err = cls(text)
    err.status_code = status
    return err


def test_classify_openai_errors():
    assert provider.classify_openai_error(_fake_error("AuthenticationError", 401)) == "auth_invalid"
    assert provider.classify_openai_error(_fake_error("RateLimitError", 429)) == "rate_limited"

    quota = _fake_error("RateLimitError", 429)
    quota.body = {"message": "insufficient_quota billing exhausted"}
    assert provider.classify_openai_error(quota) == "quota_exhausted"

    assert provider.classify_openai_error(_fake_error("NotFoundError", 404)) == "model_not_found"
    assert provider.classify_openai_error(_fake_error("APITimeoutError")) == "timeout"
    assert provider.classify_openai_error(_fake_error("APIConnectionError")) == "network"
    assert provider.classify_openai_error(_fake_error("Whatever")) == "unknown"


def test_error_messages_actionable_no_secrets():
    msg = provider.provider_error_message("quota_exhausted")
    assert "credit" in msg.lower() or "billing" in msg.lower()
    assert "sk-" not in provider.provider_error_message("auth_invalid")


def _fake_client(text=None, chunks=None, error=None):
    client = MagicMock()
    if error is not None:
        client.chat.completions.create.side_effect = error
        return client
    if chunks is not None:
        events = []
        for piece in chunks:
            delta = MagicMock()
            delta.content = piece
            choice = MagicMock()
            choice.delta = delta
            events.append(MagicMock(choices=[choice]))
        client.chat.completions.create.return_value = iter(events)
        return client
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return client


def test_generate_success_uses_chat_completions(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = _fake_client("Grounded answer here.")
    with patch("openai.OpenAI", return_value=client):
        out = provider.generate_answer("PROMPT", timeout=10, max_tokens=50)
    assert out == "Grounded answer here."
    _args, kwargs = client.chat.completions.create.call_args
    assert kwargs["model"] == "gpt-4o-mini"
    assert any(m["role"] == "user" and m["content"] == "PROMPT"
               for m in kwargs["messages"])


def test_generate_respects_model_override(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    client = _fake_client("ok")
    with patch("openai.OpenAI", return_value=client):
        provider.generate_answer("PROMPT", timeout=10)
    _args, kwargs = client.chat.completions.create.call_args
    assert kwargs["model"] == "gpt-4o"


def test_generate_error_propagates_for_classification(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = _fake_client(error=_fake_error("RateLimitError", 429))
    with patch("openai.OpenAI", return_value=client):
        with pytest.raises(Exception):
            provider.generate_answer("PROMPT", timeout=10)


def test_stream_pieces(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = _fake_client(chunks=["Hello ", "world"])
    with patch("openai.OpenAI", return_value=client):
        pieces = list(provider.stream_pieces("PROMPT", timeout=10))
    assert pieces == ["Hello ", "world"]
    _args, kwargs = client.chat.completions.create.call_args
    assert kwargs["stream"] is True


def test_rag_uses_openai_when_configured(monkeypatch):
    from utils import rag_ai
    from utils.answer_cache import invalidate_all
    invalidate_all()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AI_PROVIDER", "openai")
    fake_results = [
        {"document_id": 1, "subject_code": "BCS403", "module_number": 1,
         "page_number": 2, "chunk_number": 1, "content": "Normal forms reduce redundancy.",
         "similarity": 0.5, "filename": "Module 1.pdf", "doc_title": "Module 1.pdf"},
    ]
    with patch("utils.rag_ai.prepare_rag_request",
               return_value={"question": "q", "results": fake_results, "prompt": "P"}), \
         patch("utils.rag_ai.current_kb_version", return_value="v-test"), \
         patch("utils.openai_provider.generate_answer",
               return_value="Synthesized OpenAI answer.") as gen:
        out = rag_ai.answer_with_rag("Explain normalization", mode="fast")
    gen.assert_called_once()
    assert out["used_ai"] is True
    assert out["provider"] == "openai"
    assert out["answer_kind"] == "ai_generated"
    assert out["answer"] == "Synthesized OpenAI answer."
    assert out["error_code"] is None


def test_rag_openai_error_is_honest(monkeypatch):
    from utils import rag_ai
    from utils.answer_cache import invalidate_all
    invalidate_all()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AI_PROVIDER", "openai")
    fake_results = [
        {"document_id": 1, "subject_code": "BCS403", "module_number": 1,
         "page_number": 2, "chunk_number": 1, "content": "Normal forms reduce redundancy.",
         "similarity": 0.5, "filename": "Module 1.pdf", "doc_title": "Module 1.pdf"},
    ]
    with patch("utils.rag_ai.prepare_rag_request",
               return_value={"question": "q", "results": fake_results, "prompt": "P"}), \
         patch("utils.rag_ai.current_kb_version", return_value="v-test"), \
         patch("utils.openai_provider.generate_answer",
               side_effect=_fake_error("RateLimitError", 429)):
        out = rag_ai.answer_with_rag("Explain normalization", mode="fast")
    assert out["used_ai"] is False
    assert out.get("provider") == "openai"
    assert out["answer_kind"] == "fallback_excerpts"
    assert out["error_code"] in ("rate_limited", "quota_exhausted")
    assert "unavailable" in out["answer"]
