"""First-run study content for a locally created database."""

from pathlib import Path

from sqlalchemy import text

from utils.database import db

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _safename(filename):
    """Console-safe filename for log lines.

    Windows consoles (cp1252) raise UnicodeEncodeError printing emoji
    such as the Hibiscus in one physics filename, which would abort the
    whole registration run. Backslash-escaping keeps every terminal
    working while staying informative.
    """
    return str(filename).encode("ascii", "backslashreplace").decode("ascii")


def _safename(filename):
    """Console-safe filename for log lines.

    Windows consoles (cp1252) crash printing emoji (e.g. the Hibiscus in
    a physics filename); the deployed Linux logs are UTF-8. Escaping
    keeps both working and stays informative.
    """
    return str(filename).encode("ascii", "backslashreplace").decode("ascii")


def log_message(message):
    """Console print that never crashes on non-UTF-8 terminals.

    Windows consoles default to cp1252, where logging a filename with
    an emoji (or any non-Latin character) raises UnicodeEncodeError and
    would abort the whole registration run. Fall back to an
    ASCII-escaped line instead of crashing.
    """
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        print(ascii(message), flush=True)


def resolve_study_file(code, filename, module_number):
    """Locate an on-disk study file, or None when absent.

    Tries the mapped location first (moduleN/ or additional/
    subdirectories, else flat under knowledge_base/<CODE>/), then falls
    back to the other known locations. The fallback lets one stored
    file back two document rows (e.g. BPHYS202 Module 5 registered in
    both its module section and Additional Resources) while every row
    still points at the real file — a row is never created for a file
    that is not on disk.
    """
    subdir = STUDY_MATERIAL_SUBDIRS.get(code, {}).get(module_number, "")
    candidates = []
    if subdir:
        candidates.append(
            PROJECT_ROOT / "knowledge_base" / code / subdir / filename
        )
    candidates.append(PROJECT_ROOT / "knowledge_base" / code / filename)
    for n in (1, 2, 3, 4, 5):
        candidates.append(
            PROJECT_ROOT / "knowledge_base" / code / f"module{n}" / filename
        )
    candidates.append(
        PROJECT_ROOT / "knowledge_base" / code / "additional" / filename
    )
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            return candidate
    return None

DEFAULT_SUBJECTS = [
    ("BCS501", "Software Engineering & Project Management"),
    ("BCS502", "Computer Networks"),
    ("BCS503", "Theory of Computation"),
    ("BCS508", "Environmental Studies and E-Waste Management"),
    ("BCS515x", "Professional Elective Course"),
    ("BCSL504", "Web Technology Lab"),
    ("BNSK559", "National Service Scheme (NSS)"),
    ("BPEK559", "Physical Education (PE) (Sports and Athletics)"),
    ("BRMK557", "Research Methodology and IPR"),
    ("BYOK559", "Yoga"),
]

