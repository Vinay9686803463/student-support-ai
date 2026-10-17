import os
import re
from functools import wraps
from pathlib import Path
from io import BytesIO

import boto3
from botocore.exceptions import BotoCoreError, ClientError


from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]

# Load the project .env by absolute path BEFORE anything else imports.
# Plain load_dotenv() resolves from the current working directory, so a
# server started from another folder silently misses every key (this
# produced "provider_not_configured" with a perfectly good .env file).
# override=False keeps real environment variables authoritative.
_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)

from flask import (  # pyright: ignore[reportMissingImports]
    Flask,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for
)
from sqlalchemy import bindparam, text  # pyright: ignore[reportMissingImports]
from sqlalchemy.orm import load_only  # pyright: ignore[reportMissingImports]
from werkzeug.security import check_password_hash, generate_password_hash  # pyright: ignore[reportMissingImports]

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
from utils.bootstrap_latex import ensure_latex_materials


load_dotenv(_PROJECT_ROOT / ".env", override=False)


def get_b2_client():
    """Connect to private Backblaze B2 storage."""
    endpoint = os.getenv("B2_ENDPOINT_URL")
    key_id = os.getenv("B2_KEY_ID")
    application_key = os.getenv("B2_APPLICATION_KEY")

    if not all((endpoint, key_id, application_key)):
        return None

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key_id,
        aws_secret_access_key=application_key,
        region_name="us-east-005",
    )


def get_knowledge_file(file_path):
    """
    Return a local knowledge-base file when present.
    Otherwise retrieve the same relative key from private B2 storage.
    """
    raw_path = (file_path or "").strip().replace("\\", "/")
    if not raw_path:
        abort(404)

    relative_path = Path(raw_path)

    # Only allow paths inside knowledge_base.
    if relative_path.is_absolute() or ".." in relative_path.parts:
        abort(404)

    if not relative_path.parts or relative_path.parts[0] != "knowledge_base":
        abort(404)

    base_dir = (Path(app.root_path) / "knowledge_base").resolve()
    local_path = (Path(app.root_path) / relative_path).resolve()

    try:
        local_path.relative_to(base_dir)
    except ValueError:
        abort(404)

    # Prefer local files during development.
    if local_path.is_file():
        return local_path

    # On Vercel, retrieve missing files from B2.
    bucket = os.getenv("B2_BUCKET_NAME")
    s3 = get_b2_client()

    if not bucket or not s3:
        app.logger.error("B2 storage is not configured.")
        abort(503)

    try:
        response = s3.get_object(
            Bucket=bucket,
            Key=relative_path.as_posix(),
        )
        body = response["Body"]

        try:
            return BytesIO(body.read())
        finally:
            body.close()

    except ClientError as error:
        status = error.response.get("ResponseMetadata", {}).get(
            "HTTPStatusCode"
        )
        code = error.response.get("Error", {}).get("Code", "")

        if status == 404 or code in ("NoSuchKey", "NotFound"):
            abort(404)

        app.logger.exception("Backblaze B2 file retrieval failed.")
        abort(502)

    except BotoCoreError:
        app.logger.exception("Backblaze B2 connection failed.")
        abort(502)


app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "student-support-ai-secret-key"
)


init_database(app)

with app.app_context():
    ensure_study_content()
    # BCSL456D supplement (see utils/bootstrap_latex.py): registers the
    # LATEX manual until its entries can be folded into
    # utils/bootstrap.py (currently file-locked). Same SELECT-only +
    # INSERT-missing contract; never touches other subjects.
    ensure_latex_materials(db)


