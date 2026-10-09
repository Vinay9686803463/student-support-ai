"""
Nextcloud folder automation for Student Support AI project.

- Reads Nextcloud URL / username / app password from environment variables
  (optionally loaded from a local `.env` file, never hardcoded).
- Uses WebDAV MKCOL to create folders.
- Idempotent: existing folders are safely skipped.
- Never prints the password.

Required env vars:
    NEXTCLOUD_URL          e.g. http://localhost:8080 (default)
    NEXTCLOUD_USERNAME     e.g. 1DI24CS087 (default)
    NEXTCLOUD_APP_PASSWORD e.g. <app password created in Nextcloud UI>

Usage:
    1. Copy `.env.example` to `.env` (locally, never commit `.env`).
    2. Edit `.env` in a text editor and set NEXTCLOUD_APP_PASSWORD.
       Do NOT paste the password in chat.
    3. Run:  python scripts/nextcloud_setup.py
"""

import base64
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


# ---------------------------------------------------------------------------
# Folder structure definition
# ---------------------------------------------------------------------------

ROOT = "Student Support AI"

SEMESTERS = {
    "Semester 1": [
        "BCEDK103 - Computer Aided Engineering Drawing",
        "BCHES102 - Chemistry for CSE Stream",
        "BESCK104C - Electronics and Communication Engineering",
        "BENGK106 - Communicative English",
        "BKSKK107 - Samskrutika Kannada",
        "BMATS101 - Mathematics for CSE-Stream-I",
        "BSFHK158 - Scientific Foundations of Health",
        "BETCK105F - Waste Management",
    ],
    "Semester 2": [
        "BPWSK206 - Professional Writing Skills in English",
        "BICOK207 - Indian Constitution",
        "BIDTK258 - Innovation and Design Thinking",
        "BPLCK205C - Baasics of Java Programming",
        "BMATS201 - Mathematics for CSE Stream-II",
        "BESCK204D - Introduction to Mechanical Engineering",
        "BPHYS202 - Physics for CSE Stream",
        "BPOPS203 - Principles of Programming Using C",
    ],
    "Semester 3": [
        "BCS301 - Mathematics for Computer Science",
        "BCS302 - Digital Design & Computer Organization",
        "BCS303 - Operating Systems",
        "BCS304 - Data Structures and Applications",
        "BCSL305 - Data Structures Lab",
        "BCS306B - Object Oriented Programming with C++",
        "BSCK307 - Social Connect and Responsibility",
        "BYOK359 - Yoga",
    ],
    "Semester 4": [
        "BCS401 - Analysis & Design of Algorithms",
        "BCS402 - Microcontrollers",
        "BCS403 - Database Management Systems",
        "BCSL404 - Analysis & Design of Algorithms Lab",
        "BCS405A - Discrete Mathematical Structures",
        "BCSL456D - Technical Writing using LATEX",
        "BBOC407 - Biology for Computer Engineers",
        "BUHK408 - Universal Human Values Course",
        "BYOK459 - Yoga",
    ],
    "Semester 5": [
        "BCS501 - Software Engineering & Project Management",
        "BCS502 - Computer Networks",
        "BCS503 - Theory of Computation",
        "BCS504 - Unix System Programming",
        "BRMK557 - Research Methodology and IPR",
        "BCS508 - Environmental Studies and E-waste Management",
        "WEBTECH - Web Technology",
    ],
}

MODULES = [f"Module {i}" for i in range(1, 6)]

# Exception: Web Technology gets no Module subfolders.
# It should contain only "Web Technology Programs.pdf" (uploaded manually).
WEBTECH_SUBJECT = "WEBTECH - Web Technology"
WEBTECH_PDF = "Web Technology Programs.pdf"