DEFAULT_QUESTIONS = [
    ("BCS501", "Explain the waterfall model with its advantages and disadvantages.", "Unit 1", 10, "Medium", True, "Requirements -> Design -> Implementation -> Testing -> Maintenance. Simple and disciplined; suits stable requirements. Weakness: inflexible to late changes."),
    ("BCS501", "What is agile methodology? Compare agile with the spiral model.", "Unit 1", 10, "Medium", True, "Agile delivers working software in short sprints with customer collaboration. Spiral adds risk analysis loops per iteration; agile prioritizes responding to change over following a plan."),
    ("BCS501", "Explain COCOMO model for software cost estimation with an example.", "Unit 3", 10, "Hard", True, "COCOMO estimates effort as a*(KLOC)^b using project mode constants (organic, semi-detached, embedded), then derives schedule and staffing."),
    ("BCS501", "What is software testing? Explain black-box vs white-box testing.", "Unit 4", 10, "Medium", True, "Black-box tests functionality without code knowledge. White-box tests internal logic such as statement, branch and path coverage."),
    ("BCS501", "Explain risk management: identification, analysis and mitigation.", "Unit 5", 5, "Easy", False, "Identify risks early, assess probability and impact, plan mitigation, and monitor risks through the project."),
    ("BCS502", "Explain the seven layers of the OSI reference model with their functions.", "Unit 1", 10, "Easy", True, "Physical, Data Link, Network, Transport, Session, Presentation and Application each provide services to the layer above."),
    ("BCS502", "Compare TCP and UDP with suitable applications of each.", "Unit 3", 10, "Medium", True, "TCP is connection-oriented and reliable for the web, email and file transfer. UDP is connectionless with low overhead for streaming, DNS and gaming."),
    ("BCS502", "Explain classful IP addressing and subnetting with an example.", "Unit 2", 10, "Medium", True, "Classes A-E divide the 32-bit address space. Subnetting borrows host bits to create smaller networks; a /26 has 62 usable hosts per subnet."),
    ("BCS502", "What is routing? Explain distance vector routing with an example.", "Unit 3", 10, "Hard", True, "Each router shares its distance table with neighbours using Bellman-Ford. It is simple but can converge slowly."),
    ("BCS502", "Explain CSMA/CD and CSMA/CA access methods.", "Unit 2", 5, "Easy", False, "CSMA/CD detects collisions on wired Ethernet and backs off; CSMA/CA avoids collisions on wireless using RTS/CTS handshakes."),
    ("BCS503", "Explain finite automata and distinguish between DFA and NFA.", "Unit 2", 10, "Medium", True, "A DFA has exactly one transition per symbol per state. An NFA allows zero, one or many transitions plus epsilon moves. Every NFA has an equivalent DFA."),
    ("BCS503", "State and prove the pumping lemma for regular languages. Give one application.", "Unit 2", 10, "Hard", True, "Any long enough string in a regular language can be pumped. It can prove languages such as {a^n b^n} are not regular."),
    ("BCS503", "Design a Turing machine for language {a^n b^n c^n, n >= 1}.", "Unit 4", 10, "Hard", True, "Repeatedly mark one a, one b and one c while scanning; accept only when all symbols are marked and counts match."),
    ("BCS503", "Explain pushdown automata and its application in parsing.", "Unit 3", 10, "Medium", True, "A PDA adds a stack to finite control and recognizes context-free languages, making it the basis of parsing programming language syntax."),
    ("BCS503", "What is the halting problem? Why is it undecidable?", "Unit 5", 5, "Easy", False, "No program can decide for every input whether an arbitrary program halts; a diagonalization proof shows any decider contradicts itself."),
]

DEFAULT_RESOURCES = [
    (None, "NPTEL Computer Networks Course", "Free IIT video course covering OSI, TCP/IP, routing and switching.", "Videos", "https://nptel.ac.in"),
    (None, "VTU Official Website", "Syllabus, notifications and official VTU updates.", "Official", "https://vtu.ac.in"),
    (None, "GeeksforGeeks CSE", "Concepts, examples and quizzes for DBMS, OS, CN and TOC.", "Programming", "https://www.geeksforgeeks.org"),
    ("BCS502", "Computer Networks Notes", "Layered architecture, addressing, routing and transport protocols.", "Notes", None),
    ("BCS503", "TOC Practice Questions", "Automata, grammars, PDA and Turing machine problems.", "Papers", None),
    ("BCS501", "Software Engineering Notes", "Process models, estimation, testing and project management.", "Notes", None),
]

# Canonical file-backed Semester-1 subjects. The boot ensure below
# re-creates these rows if they were deleted and repairs a wrong
# name/semester/branch/scheme/category so the subjects always list.
# ONLY these codes are ever touched; credits, icon and description
# are always left alone, and no other subject row is written.
# (code, name, semester, branch, scheme, category, credits)
CANONICAL_SUBJECTS = [
    ("BKSKK107", "Samskrutika Kannada", 1, "CSE", "2022", "Core", 1),
    ("BSFHK158", "Scientific Foundations of Health", 1, "CSE", "2022", "Core", 1),
    ("BESCK204D", "Introduction to Mechanical Engineering", 2, "CSE", "2022", "Core", 4),
    ("BICOK207", "Indian Constitution", 2, "CSE", "2022", "Core", 1),
    ("BMATS201", "Mathematics for CSE Stream-II", 2, "CSE", "2022", "Core", 4),
    # NOTE: the corrected spelling "Basics" (not VTU's "Baasics"
    # typo) is canonical everywhere: this table, seed_subject_modules.py,
    # seed_semesters_1_to_4.py, seed_sem1_sem2.py, fix_sem_codes_1_to_4.py
    # and rename_sem2_subjects.py must all use it, or re-running any of
    # them would flip-flop the displayed name.
    ("BPLCK205C", "Basics of Java Programming", 2, "CSE", "2022", "Core", 4),
    ("BIDTK258", "Innovation and Design Thinking", 2, "CSE", "2022", "Core", 1),
    ("BPOPS203", "Principles of Programming Using C", 2, "CSE", "2022", "Core", 4),
    ("BPHYS202", "Physics for CSE Stream", 2, "CSE", "2022", "Core", 4),
]