def provider_diagnostics():
    """Check AI provider configuration without exposing secrets."""
    import importlib.util

    report = {
        "env_file": str(_PROJECT_ROOT / ".env"),
        "env_file_exists": (_PROJECT_ROOT / ".env").is_file(),
        "provider": None,
        "model": None,
        "key_present": False,
        "sdk_ok": False,
        "ready": False,
    }

    try:
        # Ensure the project's .env is loaded before checking settings.
        load_dotenv(_PROJECT_ROOT / ".env", override=False)

        from utils.rag_ai import configured_provider

        provider = (configured_provider() or "gemini").strip().lower()
        report["provider"] = provider

        if provider == "gemini":
            key = (
                os.getenv("GOOGLE_GENERATIVE_AI_API_KEY") or ""
            ).strip()

            report["key_present"] = bool(key)
            # Plausibility only (length + known placeholders): API
            # keys are long opaque strings and their prefixes vary,
            # so no AIza-style prefix is asserted here. A previous
            # AIza-only check wrongly flagged a working key. Real
            # authentication is proven by an actual API call, whose
            # classified result the chat path reports honestly.
            report["key_format_ok"] = bool(
                key
                and key.upper() not in {
                    "YOUR_API_KEY_HERE",
                    "REPLACE-ME",
                    "REPLACE_ME",
                    "NONE",
                }
                and len(key) >= 20
            )
            report["model"] = (
                os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
            ).strip()

            try:
                report["sdk_ok"] = (
                    importlib.util.find_spec("google.genai") is not None
                )
            except (ImportError, ModuleNotFoundError, ValueError):
                report["sdk_ok"] = False

            report["ready"] = (
                report["key_present"] and report["sdk_ok"]
            )

        elif provider == "openai":
            from utils import openai_provider as _openai

            report["key_present"] = _openai.openai_key_present()
            report["model"] = _openai.configured_model()
            report["sdk_ok"] = (
                importlib.util.find_spec("openai") is not None
            )
            report["ready"] = (
                report["key_present"] and report["sdk_ok"]
            )

        elif provider == "ollama":
            from utils import ollama_provider as _ollama

            report["model"] = _ollama.configured_model()
            report["key_present"] = True
            report["sdk_ok"] = True
            report["ollama_url"] = _ollama.configured_url()
            report["ready"] = _ollama.ollama_available()

        else:
            report["error"] = "Unsupported provider"

    except Exception as exc:
        # Report the exception type, never secret values.
        report["error"] = type(exc).__name__

    return report


print()
print("=" * 60)
print("STUDENT SUPPORT AI - PROVIDER CHECK")
print("=" * 60)
_diag = provider_diagnostics()
print(f"  .env file      : {_diag['env_file_exists']} ({_diag['env_file']})")
print(f"  provider       : {_diag['provider']}")
print(f"  model          : {_diag['model']}")
print(f"  key present    : {_diag['key_present']}")
print(f"  SDK installed  : {_diag['sdk_ok']}")
print(f"  ready          : {_diag['ready']}")
if _diag.get("key_format_ok") is False and _diag["provider"] == "gemini":
    print("  ! GOOGLE_GENERATIVE_AI_API_KEY looks unset or invalid:")
    print("    - paste a real key from https://aistudio.google.com/apikey")
    print("      into .env (any current key format is accepted).")
if not _diag["ready"]:
    print("  ! AI generation will fall back until this is fixed:")
    if not _diag["env_file_exists"]:
        print("    - .env not found next to app.py; create it there.")
    if not _diag["key_present"]:
        print("    - set GOOGLE_GENERATIVE_AI_API_KEY in .env (AI_PROVIDER=gemini default).")
    if not _diag["sdk_ok"]:
        print("    - run: venv\\Scripts\\pip.exe install -r requirements.txt")
print("=" * 60)
print()


# Subjects stored in the database that are NOT active academic subjects
# for the My Subjects semester list (elective placeholder, NSS, PE).
# They are never deleted; they are only excluded from the list query.
NON_LISTED_SUBJECT_CODES = frozenset({"BCS515x", "BNSK559", "BPEK559"})


# =========================================================
# LOGIN HELPER
# =========================================================

