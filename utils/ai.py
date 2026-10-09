"""Student Support AI - study assistant brain.

Two-tier answering engine:
1. Google Gemini (when GOOGLE_GENERATIVE_AI_API_KEY is set) for rich answers.
2. Built-in offline engine using the app's own database (subjects,
   questions, resources) plus a CSE knowledge base. Always available,
   no external API key required.
"""

import os
import re


def _gemini_key():
    key = (os.getenv("GOOGLE_GENERATIVE_AI_API_KEY") or "").strip()
    if not key or key.upper() in {"YOUR_API_KEY_HERE", "REPLACE-ME", "REPLACE_ME", "NONE"}:
        return None
    return key


def gemini_available():
    """True when a real Gemini key is configured AND the SDK is installed."""
    if not _gemini_key():
        return False
    try:
        import google.generativeai  # noqa: F401
        return True
    except Exception:
        return False


def _gemini_answer(message, context):
    """Ask Gemini, grounded with the student's subjects + question bank."""
    import google.generativeai as genai

    genai.configure(api_key=_gemini_key())

    subjects = context.get("subjects") or []
    subject_lines = "\n".join(
        f"- {(s.get('code') if isinstance(s, dict) else getattr(s, 'code', ''))}: "
        f"{(s.get('name') if isinstance(s, dict) else getattr(s, 'name', ''))}"
        for s in subjects[:15]
    )
    questions = context.get("questions") or []
    bank_lines = "\n".join(
        f"- {_format_question(q)}" for q in questions[:20]
    )

    prompt = (
        "You are Student Support AI, a friendly tutor for VTU CSE undergraduates. "
        "Answer clearly and concisely (under 220 words), using short bullet points "
        "where helpful. Stay on academic topics; this is a study app.\n\n"
        f"Student name: {context.get('name') or 'Student'}\n"
        f"Current semester subjects:\n{subject_lines or '(unknown)'}\n\n"
        f"Important-question bank (may be relevant):\n{bank_lines or '(empty)'}\n\n"
        f"Student question: {message}"
    )

    for model_name in ("gemini-2.0-flash", "gemini-1.5-flash"):
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                prompt,
                request_options={"timeout": 25},
            )
            text = (getattr(response, "text", "") or "").strip()
            if text:
                return text
        except Exception:
            continue
    return None