# Study-material PDFs committed under knowledge_base/<CODE>/.
# (code, [(filename, module_number slot), ...]). module_number is a
# sequential slot (same convention as the BENGK106/BMATS101 unnumbered
# files); the subject page renders these codes as unnumbered file cards,
# so the number never implies module content. Module 0 is avoided so
# files never duplicate into the Additional Resources section.
# Filenames must match the files on disk exactly.
STUDY_MATERIALS = {
    "BKSKK107": [
        ("KANNADA QUESTIONS.pdf", 1),
        ("Kannada Textbook and MCQs.pdf", 2),
        ("SK QB 1.pdf", 3),
        ("SK Model QP-1.pdf", 4),
        ("SK QB 2.pdf", 5),
        ("SK QB 3.pdf", 6),
        ("DocScanner May 7, 2023 5-45 PM.pdf", 7),
        ("DocScanner Apr 14, 2023 16-39.pdf", 8),
    ],
    "BSFHK158": [
        ("SHF QB wid Ans TIE (1).pdf", 1),
        ("SFH syllabus.pdf", 2),
        ("sfh set 2 Solved.pdf", 3),
        ("sfh set 1 solved.pdf", 4),
        ("SFH QP2.pdf", 5),
        ("SFH QP1.pdf", 6),
        ("sfh prev year 21 QP.pdf", 7),
        ("sfh prev sem QP.pdf", 8),
        ("SFH Module 1.pdf", 9),
        ("SFH Assignment 2.pdf", 10),
        ("SCIENTIFIC_FOUNDATIONS_OF_HEALTH_QUESTION_BANK_230_231018_181032.pdf", 11),
        ("Scientific Foundation Of Health MCQ.pdf", 12),
        ("21SFH29set2.pdf", 13),
        ("21SFH29set1.pdf", 14),
    ],
    "BESCK204D": [
        ("Module 1.pdf", 1),
        ("Module 2.pdf", 2),
        ("Module 3.pdf", 3),
        ("Module 4.pdf", 4),
        ("Module 5.pdf", 5),
        ("IME QP 1.pdf", 0),
        ("IME SEE QP.pdf", 0),
        ("Module 5 question Answers.pdf", 0),
        ("Module 5 short Notes.pdf", 0),
        ("Module 4 question Answers.pdf", 0),
        ("Module 3 (2).pdf", 0),
        ("pdf&rendition=1.pdf", 0),
        ("Module 1 (2).pdf", 0),
        ("Module 1 question Answers.pdf", 0),
        ("Module 2 (2).pdf", 0),
        ("Module 2 question Answers.pdf", 0),
    ],
    "BICOK207": [
        ("Notes 1.pdf", 1),
        ("Notes 2.pdf", 2),
        ("MODULE 3 MCQs.pdf", 3),
        ("Module_4_-_Parliament.pdf", 4),
        ("Module_5_-_State_Executive_and_Governor.pdf", 5),
        ("Module_3_-_Directive_Principles_of_State_Policy_(DPSPs).pdf", 0),
        ("Module 1 & 2 MCQs-IC.pdf", 0),
        ("INDIAN CONSTITUTION  NOTES Module 1 to 5.pdf", 0),
        ("IC Module 3 and 4 Notes.pdf", 0),
        ("IC Mod 5 MCQ @vtudeveloper.in.pdf", 0),
        ("IC Mod 4 MCQ @vtudeveloper.in.pdf", 0),
        ("IC Mod 3 MCQ @vtudeveloper.in.pdf", 0),
        ("IC Mod 2 MCQ @vtudeveloper.in.pdf", 0),
        ("IC Mod 1 MCQ @vtudeveloper.in.pdf", 0),
        ("IC Assignment I.pdf", 0),
        ("IC Assignment 2 Module 3 & 4.pdf", 0),
    ],
    # NOTE: 'July-2024 math.pdf' from Downloads is deliberately excluded:
    # its bytes are an HTML page (Google Analytics script), not a PDF -
    # same failure mode as the Chemistry 'Aug-2022.pdf' precedent in
    # ingest_additional_resources.py. Register it only when a genuine
    # July-2024 PDF is provided.
    "BMATS201": [
        ("BMATS201 Mod3@AzDOCUMENTS.in (1).pdf", 1),
        # Real on-disk name has a trailing space before ".pdf".
        ("BMATS201 MQP 1 & 2 .pdf", 2),
        ("Jan 2024 math.pdf", 3),
        ("July 2023 math.pdf", 4),
        ("Lab Manual Engineering Maths 2 VTU.pdf", 5),
        ("PDFGallery_20250528_111409.pdf", 6),
        ("Sealed-E-version-Mathematics-Handbook-for-I-II-Semester-22-Scheme.pdf", 7),
    ],
    # Java files requested but NOT listed (all verified absent from
    # Downloads, including subfolders): '22PLC13cset1.pdf',
    # 'JAVA MODULE 4 ANSWERS.pdf', 'JAVA MODULE 1 ANSWERS SACHIN.pdf'.
    # Similar-but-different files exist ('22PLC15cset1.pdf',
    # 'JAVA MODULE 4 ANSWERS..pdf', 'JAVA_MODULE_1 ANSWERS SACHIN.pdf')
    # and were deliberately NOT substituted - exact filenames only.
    "BPLCK205C": [
        ("Module 1 - JAVA.pdf", 1),
        ("MODULE 2 - JAVA.pdf", 2),
        ("Module 3 - JAVA.pdf", 3),
        ("MODULE 4 - JAVA.pdf", 4),
        ("BPLCK105C-BPLCK205C_module-5-textbook.pdf", 5),
        ("BPLCK105C-BPLCK205C_model-set-1-paper.pdf", 0),
        ("BPLCK205C-JAVA LAB MANUAL.pdf", 0),
        ("JAVA ALL MODULE QUE.pdf", 0),
        ("JAVA ANSWERS VTU 1.pdf", 0),
        ("Java Assignment 1.pdf", 0),
        ("Java assignment 2.pdf", 0),
        ("Java Assignment 3.pdf", 0),
        ("Java assignment.pdf", 0),
        ("JAVA MODEL QUESTION PAPER'S .pdf", 0),
        ("JAVA MODULE 1 QUESTIONS.docx", 0),
        ("JAVA MODULE 2 ANSWERS SACHIN.pdf", 0),
        ("JAVA MODULE 3 ANSWER..pdf", 0),
        ("Java previous year question papers.pdf", 0),
        ("JAVA QB2.pdf", 0),
        ("JAVA QB3.docx", 0),
        ("Java.pdf", 0),
        ("Module3.pdf", 0),
        ("module4.pdf", 0),
        ("PDF Gallery_20250424_191432.pdf", 0),
    ],
    # NOTE: the requested 'IDT Previous year question papers.pdf' does
    # not exist in Downloads; the real file is spelled 'IDT Privious
    # year question papers.pdf' ("Privious" typo) and is registered
    # as-is (never renamed). If a correctly-spelled file appears later,
    # add it as an additional row.
    "BIDTK258": [
        ("IDT Assignment II 2025.pdf", 1),
        ("IDT Assignment-01 2025.pdf", 2),
        ("IDT MCQ @vtudeveloper.in.pdf", 3),
        ("IDT Privious year question papers.pdf", 4),
    ],
    # C-programming files requested but NOT listed: 4 month/year "PDFs"
    # (Feb-2023.pdf, Jan-2024.pdf, July-2023.pdf, July-2024.pdf) are HTML
    # pages, not PDFs; 5 files are absent from Downloads
    # ('Arithmetic_Operators_in_C.docx', 'Paper-1-BPOPS103- Model Paper
    # Solution.pdf', 'Paper-2-BPOPS103- Model Paper Solution.pdf',
    # 'Pointers1-pgm.pptx', 'QB_1&2&Module.docx'). Near-matches exist
    # ('Paper-1/2-...-2022-23.pdf', 'QB_1&2Module.docx') and were NOT
    # substituted. Abbreviated requests resolved to
    # 'C programs_examples_Algorithms_Flowcharts.docx' and
    # 'Computer fundamentals and programming in C 2nd ed.pdf'.
    # Module 2 filename verified Latin O (no Cyrillic characters).
    "BPOPS203": [
        ("BPOPS103 Mod1@AzDOCUMENTS.in.pdf", 1),
        ("BPOPS103 Mod2@AzDOCUMENTS.in.pdf", 2),
        ("BPOPS103 Mod3@AzDOCUMENTS.in.pdf", 3),
        ("BPOPS103 Mod4@AzDOCUMENTS.in.pdf", 4),
        ("BPOPS103 Mod5@AzDOCUMENTS.in.pdf", 5),
        ("Module 1.pptx", 0),
        ("module 2.pptx", 0),
        ("Module3.pptx", 0),
        ("Module_4.pdf", 0),
        ("Module5.pptx", 0),
        ("1AMCS0000455_CS_BPOPS203.pdf", 0),
        ("22POP13 IMPORTANT Q-Ans.pdf", 0),
        ("22POP13LAB.pdf", 0),
        ("22POP13set1.pdf", 0),
        ("Assignment_Operators_in_C.docx", 0),
        ("Bitwise_Operators_in_C.docx", 0),
        ("BPOPS203-IA-FINAL.xlsx", 0),
        ("C Program Assignment3.docx", 0),
        ("C Programming.pptx", 0),
        ("C programs_examples_Algorithms_Flowcharts.docx", 0),
        ("C programs_examples_errors_in_c.docx", 0),
        ("Computer fundamentals and programming in C 2nd ed.pdf", 0),
        ("Conditional_Operators_in_C.docx", 0),
        ("Input output statements in C.docx", 0),
        ("Logical_Operators_in_C.docx", 0),
        ("M3-2.pdf", 0),
        ("Model Question Paper.pdf", 0),
        ("Module 5 - Files.pptx", 0),
        ("Module 5 structures_files.pptx", 0),
        ("Module1ACET.pptx", 0),
        ("Module4-1.pptx", 0),
        ("Pointers ppt.pptx", 0),
        ("Relational_Operators_in_C.docx", 0),
        ("Solutions.docx", 0),
        ("Unary_Operators_in_C.docx", 0),
    ],
    # 'BPHYS102_202 MODULE 5.pdf' is intentionally listed twice (slots 5
    # and 0): one stored file, two document rows, so it is available in
    # both the Module 5 section and Additional Resources. The on-disk
    # name below uses an escape; the real file is 'physics <HIBISCUS>.pdf'
    # (U+1F33A) — registered exactly as found, never renamed.
    "BPHYS202": [
        ("BPHYS102_202 MODULE 1.pdf", 1),
        ("Module 2 Quantum Mechanics Notes.pdf", 2),
        ("module-3-quantum-computing-quantum-gates (1).pdf", 3),
        ("BPHYS102_202 MODULE 4.pdf", 4),
        ("BPHYS102_202 MODULE 5.pdf", 5),
        ("22_scheme_physics_for_cse_module_4_notes.pdf", 0),
        # Same stored file as the Module 5 row above (explicit subdir
        # override); one file on disk, two document rows.
        ("BPHYS102_202 MODULE 5.pdf", 0, "module5"),
        ("Module 5 Physics of Animation.pdf", 0),
        ("4-2024-Jan-Solved Numerical-CSE.pdf", 0),
        ("5-2024-july-solved numericals-CSE-WWM.pdf", 0),
        ("7-2025-Jan-Solved Numerical-CSE-WWM.pdf", 0),
        ("Assignment I- Physics.pdf", 0),
        ("Assignment II- Physics.pdf", 0),
        ("Assignment III- Physics.pdf", 0),
        ("BPHYS102_202 MODEL QP2 WITH SOLUTION.pdf", 0),
        ("BPHYS102_202 PQP 1.pdf", 0),
        ("BPHYS102_202 QUESTION BANK ALL MODULE .pdf", 0),
        ("Model question paper Physics - converted.pdf", 0),
        ("Model question paper Physics.pdf", 0),
        ("phy aas.pdf", 0),
        ("PHY_Quantum Mechanis_Part 1.pdf", 0),
        ("physics assignment 2.pdf", 0),
        ("Physics Handbook.pdf", 0),
        ("physics \U0001f33a.pdf", 0),
        ("SOLVED NUMERICALS -JAN 2023 - CSE-STREAM.pdf", 0),
        ("SOLVED NUMERICALS -JULY 2023 - CSE-STREAM.pdf", 0),
    ],
}