def build_expected_folders():
    """Return ordered list of relative folder paths to create."""
    folders = [ROOT]
    for semester, subjects in SEMESTERS.items():
        sem_path = f"{ROOT}/{semester}"
        folders.append(sem_path)
        for subject in subjects:
            subject_path = f"{sem_path}/{subject}"
            folders.append(subject_path)
            if subject == WEBTECH_SUBJECT:
                continue  # no Module 1-5 for Web Technology
            for module in MODULES:
                folders.append(f"{subject_path}/{module}")
    return folders


# ---------------------------------------------------------------------------
# Minimal .env loader (no third-party dependency, no secret logging)
# ---------------------------------------------------------------------------

def load_dotenv():
    """Load KEY=VALUE pairs from local .env into os.environ (if not already set).

    Looks for .env in project root (parent of scripts/) and in CWD.
    Never prints values.
    """
    candidates = []
    try:
        script_dir = Path(__file__).resolve().parent
        candidates.append(script_dir.parent / ".env")  # project root
        candidates.append(script_dir / ".env")
    except NameError:
        pass
    candidates.append(Path.cwd() / ".env")

    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# WebDAV helpers (urllib only, no password in logs)
# ---------------------------------------------------------------------------

def dav_request(url, username, password, method, data=None, extra_headers=None):
    """Perform one authenticated WebDAV HTTP request. Returns (status, body)."""
    credentials = f"{username}:{password}".encode("utf-8")
    token = base64.b64encode(credentials).decode("ascii")
    headers = {
        "Authorization": f"Basic {token}",
        "User-Agent": "student-support-ai-nextcloud-setup/1.0",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return e.code, body
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection failed for {method} {redacted_url(url)}: {e}")


def redacted_url(url):
    """Return URL safe for logging (no credentials embedded by construction)."""
    return url


def encode_path(path):
    """URL-encode each segment of a WebDAV relative path (keep slashes)."""
    return "/".join(urllib.parse.quote(seg, safe="") for seg in path.split("/"))


def ensure_folder(base_dav_url, username, password, rel_path, stats):
    """MKCOL a single folder. Treat 405/412 as 'already exists'."""
    url = base_dav_url.rstrip("/") + "/" + encode_path(rel_path)
    status, _ = dav_request(url, username, password, "MKCOL")
    if status in (200, 201, 204):
        print(f"[CREATED] {rel_path}")
        stats["created"] += 1
        return True
    if status in (405, 412, 409, 423):
        # 405 Method Not Allowed / 412 Precondition Failed => already exists
        # 409 Conflict => parent missing (should not happen, we go in order)
        # 423 Locked => exists but locked
        # Verify with PROPFIND whether it actually exists.
        p_status, _ = dav_request(
            url, username, password, "PROPFIND",
            data=b'<?xml version="1.0"?><propfind xmlns="DAV:"><prop><resourcetype/></prop></propfind>',
            extra_headers={"Depth": "0", "Content-Type": "application/xml"},
        )
        if p_status in (200, 207):
            print(f"[EXISTS]  {rel_path}")
            stats["exists"] += 1
            return True
        if status == 409:
            print(f"[ERROR]   {rel_path} (parent missing, HTTP 409)")
        else:
            print(f"[EXISTS?] {rel_path} (HTTP {status} on MKCOL, PROPFIND={p_status})")
            stats["exists"] += 1
            return True
        stats["errors"] += 1
        return False
    print(f"[ERROR]   {rel_path} (HTTP {status})")
    stats["errors"] += 1
    return False


def verify_folder(base_dav_url, username, password, rel_path):
    """Check folder exists via PROPFIND Depth:0. Returns True/False."""
    url = base_dav_url.rstrip("/") + "/" + encode_path(rel_path)
    status, _ = dav_request(
        url, username, password, "PROPFIND",
        data=b'<?xml version="1.0"?><propfind xmlns="DAV:"><prop><resourcetype/></prop></propfind>',
        extra_headers={"Depth": "0", "Content-Type": "application/xml"},
    )
    return status in (200, 207)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    load_dotenv()

    nextcloud_url = os.environ.get("NEXTCLOUD_URL", "http://localhost:8080").rstrip("/")
    username = os.environ.get("NEXTCLOUD_USERNAME", "1DI24CS087")
    password = os.environ.get("NEXTCLOUD_APP_PASSWORD", "")

    placeholder_values = {"", "your-app-password-here", "YOUR_APP_PASSWORD",
                          "changeme", "xxx", "***", "placeholder"}
    if not password or password.strip() in placeholder_values:
        print("ERROR: NEXTCLOUD_APP_PASSWORD is not set (placeholder detected).")
        print()
        print("To fix securely (do NOT paste the password in chat):")
        print("  1. Copy .env.example to .env in the project root (if needed).")
        print("  2. Open .env in a text editor and set:")
        print("       NEXTCLOUD_APP_PASSWORD=your-app-password-from-nextcloud-ui")
        print("  3. Re-run:  python scripts/nextcloud_setup.py")
        print()
        print("Generate the app password in Nextcloud at:")
        print("  Settings -> Security -> Devices & sessions -> Create app password.")
        return 1

    base_dav_url = (
        f"{nextcloud_url}/remote.php/dav/files/{urllib.parse.quote(username, safe='')}"
    )

    print(f"Nextcloud URL : {nextcloud_url}")
    print(f"Username      : {username}")
    print("Password      : [hidden, loaded from environment]")
    print(f"WebDAV base   : {base_dav_url}")
    print()

    # Connectivity check: PROPFIND on user root.
    try:
        status, _ = dav_request(
            base_dav_url + "/",
            username, password, "PROPFIND",
            data=b'<?xml version="1.0"?><propfind xmlns="DAV:"><prop><resourcetype/></prop></propfind>',
            extra_headers={"Depth": "0", "Content-Type": "application/xml"},
        )
    except RuntimeError as e:
        print(f"ERROR: {e}")
        print("Is Nextcloud running at the URL above? Start it and retry.")
        return 1

    if status == 401:
        print("ERROR: Authentication failed (HTTP 401).")
        print("Check NEXTCLOUD_USERNAME and NEXTCLOUD_APP_PASSWORD in your local .env.")
        return 1
    if status not in (200, 207):
        print(f"WARNING: WebDAV root check returned HTTP {status}, continuing anyway.")

    folders = build_expected_folders()
    print(f"Creating {len(folders)} folders...")
    print("-" * 60)

    stats = {"created": 0, "exists": 0, "errors": 0}
    for rel_path in folders:
        try:
            ensure_folder(base_dav_url, username, password, rel_path, stats)
        except RuntimeError as e:
            print(f"[ERROR]   {rel_path} ({e})")
            stats["errors"] += 1

    print("-" * 60)
    print(f"MKCOL pass: {stats['created']} created, "
          f"{stats['exists']} already existed, {stats['errors']} errors.")
    print()
    print("Verifying final structure (PROPFIND Depth:0 per folder)...")

    missing = []
    for rel_path in folders:
        try:
            ok = verify_folder(base_dav_url, username, password, rel_path)
        except RuntimeError:
            ok = False
        if ok:
            print(f"[OK]      {rel_path}")
        else:
            print(f"[MISSING] {rel_path}")
            missing.append(rel_path)

    # Web Technology special case: only the subject folder, no modules.
    # The PDF is uploaded manually and checked separately (not created here).
    webtech_path = f"{ROOT}/Semester 5/{WEBTECH_SUBJECT}"
    print()
    print(f"Special case: {WEBTECH_SUBJECT} must have NO Module subfolders.")
    print(f"Expected PDF (upload manually in Nextcloud UI): "
          f"{webtech_path}/{WEBTECH_PDF}")

    print()
    if missing:
        print(f"VERIFICATION FAILED: {len(missing)} folder(s) missing.")
        for m in missing:
            print(f"  - {m}")
        return 1

    print(f"VERIFICATION PASSED: all {len(folders)} folders present.")
    print(f"Summary: {stats['created']} created, "
          f"{stats['exists']} already existed, 0 missing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