KNOWLEDGE_BASE = {
    "normalization": (
        "Database Normalization — detailed solution\n\n"
        "Definition: normalization is the step-by-step process of organizing "
        "tables to remove redundancy and avoid insert, update and delete anomalies.\n\n"
        "• 1NF (First Normal Form): every cell holds a single atomic value; no "
        "repeating groups. Example: split a 'Phones' column '98451, 98452' into "
        "separate rows.\n"
        "• 2NF: must be in 1NF, plus no partial dependency — every non-key "
        "attribute must depend on the WHOLE composite key. Example: in "
        "Student_Course(StudentID, CourseID, StudentName), StudentName depends "
        "only on StudentID, so move it to a Student table.\n"
        "• 3NF: must be in 2NF, plus no transitive dependency — non-key "
        "attributes must depend only on the key. Example: in Employee(EmpID, "
        "DeptID, DeptName), DeptName depends on DeptID, so move it to a "
        "Department table.\n"
        "• BCNF (stronger 3NF): every determinant must be a candidate key.\n\n"
        "Exam tip: always show the violating dependency with an arrow "
        "(e.g. DeptID → DeptName) and then show the decomposed tables. "
        "That decomposition step carries most of the marks."
    ),
    "osi": (
        "OSI Reference Model — detailed solution\n\n"
        "The OSI model standardizes communication into 7 layers. Mnemonic: "
        "Please Do Not Throw Sausage Pizza Away.\n\n"
        "1. Physical — bits on the wire: cables, hubs, voltage, data rate.\n"
        "2. Data Link — framing, MAC addressing, error detection (CRC); "
        "devices: switches, bridges.\n"
        "3. Network — logical addressing and routing (IP); devices: routers.\n"
        "4. Transport — end-to-end delivery, segmentation, flow control "
        "(TCP for reliability, UDP for speed).\n"
        "5. Session — opens, manages and closes connections/sessions.\n"
        "6. Presentation — translation, encryption, compression (JPEG, SSL/TLS).\n"
        "7. Application — services the user sees: HTTP, FTP, SMTP, DNS.\n\n"
        "Data flow: at the sender each layer adds its header "
        "(encapsulation); at the receiver each header is stripped. "
        "TCP/IP model merges these into 4 layers: Network Access, Internet, "
        "Transport, Application.\n\n"
        "Exam tip: draw the 7-layer stack with one function + one "
        "protocol/device per layer — an easy full-marks 10-mark answer."
    ),
    "network_basics": (
        "Computer Networks — detailed solution\n\n"
        "Definition: a computer network is a set of interconnected devices "
        "(computers, phones, servers) that share data and resources using "
        "agreed protocols such as TCP/IP.\n\n"
        "Types by size:\n"
        "• LAN (Local Area Network): one building/campus, fast, privately "
        "owned — e.g. your college lab network.\n"
        "• MAN (Metropolitan Area Network): spans a city — e.g. a cable-TV "
        "or city Wi-Fi network.\n"
        "• WAN (Wide Area Network): spans countries — the Internet is the "
        "largest WAN; uses routers and leased lines.\n\n"
        "Key devices: hub (broadcasts everything), switch (forwards by MAC "
        "address), router (forwards by IP address between networks), "
        "modem/gateway (connects different network types).\n\n"
        "Exam tip: define network → list LAN/MAN/WAN with one example each → "
        "mention TCP/IP as the protocol suite. That structure earns full marks."
    ),
    "tcp_udp": (
        "TCP vs UDP — detailed solution\n\n"
        "Both are Transport-layer protocols, but with opposite trade-offs.\n\n"
        "TCP (Transmission Control Protocol):\n"
        "• Connection-oriented: 3-way handshake (SYN, SYN-ACK, ACK) before data.\n"
        "• Reliable: sequence numbers, acknowledgements and retransmission.\n"
        "• Ordered delivery + congestion and flow control.\n"
        "• 20-byte header. Used by: web (HTTP), email (SMTP), file transfer (FTP).\n\n"
        "UDP (User Datagram Protocol):\n"
        "• Connectionless: no handshake, just sends datagrams.\n"
        "• Best-effort: no ACKs, no retransmission, no ordering guarantee.\n"
        "• Tiny 8-byte header, very low latency.\n"
        "• Used by: video streaming, online gaming, VoIP, DNS lookups.\n\n"
        "One-line difference for exams: TCP sacrifices speed for reliability; "
        "UDP sacrifices reliability for speed."
    ),
    "ip_addressing": (
        "IP Addressing and Subnetting — detailed solution\n\n"
        "An IPv4 address is 32 bits written as 4 octets (e.g. 192.168.1.10).\n\n"
        "Classful ranges (first octet): Class A 1–126, Class B 128–191, "
        "Class C 192–223 (D = multicast, E = experimental). Default masks: "
        "A = 255.0.0.0 (/8), B = 255.255.0.0 (/16), C = 255.255.255.0 (/24).\n\n"
        "Subnetting: borrow host bits to create smaller networks.\n"
        "Worked example — split 192.168.1.0/24 into 4 subnets:\n"
        "• Need 2 borrowed bits (2^2 = 4). New mask: /26 = 255.255.255.192.\n"
        "• Block size = 256 − 192 = 64. Subnets: .0–.63, .64–.127, "
        ".128–.191, .192–.255.\n"
        "• First subnet: network 192.168.1.0, usable .1–.62, broadcast .63.\n\n"
        "Formulas to memorize: subnets = 2^(borrowed bits); "
        "usable hosts per subnet = 2^(host bits) − 2."
    ),
    "scheduling": (
        "CPU Scheduling Algorithms — detailed solution\n\n"
        "The scheduler picks which ready-queue process runs next. Compare on "
        "average waiting time, response time and fairness.\n\n"
        "• FCFS (First Come First Served): non-preemptive, simple FIFO. "
        "Suffers the convoy effect — a long job blocks short ones.\n"
        "• SJF (Shortest Job First): picks smallest burst; provably optimal "
        "average waiting time, but needs burst estimates and can starve long jobs.\n"
        "• SRTF: preemptive SJF — best average waiting time, more context switches.\n"
        "• Round Robin: each job gets a fixed time quantum, then goes to the "
        "queue tail. Great response time and fairness; quantum too small → "
        "too many switches, too large → behaves like FCFS.\n"
        "• Priority: highest priority first; add aging (priority rises with "
        "waiting time) to prevent starvation.\n\n"
        "Exam tip: for numericals, draw the Gantt chart first, then compute "
        "completion → turnaround (CT − AT) → waiting (TAT − BT) for each process."
    ),
    "acid": (
        "ACID Properties of a Transaction — detailed solution\n\n"
        "A transaction is a logical unit of work (e.g. a bank transfer: debit "
        "A + credit B). ACID guarantees correctness:\n\n"
        "• Atomicity: all operations succeed or none do. A crash mid-transfer "
        "rolls everything back — money is never half-moved.\n"
        "• Consistency: the database moves from one valid state to another; "
        "all integrity constraints hold after commit.\n"
        "• Isolation: concurrent transactions behave as if run serially. "
        "Levels: Read Uncommitted < Read Committed < Repeatable Read < "
        "Serializable (strongest, slowest). Prevents dirty reads, "
        "non-repeatable reads and phantoms.\n"
        "• Durability: once committed, results survive crashes — via write-ahead "
        "logging and checkpoints.\n\n"
        "Related exam point: transaction states are Active → Partially "
        "Committed → Committed (or Failed → Aborted)."
    ),
    "automata": (
        "Finite Automata: DFA vs NFA — detailed solution\n\n"
        "A finite automaton = (Q, Σ, δ, q0, F): states, alphabet, transition "
        "function, start state, accept states.\n\n"
        "DFA (Deterministic):\n"
        "• For every state and every input symbol there is EXACTLY one transition.\n"
        "• No ε (empty-string) moves. Easy to simulate, used in lexical analyzers.\n\n"
        "NFA (Non-deterministic):\n"
        "• A state may have zero, one or MANY transitions on the same symbol.\n"
        "• ε-moves allowed (change state without consuming input).\n"
        "• Easier to design; every NFA converts to an equivalent DFA via "
        "subset construction (states of the DFA = sets of NFA states).\n\n"
        "Example: strings ending in '01' — NFA guesses where the final '01' "
        "begins; the DFA must remember the last two symbols explicitly.\n\n"
        "Exam tip: to prove a language non-regular, use the pumping lemma — "
        "e.g. {a^n b^n} cannot be pumped and stay in the language."
    ),
    "testing": (
        "Software Testing — detailed solution\n\n"
        "Testing levels (bottom-up):\n"
        "1. Unit testing — single functions/classes in isolation (developers).\n"
        "2. Integration testing — modules working together (top-down, "
        "bottom-up, sandwich approaches).\n"
        "3. System testing — the whole product against requirements.\n"
        "4. Acceptance testing — customer/UAT sign-off.\n\n"
        "Black-box (functional, no code knowledge):\n"
        "• Equivalence partitioning: one test per input class.\n"
        "• Boundary value analysis: test edges (e.g. 0, 1, 99, 100 for 1–100).\n\n"
        "White-box (structural, uses code): statement, branch and path "
        "coverage — every line/decision/independent path executed at least once.\n\n"
        "Also know: alpha testing (in-house) vs beta testing (real users), "
        "and regression testing (re-run old tests after every change)."
    ),
    "agile": (
        "Agile vs Waterfall vs Spiral — detailed solution\n\n"
        "Waterfall: strictly sequential phases (Requirements → Design → "
        "Implementation → Testing → Maintenance). Simple and disciplined, but "
        "late changes are very costly. Best when requirements are frozen.\n\n"
        "Agile (Manifesto: individuals, working software, collaboration, "
        "responding to change):\n"
        "• Work in short sprints (1–4 weeks) delivering a usable increment.\n"
        "• Scrum roles: Product Owner, Scrum Master, Development Team; "
        "ceremonies: sprint planning, daily stand-up, review, retrospective.\n"
        "• Welcomes changing requirements — best for evolving products.\n\n"
        "Spiral (Boehm): waterfall loops with explicit RISK ANALYSIS each "
        "iteration — best for large, high-risk projects.\n\n"
        "One-line exam answer: Waterfall = plan-driven, Agile = change-driven, "
        "Spiral = risk-driven."
    ),
    "cocomo": (
        "COCOMO Cost Estimation — detailed solution\n\n"
        "COCOMO estimates effort from project size (KLOC = thousands of lines "
        "of code): Effort = a × (KLOC)^b person-months.\n\n"
        "Basic-COCOMO constants by mode:\n"
        "• Organic (small, familiar): a = 2.4, b = 1.05.\n"
        "• Semi-detached (medium, mixed): a = 3.0, b = 1.12.\n"
        "• Embedded (complex, tight constraints): a = 3.6, b = 1.20.\n\n"
        "Worked example — 50 KLOC organic project:\n"
        "• Effort = 2.4 × 50^1.05 ≈ 2.4 × 61 ≈ 146 person-months.\n"
        "• Schedule = 2.5 × (Effort)^0.38 ≈ 2.5 × 6.7 ≈ 17 months.\n"
        "• Team ≈ 146 / 17 ≈ 9 people.\n\n"
        "Intermediate COCOMO multiplies this by cost drivers (product, "
        "hardware, personnel, project attributes). Exam tip: memorize the "
        "three (a, b) pairs and the schedule formula."
    ),
}

