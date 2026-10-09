"""First-run study content for a locally created database."""

from sqlalchemy import text

from utils.database import db

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

def ensure_study_content():
    """Populate a brand-new database once, without touching existing data."""
    subject_count = db.session.execute(
        text("SELECT COUNT(*) FROM subjects")
    ).scalar() or 0
    if subject_count:
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
        return True
    except Exception:
        db.session.rollback()
        raise
