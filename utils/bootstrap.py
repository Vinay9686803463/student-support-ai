"""First-run study content for a locally created database."""

from pathlib import Path

from sqlalchemy import text

from utils.database import db

PROJECT_ROOT = Path(__file__).resolve().parent.parent

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
# (code, name, semester, branch, scheme, category)
CANONICAL_SUBJECTS = [
    ("BKSKK107", "Samskrutika Kannada", 1, "CSE", "2022", "Core"),
    ("BSFHK158", "Scientific Foundations of Health", 1, "CSE", "2022", "Core"),
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
}


def ensure_canonical_subjects():
    """Re-create missing file-backed subject rows; repair wrong attrs.

    Only CANONICAL_SUBJECTS codes are touched. Missing rows are
    INSERTed (semester 1, CSE/2022, Core, 1 credit — matching the live
    canonical rows). Existing rows keep their id/credits/icon/
    description; only a wrong name/semester/branch/scheme/category is
    repaired so the subject lists again. Never deletes. Never raises:
    any failure rolls back that code and logs, so boot continues.
    """
    for code, name, semester, branch, scheme, category in CANONICAL_SUBJECTS:
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
                        VALUES (:c, :n, :s, :b, :sc, 1, '📚', :cat)
                    """),
                    {"c": code, "n": name, "s": semester, "b": branch,
                     "sc": scheme, "cat": category},
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
        except Exception as error:
            db.session.rollback()
            print(f"  ! canonical subject {code} skipped: {error}")


def ensure_study_materials():
    """Register on-disk study-material PDFs lacking a document row.

    For each STUDY_MATERIALS code, every listed file present under
    knowledge_base/<CODE>/ gets one knowledge_documents row (sequential
    module_number slot, title=filename stem, status 'uploaded') unless a
    row for (subject_code, original_filename) already exists. Existing
    rows are never updated or deleted. Files missing from disk are
    logged and skipped. Never raises: failures roll back and log.
    """
    try:
        from pypdf import PdfReader
    except ImportError as error:
        print(f"  ! study materials skipped (pypdf unavailable): {error}")
        return
    names = {c: n for c, n, _s, _b, _sc, _cat in CANONICAL_SUBJECTS}
    for code, files in STUDY_MATERIALS.items():
        try:
            existing = {
                r[0] for r in db.session.execute(
                    text("""
                        SELECT original_filename
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
        for filename, module_number in files:
            if filename in existing:
                continue
            pdf_path = PROJECT_ROOT / "knowledge_base" / code / filename
            if not pdf_path.is_file():
                print(f"  ! file missing, skipping: {code}/{filename}")
                continue
            try:
                pages = len(PdfReader(str(pdf_path)).pages)
            except Exception as error:
                print(f"  ! unreadable PDF, skipping {filename}: {error}")
                continue
            if pages < 1:
                print(f"  ! empty PDF, skipping: {filename}")
                continue
            try:
                db.session.execute(
                    text("""
                        INSERT INTO knowledge_documents
                            (subject_code, subject_name, module_number,
                             module_title, title, original_filename,
                             file_path, page_count, status)
                        VALUES (:c, :n, :m, NULL, :t, :f, :p, :pages,
                                'uploaded')
                    """),
                    {
                        "c": code,
                        "n": names[code],
                        "m": module_number,
                        "t": Path(filename).stem,
                        "f": filename,
                        "p": pdf_path.relative_to(PROJECT_ROOT).as_posix(),
                        "pages": pages,
                    },
                )
                db.session.commit()
                print(f"  + study material: {code} mod={module_number} "
                      f"{filename} ({pages} pages)")
            except Exception as error:
                db.session.rollback()
                print(f"  ! study material {filename} skipped: {error}")


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
