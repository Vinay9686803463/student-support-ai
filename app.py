import os
import re
from functools import wraps

from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for
)
from sqlalchemy import bindparam, text
from werkzeug.security import check_password_hash, generate_password_hash

from utils.database import (
    Conversation,
    Message,
    Note,
    Question,
    Resource,
    Subject,
    UserPreference,
    db,
    init_database
)
from utils.bootstrap import ensure_study_content


load_dotenv()


app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "student-support-ai-secret-key"
)


init_database(app)

with app.app_context():
    ensure_study_content()


# Subjects stored in the database that are NOT active academic subjects
# for the My Subjects semester list (elective placeholder, NSS, PE).
# They are never deleted; they are only excluded from the list query.
NON_LISTED_SUBJECT_CODES = frozenset({"BCS515x", "BNSK559", "BPEK559"})


# =========================================================
# LOGIN HELPER
# =========================================================

def get_current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    try:
        result = db.session.execute(
            text("""
                SELECT
                    id,
                    name,
                    email,
                    phone,
                    branch,
                    scheme,
                    current_semester
                FROM users
                WHERE id = :user_id
            """),
            {
                "user_id": user_id
            }
        ).mappings().first()

        return result

    except Exception:
        db.session.rollback()
        return None


def login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        user = get_current_user()

        if not user:
            session.clear()
            flash("Please login to continue.", "error")
            return redirect(url_for("login"))

        return view_function(*args, **kwargs)

    return wrapped_view


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


# =========================================================
# SIGNUP
# =========================================================

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or not email or not password or not confirm_password:
            flash("Please fill all required fields.", "error")
            return render_template(
                "signup.html",
                name=name,
                email=email
            )

        if "@" not in email or "." not in email:
            flash("Please enter a valid email address.", "error")
            return render_template(
                "signup.html",
                name=name,
                email=email
            )

        if len(password) < 6:
            flash(
                "Password must contain at least 6 characters.",
                "error"
            )
            return render_template(
                "signup.html",
                name=name,
                email=email
            )

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template(
                "signup.html",
                name=name,
                email=email
            )

        try:

            existing_user = db.session.execute(
                text("""
                    SELECT id
                    FROM users
                    WHERE email = :email
                """),
                {
                    "email": email
                }
            ).first()

            if existing_user:
                flash(
                    "An account with this email already exists. Please login.",
                    "error"
                )
                return render_template(
                    "signup.html",
                    name=name,
                    email=email
                )

            password_hash = generate_password_hash(password)

            # NOTE: the live DB has a legacy NOT NULL "password"
            # column, so we must write BOTH columns.
            db.session.execute(
                text("""
                    INSERT INTO users
                    (
                        name,
                        email,
                        password,
                        password_hash,
                        branch,
                        scheme,
                        current_semester
                    )
                    VALUES
                    (
                        :name,
                        :email,
                        :password,
                        :password_hash,
                        :branch,
                        :scheme,
                        :current_semester
                    )
                """),
                {
                    "name": name,
                    "email": email,
                    "password": password_hash,
                    "password_hash": password_hash,
                    "branch": "CSE",
                    "scheme": "2022",
                    "current_semester": 5
                }
            )

            db.session.commit()

            flash(
                "Account created successfully. Please login.",
                "success"
            )

            return redirect(url_for("login"))

        except Exception as error:

            db.session.rollback()

            print("SIGNUP ERROR:", error)

            flash(
                "Unable to create account. Please try again.",
                "error"
            )
            return render_template(
                "signup.html",
                name=name,
                email=email
            )

    return render_template("signup.html")


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash(
                "Please enter email and password.",
                "error"
            )
            return render_template("login.html", email=email)

        try:

            user = db.session.execute(
                text("""
                    SELECT
                        id,
                        name,
                        email,
                        password,
                        password_hash
                    FROM users
                    WHERE email = :email
                """),
                {
                    "email": email
                }
            ).mappings().first()

            if not user:
                flash(
                    "Invalid email or password.",
                    "error"
                )
                return render_template("login.html", email=email)

            stored_hash = user["password_hash"] or user["password"]

            if not stored_hash:
                flash(
                    "Invalid email or password.",
                    "error"
                )
                return render_template("login.html", email=email)

            password_ok = False

            # Preferred: proper hash check
            try:
                password_ok = check_password_hash(stored_hash, password)
            except (ValueError, AttributeError):
                password_ok = False

            # Legacy fallback: plain-text password stored in DB
            if not password_ok and stored_hash == password:
                password_ok = True
                # Auto-upgrade legacy plain password to a hash
                try:
                    new_hash = generate_password_hash(password)
                    db.session.execute(
                        text("""
                            UPDATE users
                            SET password_hash = :h,
                                password = :h
                            WHERE id = :uid
                        """),
                        {"h": new_hash, "uid": user["id"]}
                    )
                    db.session.commit()
                except Exception as upgrade_error:
                    db.session.rollback()
                    print("PASSWORD UPGRADE ERROR:", upgrade_error)

            if not password_ok:
                flash(
                    "Invalid email or password.",
                    "error"
                )
                return render_template("login.html", email=email)

            session.clear()

            session["user_id"] = user["id"]
            session["user_name"] = user["name"]

            flash(
                f"Welcome back, {user['name']}!",
                "success"
            )

            return redirect(url_for("dashboard"))

        except Exception as error:

            db.session.rollback()

            print("LOGIN ERROR:", error)

            flash(
                "Unable to login. Please try again.",
                "error"
            )
            return render_template("login.html", email=email)

    return render_template("login.html")