TOPIC_KEYWORDS = {
    "normalization": ["normal", "1nf", "2nf", "3nf", "bcnf"],
    "osi": ["osi", "layers of", "reference model", "seven layers", "7 layers"],
    "network_basics": ["computer network", "types of networks", "lan wan man", "what is networking"],
    "tcp_udp": ["tcp", "udp", "tcp/ip", "tcp ip", "handshake", "reliable", "datagram"],
    "ip_addressing": ["ip address", "subnet", "subnetting", "classful", "/24", "cidr"],
    "scheduling": ["scheduling", "fcfs", "sjf", "round robin", "gantt", "waiting time"],
    "acid": ["acid", "transaction", "isolation", "durability", "atomicity"],
    "automata": ["automata", "dfa", "nfa", "finite automata", "turing", "pumping", "regular language"],
    "testing": ["testing", "black-box", "black box", "white-box", "white box", "unit test", "integration test", "boundary value"],
    "agile": ["agile", "scrum", "sprint", "waterfall", "spiral", "manifesto"],
    "cocomo": ["cocomo", "cost estimation", "effort estimation", "kloc"],
}

EXAM_TIP_TRIGGERS = [
    "important", "exam", "prepare", "question paper", "tips", "study plan",
]

GREETING_TRIGGERS = ["hello", "hi", "hey", "namaste", "good morning", "good afternoon", "good evening"]


