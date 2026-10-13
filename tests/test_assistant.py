"""Assistant upgrade tests: pure-function unit tests (no torch/DB needed).

Run: <python> -m pytest tests/test_assistant.py -q
DB-backed checks auto-skip when DATABASE_URL is unreachable.
"""

import io
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.answer_cache import cache_key, get as cache_get, put as cache_put
from utils.subject_hints import detect_subject_hint, dynamic_name_hits, normalize_question


KNOWN = ["BCS401", "BCS403", "BCS303", "BCS502", "BCS503"]


def test_normalize_question():
    assert normalize_question("  Explain ADA? ") == "EXPLAIN ADA?"


def test_detect_direct_code():
    assert detect_subject_hint("Module 3 of BCS303?", KNOWN) == "BCS303"


def test_detect_abbreviations():
    assert detect_subject_hint("Explain binary search in ADA.", KNOWN) == "BCS401"
    assert detect_subject_hint("What is DBMS normalization?", KNOWN) == "BCS403"
    assert detect_subject_hint("Explain process scheduling in OS.", KNOWN) == "BCS303"


def test_detect_unknown_code_rejected():
    assert detect_subject_hint("Explain BCS999.", KNOWN) is None
    assert detect_subject_hint("", KNOWN) is None


def test_dynamic_name_hits():
    names = {"BCS402": "Microcontrollers", "BCS502": "Computer Networks"}
    assert dynamic_name_hits("Explain microcontrollers timers.", names) == ["BCS402"]


def test_cache_roundtrip_and_key_stability():
    key = cache_key("  Explain OSI? ", "BCS502", None, "fast", "v1")
    assert cache_get(key) is None
    cache_put(key, {"answer": "hi"})
    assert cache_get(key) == {"answer": "hi"}
    assert cache_key("explain osi?", "BCS502", None, "fast", "v1") == key
    assert cache_key("explain osi?", "BCS502", None, "fast", "v2") != key


def test_sanitize_fts_query():
    from utils.vector_search import sanitize_fts_query
    assert sanitize_fts_query("Explain binary search in ADA?") != ""
    assert sanitize_fts_query("a") == ""
    assert sanitize_fts_query("") == ""


def test_split_text_chunks():
    from utils.knowledge_ingest import clean_text, split_text
    assert clean_text("a  b\r\n\r\n\r\nc") == "a b\n\nc"
    assert split_text("") == []
    chunks = split_text("Hello world. " * 500)
    assert len(chunks) > 1
    assert all(len(c) <= 3600 for c in chunks)