# Per-code storage subdirectories and module titles for STUDY_MATERIALS
# entries that do not live flat under knowledge_base/<CODE>/. Follows
# the established precedents: module-wise PDFs under moduleN/ titled
# "Module N" (BCS502), extra files under additional/ titled
# "Additional Resources" (BCHES102). Codes absent here keep the
# unnumbered-file convention (flat layout, NULL module_title).
# {code: {module_number: subdir}}
STUDY_MATERIAL_SUBDIRS = {
    "BESCK204D": {
        1: "module1",
        2: "module2",
        3: "module3",
        4: "module4",
        5: "module5",
        0: "additional",
    },
    "BICOK207": {
        1: "module1",
        2: "module2",
        3: "module3",
        4: "module4",
        5: "module5",
        0: "additional",
    },
    "BPLCK205C": {
        1: "module1",
        2: "module2",
        3: "module3",
        4: "module4",
        5: "module5",
        0: "additional",
    },
    "BPOPS203": {
        1: "module1",
        2: "module2",
        3: "module3",
        4: "module4",
        5: "module5",
        0: "additional",
    },
    "BPHYS202": {
        1: "module1",
        2: "module2",
        3: "module3",
        4: "module4",
        5: "module5",
        0: "additional",
    },
}
# {code: {module_number: module_title}}
STUDY_MATERIAL_TITLES = {
    "BESCK204D": {
        1: "Module 1",
        2: "Module 2",
        3: "Module 3",
        4: "Module 4",
        5: "Module 5",
        0: "Additional Resources",
    },
    "BICOK207": {
        1: "Module 1",
        2: "Module 2",
        3: "Module 3",
        4: "Module 4",
        5: "Module 5",
        0: "Additional Resources",
    },
    "BPLCK205C": {
        1: "Module 1",
        2: "Module 2",
        3: "Module 3",
        4: "Module 4",
        5: "Module 5",
        0: "Additional Resources",
    },
    "BPOPS203": {
        1: "Module 1",
        2: "Module 2",
        3: "Module 3",
        4: "Module 4",
        5: "Module 5",
        0: "Additional Resources",
    },
    "BPHYS202": {
        1: "Module 1",
        2: "Module 2",
        3: "Module 3",
        4: "Module 4",
        5: "Module 5",
        0: "Additional Resources",
    },
}