def _match_topic(message):
    lowered = message.lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(k in lowered for k in keywords):
            return topic
    return None


STOPWORDS = {
    "what", "when", "where", "which", "how", "why", "who",
    "with", "from", "about", "your", "yours", "mine",
    "there", "their", "they", "them", "this", "that",
    "these", "those", "have", "has", "were", "been",
    "does", "doing", "would", "could", "should",
}


def _keywords(message):
    words = re.findall(r"[a-z]{5,}", message.lower())
    codes = re.findall(r"[a-z]{2,}\d+[a-z]?", message.lower())
    return [w for w in words + codes if w not in STOPWORDS]


def _question_text(q):
    if isinstance(q, dict):
        return str(q.get("question", ""))
    return str(getattr(q, "question", ""))


def _search_questions(message, questions):
    """Rank questions by shared meaningful keywords (stopwords ignored)."""
    keys = set(_keywords(message))
    if not keys:
        return []
    scored = []
    for q in questions:
        text_words = set(re.findall(r"[a-z]{5,}", _question_text(q).lower()))
        text_words |= set(re.findall(r"[a-z]{2,}\d+[a-z]?", _question_text(q).lower()))
        shared = keys & text_words
        if shared:
            scored.append((len(shared), q))
    scored.sort(key=lambda item: -item[0])
    return [q for _, q in scored[:5]]


def _format_question(q):
    if isinstance(q, dict):
        text = q.get("question", "")
        marks = q.get("marks")
        unit = q.get("unit")
        subject = q.get("subject_name") or q.get("subject") or ""
    else:
        text = getattr(q, "question", "")
        marks = getattr(q, "marks", None)
        unit = getattr(q, "unit", None)
        subject = ""
        subj = getattr(q, "subject", None)
        if subj is not None:
            subject = getattr(subj, "name", "") or ""
    bits = [str(text)]
    meta = " ".join(
        str(part) for part in [
            subject,
            f"({marks} marks)" if marks else "",
            f"• {unit}" if unit else "",
        ] if part
    )
    if meta:
        bits.append(meta)
    return " • ".join(bits)


