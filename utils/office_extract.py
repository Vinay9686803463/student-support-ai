"""Text extraction for legacy Office formats (stdlib + olefile only).

- .docx  -> ZIP container, word/document.xml (stdlib zipfile/xml)
- .doc   -> OLE streams + carved embedded OOXML packages
- .ppt   -> OLE 'PowerPoint Document' stream, text atoms + runs

Returns plain text with paragraph breaks preserved (best effort).
"""

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import olefile


def _clean(text):
    text = (text or "").replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\x0b\x0c]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_like_text(line):
    """Line-level filter against binary-blob gibberish.

    Real content lines carry multiple words with healthy vowel ratios;
    single-word slide titles/headings are allowed leniently.
    """
    s = (line or "").strip()
    if len(s) < 2:
        return False
    words = re.findall(r"[A-Za-z]{3,}", s)
    letters = sum(char.isalpha() for char in s)
    vowels = sum(char in "aeiouAEIOU" for char in s)
    if (
        len(words) >= 2
        and letters >= len(s) * 0.5
        and vowels >= len(s) * 0.12
    ):
        return True
    if (
        len(words) == 1
        and 5 <= len(s) <= 60
        and letters >= len(s) * 0.8
        and vowels >= 2
    ):
        return True
    return False


def _keep_text_lines(text):
    return "\n".join(
        line for line in (text or "").split("\n") if _looks_like_text(line)
    )


def _parse_docx_xml(xml_bytes):
    """Paragraph texts from word/document.xml bytes."""
    root = ET.fromstring(xml_bytes)
    para_tag = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
    text_tag = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
    parts = []
    for para in root.iter(para_tag):
        texts = [node.text or "" for node in para.iter(text_tag)]
        line = "".join(texts).strip()
        if line:
            parts.append(line)
    return parts


def extract_docx(path):
    """Extract paragraphs (and table cells) from a .docx file."""
    path = str(path)
    with zipfile.ZipFile(path) as zf:
        try:
            xml_bytes = zf.read("word/document.xml")
        except KeyError:
            return ""
    return _clean("\n".join(_parse_docx_xml(xml_bytes)))


def _carve_embedded_docx(blobs):
    """Find ZIP archives embedded in OLE streams (e.g. packaged OOXML
    documents inside a .doc's Data stream) and extract their paragraphs."""
    parts = []
    for data in blobs:
        start = 0
        while True:
            idx = data.find(b"PK\x03\x04", start)
            if idx < 0:
                break
            try:
                with zipfile.ZipFile(io.BytesIO(data[idx:])) as zf:
                    names = zf.namelist()
                    if "word/document.xml" in names:
                        parts.extend(
                            _parse_docx_xml(zf.read("word/document.xml"))
                        )
                        break
            except Exception:
                pass
            start = idx + 1
            if start > len(data) - 4:
                break
    return parts


def _ole_printable_runs(data, min_run=4):
    """Yield printable text runs from binary data.

    Collects UTF-16LE runs (ASCII letters interleaved with NUL bytes)
    and plain latin-1 runs, dropping binary noise.
    """
    runs = []
    # UTF-16LE: printable char followed by NUL, repeated.
    for match in re.finditer(
        rb"(?:[\x20-\x7e]\x00){%d,}" % min_run, data
    ):
        runs.append(match.group(0).decode("utf-16-le", errors="ignore"))
    # Plain 8-bit runs (skip ones already covered implicitly is hard;
    # dedupe later by caller if needed).
    for match in re.finditer(rb"[ -~]{%d,}" % (min_run * 2,), data):
        runs.append(match.group(0).decode("latin-1", errors="ignore"))
    return runs


def extract_doc(path):
    """Best-effort text from legacy .doc (Word 97-2003) files.

    Reads the WordDocument stream plus the Data stream (which holds
    drawing/textbox content such as form templates).
    """
    path = str(path)
    if not olefile.isOleFile(path):
        return ""
    ole = olefile.OleFileIO(path)
    try:
        blobs = []
        for stream_name in ("WordDocument", "Data", "1Table"):
            if ole.exists(stream_name):
                try:
                    with ole.openstream(stream_name) as stream:
                        blobs.append(stream.read())
                except Exception:
                    continue
    finally:
        ole.close()
    runs = []
    for data in blobs:
        runs.extend(_ole_printable_runs(data))
    # Drop runs that are clearly field-code/binary junk, then keep only
    # lines that read like real text (kills embedded image/font noise).
    kept = []
    for run in runs:
        stripped = run.strip()
        if len(stripped) < 4:
            continue
        letters = sum(char.isalpha() for char in stripped)
        if letters < len(stripped) * 0.4:
            continue
        kept.append(stripped)
    # Embedded OOXML packages (e.g. a packaged .docx inside Data).
    kept.extend(_carve_embedded_docx(blobs))
    cleaned = [line for line in kept if not _package_noise(line)]
    return _clean(_keep_text_lines("\n".join(cleaned)))