def ensure_canonical_subjects():
    """Re-create missing file-backed subject rows; repair wrong attrs.

    Only CANONICAL_SUBJECTS codes are touched. Missing rows are
    INSERTed with their canonical attributes (matching the live
    canonical rows). Existing rows keep their id/credits/icon/
    description; only a wrong name/semester/branch/scheme/category is
    repaired so the subject lists again. Never deletes. Never raises:
    any failure rolls back that code and logs, so boot continues.
    """
    for code, name, semester, branch, scheme, category, credits in CANONICAL_SUBJECTS:
        try:
            row = db.session.execute(
                text("""
                    SELECT id, subject_name, semester, branch, scheme,
                           category
                    FROM subjects
                    WHERE subject_code = :c
                """),
                {"c": code},
            ).mappings().first()
            if row is None:
                db.session.execute(
                    text("""
                        INSERT INTO subjects
                            (subject_code, subject_name, semester, branch,
                             scheme, credits, icon, category)
                        VALUES (:c, :n, :s, :b, :sc, :cr, '📚', :cat)
                    """),
                    {"c": code, "n": name, "s": semester, "b": branch,
                     "sc": scheme, "cr": credits, "cat": category},
                )
                db.session.commit()
                print(f"  + subject restored: {code} ({name})")
                continue
            fix = {}
            if row["subject_name"] != name:
                fix["subject_name"] = name
            if row["semester"] != semester:
                fix["semester"] = semester
            if row["branch"] != branch:
                fix["branch"] = branch
            if row["scheme"] != scheme:
                fix["scheme"] = scheme
            if (row["category"] or "Core") != category:
                fix["category"] = category
            if fix:
                assignments = ", ".join(f"{k} = :{k}" for k in fix)
                fix["c"] = code
                db.session.execute(
                    text(f"UPDATE subjects SET {assignments} "
                         "WHERE subject_code = :c"),
                    fix,
                )
                db.session.commit()
                print(f"  ~ subject repaired: {code} {sorted(fix)}")
            try:
                # Keep the subject_name stamped on this subject's already
                # registered study-material rows in sync (display
                # consistency only; routing/filtering uses subject_code
                # and is unaffected). Table may not exist yet — skip then.
                repaired_docs = db.session.execute(
                    text("""
                        UPDATE knowledge_documents
                        SET subject_name = :n
                        WHERE subject_code = :c
                          AND subject_name != :n
                    """),
                    {"n": name, "c": code},
                ).rowcount
                if repaired_docs:
                    db.session.commit()
                    print(f"  ~ {repaired_docs} document row(s) renamed "
                          f"for {code}")
            except Exception as doc_error:
                db.session.rollback()
                print(f"  ! document names for {code} skipped: {doc_error}")
        except Exception as error:
            db.session.rollback()
            print(f"  ! canonical subject {code} skipped: {error}")