# =========================================================
# FORGOT PASSWORD
# =========================================================

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not email or not new_password or not confirm_password:
            flash("Please fill all fields.", "error")
            return render_template("forgot_password.html", email=email)

        if "@" not in email or "." not in email:
            flash("Please enter a valid email address.", "error")
            return render_template("forgot_password.html", email=email)

        if len(new_password) < 6:
            flash(
                "Password must contain at least 6 characters.",
                "error"
            )
            return render_template("forgot_password.html", email=email)

        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("forgot_password.html", email=email)

        try:

            user = db.session.execute(
                text("""
                    SELECT id
                    FROM users
                    WHERE email = :email
                """),
                {"email": email}
            ).first()

            if not user:
                flash(
                    "No account found with this email.",
                    "error"
                )
                return render_template("forgot_password.html", email=email)

            password_hash = generate_password_hash(new_password)

            db.session.execute(
                text("""
                    UPDATE users
                    SET password = :h,
                        password_hash = :h
                    WHERE email = :email
                """),
                {"h": password_hash, "email": email}
            )

            db.session.commit()

            flash(
                "Password reset successfully. Please login.",
                "success"
            )

            return redirect(url_for("login"))

        except Exception as error:

            db.session.rollback()

            print("FORGOT PASSWORD ERROR:", error)

            flash(
                "Unable to reset password. Please try again.",
                "error"
            )
            return render_template("forgot_password.html", email=email)

    return render_template("forgot_password.html")


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(url_for("login"))


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
@login_required
def dashboard():

    user = get_current_user()

    # Each count is guarded so the dashboard never 500s on
    # schema drift (e.g. live DB column names differ).
    try:
        note_count = Note.query.filter_by(
            user_id=user["id"]
        ).count()
    except Exception as error:
        db.session.rollback()
        print("DASHBOARD NOTE COUNT ERROR:", error)
        note_count = 0

    try:
        conversation_count = Conversation.query.filter_by(
            user_id=user["id"]
        ).count()
    except Exception as error:
        db.session.rollback()
        print("DASHBOARD CONVERSATION COUNT ERROR:", error)
        conversation_count = 0

    try:
        subject_count = Subject.query.filter_by(
            branch=user["branch"],
            scheme=user["scheme"],
            semester=user["current_semester"]
        ).count()
    except Exception as error:
        db.session.rollback()
        print("DASHBOARD SUBJECT COUNT ERROR:", error)
        try:
            subject_count = db.session.execute(
                text("""
                    SELECT COUNT(*)
                    FROM subjects
                    WHERE branch = :branch
                      AND scheme = :scheme
                      AND semester = :semester
                """),
                {
                    "branch": user["branch"],
                    "scheme": user["scheme"],
                    "semester": user["current_semester"]
                }
            ).scalar() or 0
        except Exception as fallback_error:
            db.session.rollback()
            print("DASHBOARD SUBJECT FALLBACK ERROR:", fallback_error)
            subject_count = 0

    try:
        question_count = (
            db.session.query(Question)
            .join(Subject)
            .filter(
                Subject.branch == user["branch"],
                Subject.scheme == user["scheme"],
                Subject.semester == user["current_semester"]
            )
            .count()
        )
    except Exception as error:
        db.session.rollback()
        print("DASHBOARD QUESTION COUNT ERROR:", error)
        try:
            question_count = db.session.execute(
                text("""
                    SELECT COUNT(*)
                    FROM questions q
                    JOIN subjects s ON s.id = q.subject_id
                    WHERE s.branch = :branch
                      AND s.scheme = :scheme
                      AND s.semester = :semester
                """),
                {
                    "branch": user["branch"],
                    "scheme": user["scheme"],
                    "semester": user["current_semester"]
                }
            ).scalar() or 0
        except Exception as fallback_error:
            db.session.rollback()
            print("DASHBOARD QUESTION FALLBACK ERROR:", fallback_error)
            question_count = 0

    return render_template(
        "dashboard.html",
        user=user,
        note_count=note_count,
        conversation_count=conversation_count,
        subject_count=subject_count,
        question_count=question_count
    )


# =========================================================
# CHAT
# =========================================================

@app.route("/chat")
@login_required
def chat():

    user = get_current_user()

    return render_template(
        "chat.html",
        user=user
    )


# =========================================================
# CHAT API (offline study assistant, no API key needed)
# =========================================================

