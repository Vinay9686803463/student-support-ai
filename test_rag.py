from utils.rag import prepare_rag_request


def main():

    question = (
        "Explain the seven layers of the OSI model "
        "and their functions."
    )

    print()
    print("=" * 70)
    print("STUDENT SUPPORT AI - RAG TEST")
    print("=" * 70)
    print()

    print("Question:")
    print(question)
    print()

    result = prepare_rag_request(
        question=question,
        subject_code="BCS502",
        limit=5,
    )

    results = result["results"]

    print(
        f"Retrieved chunks: {len(results)}"
    )

    print()

    for index, item in enumerate(
        results,
        start=1,
    ):

        print("-" * 70)

        print(
            f"Result {index}"
        )

        print(
            f"Module     : "
            f"{item['module_number']}"
        )

        print(
            f"Page       : "
            f"{item['page_number']}"
        )

        print(
            f"Similarity : "
            f"{item['similarity']:.4f}"
        )

        print()

        print(
            item["content"][:500]
        )

        print()

    print("=" * 70)
    print("GENERATED RAG PROMPT")
    print("=" * 70)
    print()

    print(result["prompt"])

    print()
    print("=" * 70)
    print("RAG TEST COMPLETE")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()