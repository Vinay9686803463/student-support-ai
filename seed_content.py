"""Seed important questions + study resources (idempotent).

Run:  venv\\Scripts\\python.exe seed_content.py
Skips rows that already exist, so it is safe to run many times.
"""

from app import app
from sqlalchemy import text

from utils.database import db


QUESTIONS = [
    # BCS501 - Software Engineering & Project Management
    ("BCS501", "Explain the waterfall model with its advantages and disadvantages.", "Unit 1", 10, "Medium", True,
     "Requirements -> Design -> Implementation -> Testing -> Maintenance. Simple and disciplined; suits stable requirements. Weakness: inflexible to late changes."),
    ("BCS501", "What is agile methodology? Compare agile with the spiral model.", "Unit 1", 10, "Medium", True,
     "Agile delivers working software in short sprints with customer collaboration. Spiral adds risk analysis loops per iteration; agile prioritizes responding to change over following a plan."),
    ("BCS501", "Explain COCOMO model for software cost estimation with an example.", "Unit 3", 10, "Hard", True,
     "COCOMO estimates effort as a*(KLOC)^b using project mode constants (organic, semi-detached, embedded), then derives schedule and staffing."),
    ("BCS501", "What is software testing? Explain black-box vs white-box testing.", "Unit 4", 10, "Medium", True,
     "Black-box tests functionality without code knowledge (equivalence partitioning, boundary value). White-box tests internal logic (statement, branch, path coverage)."),
    ("BCS501", "Explain risk management: identification, analysis and mitigation.", "Unit 5", 5, "Easy", False,
     "Identify risks early, assess probability x impact, plan avoidance/transfer/mitigation, and monitor them through the project."),
    # BCS502 - Computer Networks
    ("BCS502", "Explain the seven layers of the OSI reference model with their functions.", "Unit 1", 10, "Easy", True,
     "Physical, Data Link, Network, Transport, Session, Presentation, Application - each layer provides services to the layer above."),
    ("BCS502", "Compare TCP and UDP with suitable applications of each.", "Unit 3", 10, "Medium", True,
     "TCP is connection-oriented and reliable (web, email, file transfer). UDP is connectionless with low overhead (video streaming, DNS, gaming)."),
    ("BCS502", "Explain classful IP addressing and subnetting with an example.", "Unit 2", 10, "Medium", True,
     "Classes A-E divide the 32-bit space; subnetting borrows host bits to create smaller networks, e.g. /26 gives 62 usable hosts per subnet."),
    ("BCS502", "What is routing? Explain distance vector routing with an example.", "Unit 3", 10, "Hard", True,
     "Each router shares its distance table with neighbours (Bellman-Ford). Simple but slow to converge (count-to-infinity problem)."),
    ("BCS502", "Explain CSMA/CD and CSMA/CA access methods.", "Unit 2", 5, "Easy", False,
     "CSMA/CD detects collisions on wired Ethernet and backs off; CSMA/CA avoids collisions on wireless using RTS/CTS handshakes."),
    # BCS503 - Theory of Computation
    ("BCS503", "Explain finite automata and distinguish between DFA and NFA.", "Unit 2", 10, "Medium", True,
     "DFA has exactly one transition per symbol per state; NFA allows zero, one or many plus epsilon moves. Every NFA converts to an equivalent DFA."),
    ("BCS503", "State and prove the pumping lemma for regular languages. Give one application.", "Unit 2", 10, "Hard", True,
     "Any long enough string in a regular language can be pumped (xy^iz). Used to prove languages like {a^n b^n} are non-regular."),
    ("BCS503", "Design a Turing machine for language {a^n b^n c^n, n >= 1}.", "Unit 4", 10, "Hard", True,
     "Repeatedly mark one a, one b and one c while scanning; accept only when all symbols are marked and counts match - showing TM power beyond PDAs."),
    ("BCS503", "Explain pushdown automata and its application in parsing.", "Unit 3", 10, "Medium", True,
     "A PDA adds a stack to finite control, recognizing context-free languages - the basis of parsing programming language syntax."),
    ("BCS503", "What is the halting problem? Why is it undecidable?", "Unit 5", 5, "Easy", False,
     "No program can decide for every input whether an arbitrary program halts; a diagonalization proof shows any decider contradicts itself."),
]

RESOURCES = [
    (None, "NPTEL Computer Networks Course", "Free IIT video course covering OSI, TCP/IP, routing and switching.", "Videos", "https://nptel.ac.in"),
    (None, "VTU Official Website", "Syllabus, notifications and official VTU updates.", "Official", "https://vtu.ac.in"),
    (None, "GeeksforGeeks CSE", "Concepts, examples and quizzes for DBMS, OS, CN and TOC.", "Programming", "https://www.geeksforgeeks.org"),
    ("BCS502", "Computer Networks Notes", "Layered architecture, addressing, routing and transport protocols.", "Notes", None),
    ("BCS503", "TOC Practice Questions", "Automata, grammars, PDA and Turing machine problems.", "Papers", None),
    ("BCS501", "Software Engineering Notes", "Process models, estimation, testing and project management.", "Notes", None),
]


with app.app_context():
    code_to_id = {
        row[0]: row[1]
        for row in db.session.execute(
            text("SELECT subject_code, id FROM subjects")
        ).fetchall()
    }

    added_q = 0
    for code, question, unit, marks, difficulty, important, answer in QUESTIONS:
        sid = code_to_id.get(code)
        if not sid:
            print(f"  ! subject {code} missing, skipped question")
            continue
        exists = db.session.execute(
            text("""
                SELECT id FROM questions
                WHERE subject_id = :sid AND question = :q
            """),
            {"sid": sid, "q": question}
        ).first()
        if exists:
            continue
        db.session.execute(
            text("""
                INSERT INTO questions
                    (subject_id, question, unit, marks, difficulty, answer, is_important)
                VALUES
                    (:sid, :q, :unit, :marks, :difficulty, :answer, :important)
            """),
            {
                "sid": sid, "q": question, "unit": unit,
                "marks": marks, "difficulty": difficulty,
                "answer": answer, "important": important
            }
        )
        added_q += 1

    added_r = 0
    for code, title, description, rtype, url in RESOURCES:
        sid = code_to_id.get(code) if code else None
        exists = db.session.execute(
            text("SELECT id FROM resources WHERE title = :t"),
            {"t": title}
        ).first()
        if exists:
            continue
        db.session.execute(
            text("""
                INSERT INTO resources
                    (subject_id, title, description, resource_type, resource_url, category, is_featured)
                VALUES
                    (:sid, :t, :d, :rt, :u, 'General', FALSE)
            """),
            {"sid": sid, "t": title, "d": description, "rt": rtype, "u": url}
        )
        added_r += 1

    db.session.commit()
    print(f"Questions added: {added_q} | Resources added: {added_r}")