@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():

    from utils.rag_ai import answer_with_rag
    from utils.ai import generate_answer, gemini_available

    user = get_current_user()

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()

    if not message:
        return {"reply": "Please type a question first."}, 400

    if len(message) > 2000:
        return {"reply": "Please keep questions under 2000 characters."}, 400

    # Try RAG first: retrieve VTU knowledge and answer grounded in it.
    # Subject-aware: the chat client may pass subject_code/module_number
    # (e.g. from a subject page). Both are optional; when absent the
    # search spans all subjects. Values are validated against the
    # subjects table so one subject can never pull another's chunks
    # via a forged code.
    try:
        requested_code = (data.get("subject_code") or "").strip().upper()
        requested_module = data.get("module_number")
        rag_subject = None
        rag_module = None
        if requested_code:
            try:
                exists = db.session.execute(
                    text("SELECT 1 FROM subjects WHERE subject_code = :c"),
                    {"c": requested_code},
                ).first()
                if exists:
                    rag_subject = requested_code
            except Exception:
                db.session.rollback()
                rag_subject = None
        try:
            if requested_module is not None and str(requested_module).strip() != "":
                rag_module = int(requested_module)
                if rag_module not in (1, 2, 3, 4, 5):
                    rag_module = None
        except (TypeError, ValueError):
            rag_module = None

        rag_result = answer_with_rag(
            question=message,
            subject_code=rag_subject,
            module_number=rag_module,
            limit=5,
        )

        answer = rag_result.get("answer", "")
        sources = rag_result.get("sources", [])
        used_rag = rag_result.get("used_rag", False)
        used_ai = rag_result.get("used_ai", False)

        # If RAG produced an answer, use it.
        if answer:
            engine = "gemini" if used_ai else "study bank"
            return {
                "reply": answer,
                "answer": answer,
                "sources": sources,
                "used_rag": used_rag,
                "used_ai": used_ai,
                "engine": engine,
            }

    except Exception as rag_error:
        print("RAG ERROR:", rag_error)
        # Fall through to offline engine below.

    # Build context from the app's own data (best effort).
    subjects_ctx, questions_ctx, resources_ctx = [], [], []
    try:
        rows = db.session.execute(
            text("""
                SELECT subject_code AS code, subject_name AS name
                FROM subjects
                WHERE branch = :branch
                  AND scheme = :scheme
                  AND semester = :semester
                ORDER BY subject_code ASC
            """),
            {
                "branch": user["branch"],
                "scheme": user["scheme"],
                "semester": user["current_semester"]
            }
        ).mappings().all()
        subjects_ctx = [dict(r) for r in rows]
    except Exception as error:
        db.session.rollback()
        print("CHAT SUBJECTS CTX ERROR:", error)

    try:
        rows = db.session.execute(
            text("""
                SELECT q.question, q.unit, q.marks,
                       s.subject_name AS subject_name,
                       s.subject_code AS subject_code
                FROM questions q
                JOIN subjects s ON s.id = q.subject_id
                WHERE s.branch = :branch
                  AND s.scheme = :scheme
                  AND s.semester = :semester
                ORDER BY q.id ASC
                LIMIT 200
            """),
            {
                "branch": user["branch"],
                "scheme": user["scheme"],
                "semester": user["current_semester"]
            }
        ).mappings().all()
        questions_ctx = [dict(r) for r in rows]
    except Exception as error:
        db.session.rollback()
        print("CHAT QUESTIONS CTX ERROR:", error)

    try:
        rows = db.session.execute(
            text("""
                SELECT title, description
                FROM resources
                ORDER BY id ASC
                LIMIT 50
            """)
        ).mappings().all()
        resources_ctx = [dict(r) for r in rows]
    except Exception as error:
        db.session.rollback()
        print("CHAT RESOURCES CTX ERROR:", error)

    # Fallback: offline study-assistant engine.
    try:
        reply = generate_answer(
            message,
            {
                "name": user["name"],
                "subjects": subjects_ctx,
                "questions": questions_ctx,
                "resources": resources_ctx
            }
        )
        engine = "gemini" if gemini_available() else "offline"
    except Exception as error:
        print("CHAT GENERATE ERROR:", error)
        reply = (
            "I had trouble processing that. Please try again, "
            "for example: 'Explain DBMS normalization'."
        )
        engine = "offline"

    return {"reply": reply, "answer": reply, "sources": [], "used_rag": False, "used_ai": False, "engine": engine}


# =========================================================
# SUBJECTS
# =========================================================

@app.route("/subjects")
@login_required
def subjects():

    user = get_current_user()

    # Semester selection (?semester=N). Defaults to the student's own
    # current semester; invalid values fall back to it as well.
    try:
        selected_semester = int(
            request.args.get("semester", user["current_semester"])
        )
    except (TypeError, ValueError):
        selected_semester = user["current_semester"]

    if selected_semester not in (1, 2, 3, 4, 5, 6, 7, 8):
        selected_semester = user["current_semester"]

    try:
        subjects = (
            Subject.query
            .filter_by(
                branch=user["branch"],
                scheme=user["scheme"],
                semester=selected_semester
            )
            .filter(
                Subject.code.notin_(NON_LISTED_SUBJECT_CODES)
            )
            .filter(
                Subject.category.is_(None)
                | (Subject.category != "Activity")
            )
            .order_by(Subject.code.asc())
            .all()
        )
    except Exception as error:
        db.session.rollback()
        print("SUBJECTS ORM ERROR, using raw SQL fallback:", error)
        # Live DB uses subject_code / subject_name column names.
        rows = db.session.execute(
            text("""
                SELECT
                    id,
                    subject_code AS code,
                    subject_name AS name,
                    semester,
                    branch,
                    scheme,
                    category
                FROM subjects
                WHERE branch = :branch
                  AND scheme = :scheme
                  AND semester = :semester
                  AND subject_code NOT IN ('BCS515x', 'BNSK559', 'BPEK559')
                  AND (category IS NULL OR category != 'Activity')
                ORDER BY subject_code ASC
            """),
            {
                "branch": user["branch"],
                "scheme": user["scheme"],
                "semester": selected_semester
            }
        ).mappings().all()
        # Add defaults the template expects.
        subjects = [
            {
                **dict(row),
                "credits": 4,
                "icon": "📚",
                "description": None
            }
            for row in rows
        ]

    def _subject_category(row):
        if isinstance(row, dict):
            return row.get("category")
        return getattr(row, "category", None)

    core_subjects = []
    alternative_subjects = []
    elective_subjects = []
    professional_subjects = []

    for subject_row in subjects:
        subject_category = _subject_category(subject_row) or "Core"
        if subject_category == "Alternative":
            alternative_subjects.append(subject_row)
        elif subject_category == "Elective":
            elective_subjects.append(subject_row)
        elif subject_category == "Professional Elective":
            professional_subjects.append(subject_row)
        else:
            core_subjects.append(subject_row)

    return render_template(
        "subjects.html",
        user=user,
        subjects=core_subjects,
        alternatives=alternative_subjects,
        electives=elective_subjects,
        professional_electives=professional_subjects,
        total_subjects=(
            len(core_subjects)
            + len(alternative_subjects)
            + len(elective_subjects)
            + len(professional_subjects)
        ),
        semester=selected_semester
    )


