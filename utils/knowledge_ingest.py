import os
import re
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from pypdf import PdfReader


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")


BASE_KNOWLEDGE_FOLDER = Path("knowledge_base")


# ---------------------------------------------------------
# TEXT CLEANING
# ---------------------------------------------------------

def clean_text(text):
    if not text:
        return ""

    text = text.replace("\x00", " ")

    # Normalize line endings
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Remove excessive spaces
    text = re.sub(r"[ \t]+", " ", text)

    # Remove excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ---------------------------------------------------------
# CHUNKING
# ---------------------------------------------------------

def split_text(text, chunk_size=3500, overlap=500):
    """
    Split text into overlapping chunks.

    chunk_size:
        Approximate number of characters per chunk.

    overlap:
        Number of characters repeated between chunks.
    """

    text = clean_text(text)

    if not text:
        return []

    chunks = []

    start = 0
    text_length = len(text)

    while start < text_length:

        end = min(start + chunk_size, text_length)

        # Try to finish at a natural paragraph boundary
        if end < text_length:

            paragraph_break = text.rfind("\n\n", start, end)

            if paragraph_break > start + 1000:
                end = paragraph_break

            else:
                sentence_break = text.rfind(". ", start, end)

                if sentence_break > start + 1000:
                    end = sentence_break + 1

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= text_length:
            break

        next_start = end - overlap

        if next_start <= start:
            next_start = end

        start = next_start

    return chunks


# ---------------------------------------------------------
# PDF EXTRACTION
# ---------------------------------------------------------

def extract_pdf_pages(pdf_path):
    reader = PdfReader(str(pdf_path))

    pages = []

    for page_number, page in enumerate(reader.pages, start=1):

        try:
            text = page.extract_text() or ""
        except Exception as error:
            print(
                f"  [!] Could not read page {page_number}: {error}"
            )
            text = ""

        text = clean_text(text)

        pages.append(
            {
                "page_number": page_number,
                "text": text,
            }
        )

    return pages


# ---------------------------------------------------------
# DATABASE HELPERS
# ---------------------------------------------------------

def get_connection():
    # prepare_threshold=None disables automatic server-side prepared
    # statements, which collide ("_pg3_0 already exists") when the
    # database sits behind a pooling proxy that reuses server sessions.
    return psycopg.connect(DATABASE_URL, prepare_threshold=None)


def document_already_exists(
    connection,
    subject_code,
    module_number,
    original_filename,
):
    with connection.cursor() as cursor:

        cursor.execute(
            """
            SELECT id
            FROM knowledge_documents
            WHERE subject_code = %s
              AND module_number = %s
              AND original_filename = %s
            LIMIT 1
            """,
            (
                subject_code,
                module_number,
                original_filename,
            ),
        )

        row = cursor.fetchone()

        return row[0] if row else None


# ---------------------------------------------------------
# PROCESS ONE PDF
# ---------------------------------------------------------

