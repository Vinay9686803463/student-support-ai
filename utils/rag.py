import os

from dotenv import load_dotenv

from utils.vector_search import search_knowledge


load_dotenv()


def build_context(results):
    """
    Convert retrieved knowledge chunks into a clean
    context block for the AI model.
    """

    if not results:
        return ""

    context_parts = []

    for index, result in enumerate(results, start=1):

        context_parts.append(
            f"""
SOURCE {index}
Subject: {result["subject_code"]}
Module: {result["module_number"]}
Page: {result["page_number"]}
Similarity: {result["similarity"]:.4f}

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
You are Student Support AI, an academic assistant
for VTU Computer Science and Engineering students.

Answer the student's question using the provided
VTU knowledge base whenever relevant.

IMPORTANT RULES:

1. Prefer the provided knowledge base over general knowledge.
2. Do not invent information that is not supported by
   the retrieved content.
3. If the retrieved content does not contain enough
   information, clearly say so.
4. Explain concepts clearly for an engineering student.
5. For exam-oriented questions, give a structured answer.
6. Use headings, bullet points, numbered lists, examples,
   tables, or steps when useful.
7. Preserve important technical terminology.
8. Do not mention internal retrieval, embeddings,
   pgvector, or RAG to the student.

STUDENT QUESTION:
{question}

RETRIEVED VTU KNOWLEDGE:
{context}

Now answer the student's question.
""".strip()

    return prompt


def retrieve_knowledge(
    question,
    subject_code=None,
    module_number=None,
    limit=5,
):
    """
    Retrieve the most relevant knowledge chunks.
    """

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