# =========================================================
# SUBJECT DETAILS
# =========================================================

@app.route("/subject/<subject_code>")
@app.route("/subjects/<subject_code>")
@login_required
def subject_detail(subject_code):

    from flask import abort
    from werkzeug.exceptions import HTTPException

    user = get_current_user()

    try:
        # Subject codes are globally unique; the lookup spans all
        # semesters so semester-1..4 cards open their detail pages.
        subject = (
            Subject.query
            .filter_by(
                code=subject_code,
                branch=user["branch"],
                scheme=user["scheme"]
            )
            .first_or_404()
        )
        subject_id = subject.id
        # Normalize ORM object access for the template.
        subject = {
            "id": subject.id,
            "code": subject.code,
            "name": subject.name,
            "branch": subject.branch,
            "scheme": subject.scheme,
            "semester": subject.semester,
            "credits": getattr(subject, "credits", 4),
            "icon": getattr(subject, "icon", "📚"),
            "description": getattr(subject, "description", None)
        }
    except HTTPException:
        raise
    except Exception as error:
        db.session.rollback()
        print("SUBJECT DETAIL ORM ERROR, using raw SQL fallback:", error)
        row = db.session.execute(
            text("""
                SELECT
                    id,
                    subject_code AS code,
                    subject_name AS name,
                    semester, branch, scheme
                FROM subjects
                WHERE subject_code = :code
                  AND branch = :branch
                  AND scheme = :scheme
            """),
            {
                "code": subject_code,
                "branch": user["branch"],
                "scheme": user["scheme"]
            }
        ).mappings().first()
        if not row:
            abort(404)
        subject = {
            **dict(row),
            "credits": 4,
            "icon": "📚",
            "description": None
        }
        subject_id = subject["id"]

    # Semester list the subject was opened from, so "Back to My Subjects"
    # returns there. Reuses the existing ?semester= query pattern (which
    # also survives a refresh). Falls back to the subject's own semester,
    # never to the user's current semester.
    try:
        from_semester = int(
            request.args.get("semester", subject["semester"])
        )
    except (TypeError, ValueError):
        from_semester = subject["semester"]

    if from_semester not in (1, 2, 3, 4, 5, 6, 7, 8):
        from_semester = subject["semester"]

    questions = (
        Question.query
        .filter_by(subject_id=subject_id)
        .order_by(Question.id.asc())
        .all()
    )

    try:
        resources = (
            Resource.query
            .filter_by(subject_id=subject_id)
            .order_by(Resource.id.asc())
            .all()
        )
    except Exception as error:
        db.session.rollback()
        print("SUBJECT RESOURCES FALLBACK:", error)
        resources = db.session.execute(
            text("""
                SELECT
                    id, subject_id, title, description,
                    resource_type,
                    resource_url AS url
                FROM resources
                WHERE subject_id = :sid
                ORDER BY id ASC
            """),
            {"sid": subject_id}
        ).mappings().all()
        resources = [
            {**dict(r), "category": "General", "is_featured": False}
            for r in resources
        ]

    # Real syllabus units + topics when the database has them.
    unit_cards = []
    has_db_units = False
    has_question_units = False
    try:
        unit_rows = db.session.execute(
            text("""
                SELECT u.id, u.unit_number, u.unit_name
                FROM units u
                WHERE u.subject_id = :sid
                ORDER BY u.unit_number ASC
            """),
            {"sid": subject_id}
        ).mappings().all()
        has_db_units = len(unit_rows) > 0
        # One batched topics query for all units (was one query per unit).
        try:
            unit_ids = [unit_row["id"] for unit_row in unit_rows]
            topics_by_unit = {}
            if unit_ids:
                for topic_row in db.session.execute(
                    text("""
                        SELECT unit_id, topic_name
                        FROM topics
                        WHERE unit_id IN :uids
                        ORDER BY unit_id ASC, id ASC
                    """).bindparams(
                        bindparam("uids", expanding=True)
                    ),
                    {"uids": unit_ids}
                ).fetchall():
                    if topic_row[1]:
                        topics_by_unit.setdefault(
                            topic_row[0], []
                        ).append(topic_row[1])
        except Exception:
            db.session.rollback()
            topics_by_unit = {}
        for unit_row in unit_rows:
            topic_names = topics_by_unit.get(unit_row["id"], [])
            if topic_names:
                shown = ", ".join(topic_names[:6])
                if len(topic_names) > 6:
                    shown += f", +{len(topic_names) - 6} more"
                description = f"Topics: {shown}."
            else:
                description = (
                    f"Key topics and important questions from "
                    f"Unit {unit_row['unit_number']}."
                )
            unit_cards.append(
                {
                    "title": f"Unit {unit_row['unit_number']}: {unit_row['unit_name']}",
                    "description": description
                }
            )
    except Exception as error:
        db.session.rollback()
        print("SUBJECT UNITS FALLBACK:", error)
        unit_cards = []

    if not unit_cards:
        unit_numbers = sorted(
            {
                (
                    question["unit"]
                    if isinstance(question, dict)
                    else question.unit
                )
                for question in questions
            } - {None, ""}
        )

        if unit_numbers:
            has_question_units = True
            unit_cards = [
                {
                    "title": f"Unit {unit}",
                    "description": (
                        f"Key topics and important questions from {unit} "
                        f"of {subject['name']}."
                    )
                }
                for unit in unit_numbers
            ]
        else:
            # Default VTU 5-unit structure so the page never looks empty.
            unit_cards = [
                {
                    "title": f"Unit {i}",
                    "description": (
                        f"Core topics from Unit {i} of {subject['name']}. "
                        "Questions for this unit will appear here soon."
                    )
                }
                for i in range(1, 6)
            ]

    # Web Technology exception (BCSL504): single-file subject, no modules.
    # Its "Web Technology Programs.pdf" is rendered in the Study Material
    # section as one unnumbered file; the Units grid stays empty.
    if subject.get("code") == "BCSL504":
        unit_cards = []

    try:
        note_total = db.session.execute(
            text("""
                SELECT COUNT(*)
                FROM notes
                WHERE user_id = :uid
            """),
            {"uid": user["id"]}
        ).scalar() or 0
    except Exception:
        db.session.rollback()
        note_total = 0

    subject["units"] = len(unit_cards)
    subject["questions"] = len(questions)
    subject["notes"] = note_total

    # Knowledge-base PDFs for this subject (generic by subject code).
    # Reads the existing knowledge_documents table; never duplicates,
    # never ingests, never touches embeddings.
    knowledge_modules = []
    try:
        doc_rows = db.session.execute(
            text("""
                SELECT
                    id,
                    module_number,
                    module_title,
                    title,
                    original_filename,
                    page_count,
                    status
                FROM knowledge_documents
                WHERE subject_code = :code
                ORDER BY module_number ASC, id ASC
            """),
            {"code": subject["code"]}
        ).mappings().all()
    except Exception as error:
        db.session.rollback()
        print("SUBJECT KNOWLEDGE DOCS ERROR:", error)
        doc_rows = []

    docs_by_module = {}
    for doc_row in doc_rows:
        try:
            module_number = int(doc_row["module_number"])
        except (TypeError, ValueError):
            continue
        filename = (
            doc_row["original_filename"]
            or doc_row["title"]
            or f"Module {module_number}.pdf"
        )
        docs_by_module.setdefault(module_number, []).append(
            {
                "id": doc_row["id"],
                "filename": filename,
                "title": doc_row["title"],
                "module_title": doc_row["module_title"],
                "page_count": doc_row["page_count"],
                "status": doc_row["status"]
            }
        )

    # Map existing unit cards to module numbers for topics/titles.
    # NOTE: units are used ONLY to enrich titles/topics of modules that
    # actually have PDFs. Modules without documents are never created,
    # so subjects with no PDFs (e.g. BCEDK103) render zero Module cards
    # instead of five empty "No PDF uploaded yet." cards.
    unit_by_number = {}
    for unit_card in unit_cards:
        title = (unit_card.get("title") or "")
        match = re.match(r"\s*Unit\s+(\d+)\b", title, re.IGNORECASE)
        if match:
            unit_by_number[int(match.group(1))] = unit_card

    # Additional Resources: documents filed under module 0 render in a
    # separate section below Modules 1-5 (any subject; reusable for later
    # uploads without code changes). Same dict shape as module documents.
    additional_resources = docs_by_module.get(0, [])

    # Reusable Module 1-5 slot pattern: any subject with at least one
    # study file shows slots 1-5 in order; slots without a PDF render as
    # empty placeholders ready for later uploads. Subjects with zero
    # files still render zero cards (clean empty state is preserved).
    # Module 0 (Additional Resources) never becomes a module card.
    if docs_by_module:
        module_numbers = sorted((set(docs_by_module) | {1, 2, 3, 4, 5}) - {0})
    else:
        module_numbers = []

    # Unnumbered file collections (BCEDK103, BENGK106, BMATS101):
    # their files (primers, question papers, solved papers, question
    # banks, formula sheets, ...) are not module-wise, so each document
    # renders as its own unnumbered file card in the existing View File
    # format, never as Module 1-5.
    # Scoped to these codes only; other subjects are untouched.
    if subject.get("code") in ("BCEDK103", "BENGK106", "BMATS101") and doc_rows:
        for doc_row in doc_rows:
            doc_filename = (
                doc_row["original_filename"]
                or doc_row["title"]
                or "Study material.pdf"
            )
            knowledge_modules.append(
                {
                    "number": None,
                    "title": None,
                    "topics": None,
                    "documents": [
                        {
                            "id": doc_row["id"],
                            "filename": doc_filename,
                            "title": doc_row["title"],
                            "module_title": doc_row["module_title"],
                            "page_count": doc_row["page_count"],
                            "status": doc_row["status"]
                        }
                    ]
                }
            )
    # Web Technology exception: always render its single PDF as one
    # unnumbered file, never as Module 1-5 (even if questions exist).
    elif subject.get("code") == "BCSL504" and doc_rows:
        only_row = doc_rows[0]
        only_filename = (
            only_row["original_filename"]
            or only_row["title"]
            or "Study material.pdf"
        )
        knowledge_modules.append(
            {
                "number": None,
                "title": None,
                "topics": None,
                "documents": [
                    {
                        "id": only_row["id"],
                        "filename": only_filename,
                        "title": only_row["title"],
                        "module_title": only_row["module_title"],
                        "page_count": only_row["page_count"],
                        "status": only_row["status"]
                    }
                ]
            }
        )
    elif len(doc_rows) == 1 and not has_db_units and not has_question_units:
        only_row = doc_rows[0]
        only_filename = (
            only_row["original_filename"]
            or only_row["title"]
            or "Study material.pdf"
        )
        knowledge_modules.append(
            {
                "number": None,
                "title": None,
                "topics": None,
                "documents": [
                    {
                        "id": only_row["id"],
                        "filename": only_filename,
                        "title": only_row["title"],
                        "module_title": only_row["module_title"],
                        "page_count": only_row["page_count"],
                        "status": only_row["status"]
                    }
                ]
            }
        )
    else:
        for module_number in module_numbers:
            module_docs = docs_by_module.get(module_number, [])
            module_title = None
            for module_doc in module_docs:
                if module_doc["module_title"]:
                    module_title = module_doc["module_title"]
                    break
            unit_card = unit_by_number.get(module_number)
            if unit_card:
                if not module_title:
                    unit_title = (unit_card.get("title") or "")
                    cleaned = re.sub(
                        r"^\s*Unit\s+\d+\s*:?\s*",
                        "",
                        unit_title,
                        flags=re.IGNORECASE
                    ).strip()
                    module_title = cleaned or None
                topics = unit_card.get("description")
            else:
                topics = None
            knowledge_modules.append(
                {
                    "number": module_number,
                    "title": module_title,
                    "topics": topics,
                    "documents": module_docs
                }
            )

    subject["pdf_count"] = sum(
        len(module["documents"]) for module in knowledge_modules
    )

    return render_template(
        "subject_detail.html",
        user=user,
        subject=subject,
        questions=questions,
        resources=resources,
        unit_list=unit_cards,
        knowledge_modules=knowledge_modules,
        additional_resources=additional_resources,
        from_semester=from_semester
    )