def process_pdf(
    pdf_path,
    subject_code,
    subject_name,
    module_number,
    module_title,
    source="",
):
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"PDF not found: {pdf_path}"
        )

    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Only PDF files are supported: {pdf_path}"
        )

    print()
    print("-" * 60)
    print(f"Processing: {pdf_path.name}")
    print(f"Subject : {subject_name}")
    print(f"Module  : {module_number}")
    print("-" * 60)

    connection = get_connection()

    try:

        existing_id = document_already_exists(
            connection,
            subject_code,
            module_number,
            pdf_path.name,
        )

        if existing_id:

            print(
                f"[!] Already processed. Document ID: {existing_id}"
            )

            return existing_id

        # -------------------------------------------------
        # INSERT DOCUMENT
        # -------------------------------------------------

        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO knowledge_documents
                (
                    subject_code,
                    subject_name,
                    module_number,
                    module_title,
                    title,
                    original_filename,
                    file_path,
                    source,
                    status
                )
                VALUES
                (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, 'processing'
                )
                RETURNING id
                """,
                (
                    subject_code,
                    subject_name,
                    module_number,
                    module_title,
                    pdf_path.stem,
                    pdf_path.name,
                    str(pdf_path),
                    source,
                ),
            )

            document_id = cursor.fetchone()[0]

        connection.commit()

        print(f"[OK] Document created: {document_id}")

        # -------------------------------------------------
        # EXTRACT PDF
        # -------------------------------------------------

        print("Extracting PDF text...")

        pages = extract_pdf_pages(pdf_path)

        print(f"[OK] Pages found: {len(pages)}")

        total_chunks = 0
        pages_with_text = 0

        # -------------------------------------------------
        # PROCESS EACH PAGE
        # -------------------------------------------------

        with connection.cursor() as cursor:

            for page in pages:

                page_number = page["page_number"]
                page_text = page["text"]

                if not page_text:
                    continue

                pages_with_text += 1

                chunks = split_text(page_text)

                for chunk_number, chunk in enumerate(
                    chunks,
                    start=1,
                ):

                    cursor.execute(
                        """
                        INSERT INTO knowledge_chunks
                        (
                            document_id,
                            subject_code,
                            module_number,
                            page_number,
                            chunk_number,
                            content,
                            character_count,
                            word_count
                        )
                        VALUES
                        (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s
                        )
                        """,
                        (
                            document_id,
                            subject_code,
                            module_number,
                            page_number,
                            chunk_number,
                            chunk,
                            len(chunk),
                            len(chunk.split()),
                        ),
                    )

                    total_chunks += 1

        # -------------------------------------------------
        # UPDATE DOCUMENT
        # -------------------------------------------------

        with connection.cursor() as cursor:

            cursor.execute(
                """
                UPDATE knowledge_documents
                SET
                    page_count = %s,
                    status = 'processed',
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    len(pages),
                    document_id,
                ),
            )

            cursor.execute(
                """
                INSERT INTO knowledge_processing_logs
                (
                    document_id,
                    action,
                    status,
                    message
                )
                VALUES
                (
                    %s,
                    'pdf_ingestion',
                    'success',
                    %s
                )
                """,
                (
                    document_id,
                    (
                        f"Processed {len(pages)} pages, "
                        f"{pages_with_text} pages with text, "
                        f"{total_chunks} chunks created."
                    ),
                ),
            )

        connection.commit()

        print()
        print(f"[OK] PDF processed successfully")
        print(f"  Document ID : {document_id}")
        print(f"  Pages       : {len(pages)}")
        print(f"  Text pages  : {pages_with_text}")
        print(f"  Chunks      : {total_chunks}")
        print()

        return document_id

    except Exception as error:

        connection.rollback()

        print()
        print(f"[FAIL] PDF processing failed: {error}")
        print()

        try:
            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    UPDATE knowledge_documents
                    SET
                        status = 'failed',
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (document_id,),
                )

                cursor.execute(
                    """
                    INSERT INTO knowledge_processing_logs
                    (
                        document_id,
                        action,
                        status,
                        message
                    )
                    VALUES
                    (
                        %s,
                        'pdf_ingestion',
                        'failed',
                        %s
                    )
                    """,
                    (
                        document_id,
                        str(error),
                    ),
                )

            connection.commit()

        except Exception:
            connection.rollback()

        raise

    finally:
        connection.close()


# ---------------------------------------------------------
# PROCESS FOLDER
# ---------------------------------------------------------

def process_module_folder(
    folder,
    subject_code,
    subject_name,
    module_number,
    module_title,
):
    folder = Path(folder)

    if not folder.exists():
        print(f"Folder does not exist: {folder}")
        return

    pdf_files = sorted(
        folder.glob("*.pdf")
    )

    if not pdf_files:
        print(f"No PDF files found in: {folder}")
        return

    print()
    print("=" * 60)
    print(f"MODULE {module_number}")
    print(f"Found {len(pdf_files)} PDF files")
    print("=" * 60)

    for pdf_file in pdf_files:

        try:
            process_pdf(
                pdf_path=pdf_file,
                subject_code=subject_code,
                subject_name=subject_name,
                module_number=module_number,
                module_title=module_title,
            )

        except Exception as error:

            print(
                f"[FAIL] Skipping {pdf_file.name}: {error}"
            )


# ---------------------------------------------------------
# COMPUTER NETWORKS EXAMPLE
# ---------------------------------------------------------

def process_computer_networks():
    """
    Example structure:

    knowledge_base/
        CS501/
            module1/
            module2/
            module3/
            module4/
            module5/
    """

    subject_code = "CS501"
    subject_name = "Computer Networks"

    module_titles = {
        1: "Module 1",
        2: "Module 2",
        3: "Module 3",
        4: "Module 4",
        5: "Module 5",
    }

    subject_folder = (
        BASE_KNOWLEDGE_FOLDER / subject_code
    )

    for module_number, module_title in module_titles.items():

        module_folder = (
            subject_folder
            / f"module{module_number}"
        )

        process_module_folder(
            folder=module_folder,
            subject_code=subject_code,
            subject_name=subject_name,
            module_number=module_number,
            module_title=module_title,
        )


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("STUDENT SUPPORT AI")
    print("VTU KNOWLEDGE BASE INGESTION")
    print("=" * 60)

    process_computer_networks()

    print()
    print("=" * 60)
    print("INGESTION COMPLETE")
    print("=" * 60)
    print()