def get_current_user():
    # Cached per request in Flask's `g`: login_required() and the view
    # function both need the current user, and without this cache every
    # authenticated page issued the same SELECT twice. Same row, same
    # shape — just one round-trip instead of two.
    if "_current_user" in g:
        return g._current_user

    user_id = session.get("user_id")

    if not user_id:
        g._current_user = None
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

        g._current_user = result
        return result

    except Exception:
        db.session.rollback()
        g._current_user = None
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
            except Exception as lookup_error:
                # Temporary diagnostic: type only, no email/SQL/secrets.
                print(
                    "LOGIN DIAG: user_found=False "
                    f"lookup_error={type(lookup_error).__name__}"
                )
                raise

            user_found = user is not None
            has_password_hash = bool(
                user["password_hash"]) if user_found else False
            has_legacy_password = bool(
                user["password"]) if user_found else False
            # Temporary diagnostic: booleans only, no PII or secrets.
            print(
                f"LOGIN DIAG: user_found={user_found} "
                f"has_password_hash={has_password_hash} "
                f"has_legacy_password={has_legacy_password}"
            )

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
            except (ValueError, AttributeError) as verify_error:
                password_ok = False
                # Temporary diagnostic: type only, no PII or secrets.
                print(
                    "LOGIN DIAG: password_ok=False "
                    f"verify_error={type(verify_error).__name__}"
                )

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
                    # Temporary diagnostic: type only, redacted.
                    print(
                        "PASSWORD UPGRADE ERROR: "
                        f"{type(upgrade_error).__name__}"
                    )

            # Temporary diagnostic: booleans only, no PII or secrets.
            print(f"LOGIN DIAG: password_ok={bool(password_ok)}")

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

            # Temporary diagnostic: type only, redacted (no email,
            # password, hash, DATABASE_URL, or session secret).
            print(f"LOGIN DIAG: exception={type(error).__name__}")

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

    # Fast path: all four counts in a single round-trip (was four
    # sequential COUNT queries). Returns the exact same numbers; any
    # failure (e.g. schema drift) rolls back and falls through to the
    # individually guarded counts below, so the page never 500s.
    try:
        combined = db.session.execute(
            text("""
                SELECT
                    (SELECT COUNT(*) FROM notes
                      WHERE user_id = :uid) AS note_count,
                    (SELECT COUNT(*) FROM conversations
                      WHERE user_id = :uid) AS conversation_count,
                    (SELECT COUNT(*) FROM subjects
                      WHERE branch = :branch
                        AND scheme = :scheme
                        AND semester = :semester) AS subject_count,
                    (SELECT COUNT(*) FROM questions q
                      JOIN subjects s ON s.id = q.subject_id
                      WHERE s.branch = :branch
                        AND s.scheme = :scheme
                        AND s.semester = :semester) AS question_count
            """),
            {
                "uid": user["id"],
                "branch": user["branch"],
                "scheme": user["scheme"],
                "semester": user["current_semester"]
            }
        ).mappings().first()

        if combined is not None:
            return render_template(
                "dashboard.html",
                user=user,
                note_count=combined["note_count"] or 0,
                conversation_count=combined["conversation_count"] or 0,
                subject_count=combined["subject_count"] or 0,
                question_count=combined["question_count"] or 0
            )
    except Exception as error:
        db.session.rollback()
        print("DASHBOARD COMBINED COUNT FALLBACK:", error)

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

# How many starter suggestions the chat page shows per load.
SUGGESTION_COUNT = 4