def extract_ppt(path):
    """Best-effort text from legacy .ppt (PowerPoint 97-2003) files.

    Scans the 'PowerPoint Document' stream for TextCharsAtom (0x0FA0,
    UTF-16LE payload) and TextBytesAtom (0x0FA1, 8-bit payload) records.
    """
    path = str(path)
    if not olefile.isOleFile(path):
        return ""
    ole = olefile.OleFileIO(path)
    try:
        if ole.exists("PowerPoint Document"):
            with ole.openstream("PowerPoint Document") as stream:
                data = stream.read()
        else:
            # Fall back to the largest stream.
            biggest, best = 0, None
            for entry in ole.listdir():
                try:
                    size = ole.get_size(entry)
                except Exception:
                    continue
                if size > biggest:
                    biggest, best = size, entry
            if best is None:
                return ""
            with ole.openstream(best) as stream:
                data = stream.read()
    finally:
        ole.close()

    texts = []
    _ppt_walk(data, texts)
    lines = [
        line
        for line in _keep_text_lines("\n".join(texts)).split("\n")
        if line.strip() and not _ppt_noise(line)
    ]
    if not lines:
        # Fallback: printable runs straight from the stream.
        runs = []
        for run in _ole_printable_runs(data):
            stripped = run.strip()
            if len(stripped) >= 4:
                runs.append(stripped)
        lines = [
            line
            for line in _keep_text_lines("\n".join(runs)).split("\n")
            if line.strip() and not _ppt_noise(line)
        ]
    # Dedupe master-slide repeats, preserving order.
    seen, deduped = set(), []
    for line in lines:
        key = line.strip()
        if key and key not in seen and not _package_noise(key):
            seen.add(key)
            deduped.append(line)
    return _clean("\n".join(deduped))

_PPT_TEMPLATE_NOISE = ("Placeholder", "Office Theme", "KSO_", "Click to edit")

_PPT_OUTLINE_LEVELS = frozenset({
    "First level", "Second level", "Third level", "Fourth level", "Fifth level",
})

# OOXML package/style debris that leaks out of hybrid binary files.
_PACKAGE_NOISE = (
    "[Content_Types]", ".rels", ".xml", "theme/", "_rels", "PK",
    "<?xml", "xmlns", "DrawingML", "drawingml",
    "http://", "https://", "www.",
    "AutoShape", "Text Box", "_GoBack", "ACD Systems",
    "PMingLiU", "MSungLiU",
)

_STYLE_NAMES = frozenset({
    "Normal", "Default Paragraph Font", "Table Normal", "No List",
    "Body Text", "Title", "List Paragraph", "Table Paragraph", "Unknown",
    "Heading", "Caption", "Subtitle", "Header", "Header Char", "Admin",
})

_FONT_NAMES = frozenset({
    "Arial", "Calibri", "Calibri Light", "Times New Roman", "Symbol",
    "Wingdings", "Cambria Math", "Cambria", "Tahoma", "Verdana",
})

_CONSONANT_RUN = re.compile(r"[bcdfghjklmnpqrstvwxzBCDFGHJKLMNPQRSTVWXZ]{5,}")


def _package_noise(line):
    stripped = (line or "").strip()
    if any(key in stripped for key in _PACKAGE_NOISE):
        return True
    if stripped in _STYLE_NAMES or stripped in _FONT_NAMES:
        return True
    # Random binary decoded as text forms impossible consonant clusters.
    return bool(_CONSONANT_RUN.search(stripped))


def _ppt_noise(line):
    stripped = (line or "").strip()
    if any(key in stripped for key in _PPT_TEMPLATE_NOISE):
        return True
    if stripped in _FONT_NAMES or stripped in _PPT_OUTLINE_LEVELS:
        return True
    return False


def _ppt_walk(data, texts):
    """Recursively walk PowerPoint records, collecting text atoms.

    Container records (recVer == 0x0F) are descended into; TextCharsAtom
    (0x0FA0, UTF-16LE) and TextBytesAtom (0x0FA1, 8-bit) payloads are kept.
    """
    pos, end = 0, len(data)
    while pos + 8 <= end:
        header = int.from_bytes(data[pos:pos + 2], "little")
        rec_ver = header & 0x000F
        rec_type = int.from_bytes(data[pos + 2:pos + 4], "little")
        rec_len = int.from_bytes(data[pos + 4:pos + 8], "little")
        if rec_len < 0 or pos + 8 + rec_len > end + 8:
            break
        payload = data[pos + 8:pos + 8 + rec_len]
        if rec_ver == 0x0F:
            _ppt_walk(payload, texts)
        elif rec_type == 0x0FA0:  # TextCharsAtom: UTF-16LE
            try:
                decoded = payload.decode("utf-16-le", errors="ignore").strip()
                if decoded:
                    texts.append(decoded)
            except Exception:
                pass
        elif rec_type == 0x0FA1:  # TextBytesAtom: 8-bit chars
            try:
                decoded = payload.decode("latin-1", errors="ignore").strip()
                if decoded:
                    texts.append(decoded)
            except Exception:
                pass
        if rec_len == 0 and rec_ver != 0x0F:
            pos += 8
        else:
            pos += 8 + rec_len


def extract_office_text(path):
    """Dispatch by extension; returns plain text (possibly empty)."""
    suffix = Path(path).suffix.lower()
    if suffix == ".docx":
        return extract_docx(path)
    if suffix == ".doc":
        return extract_doc(path)
    if suffix in (".ppt", ".pptx", ".pps"):
        return extract_ppt(path)
    return ""
