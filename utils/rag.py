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
    "the", "a", "an", "is", "are", "was", "were", "problem", "problems",
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


def relevance_terms(question):
    """Content words a retrieved chunk must contain at least one of.

    Built from the same sanitized terms as the keyword query, so
    generic words ("vs", "models", stopwords) can never qualify an
    unrelated document. Empty when the question has no content
    words, meaning no gate is applied.
    """
    from utils.vector_search import sanitize_fts_query

    return [
        word.lower()
        for word in sanitize_fts_query(question).split()
        if word
    ]


def meets_relevance(result, terms):
    """True when a chunk shares at least one content word.

    Long terms (5+) match as substrings so plurals still hit;
    short terms (codes like DFA, OSI, TCP) must match whole
    tokens so "hi" never matches inside "which". No terms means
    no gate. Semester-blind: relevance only, never a semester
    allow-list.
    """
    if not terms:
        return True
    content = (result.get("content") or "").lower()
    for term in terms:
        if len(term) >= 5:
            if term in content:
                return True
        elif re.search(
            r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])",
            content,
        ):
            return True
    return False


def _relevant_only(results, question):
    """Drop retrieved chunks sharing no content word with the question."""
    terms = relevance_terms(question)
    if not terms:
        return list(results or [])
    return [
        result for result in (results or [])
        if meets_relevance(result, terms)
    ]


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

    # Build conversation history block (last 6 messages = 3 turns)
    history_block = ""
    if history and isinstance(history, list):
        recent = history[-6:]
        lines = []
        for msg in recent:
            role = (msg.get("role") or "").strip().lower()
            content = (msg.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                label = "Student" if role == "user" else "Assistant"
                # Truncate long messages to avoid exceeding token limits
                if len(content) > 500:
                    content = content[:500] + "..."
                lines.append(f"{label}: {content}")
        if lines:
            history_block = "\n".join(lines)

    prompt = f"""
You are an expert university study assistant for VTU Computer Science and Engineering students. Generate detailed, thorough, and well-structured answers similar to ChatGPT. Answer the student's actual question directly and accurately with comprehensive explanations.

ANSWER QUALITY REQUIREMENTS:
- Provide complete, detailed explanations — not just summaries or bullet points.
- For "explain" or "describe" questions: give a thorough conceptual explanation with definitions, how it works, examples, advantages/disadvantages, and real-world applications.
- For "compare" or "differentiate" questions: explain both concepts in detail, then provide a comparison table covering key aspects (connection type, reliability, ordering, overhead, header size, speed, applications, etc.).
- For 10-mark VTU exam questions: provide an exam-ready answer with clear headings, definitions, detailed explanations, examples, diagrams described in text, and a summary of key points.
- For numerical problems: show formulas, substitute values, perform step-by-step calculations with units, and state the final result clearly.
- For short-answer questions: be concise but still complete.
- Use Markdown formatting: headings (##, ###), bold, italic, bullet/numbered lists, tables, and fenced code blocks for code examples.
- Include practical examples and real-world scenarios to help students understand.
- End with a brief summary or "Key Points" section for exam preparation when appropriate.
- Adapt the structure to the question type. Do not force every answer to contain all sections.

Use the retrieved study materials as supporting context, not as a replacement for an answer. Explain concepts in clear, natural language. Cite only sources actually used. If the sources are insufficient, state what is missing and provide a clearly labeled general explanation when appropriate. Never return only filenames, citations, search results, or raw document excerpts unless the student explicitly requests them.

Additional rules:
1. Prefer the retrieved VTU knowledge over general knowledge, and do not invent facts the sources do not support.
2. Preserve important technical terminology for an engineering student.
3. For exam-oriented questions, give a structured, mark-worthy answer.
4. Use headings, bullet points, numbered lists, examples, tables, code blocks, or steps when useful.
5. Do not mention internal retrieval, embeddings, pgvector, or RAG to the student.
6. Do not add inline citation markers such as [Source 1] or source lists; that bookkeeping is handled backstage, and the student sees only the prose answer.

{f"CONVERSATION HISTORY (for context):\\n{history_block}\\n" if history_block else ""}STUDENT QUESTION:
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
            return _relevant_only(
                search_hybrid(
                    question=question,
                    subject_code=subject_code,
                    module_number=module_number,
                    limit=limit,
                ),
                question,
            )
        except Exception:
            pass

    results = search_knowledge(
        question=question,
        subject_code=subject_code,
        module_number=module_number,
        limit=limit,
    )

    return _relevant_only(results, question)


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
