import os

from dotenv import load_dotenv

from utils.rag import prepare_rag_request


load_dotenv()


def _gemini_key():
    key = (
        os.getenv("GOOGLE_GENERATIVE_AI_API_KEY")
        or ""
    ).strip()

    if not key:
        return None

    if key.upper() in {
        "YOUR_API_KEY_HERE",
        "REPLACE-ME",
        "REPLACE_ME",
        "NONE",
    }:
        return None

    return key


def gemini_available():
    """
    Check whether Gemini is configured and
    the Google Generative AI package is installed.
    """

    if not _gemini_key():
        return False

    try:
        import google.generativeai  # noqa: F401

        return True

    except Exception:
        return False


def _call_gemini(prompt):
    """
    Send the RAG-grounded prompt to Gemini.
    """

    import google.generativeai as genai

    genai.configure(
        api_key=_gemini_key()
    )

    models = [
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]

    for model_name in models:

        try:

            model = genai.GenerativeModel(
                model_name
            )

            response = model.generate_content(
                prompt,
                request_options={
                    "timeout": 30
                },
            )

            answer = (
                getattr(response, "text", "")
                or ""
            ).strip()

            if answer:
                return answer

        except Exception:
            continue

    return None


def answer_with_rag(
    question,
    subject_code=None,
    module_number=None,
    limit=5,
):
    """
    Main RAG-powered answer function.

    Flow:

    Question
        ↓
    Vector search
        ↓
    Relevant VTU chunks
        ↓
    RAG prompt
        ↓
    Gemini
        ↓
    Grounded answer
    """

    question = (
        question or ""
    ).strip()

    if not question:

        return {
            "answer": (
                "Please enter a question."
            ),
            "sources": [],
            "used_rag": False,
            "used_ai": False,
        }

    # Retrieve relevant VTU knowledge.
    rag_data = prepare_rag_request(
        question=question,
        subject_code=subject_code,
        module_number=module_number,
        limit=limit,
    )

    results = rag_data["results"]
    prompt = rag_data["prompt"]

    # Try Gemini first.
    if gemini_available():

        try:

            answer = _call_gemini(
                prompt
            )

            if answer:

                return {
                    "answer": answer,
                    "sources": results,
                    "used_rag": bool(results),
                    "used_ai": True,
                }

        except Exception:
            pass

    # No AI provider available.
    #
    # We still return the retrieved knowledge so
    # the application can use it as a fallback.
    if results:

        fallback_parts = [
            "I found the following relevant "
            "VTU material in the knowledge base:\n"
        ]

        for index, result in enumerate(
            results,
            start=1,
        ):

            fallback_parts.append(
                f"\n{index}. "
                f"Module {result['module_number']}, "
                f"Page {result['page_number']}\n"
            )

            fallback_parts.append(
                result["content"]
            )

        fallback_answer = "".join(
            fallback_parts
        )

        return {
            "answer": fallback_answer,
            "sources": results,
            "used_rag": True,
            "used_ai": False,
        }

    return {
        "answer": (
            "I couldn't find relevant material "
            "in the knowledge base for "
            "that question."
        ),
        "sources": [],
        "used_rag": False,
        "used_ai": False,
    }


def format_sources(results):
    """
    Convert retrieved chunks into simple
    source information for the chat UI.
    """

    sources = []

    seen = set()

    for result in results:

        key = (
            result["document_id"],
            result["page_number"],
        )

        if key in seen:
            continue

        seen.add(key)

        sources.append(
            {
                "document_id": result[
                    "document_id"
                ],
                "subject_code": result[
                    "subject_code"
                ],
                "module_number": result[
                    "module_number"
                ],
                "page_number": result[
                    "page_number"
                ],
                "similarity": result[
                    "similarity"
                ],
            }
        )

    return sources