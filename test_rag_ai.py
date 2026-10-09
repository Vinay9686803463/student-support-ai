from utils.rag_ai import answer_with_rag


def main():

    question = (
        "Explain the seven layers of the OSI model "
        "and give the main function of each layer."
    )

    print()
    print("=" * 70)
    print("STUDENT SUPPORT AI")
    print("RAG + AI TEST")
    print("=" * 70)
    print()

    print("Question:")
    print(question)
    print()

    result = answer_with_rag(
        question=question,
        subject_code="BCS502",
        limit=5,
    )

    print(
        f"RAG used : "
        f"{result['used_rag']}"
    )

    print(
        f"AI used  : "
        f"{result['used_ai']}"
    )

    print()

    print("=" * 70)
    print("ANSWER")
    print("=" * 70)
    print()

    print(
        result["answer"]
    )

    print()

    print("=" * 70)
    print("SOURCES")
    print("=" * 70)
    print()

    sources = result["sources"]

    if not sources:

        print("No sources found.")

    else:

        seen = set()

        for source in sources:

            key = (
                source["document_id"],
                source["page_number"],
            )

            if key in seen:
                continue

            seen.add(key)

            print(
                f"📄 Document ID: "
                f"{source['document_id']}"
            )

            print(
                f"   Subject: "
                f"{source['subject_code']}"
            )

            print(
                f"   Module: "
                f"{source['module_number']}"
            )

            print(
                f"   Page: "
                f"{source['page_number']}"
            )

            print(
                f"   Similarity: "
                f"{source['similarity']:.4f}"
            )

            print()

    print("=" * 70)
    print("RAG + AI TEST COMPLETE")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()