@app.route("/api/chat/suggestions", methods=["GET"])
@login_required
def api_chat_suggestions():
    """Starter question suggestions for the chat page.

    Derived from the real subjects table: only subjects whose rows say
    they belong to the student's semester (branch + scheme) qualify, so
    elective/PE placeholders filtered out of the UI never surface here
    either. When the page carries a subject context (subject deep
    links), that subject's questions come first; otherwise the load is
    a round-robin mixture across ALL supported semester subjects, and
    it rotates across page loads (random shuffle per request) so the
    same four chips don't repeat forever.
    """
    user = get_current_user()

    data = request.args
    try:
        semester = int(data.get("semester", user["current_semester"]))
    except (TypeError, ValueError):
        semester = user["current_semester"]
    if semester not in (1, 2, 3, 4, 5, 6, 7, 8):
        semester = user["current_semester"]

    requested_code = (data.get("subject_code") or "").strip().upper()

    try:
        rows = db.session.execute(
            text("""
                SELECT q.question, s.subject_code
                FROM questions q
                JOIN subjects s ON s.id = q.subject_id
                WHERE s.branch = :branch
                  AND s.scheme = :scheme
                  AND s.semester = :semester
                ORDER BY s.subject_code ASC, q.id ASC
            """),
            {
                "branch": user["branch"],
                "scheme": user["scheme"],
                "semester": semester,
            }
        ).mappings().all()
    except Exception:
        db.session.rollback()
        rows = []

    by_code = {}
    for row in rows:
        code = row["subject_code"]
        question = (row["question"] or "").strip()
        if code and question:
            by_code.setdefault(code, []).append(question)

    codes = sorted(by_code)
    mixture = False
    if requested_code:
        # The requested subject is always tried first; if it has no
        # question rows we fall through to the other semester subjects
        # rather than showing nothing (or inventing questions). Codes
        # with no DB rows at all are dropped (can't invent questions).
        subject_codes = ([requested_code] if requested_code in by_code
                         else [])
        subject_codes += [c for c in codes
                          if c != requested_code and c in by_code]
    else:
        subject_codes = [c for c in codes if c in by_code]
        mixture = True
        # Shuffle subject order so no single subject (e.g. SEPM/BCS501,
        # which sorts first alphabetically) always claims the first slot.
        import random as _subj_random
        _subj_random.shuffle(subject_codes)

    suggestions = []
    if mixture:
        # Vary across page loads: shuffle each subject's pool, then
        # pick round-robin across every supported subject so one
        # subject (e.g. Software Engineering) can never dominate.
        import random as _random
        pools = {c: list(by_code[c]) for c in subject_codes}
        for pool in pools.values():
            _random.shuffle(pool)
        while len(suggestions) < SUGGESTION_COUNT:
            any_added = False
            for code in subject_codes:
                if len(suggestions) >= SUGGESTION_COUNT:
                    break
                if pools.get(code):
                    suggestions.append((code, pools[code].pop()))
                    any_added = True
            if not any_added:
                break
    else:
        pools = {c: list(by_code[c]) for c in subject_codes}
        import random as _random
        for pool in pools.values():
            _random.shuffle(pool)
        for code in subject_codes:
            for question in pools.get(code, []):
                if len(suggestions) >= SUGGESTION_COUNT:
                    break
                suggestions.append((code, question))
            if len(suggestions) >= SUGGESTION_COUNT:
                break

    return {
        "semester": semester,
        "subjects": subject_codes,
        "subject_code": requested_code if requested_code else None,
        "as_mix": mixture,
        "suggestions": [
            {"text": question, "subject_code": code}
            for code, question in suggestions
        ],
    }