def ensure_study_materials():
    """Register on-disk study files lacking a document row.

    For each STUDY_MATERIALS code, every listed file present under its
    directory gets one knowledge_documents row per listed
    (filename, module_number) slot (title=filename stem, status
    'uploaded') unless a row for that triple already exists. PDFs
    record their
    pypdf page count; Office documents (.docx/.doc/.ppt/.pptx/.xlsx,
    served as downloads by the existing document viewer) record 0. Existing
    rows are never updated or deleted. Files missing from disk are
    logged and skipped. Never raises: failures roll back and log.
    """
    try:
        from pypdf import PdfReader
    except ImportError as error:
        print(f"  ! study materials skipped (pypdf unavailable): {error}")
        return
    names = {c: n for c, n, _s, _b, _sc, _cat, _cr in CANONICAL_SUBJECTS}
    subdirs = STUDY_MATERIAL_SUBDIRS
    titles = STUDY_MATERIAL_TITLES
    for code, files in STUDY_MATERIALS.items():
        try:
            # Keyed by (filename, module): one subject may intentionally
            # list the same file under two slots (e.g. BPHYS202 Module 5
            # appears in both Module 5 and Additional Resources).
            existing = {
                (row[0], row[1]) for row in db.session.execute(
                    text("""
                        SELECT original_filename, module_number
                        FROM knowledge_documents
                        WHERE subject_code = :c
                    """),
                    {"c": code},
                ).fetchall()
            }
        except Exception as error:
            db.session.rollback()
            print(f"  ! study materials for {code} skipped: {error}")
            continue
        for entry in files:
            filename, module_number = entry[0], entry[1]
            if (filename, module_number) in existing:
                continue
            subdir = (
                entry[2]
                if len(entry) > 2
                else subdirs.get(code, {}).get(module_number, "")
            )
            module_title = titles.get(code, {}).get(module_number)
            if subdir:
                pdf_path = PROJECT_ROOT / "knowledge_base" / code / subdir / filename
            else:
                pdf_path = PROJECT_ROOT / "knowledge_base" / code / filename
            if not pdf_path.is_file():
                print(f"  ! file missing, skipping: {code}/{_safename(filename)}")
                continue
            suffix = pdf_path.suffix.lower()
            if suffix == ".pdf":
                try:
                    pages = len(PdfReader(str(pdf_path)).pages)
                except Exception as error:
                    print(f"  ! unreadable PDF, skipping {_safename(filename)}: {_safename(error)}")
                    continue
                if pages < 1:
                    print(f"  ! empty PDF, skipping: {_safename(filename)}")
                    continue
            elif suffix in (".docx", ".doc", ".ppt", ".pptx", ".xlsx"):
                # Office documents reuse the existing document viewer
                # (/knowledge/document/<id> serves them as downloads;
                # .xlsx falls back to application/octet-stream there);
                # page counts do not apply, so 0 hides the label.
                if pdf_path.stat().st_size < 1:
                    print(f"  ! empty document, skipping: {_safename(filename)}")
                    continue
                pages = 0
            else:
                print(f"  ! unsupported type, skipping: {_safename(filename)}")
                continue
            try:
                db.session.execute(
                    text("""
                        INSERT INTO knowledge_documents
                            (subject_code, subject_name, module_number,
                             module_title, title, original_filename,
                             file_path, page_count, status)
                        VALUES (:c, :n, :m, :mt, :t, :f, :p, :pages,
                                'uploaded')
                    """),
                    {
                        "c": code,
                        "n": names[code],
                        "m": module_number,
                        "mt": module_title,
                        "t": Path(filename).stem,
                        "f": filename,
                        "p": pdf_path.relative_to(PROJECT_ROOT).as_posix(),
                        "pages": pages,
                    },
                )
                db.session.commit()
                print(f"  + study material: {code} mod={module_number} "
                      f"{_safename(filename)} ({pages} pages)")
            except Exception as error:
                db.session.rollback()
                print(f"  ! study material {_safename(filename)} skipped: {_safename(error)}")