def _make_docx(paragraphs):
    buf = io.BytesIO()
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = ('<?xml version="1.0"?><w:document '
           'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{body}</w:body></w:document>")
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_extract_docx(tmp_path):
    from utils.office_extract import extract_docx
    p = tmp_path / "sample.docx"
    p.write_bytes(_make_docx(["Normalization removes redundancy.", "Second paragraph."]))
    text = extract_docx(str(p))
    assert "Normalization removes redundancy." in text


def _make_pptx(slides):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i, title in enumerate(slides, 1):
            xml = ('<?xml version="1.0"?><p:sld '
                   'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                   'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                   f"<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{title}</a:t>"
                   "</a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>")
            zf.writestr(f"ppt/slides/slide{i}.xml", xml)
    return buf.getvalue()


def test_extract_pptx(tmp_path):
    from utils.office_extract import extract_pptx
    p = tmp_path / "deck.pptx"
    p.write_bytes(_make_pptx(["OSI Layers", "TCP versus UDP"]))
    text = extract_pptx(str(p))
    assert "OSI Layers" in text and "TCP versus UDP" in text


def test_extract_txt(tmp_path):
    from utils.office_extract import extract_txt
    p = tmp_path / "notes.txt"
    p.write_text("ACID properties: atomicity, consistency.", encoding="utf-8")
    assert "ACID properties" in extract_txt(str(p))


def test_normalize_mode():
    from utils.rag_ai import normalize_mode
    assert normalize_mode("FAST") == "fast"
    assert normalize_mode("weird") == "detailed"
    assert normalize_mode(None) == "detailed"


def test_classify_provider_error():
    from utils import rag_ai as _rag_ai_mod
    from utils.rag_ai import _classify_provider_error, get_last_provider_error
    _rag_ai_mod._LAST_PROVIDER_ERROR.update({"code": None, "at": None, "model": None})
    assert _classify_provider_error(Exception("API key not valid")) == "auth_invalid"
    assert _classify_provider_error(Exception("quota exhausted")) == "quota_exceeded"
    assert _classify_provider_error(Exception("429 rate limit")) == "rate_limited"
    assert _classify_provider_error(Exception("request timed out")) == "timeout"
    assert _classify_provider_error(Exception("DNS resolve failed")) == "network"
    assert _classify_provider_error(Exception("weird")) == "unknown"
    assert get_last_provider_error()["code"] is None


def test_answer_kind_no_provider_stubbed():
    from unittest.mock import patch
    from utils import rag_ai
    from utils.answer_cache import invalidate_all
    invalidate_all()
    fake_results = [
        {"document_id": 1, "subject_code": "BCS403", "module_number": 1,
         "page_number": 2, "chunk_number": 1, "content": "Normal forms reduce redundancy.",
         "similarity": 0.5, "filename": "Module 1.pdf", "doc_title": "Module 1.pdf"},
    ]
    with patch.object(rag_ai, "gemini_available", return_value=False), \
         patch("utils.rag_ai.prepare_rag_request",
               return_value={"question": "q", "results": fake_results, "prompt": "P"}), \
         patch("utils.rag_ai.current_kb_version", return_value="test-v1"), \
         patch("utils.rag_ai.active_provider", return_value=None), \
         patch("utils.rag_ai.get_last_provider_error", return_value={}):
        out = rag_ai.answer_with_rag("Explain normalization", mode="fast")
    assert out["used_ai"] is False
    assert out["answer_kind"] == "fallback_excerpts"
    assert out["error_code"] == "provider_not_configured"
    assert "Direct AI answering is currently unavailable" in out["answer"]


def test_coverage_rerank_prefers_topical_passage():
    from utils.rag import coverage_score, distinctive_terms, rerank_by_coverage
    q = "Explain database normalization with 1NF 2NF and 3NF"
    terms = distinctive_terms(q)
    assert "normalization" in terms
    off_topic = {"content": "DBMS classifications and three-schema architecture utilities."}
    on_topic = {"content": "First normal form 1NF eliminates repeating groups; "
                           "normalization removes redundancy."}
    assert coverage_score(on_topic["content"], terms) > coverage_score(off_topic["content"], terms)
    ranked = rerank_by_coverage([off_topic, on_topic], q)
    assert ranked[0] is on_topic
    # Never drops results.
    assert len(rerank_by_coverage([off_topic, on_topic], "???")) == 2


def test_mode_limits_differ():
    from utils.rag import MODE_LIMITS
    assert MODE_LIMITS["fast"] < MODE_LIMITS["detailed"]


def _db_reachable():
    try:
        import psycopg
        from dotenv import load_dotenv
        load_dotenv()
        with psycopg.connect(os.getenv("DATABASE_URL"),
                             connect_timeout=8, prepare_threshold=None) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _db_reachable(), reason="DATABASE_URL unreachable")


@needs_db
def test_fts_finds_indexed_content():
    from utils.vector_search import search_fts
    results = search_fts("normalization", limit=3)
    assert results, "expected indexed content for 'normalization'"
    assert all("content" in r and r["content"] for r in results)


@needs_db
def test_answer_with_rag_grounded():
    from utils.rag_ai import answer_with_rag
    out = answer_with_rag("Explain DBMS normalization", mode="fast")
    assert out["answer"]
    assert out["used_rag"] is True
    assert out["mode"] == "fast"
    assert "latency_ms" in out


@needs_db
def test_normalization_retrieval_is_topical():
    from utils.rag import prepare_rag_request
    data = prepare_rag_request(
        "Explain database normalization with 1NF 2NF and 3NF", limit=5)
    assert data["results"], "expected indexed normalization content"
    top = " ".join(r["content"] for r in data["results"][:2]).lower()
    assert any(k in top for k in ("normal", "functional depend", "1nf", "2nf", "3nf")), top[:200]
