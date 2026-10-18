import os
import re

from dotenv import load_dotenv

from utils.subject_hints import detect_subject_hint, dynamic_name_hits
from utils.vector_search import search_hybrid, search_knowledge


load_dotenv()


# Retrieval budgets per answer mode.
MODE_LIMITS = {
    "fast": 3,
    "detailed": 8,
}

# Prompt context budgets per mode: smaller prompts generate much
# faster (measured: 10k-char prompt ~16-45s+; ~4k-char prompt ~8-15s).
MODE_CONTEXT_CHARS = {
    "fast": 1500,
    "detailed": 3000,
}


def detect_query_subject(question, code_to_name):
    """Best-effort subject hint from abbreviations or name words."""
    known = list((code_to_name or {}).keys())
    hit = detect_subject_hint(question, known)
    if hit:
        return hit
    hits = dynamic_name_hits(question, code_to_name or {})
    return hits[0] if hits else None


QUESTION_STOPWORDS = frozenset({
    "what", "whats", "which", "explain", "describe", "define", "give",
    "tell", "about", "notes", "note", "module", "important", "concepts",
    "concept", "topic", "topics", "exam", "simple", "words", "word",
    "step", "detail", "detailed", "brief", "short", "answer", "question",
    "summarize", "summary", "mean", "means", "meaning", "with", "from",
    "that", "this", "these", "those", "their", "there", "here", "your",
    "yours", "some", "such", "into", "using", "used", "uses", "role",
})


def distinctive_terms(question):
    """Content-bearing question words used for relevance ranking."""
    terms = []
    for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9+]*", question or ""):
        lowered = word.lower()
        if lowered in QUESTION_STOPWORDS:
            continue
        # Normal-form codes (1NF/2NF/3NF/...) are short but carry the
        # whole topic: keep any short token containing a digit.
        if len(lowered) >= 4 or (
            len(lowered) >= 2
            and any(char.isdigit() for char in lowered)
        ):
            terms.append(lowered)
    return terms


def coverage_score(content, terms):
    """How many distinctive question terms appear in the passage."""
    lowered = (content or "").lower()
    return sum(1 for term in terms if term in lowered)


def rerank_by_coverage(results, question):
    """Stable re-rank: passages covering more question terms come first.

    Never drops results (callers may assert full passthrough); ties
    keep the retrieval order.
    """
    terms = distinctive_terms(question)
    if not terms or not results:
        return list(results)
    scored = [
        (coverage_score(result.get("content", ""), terms), index, result)
        for index, result in enumerate(results)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [result for _score, _index, result in scored]


def build_context(results, max_chars_per_source=None):
    """
    Convert retrieved knowledge chunks into a clean
    context block for the AI model.
    """
    if not results:
        return ""

    context_parts = []

    for index, result in enumerate(results, start=1):

        filename = result.get("filename") or result.get("doc_title") or ""
        content = result["content"] or ""

        if max_chars_per_source and len(content) > max_chars_per_source:
            content = content[:max_chars_per_source].rstrip() + " [...]"

        context_parts.append(
            f"""
SOURCE {index}
Subject: {result["subject_code"]}
Module: {result["module_number"]}
Page: {result["page_number"]}
Similarity: {result["similarity"]:.4f}
{f"File: {filename}" if filename else ""}

Content:
{content}
""".strip()
        )

    return "\n\n".join(context_parts)


def build_rag_prompt(
    question,
    results,
    max_chars_per_source=None,
    history=None,
):
    """
    Build the prompt that will eventually be sent
    to the AI model.
    """

    context = build_context(results, max_chars_per_source)

    if not context:

        context = (
            "No relevant VTU knowledge was found "
            "in the knowledge base."
        )

    history_block = ""
    if history and isinstance(history, list):
        lines = []
        for msg in history[-6:]:
            role = (msg.get("role") or "").strip().lower() if isinstance(msg, dict) else ""
            content = (msg.get("content") or "").strip() if isinstance(msg, dict) else str(msg)
            if role in ("user", "assistant") and content:
                label = "Student" if role == "user" else "Assistant"
                if len(content) > 500:
                    content = content[:500] + "..."
                lines.append(f"{label}: {content}")
        if lines:
            history_block = "CONVERSATION HISTORY:\\n" + "\\n".join(lines) + "\\n\\n"

    prompt = f"""
You are a helpful university study assistant. Answer the student's actual question directly and accurately. Use the retrieved study materials as supporting context, not as a replacement for an answer. Explain concepts in clear, natural language. For problem-solving questions, show the method and steps. For algorithms, include pseudocode and complexity when relevant. For numerical problems, show calculations and the final result. For comparison questions, explain the differences clearly. Structure longer answers with headings and examples. Cite only sources actually used. If the sources are insufficient, answer from appropriate general knowledge without mentioning retrieval or limitations, and provide a clear, helpful explanation. Never return only filenames, citations, search results, or raw document excerpts unless the student explicitly requests them.

Additional rules:
1. Prefer the retrieved VTU knowledge over general knowledge, and do not invent facts the sources do not support.
2. Preserve important technical terminology for an engineering student.
3. For exam-oriented questions, give a structured, mark-worthy answer.
4. Use headings, bullet points, numbered lists, examples, tables, or steps when useful.
5. Do not mention internal retrieval, embeddings, pgvector, or RAG to the student.
6. When you rely on a retrieved passage, cite it as [Source N] where N matches the SOURCE number below.

{history_block}STUDENT QUESTION:
{question}

RETRIEVED VTU KNOWLEDGE:
{context}

Now answer the student's question directly.
""".strip()

    return prompt


def retrieve_knowledge(
    question,
    subject_code=None,
    module_number=None,
    limit=5,
    use_hybrid=True,
):
    """
    Retrieve the most relevant knowledge chunks.

    Hybrid (keyword + vector) by default so subjects without
    embeddings are still searchable; falls back gracefully.
    """

    if use_hybrid:
        try:
            return search_hybrid(
                question=question,
                subject_code=subject_code,
                module_number=module_number,
                limit=limit,
            )
        except Exception:
            pass

    results = search_knowledge(
        question=question,
        subject_code=subject_code,
        module_number=module_number,
        limit=limit,
    )

    return results


def prepare_rag_request(
    question,
    subject_code=None,
    module_number=None,
    limit=5,
    max_chars_per_source=None,
    history=None,
):
    """
    Retrieve relevant knowledge and prepare the
    final prompt for the AI model.
    """

    results = retrieve_knowledge(
        question=question,
        subject_code=subject_code,
        module_number=module_number,
        limit=limit,
    )

    # Re-rank so passages covering the question's distinctive terms
    # (e.g. normalization, 1NF, functional dependency) outrank
    # same-subject passages on other topics.
    results = rerank_by_coverage(results, question)

    prompt = build_rag_prompt(
        question=question,
        results=results,
        max_chars_per_source=max_chars_per_source,
        history=history,
    )

    return {
        "question": question,
        "results": results,
        "prompt": prompt,
    }
