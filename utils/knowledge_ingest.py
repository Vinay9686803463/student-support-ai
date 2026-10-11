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
    """Extract text per PDF page.

    Prefers pdfminer.six (fast, good layout handling) and falls back
    to pypdf when pdfminer is unavailable or fails on a file.
    """
    try:
        return _extract_pdf_pages_pdfminer(pdf_path)
    except Exception as pdfminer_error:
        print(f"  [i] pdfminer failed ({pdfminer_error}); trying pypdf...")
        return _extract_pdf_pages_pypdf(pdf_path)


def _extract_pdf_pages_pdfminer(pdf_path, budget_seconds=60):
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTTextContainer
    import time as _time

    laparams = LAParams()
    pages = []
    started = _time.monotonic()

    for page_number, layout in enumerate(
        extract_pages(str(pdf_path), laparams=laparams), start=1
    ):
        if _time.monotonic() - started > budget_seconds:
            print(
                f"  [i] extraction budget exceeded at page {page_number}; "
                f"keeping {len(pages)} pages"
            )
            break
        parts = []
        for element in layout:
            if isinstance(element, LTTextContainer):
                parts.append(element.get_text())
        pages.append(
            {
                "page_number": page_number,
                "text": clean_text("\n".join(parts)),
            }
        )

    return pages


def _extract_pdf_pages_pypdf(pdf_path):
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
# GENERIC DOCUMENT EXTRACTION (PDF + Office + text)
# ---------------------------------------------------------

# Extensions with no indexable text content.
NON_INDEXABLE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
    ".mp4", ".mp3", ".zip",
})


def extract_document_pages(doc_path):
    """Extract text units from any supported document.

    Returns (pages, skipped_reason):
    - PDF   -> one entry per PDF page (page_number = real page).
    - DOCX/DOC/PPT/PPTX/XLSX/TXT -> one entry per ~page-sized text
      block (page_number = block index, 1-based).
    - Images/other -> ([], reason string); never raises for these.
    """
    from utils.office_extract import extract_office_text

    doc_path = Path(doc_path)
    suffix = doc_path.suffix.lower()

    if suffix == ".pdf":
        return extract_pdf_pages(doc_path), ""

    if suffix in NON_INDEXABLE_EXTENSIONS:
        return [], f"extension {suffix} has no indexable text"

    if suffix in (".docx", ".doc", ".ppt", ".pptx", ".pps", ".xlsx", ".txt"):
        try:
            text = extract_office_text(doc_path)
        except Exception as error:
            return [], f"extraction failed: {error}"
        text = clean_text(text)
        if not text:
            return [], "no extractable text (scanned or empty); OCR not available"
        # Block-per-page so chunk/page metadata stays meaningful.
        blocks, current = [], []
        current_len = 0
        for paragraph in text.split("\n"):
            current.append(paragraph)
            current_len += len(paragraph)
            if current_len >= 3000:
                blocks.append("\n".join(current).strip())
                current, current_len = [], 0
        if current:
            leftover = "\n".join(current).strip()
            if leftover:
                blocks.append(leftover)
        return [
            {"page_number": number, "text": block}
            for number, block in enumerate(blocks, start=1)
            if block
        ], ""

    return [], f"unsupported extension: {suffix or '(none)'}"


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
    """Backward-compatible wrapper: PDFs go through process_document."""
    return process_document(
        doc_path=pdf_path,
        subject_code=subject_code,
        subject_name=subject_name,
        module_number=module_number,
        module_title=module_title,
        source=source,
        expect_suffix=".pdf",
    )


