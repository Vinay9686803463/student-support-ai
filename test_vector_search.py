from utils.vector_search import search_knowledge


def main():

    question = (
        "What are the seven layers of the OSI model?"
    )

    print()
    print("=" * 60)
    print("VECTOR SEARCH TEST")
    print("=" * 60)
    print()

    print(f"Question: {question}")
    print()

    results = search_knowledge(
        question=question,
        subject_code="BCS502",
        limit=5,
    )

    if not results:

        print("✗ No results found.")
        return

    for index, result in enumerate(
        results,
        start=1,
    ):

        print("-" * 60)
        print(f"RESULT {index}")
        print("-" * 60)

        print(
            f"Similarity : "
            f"{result['similarity']:.4f}"
        )

        print(
            f"Module     : "
            f"{result['module_number']}"
        )

        print(
            f"Page       : "
            f"{result['page_number']}"
        )

        print(
            f"Chunk      : "
            f"{result['chunk_number']}"
        )

        print()

        print(
            result["content"][:1000]
        )

        print()

    print("=" * 60)
    print("VECTOR SEARCH TEST COMPLETE")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()