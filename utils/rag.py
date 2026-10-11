import os

from dotenv import load_dotenv

from utils.subject_hints import detect_subject_hint, dynamic_name_hits
from utils.vector_search import search_hybrid, search_knowledge


load_dotenv()


# Retrieval budgets per answer mode.
MODE_LIMITS = {
    "fast": 3,
    "detailed": 8,
}


def detect_query_subject(question, code_to_name):
    """Best-effort subject hint from abbreviations or name words."""
    known = list((code_to_name or {}).keys())
    hit = detect_subject_hint(question, known)
    if hit:
        return hit
    hits = dynamic_name_hits(question, code_to_name or {})
    return hits[0] if hits else None


def build_context(results):
    """
    Convert retrieved knowledge chunks into a clean
    context block for the AI model.
    """

    if not results:
        return ""

    context_parts = []

    for index, result in enumerate(results, start=1):

        filename = result.get("filename") or result.get("doc_title") or ""

        context_parts.append(
            f"""
SOURCE {index}
Subject: {result["subject_code"]}
Module: {result["module_number"]}
Page: {result["page_number"]}
Similarity: {result["similarity"]:.4f}
{f"File: {filename}" if filename else ""}

Content:
{result["content"]}
""".strip()
        )

    return "\n\n".join(context_parts)


def build_rag_prompt(
    question,
    results,
):
    """
    Build the prompt that will eventually be sent
    to the AI model.
    """

    context = build_context(results)

    if not context:

        context = (
            "No relevant VTU knowledge was found "
            "in the knowledge base."
        )

    prompt = f"""
You are a helpful university study assistant. Answer the student's actual question directly and accurately. Use the retrieved study materials as supporting context, not as a replacement for an answer. Explain concepts in clear, natural language. For problem-solving questions, show the method and steps. For algorithms, include pseudocode and complexity when relevant. For numerical problems, show calculations and the final result. For comparison questions, explain the differences clearly. Structure longer answers with headings and examples. Cite only sources actually used. If the sources are insufficient, state what is missing and provide a clearly labeled general explanation when appropriate. Never return only filenames, citations, search results, or raw document excerpts unless the student explicitly requests them.

Additional rules:
1. Prefer the retrieved VTU knowledge over general knowledge, and do not invent facts the sources do not support.
2. Preserve important technical terminology for an engineering student.
3. For exam-oriented questions, give a structured, mark-worthy answer.
4. Use headings, bullet points, numbered lists, examples, tables, or steps when useful.
5. Do not mention internal retrieval, embeddings, pgvector, or RAG to the student.
6. When you rely on a retrieved passage, cite it as [Source N] where N matches the SOURCE number below.

STUDENT QUESTION:
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

    prompt = build_rag_prompt(
        question=question,
        results=results,
    )

    return {
        "question": question,
        "results": results,
        "prompt": prompt,
    }