# =========================================================
# KNOWLEDGE PDF VIEWER (serves PDFs registered in
# knowledge_documents; the browser never supplies a path)
# =========================================================

@app.route("/knowledge/pdf/<int:document_id>")
@login_required
def knowledge_pdf(document_id):

    from pathlib import Path

    try:
        row = db.session.execute(
            text("""
                SELECT
                    id,
                    original_filename,
                    file_path
                FROM knowledge_documents
                WHERE id = :doc_id
            """),
            {"doc_id": document_id}
        ).mappings().first()
    except Exception as error:
        db.session.rollback()
        print("KNOWLEDGE PDF QUERY ERROR:", error)
        row = None

    if not row or not (row["file_path"] or "").strip():
        abort(404)

    raw_path = (row["file_path"] or "").strip().replace("\\", "/")

    base_dir = Path(app.root_path) / "knowledge_base"

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = Path(app.root_path) / raw_path

    try:
        resolved = candidate.resolve()
        base_resolved = base_dir.resolve()
    except Exception:
        abort(404)

    try:
        resolved.relative_to(base_resolved)
    except ValueError:
        # Path escapes the knowledge base: refuse to serve it.
        abort(404)

    if resolved.suffix.lower() != ".pdf" or not resolved.is_file():
        abort(404)

    return send_file(
        resolved,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=row["original_filename"] or resolved.name
    )