def ensure_study_content():
    """Populate a brand-new database once, without touching existing data."""
    subject_count = db.session.execute(
        text("SELECT COUNT(*) FROM subjects")
    ).scalar() or 0
    if subject_count:
        # Existing database: only the always-on restoration below runs;
        # the first-run seed is skipped so existing data is untouched.
        try:
            ensure_canonical_subjects()
        except Exception as error:
            print(f"  ! canonical subjects skipped: {error}")
        try:
            ensure_study_materials()
        except Exception as error:
            print(f"  ! study materials skipped: {error}")
        return False

    try:
        for code, name in DEFAULT_SUBJECTS:
            db.session.execute(
                text("""
                    INSERT INTO subjects
                        (subject_code, subject_name, semester, branch, scheme, credits, icon)
                    VALUES (:code, :name, 5, 'CSE', '2022', 4, '📚')
                """),
                {"code": code, "name": name},
            )

        subject_ids = {
            row["subject_code"]: row["id"]
            for row in db.session.execute(
                text("SELECT id, subject_code FROM subjects")
            ).mappings()
        }

        for code, question, unit, marks, difficulty, important, answer in DEFAULT_QUESTIONS:
            db.session.execute(
                text("""
                    INSERT INTO questions
                        (subject_id, question, unit, marks, difficulty, answer, is_important)
                    VALUES
                        (:subject_id, :question, :unit, :marks, :difficulty, :answer, :important)
                """),
                {
                    "subject_id": subject_ids[code],
                    "question": question,
                    "unit": unit,
                    "marks": marks,
                    "difficulty": difficulty,
                    "answer": answer,
                    "important": important,
                },
            )

        for code, title, description, resource_type, url in DEFAULT_RESOURCES:
            db.session.execute(
                text("""
                    INSERT INTO resources
                        (subject_id, title, description, resource_type, resource_url, category, is_featured)
                    VALUES (:subject_id, :title, :description, :resource_type, :url, 'General', FALSE)
                """),
                {
                    "subject_id": subject_ids.get(code) if code else None,
                    "title": title,
                    "description": description,
                    "resource_type": resource_type,
                    "url": url,
                },
            )

        db.session.commit()

        # Fresh database: also restore the canonical file-backed
        # subjects and register their study materials.
        try:
            ensure_canonical_subjects()
        except Exception as error:
            print(f"  ! canonical subjects skipped: {error}")
        try:
            ensure_study_materials()
        except Exception as error:
            print(f"  ! study materials skipped: {error}")
        return True
    except Exception:
        db.session.rollback()
        raise
