"""Subject-hint detection for chat questions (pure functions + DB map).

Maps common abbreviations and name fragments (ADA, DBMS, OS, CN, ...) to
real subject codes from the subjects table, so retrieval can prioritize
the right subject's documents. Nothing here needs torch or a GPU.
"""

import re


# Static aliases checked before the dynamic table-driven map.
STATIC_ALIASES = {
    "ADA": "BCS401",
    "DBMS": "BCS403",
    "DB": "BCS403",
    "OS": "BCS303",
    "OPERATING SYSTEMS": "BCS303",
    "CN": "BCS502",
    "NETWORKS": "BCS502",
    "TOC": "BCS503",
    "FLAT": "BCS503",
    "SEPM": "BCS501",
    "USP": "BCS504",
    "UNIX": "BCS504",
    "DSA": "BCS304",
    "DATA STRUCTURES": "BCS304",
    "DDCO": "BCS302",
    "CO": "BCS302",
    "MATHS": None,  # ambiguous across semesters; resolved dynamically
    "MATH": None,
    "JAVA": "BPLCK205C",
    "PYTHON": None,
    "C++": "BCS306B",
    "CPP": "BCS306B",
    "PHYSICS": "BPHYS202",
    "CHEMISTRY": "BCHES102",
    "KANNADA": "BKSKK107",
    "ENGLISH": None,
    "MECHANICAL": "BESCK204D",
    "ECE": "BESCK104C",
    "CAED": "BCEDK103",
    "DRAWING": "BCEDK103",
    "MICROCONTROLLER": "BCS402",
    "MC": None,
    "ALGORITHMS": "BCS401",
    "WT": "BCSL504",
    "WEB": "BCSL504",
    "RMIP": "BRMK557",
    "IPR": "BRMK557",
    "UHV": "BUHK408",
    "YOGA": None,
    "BIOLOGY": "BBOC407",
    "LATEX": "BCSL456D",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+]*")


def normalize_question(question):
    return (question or "").strip().upper()


def detect_subject_hint(question, known_codes):
    """Return a subject_code hinted by the question, or None.

    known_codes: iterable of real subject codes (validates the hit so a
    forged/unknown code can never be returned).
    """
    known = {str(code).upper() for code in (known_codes or [])}
    text = normalize_question(question)
    if not text:
        return None

    words = set(_WORD_RE.findall(text))

    # Direct code mention wins ("BCS401", "Module 3 of BCS303").
    for word in words:
        if word in known:
            return word

    for alias, code in STATIC_ALIASES.items():
        if code is None:
            continue
        if code not in known:
            continue
        if alias in ("OS", "CN", "DB", "MC", "CO", "WT"):
            # Short aliases only count as standalone words.
            if alias in words:
                return code
        elif alias in text:
            return code

    # Dynamic: distinctive long words from subject names handled by
    # callers via candidates; kept here for testability.
    return None


def dynamic_name_hits(question, code_to_name):
    """Match distinctive subject-name words in the question.

    code_to_name: {code: full name}. Returns codes whose distinctive
    (length>=6, non-stopword) name words appear in the question.
    """
    stop = {
        "ENGINEERING", "SCIENCE", "COMPUTER", "INTRODUCTION", "STRUCTURES",
        "STRUCTURE", "SYSTEMS", "SYSTEM", "MANAGEMENT", "COURSE", "WITH",
        "USING", "FROM", "STREAM", "FOUNDATIONS", "FOUNDATION", "STUDIES",
    }
    words = set(_WORD_RE.findall(normalize_question(question)))
    hits = []
    for code, name in (code_to_name or {}).items():
        for token in _WORD_RE.findall(str(name or "").upper()):
            if len(token) >= 6 and token not in stop and token in words:
                hits.append(code)
                break
    return hits