# =========================================================
# KNOWLEDGE DOCUMENT VIEWER (project resources: docx/doc/ppt;
# same security model as the PDF viewer — id lookup only)
# =========================================================

@app.route("/knowledge/document/<int:document_id>")
@login_required
def knowledge_document(document_id):

    from pathlib import Path

    try:
        row = db.session.execute(
            text("""
                SELECT
                    id,
                    original_filename,
                    file_path
                FROM knowledge_documents
                WHERE id = :doc_id
            """),
            {"doc_id": document_id}
        ).mappings().first()
    except Exception as error:
        db.session.rollback()
        print("KNOWLEDGE DOCUMENT QUERY ERROR:", error)
        row = None

    if not row or not (row["file_path"] or "").strip():
        abort(404)

    raw_path = (row["file_path"] or "").strip().replace("\\", "/")

    base_dir = Path(app.root_path) / "knowledge_base"

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = Path(app.root_path) / raw_path

    try:
        resolved = candidate.resolve()
        base_resolved = base_dir.resolve()
    except Exception:
        abort(404)

    try:
        resolved.relative_to(base_resolved)
    except ValueError:
        # Path escapes the knowledge base: refuse to serve it.
        abort(404)

    if not resolved.is_file():
        abort(404)

    suffix = resolved.suffix.lower()

    if suffix == ".pdf":
        return send_file(
            resolved,
            mimetype="application/pdf",
            as_attachment=False,
            download_name=row["original_filename"] or resolved.name
        )

    mime_types = {
        ".docx": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        ".doc": "application/msword",
        ".ppt": "application/vnd.ms-powerpoint",
        ".pptx": (
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation"
        ),
    }

    # Office formats cannot render reliably in the browser, so they are
    # served as downloads instead of inline documents.
    return send_file(
        resolved,
        mimetype=mime_types.get(suffix, "application/octet-stream"),
        as_attachment=True,
        download_name=row["original_filename"] or resolved.name
    )