@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():

    from utils.rag_ai import answer_with_rag, generate_followup_suggestions
    from utils.ai import generate_answer, gemini_available

    user = get_current_user()

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()

    if not message:
        return {"reply": "Please type a question first."}, 400

    if len(message) > 2000:
        return {"reply": "Please keep questions under 2000 characters."}, 400

    # Try RAG first: retrieve study-material knowledge, grounded in it.
    # Subject-aware: the chat client may pass subject_code/module_number
    # (e.g. from a subject page). Both are optional; when absent the
    # search spans all subjects, with an automatic hint from common
    # abbreviations (ADA, DBMS, ...) and subject-name words. Values are
    # validated against the subjects table so one subject can never
    # pull another's chunks via a forged code. Mode selects the
    # retrieval budget: "fast" (quick, concise) or "detailed".
    try:
        from utils.rag_ai import normalize_mode
        from utils.rag import detect_query_subject

        mode = normalize_mode(data.get("mode"))
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
        if not rag_subject:
            try:
                rows = db.session.execute(
                    text("SELECT subject_code, subject_name FROM subjects")
                ).mappings().all()
                hint = detect_query_subject(
                    message,
                    {r["subject_code"]: r["subject_name"] for r in rows},
                )
                if hint:
                    rag_subject = hint
            except Exception:
                db.session.rollback()
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
            mode=mode,
            history=data.get("history"),
        )

        answer = rag_result.get("answer", "")
        sources = rag_result.get("sources", [])
        used_rag = rag_result.get("used_rag", False)
        used_ai = rag_result.get("used_ai", False)

        # If RAG produced an answer, use it.
        if answer:
            provider = rag_result.get("provider")
            if used_ai:
                engine = {"openai": "openai", "gemini": "gemini"}.get(
                    provider, "openai")
            else:
                engine = "study bank"
            return {
                "reply": answer,
                "answer": answer,
                "sources": sources,
                "used_rag": used_rag,
                "used_ai": used_ai,
                "provider": provider,
                "answer_kind": rag_result.get("answer_kind", "fallback_excerpts"),
                "error_code": rag_result.get("error_code"),
                "engine": engine,
                "mode": rag_result.get("mode", mode),
                "latency_ms": rag_result.get("latency_ms", 0),
                "cached": rag_result.get("cached", False),
                "suggestions": rag_result.get("suggestions") or [],
                "has_general_explanation": rag_result.get(
                    "has_general_explanation", False),
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
        # All-semester question bank (branch + scheme only): the study
        # assistant must answer from materials of every semester, not
        # just the student's current one. The subjects list above stays
        # current-semester scoped for identity/greeting purposes.
        rows = db.session.execute(
            text("""
                SELECT q.question, q.unit, q.marks,
                       s.subject_name AS subject_name,
                       s.subject_code AS subject_code
                FROM questions q
                JOIN subjects s ON s.id = q.subject_id
                WHERE s.branch = :branch
                  AND s.scheme = :scheme
                ORDER BY q.id ASC
                LIMIT 200
            """),
            {
                "branch": user["branch"],
                "scheme": user["scheme"]
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
                "resources": resources_ctx,
                "history": data.get("history"),
            }
        )
        # Label honestly: generate_answer's only live-AI tier is
        # OpenAI, so the engine is "openai" exactly when an OpenAI
        # key is configured, else "offline". active_provider() must
        # not be used here: it can report gemini/ollama, which this
        # path never calls, mislabeling study-bank text as AI-made.
        try:
            from utils import openai_provider as _fallback_openai
            engine = (
                "openai"
                if _fallback_openai.openai_available()
                else "offline"
            )
        except Exception:
            engine = "offline"
    except Exception as error:
        print("CHAT GENERATE ERROR:", error)
        reply = (
            "I had trouble processing that. Please try again, "
            "for example: 'Explain DBMS normalization'."
        )
        engine = "offline"

    # Offline/fallback answers: attach topic-based suggestions too.
    from utils.rag_ai import _offline_general_explanation
    _has_general = _offline_general_explanation(message) is not None
    return {"reply": reply, "answer": reply, "sources": [], "used_rag": False, "used_ai": False, "engine": engine, "suggestions": generate_followup_suggestions(message, reply), "has_general_explanation": _has_general}


# =========================================================
# CHAT API - STREAMING (Server-Sent Events)
# =========================================================

@app.route("/api/chat/stream", methods=["POST"])
@login_required
def api_chat_stream():

    import json as _json

    from utils.rag_ai import normalize_mode, stream_answer

    user = get_current_user()

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()

    if not message:
        def _empty():
            yield 'event: error\ndata: {"error": "Please type a question first."}\n\n'
        return Response(_empty(), mimetype="text/event-stream")

    if len(message) > 2000:
        def _too_long():
            yield 'event: error\ndata: {"error": "Please keep questions under 2000 characters."}\n\n'
        return Response(_too_long(), mimetype="text/event-stream")

    mode = normalize_mode(data.get("mode"))

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
    if not rag_subject:
        try:
            from utils.rag import detect_query_subject
            rows = db.session.execute(
                text("SELECT subject_code, subject_name FROM subjects")
            ).mappings().all()
            hint = detect_query_subject(
                message,
                {r["subject_code"]: r["subject_name"] for r in rows},
            )
            if hint:
                rag_subject = hint
        except Exception:
            db.session.rollback()
    try:
        if requested_module is not None and str(requested_module).strip() != "":
            rag_module = int(requested_module)
            if rag_module not in (1, 2, 3, 4, 5):
                rag_module = None
    except (TypeError, ValueError):
        rag_module = None

    def _generate():
        try:
            for item in stream_answer(
                question=message,
                subject_code=rag_subject,
                module_number=rag_module,
                mode=mode,
                history=data.get("history"),
            ):
                yield f"event: {item['event']}\ndata: {_json.dumps(item['data'])}\n\n"
        except GeneratorExit:
            # Client pressed stop / disconnected: just end the stream.
            return
        except Exception as stream_error:
            print("CHAT STREAM ERROR:", stream_error)
            yield 'event: error\ndata: {"error": "Streaming failed. Please retry."}\n\n'

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return Response(_generate(), mimetype="text/event-stream", headers=headers)


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

    # My Academic Journey scope: only the 5th Semester is accessible.
    # Locked semesters (1-4, 6-8) never render an empty subject list;
    # direct route access redirects back to the 5th Semester page.
    # No database rows are touched; the 5th-semester path below is
    # completely unchanged.
    if selected_semester != 5:
        _ORDINAL = {
            1: "1st", 2: "2nd", 3: "3rd", 4: "4th",
            6: "6th", 7: "7th", 8: "8th",
        }
        flash(
            f"{_ORDINAL.get(selected_semester, 'That')} Semester is "
            "locked. Only 5th Semester is available.",
            "error"
        )
        return redirect(url_for("subjects"))

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

    from werkzeug.exceptions import HTTPException  # pyright: ignore[reportMissingImports]

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

    # My Academic Journey scope: only 5th-semester subjects are
    # accessible. Direct route access to any other semester's subject
    # redirects back to the 5th Semester page instead of rendering an
    # empty detail page. No rows are touched; the 5th-semester path
    # below is completely unchanged.
    if subject.get("semester") != 5:
        flash(
            "That semester is locked. "
            "Only 5th Semester is available.",
            "error"
        )
        return redirect(url_for("subjects"))

    # Only id/unit are used below (counts + unit cards); the large
    # `answer` TEXT column stays deferred so the DB transfers less per
    # row. Attribute access still works transparently (lazy-loads on
    # demand), so callers see identical objects.
    questions = (
        Question.query
        .options(load_only(Question.id, Question.unit))
        .filter_by(subject_id=subject_id)
        .order_by(Question.id.asc())
        .all()
    )

    try:
        resources = (
            Resource.query
            .options(load_only(Resource.id, Resource.subject_id,
                               Resource.title, Resource.category,
                               Resource.resource_type, Resource.url,
                               Resource.is_featured))
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

    # Web Technology exception (BCS504): single-file subject, no modules.
    # Its "Web Technology Programs.pdf" is rendered in the Study Material
    # section as one unnumbered file; the Units grid stays empty.
    if subject.get("code") == "BCS504":
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

    # BCS405A exception: this subject shows its files directly under
    # Study Material with no Additional Resources section. Rows are
    # deduplicated by filename (Study Material row wins), so a duplicate
    # module-0 row can never produce a second card or section.
    # Scoped to this code only; other subjects are untouched.
    if subject.get("code") == "BCS405A":
        seen_filenames = set()
        unique_rows = []
        for doc_row in sorted(doc_rows, key=lambda r: (r["module_number"] != 1, r["id"])):
            filename = doc_row["original_filename"] or doc_row["title"]
            if filename in seen_filenames:
                continue
            seen_filenames.add(filename)
            unique_rows.append(doc_row)
        doc_rows = unique_rows
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
        additional_resources = []

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

    # BCS405A never shows an Additional Resources section: its files live
    # directly under Study Material (deduplicated above). Scoped override;
    # other subjects are untouched.
    if subject.get("code") == "BCS405A":
        additional_resources = []

    # Reusable Module 1-5 slot pattern: any subject with at least one
    # study file shows slots 1-5 in order; slots without a PDF render as
    # empty placeholders ready for later uploads. Subjects with zero
    # files still render zero cards (clean empty state is preserved).
    # Module 0 (Additional Resources) never becomes a module card.
    if docs_by_module:
        module_numbers = sorted((set(docs_by_module) | {1, 2, 3, 4, 5}) - {0})
    else:
        module_numbers = []

    # Unnumbered file collections (BCEDK103, BENGK106, BMATS101,
    # BMATS201, BKSKK107, BSFHK158, BIDTK258, BYOK359, BSCK307, BCS301,
    # BUHK408, BCSL305, BYOK459, BCS405A, BCSL404, BCSL456D):
    # their files (primers, question papers, solved papers, question
    # banks, formula sheets, textbooks, scanned notes, ...) are not
    # module-wise, so each document
    # renders as its own unnumbered file card in the existing View File
    # format, never as Module 1-5.
    # Scoped to these codes only; other subjects are untouched.
    if subject.get("code") in ("BCEDK103", "BENGK106", "BMATS101", "BMATS201", "BKSKK107", "BSFHK158", "BIDTK258", "BYOK359", "BSCK307", "BCS301", "BUHK408", "BCSL305", "BYOK459", "BCS405A", "BCSL404", "BCSL456D") and doc_rows:
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
    elif subject.get("code") == "BCS504" and doc_rows:
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
# KNOWLEDGE PDF VIEWER (local files + Backblaze B2)
# =========================================================

@app.route("/knowledge/pdf/<int:document_id>")
@login_required
def knowledge_pdf(document_id):
    try:
        row = db.session.execute(
            text("""
                SELECT id, original_filename, file_path
                FROM knowledge_documents
                WHERE id = :doc_id
            """),
            {"doc_id": document_id},
        ).mappings().first()
    except Exception:
        db.session.rollback()
        app.logger.exception("KNOWLEDGE PDF QUERY ERROR")
        abort(500)

    if not row or not (row["file_path"] or "").strip():
        abort(404)

    raw_path = row["file_path"].strip().replace("\\", "/")

    if Path(raw_path).suffix.lower() != ".pdf":
        abort(404)

    file_obj = get_knowledge_file(raw_path)

    return send_file(
        file_obj,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=row["original_filename"] or Path(raw_path).name,
    )


# =========================================================
# KNOWLEDGE DOCUMENT VIEWER (local files + Backblaze B2)
# =========================================================

@app.route("/knowledge/document/<int:document_id>")
@login_required
def knowledge_document(document_id):
    try:
        row = db.session.execute(
            text("""
                SELECT id, original_filename, file_path
                FROM knowledge_documents
                WHERE id = :doc_id
            """),
            {"doc_id": document_id},
        ).mappings().first()
    except Exception:
        db.session.rollback()
        app.logger.exception("KNOWLEDGE DOCUMENT QUERY ERROR")
        abort(500)

    if not row or not (row["file_path"] or "").strip():
        abort(404)

    raw_path = row["file_path"].strip().replace("\\", "/")
    suffix = Path(raw_path).suffix.lower()

    mime_types = {
        ".pdf": "application/pdf",
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
        ".xlsx": (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".txt": "text/plain",
    }

    if suffix not in mime_types:
        abort(404)

    file_obj = get_knowledge_file(raw_path)
    filename = row["original_filename"] or Path(raw_path).name

    inline_types = {
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".txt"
    }

    return send_file(
        file_obj,
        mimetype=mime_types[suffix],
        as_attachment=suffix not in inline_types,
        download_name=filename,
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
# REQUEST TEARDOWN (release the thread-local retrieval connection)
# =========================================================

@app.teardown_appcontext
def close_retrieval_connection(_error):
    try:
        from utils.db_conn import close_conn
        close_conn()
    except Exception:
        pass


# =========================================================
# PROVIDER STATUS (safe self-check: booleans and names only)
# =========================================================

@app.route("/api/provider-status")
@login_required
def api_provider_status():
    return provider_diagnostics()


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