def generate_answer(message, context=None):
    """Build a study-assistant reply for *message*.

    context may contain: name, subjects, questions, resources, notes.
    Everything is optional; the assistant always answers something useful.
    """
    context = context or {}
    name = context.get("name") or "there"
    questions = context.get("questions") or []
    resources = context.get("resources") or []
    subjects = context.get("subjects") or []

    text = (message or "").strip()
    lowered = text.lower()

    if not text:
        return "Please type a question about your studies and I'll help."

    if len(text) < 3:
        return (
            f"Hi {name}! Could you add a little more detail? "
            "For example: 'Explain DBMS normalization'."
        )

    # Tier 1: Google Gemini (only when a real key is configured).
    # Any failure falls through to the offline engine below.
    if gemini_available():
        try:
            gemini_reply = _gemini_answer(text, context)
            if gemini_reply:
                return gemini_reply
        except Exception:
            pass

    if any(g == lowered.strip("!., ") for g in GREETING_TRIGGERS):
        subject_names = ", ".join(
            (s.get("name") if isinstance(s, dict) else getattr(s, "name", ""))
            for s in subjects[:5]
        )
        line = f" You are studying {subject_names}." if subject_names else ""
        return (
            f"Hello {name}! 👋 I'm your VTU CSE study assistant.{line} "
            "Ask me about a concept (e.g. 'Explain OSI layers'), "
            "important questions, or exam preparation."
        )

    if any(t in lowered for t in EXAM_TIP_TRIGGERS):
        lines = [
            f"Hi {name}! Here's a focused exam plan:",
            "1. Cover high-weightage units first (Units 1–3 in most VTU subjects).",
            "2. Practice one 10-mark question daily per subject.",
            "3. Revise definitions + diagrams (OSI, scheduling, ER diagrams).",
            "4. Solve the last 3 years' VTU papers under timed conditions.",
        ]
        related = _search_questions(text, questions)
        if related:
            lines.append("")
            lines.append("Related questions from your bank:")
            lines.extend(f"• {_format_question(q)}" for q in related)
        return "\n".join(lines)

    topic = _match_topic(text)
    if topic:
        answer = KNOWLEDGE_BASE[topic]
        related = _search_questions(text, questions)
        if related:
            answer += "\n\nRelated questions from your bank:\n"
            answer += "\n".join(f"• {_format_question(q)}" for q in related)
        if resources:
            answer += (
                "\n\nTip: check the Resources page for notes and videos "
                "on this topic."
            )
        return answer

    related = _search_questions(text, questions)
    if related:
        lines = [f"I found {len(related)} related question(s) in your bank:"]
        lines.extend(f"• {_format_question(q)}" for q in related)
        lines.append(
            "\nTell me which one to explain (e.g. 'explain question 1'), "
            "or ask about a specific topic."
        )
        return "\n".join(lines)

    # Subject-name / subject-code match (e.g. "questions for BCS502").
    subject_hit = None
    for s in subjects:
        code = (s.get("code") if isinstance(s, dict) else getattr(s, "code", "")) or ""
        nm = (s.get("name") if isinstance(s, dict) else getattr(s, "name", "")) or ""
        if code and code.lower() in lowered:
            subject_hit = (code, nm)
            break
        for token in re.findall(r"[a-z]{5,}", nm.lower()):
            if token not in STOPWORDS and token in lowered:
                subject_hit = (code, nm)
                break
        if subject_hit:
            break
    if subject_hit:
        code, nm = subject_hit
        named = [
            q for q in questions
            if str((q.get("subject_code") if isinstance(q, dict) else "") or "").lower() == code.lower()
            or str((q.get("subject_name") if isinstance(q, dict) else "") or "").lower() == nm.lower()
        ][:5]
        lines = [f"Important questions for {nm} ({code}):" if nm else f"Questions for {code}:"]
        if named:
            lines.extend(f"• {_format_question(q)}" for q in named)
        else:
            lines.append("Your question bank has no entries for it yet — try the Important Questions page.")
        lines.append("\nAsk me to explain any of these topics.")
        return "\n".join(lines)

    if "syllabus" in lowered or "subject" in lowered:
        if subjects:
            names = "\n".join(
                f"• {(s.get('code') if isinstance(s, dict) else getattr(s, 'code', ''))} "
                f"— {(s.get('name') if isinstance(s, dict) else getattr(s, 'name', ''))}"
                for s in subjects[:11]
            )
            return (
                f"Your current semester subjects:\n{names}\n\n"
                "Open any subject to see its units, questions and resources, "
                "or ask me about a topic from one of them."
            )
        return (
            "Open the My Subjects page to browse your semester subjects, "
            "then ask me about any topic from them."
        )

    if "notes" in lowered:
        return (
            "You can save this in My Notes:\n"
            "1. Go to My Notes → + New Note.\n"
            "2. Pick the subject and paste the key points.\n"
            "3. Use the search box later for quick revision.\n\n"
            "Want me to summarize the topic first? Just ask, "
            "e.g. 'Summarize normalization'."
        )

    return (
        f"Thanks {name}! Here's how I can help with that:\n"
        "• If it's a concept, rephrase as 'Explain <topic>' — "
        "e.g. 'Explain ACID properties'.\n"
        "• If it's exam prep, ask 'Give important questions for <subject>'.\n"
        "• If it's a subject overview, ask 'What are my subjects?'.\n\n"
        "Try one of the suggestion chips below to get started. 🚀"
    )