def process_document(
    doc_path,
    subject_code,
    subject_name,
    module_number,
    module_title,
    source="",
    expect_suffix=None,
):
    doc_path = Path(doc_path)

    if not doc_path.exists():
        raise FileNotFoundError(
            f"Document not found: {doc_path}"
        )

    if expect_suffix and doc_path.suffix.lower() != expect_suffix:
        raise ValueError(
            f"Expected {expect_suffix} file: {doc_path}"
        )

    print()
    print("-" * 60)
    print(f"Processing: {doc_path.name}")
    print(f"Subject : {subject_name}")
    print(f"Module  : {module_number}")
    print("-" * 60)

    connection = get_connection()

    try:

        existing_id = document_already_exists(
            connection,
            subject_code,
            module_number,
            doc_path.name,
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
                    doc_path.stem,
                    doc_path.name,
                    str(doc_path),
                    source,
                ),
            )

            document_id = cursor.fetchone()[0]

        connection.commit()

        print(f"[OK] Document created: {document_id}")

        # -------------------------------------------------
        # EXTRACT TEXT (PDF pages or Office/text blocks)
        # -------------------------------------------------

        print("Extracting document text...")

        pages, skipped_reason = extract_document_pages(doc_path)

        print(f"[OK] Text units found: {len(pages)}")

        if not pages:
            raise ValueError(
                f"No indexable text: {skipped_reason or 'empty document'}"
            )

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
        print(f"[OK] Document processed successfully")
        print(f"  Document ID : {document_id}")
        print(f"  Text units  : {len(pages)}")
        print(f"  Units w/text: {pages_with_text}")
        print(f"  Chunks      : {total_chunks}")
        print()

        return document_id

    except Exception as error:

        connection.rollback()

        print()
        print(f"[FAIL] Document processing failed: {error}")
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
# RE-INDEX ONE DOCUMENT (handles updated or replaced files)
# ---------------------------------------------------------

def reindex_document_by_id(document_id):
    """Delete a document's chunks and re-extract them from disk.

    Used when the source file changed after the first import, or to
    retry a previously failed document. Embeddings for the fresh
    chunks are (re)generated by generate_embeddings.py. Returns the
    number of chunks created.
    """
    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    subject_code,
                    subject_name,
                    module_number,
                    module_title,
                    original_filename,
                    file_path,
                    source
                FROM knowledge_documents
                WHERE id = %s
                """,
                (document_id,),
            )
            row = cursor.fetchone()

        if not row:
            raise ValueError(f"Document id={document_id} not found")

        (subject_code, _name, module_number, _title,
         filename, file_path, _source) = row

        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM knowledge_chunks WHERE document_id = %s",
                (document_id,),
            )
            deleted = cursor.rowcount

        connection.commit()
        print(f"Deleted {deleted} old chunks for document {document_id}")

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT subject_name, module_title, source
                FROM knowledge_documents
                WHERE id = %s
                """,
                (document_id,),
            )
            meta = cursor.fetchone()

        stored = Path(file_path)
        if not stored.is_absolute():
            stored = Path(__file__).resolve().parent.parent / stored

        pages, skipped = extract_document_pages(stored)

        if not pages:
            raise ValueError(f"No indexable text: {skipped}")

        total = 0
        with connection.cursor() as cursor:
            for page in pages:
                if not page["text"]:
                    continue
                for chunk_number, chunk in enumerate(
                    split_text(page["text"]), start=1
                ):
                    cursor.execute(
                        """
                        INSERT INTO knowledge_chunks
                        (
                            document_id, subject_code, module_number,
                            page_number, chunk_number, content,
                            character_count, word_count
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            document_id, subject_code, module_number,
                            page["page_number"], chunk_number, chunk,
                            len(chunk), len(chunk.split()),
                        ),
                    )
                    total += 1
            cursor.execute(
                """
                UPDATE knowledge_documents
                SET status = 'processed', updated_at = NOW()
                WHERE id = %s
                """,
                (document_id,),
            )
            cursor.execute(
                """
                INSERT INTO knowledge_processing_logs
                (document_id, action, status, message)
                VALUES (%s, 'reindex', 'success', %s)
                """,
                (document_id, f"Re-indexed into {total} chunks."),
            )

        connection.commit()
        print(f"[OK] Document {document_id} re-indexed: {total} chunks")
        return total

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

    doc_files = sorted(
        path
        for path in folder.glob("*")
        if path.is_file()
        and path.suffix.lower()
        in (".pdf", ".docx", ".doc", ".ppt", ".pptx", ".pps", ".xlsx", ".txt")
    )

    if not doc_files:
        print(f"No supported documents found in: {folder}")
        return

    print()
    print("=" * 60)
    print(f"MODULE {module_number}")
    print(f"Found {len(doc_files)} documents")
    print("=" * 60)

    for doc_file in doc_files:

        try:
            process_document(
                doc_path=doc_file,
                subject_code=subject_code,
                subject_name=subject_name,
                module_number=module_number,
                module_title=module_title,
            )

        except Exception as error:

            print(
                f"[FAIL] Skipping {doc_file.name}: {error}"
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