# =========================================================
# NOTES
# =========================================================

@app.route("/notes")
@login_required
def notes():

    user = get_current_user()

    notes_list = (
        Note.query
        .filter_by(user_id=user["id"])
        .order_by(Note.updated_at.desc())
        .all()
    )

    return render_template(
        "notes.html",
        user=user,
        notes=notes_list
    )


# =========================================================
# CREATE NOTE
# =========================================================

@app.route("/notes/create", methods=["POST"])
@login_required
def create_note():

    user = get_current_user()

    title = request.form.get(
        "title",
        ""
    ).strip()

    subject = request.form.get(
        "subject",
        ""
    ).strip()

    content = request.form.get(
        "content",
        ""
    ).strip()

    if not title or not subject or not content:
        flash(
            "Please fill all note fields.",
            "error"
        )
        return redirect(url_for("notes"))

    try:

        note = Note(
            user_id=user["id"],
            title=title,
            subject=subject,
            content=content
        )

        db.session.add(note)
        db.session.commit()

        flash(
            "Note created successfully.",
            "success"
        )

    except Exception as error:

        db.session.rollback()

        print("CREATE NOTE ERROR:", error)

        flash(
            "Unable to create note.",
            "error"
        )

    return redirect(url_for("notes"))


# =========================================================
# EDIT NOTE
# =========================================================

@app.route("/notes/edit/<int:note_id>", methods=["POST"])
@login_required
def edit_note(note_id):

    user = get_current_user()

    note = Note.query.filter_by(
        id=note_id,
        user_id=user["id"]
    ).first()

    if not note:
        flash(
            "Note not found.",
            "error"
        )
        return redirect(url_for("notes"))

    title = request.form.get(
        "title",
        ""
    ).strip()

    subject = request.form.get(
        "subject",
        ""
    ).strip()

    content = request.form.get(
        "content",
        ""
    ).strip()

    if not title or not subject or not content:
        flash(
            "Please fill all note fields.",
            "error"
        )
        return redirect(url_for("notes"))

    try:

        note.title = title
        note.subject = subject
        note.content = content

        db.session.commit()

        flash(
            "Note updated successfully.",
            "success"
        )

    except Exception as error:

        db.session.rollback()

        print("EDIT NOTE ERROR:", error)

        flash(
            "Unable to update note.",
            "error"
        )

    return redirect(url_for("notes"))


# =========================================================
# DELETE NOTE
# =========================================================

@app.route("/notes/delete/<int:note_id>", methods=["POST"])
@login_required
def delete_note(note_id):

    user = get_current_user()

    note = Note.query.filter_by(
        id=note_id,
        user_id=user["id"]
    ).first()

    if not note:
        flash(
            "Note not found.",
            "error"
        )
        return redirect(url_for("notes"))

    try:

        db.session.delete(note)
        db.session.commit()

        flash(
            "Note deleted successfully.",
            "success"
        )

    except Exception as error:

        db.session.rollback()

        print("DELETE NOTE ERROR:", error)

        flash(
            "Unable to delete note.",
            "error"
        )

    return redirect(url_for("notes"))


# =========================================================
# QUESTIONS
# =========================================================

@app.route("/questions")
@login_required
def questions():

    user = get_current_user()

    try:
        questions_list = (
            Question.query
            .join(Subject)
            .filter(
                Subject.branch == user["branch"],
                Subject.scheme == user["scheme"],
                Subject.semester == user["current_semester"]
            )
            .order_by(Question.id.asc())
            .all()
        )

        subjects_list = (
            Subject.query
            .filter_by(
                branch=user["branch"],
                scheme=user["scheme"],
                semester=user["current_semester"]
            )
            .order_by(Subject.code.asc())
            .all()
        )
    except Exception as error:
        db.session.rollback()
        print("QUESTIONS ORM ERROR, using raw SQL fallback:", error)
        questions_list = db.session.execute(
            text("""
                SELECT
                    q.id, q.subject_id, q.question, q.unit,
                    q.marks, q.difficulty, q.answer,
                    q.is_important, q.created_at
                FROM questions q
                JOIN subjects s ON s.id = q.subject_id
                WHERE s.branch = :branch
                  AND s.scheme = :scheme
                  AND s.semester = :semester
                ORDER BY q.id ASC
            """),
            {
                "branch": user["branch"],
                "scheme": user["scheme"],
                "semester": user["current_semester"]
            }
        ).mappings().all()
        rows = db.session.execute(
            text("""
                SELECT
                    id,
                    subject_code AS code,
                    subject_name AS name,
                    semester, branch, scheme
                FROM subjects
                WHERE branch = :branch
                  AND scheme = :scheme
                  AND semester = :semester
                ORDER BY subject_code ASC
            """),
            {
                "branch": user["branch"],
                "scheme": user["scheme"],
                "semester": user["current_semester"]
            }
        ).mappings().all()
        subjects_list = [
            {**dict(row), "credits": 4, "icon": "📚", "description": None}
            for row in rows
        ]

    return render_template(
        "questions.html",
        user=user,
        questions=questions_list,
        subjects=subjects_list
    )


