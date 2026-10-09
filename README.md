# Student Support AI

AI-powered academic companion for VTU CSE students — subjects, important
questions, notes, resources and an offline study-assistant chat.

## Run on localhost (Windows)

```bat
cd student-support-ai
venv\Scripts\activate
venv\Scripts\python.exe app.py
```

Then open **http://127.0.0.1:5000** in your browser.

## First-time setup

1. Python 3.10+ with a virtual environment in `venv/`.
2. Install dependencies:

   ```bat
   venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Optionally create a `.env` file (see below) to use PostgreSQL. Without
   one, the app creates and uses a local `student_support_ai.db` SQLite
   database automatically.
4. Seed the study content (safe to re-run, skips existing rows):

   ```bat
   venv\Scripts\python.exe seed_subjects.py
   venv\Scripts\python.exe seed_content.py
   ```

## Optional PostgreSQL environment (`.env`)

```env
DATABASE_URL=postgresql://user:password@host:port/postgres
SECRET_KEY=any-long-random-string
```

On startup, the app creates missing tables and safely adds fields required by
newer app versions to an existing PostgreSQL database. It never deletes or
overwrites existing records during this compatibility step.

## Features

- Signup / Login / Forgot password (email + new password reset)
- Dashboard with live counts (notes, conversations, subjects, questions)
- Ask AI chat — works offline, answers from your own study bank
  (`POST /api/chat`, brain in `utils/ai.py`, frontend in `static/js/chat.js`)
- My Subjects + subject detail pages (units, questions, resources)
- Important Questions with search / subject / difficulty filters
- My Notes (create, edit, delete, search)
- Resources (study bank + curated VTU/NPTEL links)
- Settings (profile name, preferences, logout)

## Project layout

```text
app.py                 Flask app (all routes)
utils/database.py      SQLAlchemy models + init
utils/ai.py            Offline chat answer engine
templates/             HTML pages
static/css/style.css   All styling
static/js/             chat.js, dashboard.js, main.js
seed_subjects.py       Seed VTU subjects
seed_content.py        Seed questions + resources
```

## Health check

- `GET /database-test` → `Database connection successful.`