# =========================================================
# RESOURCES
# =========================================================

@app.route("/resources")
@login_required
def resources():

    user = get_current_user()

    try:
        resources_list = (
            Resource.query
            .outerjoin(Subject)
            .filter(
                (
                    Subject.id.is_(None)
                )
                |
                (
                    (Subject.branch == user["branch"])
                    &
                    (Subject.scheme == user["scheme"])
                    &
                    (Subject.semester == user["current_semester"])
                )
            )
            .order_by(
                Resource.is_featured.desc(),
                Resource.id.asc()
            )
            .all()
        )
    except Exception as error:
        db.session.rollback()
        print("RESOURCES ORM ERROR, using raw SQL fallback:", error)
        # Live DB: resource_url instead of url, no category/is_featured.
        resources_list = db.session.execute(
            text("""
                SELECT
                    r.id, r.subject_id, r.title, r.description,
                    r.resource_type,
                    r.resource_url AS url
                FROM resources r
                LEFT JOIN subjects s ON s.id = r.subject_id
                WHERE s.id IS NULL
                   OR (s.branch = :branch
                       AND s.scheme = :scheme
                       AND s.semester = :semester)
                ORDER BY r.id ASC
            """),
            {
                "branch": user["branch"],
                "scheme": user["scheme"],
                "semester": user["current_semester"]
            }
        ).mappings().all()
        resources_list = [
            {**dict(row), "category": "General", "is_featured": False}
            for row in resources_list
        ]

    return render_template(
        "resources.html",
        user=user,
        resources=resources_list
    )


# =========================================================
# SETTINGS
# =========================================================

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():

    user = get_current_user()

    if request.method == "POST":

        action = request.form.get("action", "profile")

        # ---- Contact update: email + mobile ----
        if action == "contact":

            new_email = request.form.get("email", "").strip().lower()
            new_phone = request.form.get("phone", "").strip()

            if not new_email or "@" not in new_email or "." not in new_email:
                flash("Please enter a valid email address.", "error")
                return redirect(url_for("settings") + "#contact")

            if new_phone and not re.fullmatch(r"[+\d][\d\s\-]{6,19}", new_phone):
                flash("Please enter a valid mobile number.", "error")
                return redirect(url_for("settings") + "#contact")

            try:
                taken = db.session.execute(
                    text("""
                        SELECT id
                        FROM users
                        WHERE email = :email AND id != :uid
                    """),
                    {"email": new_email, "uid": user["id"]}
                ).first()

                if taken:
                    flash(
                        "This email is already used by another account.",
                        "error"
                    )
                    return redirect(url_for("settings") + "#contact")

                db.session.execute(
                    text("""
                        UPDATE users
                        SET email = :email,
                            phone = :phone
                        WHERE id = :uid
                    """),
                    {
                        "email": new_email,
                        "phone": new_phone or None,
                        "uid": user["id"]
                    }
                )

                db.session.commit()

                flash("Contact details updated successfully.", "success")

            except Exception as error:

                db.session.rollback()

                print("SETTINGS CONTACT ERROR:", error)

                flash("Unable to update contact details.", "error")

            return redirect(url_for("settings") + "#contact")

        # ---- Profile update: name ----
        name = request.form.get(
            "name",
            ""
        ).strip()

        if not name:
            flash(
                "Name cannot be empty.",
                "error"
            )
            return redirect(url_for("settings"))

        try:

            db.session.execute(
                text("""
                    UPDATE users
                    SET name = :name
                    WHERE id = :user_id
                """),
                {
                    "name": name,
                    "user_id": user["id"]
                }
            )

            db.session.commit()

            session["user_name"] = name

            flash(
                "Profile updated successfully.",
                "success"
            )

            return redirect(url_for("settings"))

        except Exception as error:

            db.session.rollback()

            print("SETTINGS ERROR:", error)

            flash(
                "Unable to update profile.",
                "error"
            )

    preference = UserPreference.query.filter_by(
        user_id=user["id"]
    ).first()

    return render_template(
        "settings.html",
        user=user,
        preference=preference
    )


# =========================================================
# ERROR PAGES (never leak a stack trace to the browser)
# =========================================================

@app.errorhandler(404)
def page_not_found(error):
    return render_template(
        "error.html",
        code=404,
        message="The page you are looking for does not exist."
    ), 404


@app.errorhandler(500)
def internal_error(error):
    try:
        db.session.rollback()
    except Exception:
        pass
    return render_template(
        "error.html",
        code=500,
        message="Something went wrong on our side. Please try again."
    ), 500


# =========================================================
# DATABASE TEST
# =========================================================

@app.route("/database-test")
def database_test():

    try:

        db.session.execute(
            text("SELECT 1")
        )

        return "Database connection successful."

    except Exception as error:

        return f"Database connection failed: {error}"


# =========================================================
# RUN APP
# =========================================================

if __name__ == "__main__":
    app.run(
        debug=True
    )
