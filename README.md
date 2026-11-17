# Quiz Master

**A full-stack quiz platform with three independent quiz modes, server-side scoring, achievements, leaderboards and AI-assisted question management.**

Built with Flask, PostgreSQL (Supabase) and Google Gemini. Deployable on Render.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.1-000000?logo=flask&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-4169E1?logo=postgresql&logoColor=white)
![Gemini](https://img.shields.io/badge/Google-Gemini_API-4285F4?logo=google&logoColor=white)
![Deploy](https://img.shields.io/badge/Deploy-Render-46E3B7)

<!-- Add screenshots to docs/screenshots/ and reference them here, for example:
![Home](docs/screenshots/home.png)  ![Quiz](docs/screenshots/quiz.png) -->

---

## Table of contents

1. [Features](#1-features)
2. [Tech stack](#2-tech-stack)
3. [How the quizzes work](#3-how-the-quizzes-work)
4. [Project structure](#4-project-structure)
5. [Getting started (local)](#5-getting-started-local)
6. [Configuration](#6-configuration)
7. [Database and migrations](#7-database-and-migrations)
8. [Question management (CSV + Gemini)](#8-question-management-csv--gemini)
9. [Pages and statistics](#9-pages-and-statistics)
10. [HTTP routes](#10-http-routes)
11. [Testing](#11-testing)
12. [Deployment on Render](#12-deployment-on-render)
13. [Security](#13-security)
14. [Troubleshooting](#14-troubleshooting)
15. [Known limitations](#15-known-limitations)
16. [Licensing and attribution](#16-licensing-and-attribution)

---

## 1. Features

**Quizzing**
- **Three separate quiz modes** with their own question datasets and progress: Category Quizzes (56 categories), All Quiz (one question per category in a fixed order) and a Daily Challenge (up to 50 questions, one saved game per day).
- Instant answer feedback with the correct option and a full explanation, a live timer with pause/resume, hints, Previous/Next navigation, and a Finish & Save step that stores the game atomically.
- English questions for every category; the **Kannada** category is fully in Kannada.

**Progress and motivation**
- Daily streaks, **43 achievements and badges**, bookmarks, and a combined **leaderboard** (All Time / This Month / This Week / Today).
- Personal statistics: Home summary, Profile (category quizzes), All Quiz page (Quiz 2 only), My Performance (all modes plus a last-10-games chart), and a filterable History.

**Accounts**
- Registration and login (username or email), secure password hashing, CSRF protection, rate limiting, light/dark mode saved per user, feedback form.

**Question management (administrators)**
- Import questions from **CSV** (preview, validation, duplicate detection), generate them with **Google Gemini**, export datasets to CSV, and see stored counts per mode and category.
- Optional importers for Open Trivia DB and The Trivia API.

---

## 2. Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, Flask 3.1, SQLAlchemy 2.x |
| Database | PostgreSQL on Supabase (SQLite for local development only) |
| Frontend | Server-rendered Jinja templates, vanilla JavaScript, CSS (no framework, no inline scripts or styles) |
| AI | Google Gemini API (called only from the backend) |
| Security | Flask-WTF (CSRF), Flask-Limiter (rate limits), Werkzeug password hashing |
| Server | Gunicorn on Render |
| Tests | pytest, jsdom (browser-side checks) |

---

## 3. How the quizzes work

### Quiz modes

| Mode | Questions come from | Progress | Hints | Notes |
|---|---|---|---|---|
| **Category Quiz** | the `category` dataset of the chosen category | one pointer per user and category | 10 | Plays on indefinitely: when you reach the last question of a batch, the next unseen ones are added. Completed questions are never repeated; when a category is exhausted the card offers **Play Again**. |
| **All Quiz** | the `all` dataset, one question per category in the fixed 56-category order | one pointer per user | 10 | Cycles through all categories, then continues with fresh questions. |
| **Daily Quiz** | the `daily` dataset, a shared set per calendar day | none (a record per day) | 5 | Up to 50 questions. One completed challenge per user per day, enforced by the database. Drives the daily streak. |

Questions of one mode are **never** used by another mode. Each mode has its own dataset in the same `questions` table, identified by its `pool` column (`category`, `all`, `daily`).

### Rules (all enforced on the server)

- Correct answer **+10**, wrong answer **-5**, hint **0**. The running score never drops below **0**.
- Each question can be answered once; the correct answer is never sent to the browser before a question is resolved.
- Using a hint reveals the answer and resolves the question without changing the score.
- The timer is calculated from server timestamps. Paused time is excluded; client-supplied time is never trusted.
- **Exit** discards an unsaved game. **Finish & Save** stores the game, answers and progress in one transaction; repeating the request is harmless. A game with no resolved question cannot be saved.
- A Daily Challenge counts as completed when every question is resolved and the game is saved. Streaks use the application time zone (default `Asia/Kolkata`).
- Progress pointers only move when a game is **saved**, by the number of questions resolved.

### Achievements

43 achievements are evaluated on the server after each saved game, for example games played, correct answers, correct-answer streaks, categories explored, perfect rounds, daily streaks, hint-free games, speed and accuracy. Each shows only its name, requirement and a status of **Locked** or **Earned**. Earned achievements are permanent.

### Leaderboard

One combined ranking per user over saved games of all three modes. Order: total score, then total correct answers, then total questions played, then total time (lower is better), then username. Only usernames are shown. Date ranges use the application time zone.

---

## 4. Project structure

```
quiz-master-api/
├── run.py                      Entry point (Gunicorn target: run:app)
├── config.py                   Environment-driven configuration
├── render.yaml                 Optional Render blueprint
├── requirements.txt            Runtime dependencies
├── requirements-dev.txt        + test dependencies
├── .env.example                Template for local settings (copy to .env)
├── migrations/                 SQL for PostgreSQL (also applied automatically on start)
├── app/
│   ├── __init__.py             Application factory, security headers, CLI commands
│   ├── models.py               SQLAlchemy models
│   ├── database.py             Engine/session handling and safe schema upgrades
│   ├── categories.py           The 56 categories (order, emoji, dataset names)
│   ├── auth/                   Register, login, logout, validation, admin check
│   ├── routes/                 pages.py, quiz.py (gameplay API), admin_questions.py, admin.py
│   ├── services/               quiz_engine, scoring, progress, daily_streak, achievements,
│   │                           reports, feedback, question_bank, question_validator,
│   │                           ai_question_generator, generation_jobs, question_sources, seed
│   ├── data/seed_questions.py  Starter question bank (2 per category)
│   ├── templates/              Jinja templates
│   └── static/                 css/, js/, images/
└── tests/                      pytest suite and jsdom browser-side checks
```

### Data model

| Table | Purpose |
|---|---|
| `users`, `user_preferences` | Accounts and per-user settings (dark mode) |
| `categories` | The 56 categories (fixed order) |
| `questions` | All questions; `pool` = quiz mode (`category` / `all` / `daily`) |
| `quiz_games`, `quiz_game_answers` | Games (in progress and saved) and every answer |
| `user_category_progress`, `play_all_progress` | Independent progress pointers |
| `daily_question_sets`, `daily_game_records`, `user_daily_streaks` | Daily Challenge sets, one-per-day records and streaks |
| `user_achievements`, `user_achievement_state` | Earned achievements and correct-answer streak state |
| `bookmarks`, `feedback` | Bookmarked questions and user feedback |

Key design choices: services receive an explicit database session; every game action locks and validates the game on the server; saving a game is an atomic claim, so duplicate requests cannot double-count; achievements are awarded after the save is committed and can never block it.

---

## 5. Getting started (local)

### Prerequisites

- Python 3.12
- Git
- Optional: PostgreSQL (or a Supabase project) and a Gemini API key

### Install

```bash
git clone https://github.com/sa2004-1992/quiz-master-api.git
cd quiz-master-api
python -m venv .venv
```

Activate the virtual environment:

| System | Command |
|---|---|
| macOS / Linux | `source .venv/bin/activate` |
| Windows PowerShell | `.\.venv\Scripts\Activate.ps1` (if blocked: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`) |

```bash
pip install -r requirements-dev.txt
cp .env.example .env          # Windows: copy .env.example .env
```

### Quick local run (no database setup)

Edit `.env` and set:

```env
FLASK_ENV=development
DATABASE_URL=
```

With an empty `DATABASE_URL` in development the app uses a local SQLite file (`dev.sqlite3`). **SQLite is for local development only**; production refuses to start with SQLite.

```bash
python run.py
```

Open <http://localhost:5000>, register an account and log in. On first start the tables, the 56 categories and a starter bank of questions are created automatically.

> `python run.py` serves plain HTTP, so session cookies are not marked `Secure` there. Open the site as `http://localhost:5000` (not `https://`).

### Make yourself an administrator

Add your username to `.env` and restart:

```env
ADMIN_USERNAMES=your_username
```

Log in with that account; **Manage Questions** appears in the sidebar. Use a strong, unique password for administrator accounts.

---

## 6. Configuration

All settings come from environment variables (a `.env` file is read automatically). Values that still start with `replace_with` are treated as unset. **Never commit `.env`.**

### Required in production

| Variable | Description |
|---|---|
| `SECRET_KEY` | Long random string used to sign sessions. Generate one: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | PostgreSQL connection string (Supabase). `postgres://` and `postgresql://` are converted automatically and `sslmode=require` is added for remote hosts |
| `FLASK_ENV` | `production` on the server, `development` locally |

### Common optional settings

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | empty | Enables Gemini generation. Without it the site works with stored questions only |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | Model name. Check Google's model list and your quota; change it here, no code change needed |
| `ADMIN_USERNAMES` | empty | Comma-separated usernames allowed to manage questions (case-insensitive). Empty = admin tools off |
| `APP_TIMEZONE` | `Asia/Kolkata` | Time zone for daily limits, streaks, achievements and date filters |
| `SESSION_COOKIE_SECURE` | `true` in production | Override the Secure cookie flag |
| `RATELIMIT_STORAGE_URI` | `memory://` | Rate-limit storage; use a Redis URL for limits shared across workers |
| `LOGIN_RATE_LIMIT` / `REGISTER_RATE_LIMIT` / `FEEDBACK_RATE_LIMIT` | `10 per minute` / `5 per minute` / `5 per minute` | Request limits |
| `ADMIN_API_TOKEN` | empty | Enables the token-protected `POST /api/admin/generate-questions` endpoint |

### Quiz and admin tuning

| Variable | Default | Description |
|---|---|---|
| `QUESTIONS_PER_GAME` | `10` | Questions added per batch in a Category Quiz |
| `ALL_QUIZ_QUESTIONS` | `56` | Questions per All Quiz batch |
| `DAILY_QUESTION_COUNT` | `50` | Daily Challenge size (maximum 50) |
| `HINTS_PER_GAME` / `DAILY_HINTS` | `10` / `5` | Hint limits |
| `CSV_MAX_BYTES` / `CSV_MAX_ROWS` | 2 MB / 2000 | CSV upload limits |
| `ADMIN_MAX_GENERATE` | `30` | Maximum questions per Gemini request |
| `ADMIN_GENERATE_RATE_LIMIT` / `ADMIN_CSV_RATE_LIMIT` | `6 per minute` / `30 per minute` | Admin request limits |
| `GEMINI_TIMEOUT`, `GEMINI_RETRIES`, `GEMINI_MAX_CALLS_PER_MINUTE`, `GEMINI_BATCH_SIZE` | 30 s, 2, 8, 10 | Gemini call behaviour |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | 5, 5 | Connection pool |
| `AUTO_INIT_DB`, `SEED_ON_STARTUP` | `true`, `true` | Create tables and seed starter data at start |

---

## 7. Database and migrations

### Supabase (PostgreSQL)

1. Create a project at [supabase.com](https://supabase.com) and wait for it to finish provisioning.
2. Open **Connect** and copy a **pooler** connection string. Render's free tier is IPv4-only and Supabase's direct host may be IPv6-only, so use the Session pooler (port 5432) or Transaction pooler (port 6543) string.
3. URL-encode special characters in the password and put the string in `DATABASE_URL`.
4. Start the app. Missing tables are created automatically and **nothing is ever dropped**.

Optionally create the schema yourself: run `migrations/001_initial_schema.sql` in the Supabase SQL editor, or `flask --app run init-db`.

### Safe upgrades

Schema changes are additive and applied automatically at startup (idempotent). The same SQL is kept in `migrations/` for manual use:

| File | Change |
|---|---|
| `001_initial_schema.sql` | Full schema for a new database |
| `002_add_game_answer_counts.sql` | Per-game answered / wrong counts (backfilled from saved answers) |
| `003_achievements.sql` | Achievement tables |
| `004_question_modes.sql` | Adds the `all` quiz mode and per-mode, per-category duplicate protection |

On SQLite (development) the `questions` table is rebuilt when an old version is detected, copying every row and id. Existing games, answers, progress and daily assignments are preserved.

### Row Level Security

The app connects as a privileged database role. If Supabase shows tables as **UNRESTRICTED**, enable Row Level Security so the public Supabase API cannot read them:

```sql
DO $$ DECLARE t record; BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
  END LOOP;
END $$;
```

Test the site afterwards to confirm everything still works.

---

## 8. Question management (CSV + Gemini)

Administrators (see `ADMIN_USERNAMES`) get **Manage Questions** (`/admin/questions`):

- **Question bank**: stored counts per category for each quiz mode.
- **Import from CSV**: validate, preview, then confirm.
- **Generate with Gemini**: generate directly into a chosen mode.
- **Browse and export**: list stored questions of one mode and download them as CSV.

### The three datasets

Every question belongs to exactly one mode. A question imported or generated for one mode never appears in another, and nothing is copied between modes automatically. A starter bank of two questions per category is seeded into each mode once. Duplicate protection is per mode **and** category.

### CSV format

The file must have exactly these eight columns, in this order, in UTF-8 (Kannada supported; in Excel use *CSV UTF-8*). Do not include `id` or `quiz_mode`.

```csv
question_text,option_a,option_b,option_c,option_d,correct_answer,explanation,category_name
"What is the capital of India?","Mumbai","New Delhi","Bengaluru","Chennai","B","New Delhi is the capital of India.","General Knowledge (GK)"
```

- `correct_answer` must be exactly `A`, `B`, `C` or `D`.
- `category_name` must be one of the 56 categories. For the Kannada category write `ಕನ್ನಡ` (the name `Kannada` is also accepted). The website itself always shows **Kannada**.
- Commas, quotes and line breaks inside quoted fields are supported.
- Kannada rows need the question, all options and the explanation in Kannada.
- A template (with an English and a Kannada example row) can be downloaded from the import card.

**Workflow:** choose the quiz mode (for Category Quiz also a category, or "use category_name from each row"), choose or drag in the file, **Validate & Preview** (valid / invalid / duplicate counts with a reason for every problem row), then **Confirm Import**. The file is validated again on the server and only valid rows are saved. Invalid rows are always reported, never silently skipped.

### Gemini generation

Requires `GEMINI_API_KEY` (the key never reaches the browser). Choose the mode, the number of questions (1 to `ADMIN_MAX_GENERATE`) and the language (Auto: Kannada for the Kannada category, English otherwise). For All Quiz and Daily Quiz the categories with the fewest stored questions are filled first. Results are reported only after the questions are saved; quota, network and invalid-response problems are handled without exposing internals. Generation is rate limited.

### Duplicate detection

Questions are normalised (case, whitespace, punctuation) and hashed for exact matches. A reworded question is also flagged when its wording is nearly identical, its numbers are the same **and** its correct answer is the same. This is a practical heuristic, not a guarantee; existing questions are never deleted or changed.

### Command line tools

```bash
flask --app run init-db                                        # create tables, seed categories and starter questions
flask --app run generate-questions --category "Python" --batches 3
flask --app run generate-questions --pool all --batches 2      # --pool category | all | daily
flask --app run import-questions --source all --rounds 5       # Open Trivia DB and The Trivia API
```

Open Trivia DB allows one request every five seconds and The Trivia API is free for non-commercial use only; both are English-only and cover only some categories.

---

## 9. Pages and statistics

| Page | What it shows |
|---|---|
| **Home** | Daily Challenge card with streaks, Play All Quiz, and personal statistics |
| **Quizzes** | The 56 categories with emoji, live search, Start / Continue / Play Again |
| **All Quiz** | Quiz 2 only: statistics, personal records, performance and progress |
| **Profile** | Account details and Category Quiz statistics (overall performance, personal records, per-category cards) |
| **History** | Saved games with search, category and date filters, 20 per page |
| **Leaderboard** | Combined ranking with period filters |
| **My Performance** | Combined statistics, a per-mode table and a last-10-games bar or pie chart |
| **Achievements & Badges** | All 43 achievements as Locked or Earned |
| **Bookmarked Questions** | Questions saved during quizzes |
| **Feedback** | Star rating and message, plus your submitted feedback |
| **Manage Questions** | Administrators only |

Statistics of different quiz modes are not mixed except where stated (Home, My Performance and the Leaderboard are combined views; Profile covers Category Quizzes; the All Quiz page covers Quiz 2).

---

## 10. HTTP routes

All state-changing requests require a CSRF token (forms) or the `X-CSRFToken` header (JSON).

**Public**

| Method | Path | Description |
|---|---|---|
| GET | `/healthz` | Health check (database reachable) |
| GET, POST | `/login`, `/register` | Authentication (rate limited) |

**Authenticated user**

| Method | Path | Description |
|---|---|---|
| GET | `/`, `/home`, `/quizzes`, `/all-quiz`, `/history`, `/leaderboard`, `/profile`, `/performance`, `/achievements`, `/bookmarks`, `/feedback` | Pages |
| POST | `/logout`, `/profile/clear-data`, `/all-quiz/clear-data` | Logout; clear your data (type `DELETE` to confirm) |
| POST | `/quiz/start/category/<id>`, `/quiz/start/all`, `/quiz/start/daily` | Start or resume a game |
| GET | `/quiz/<game_id>` | The playing page |
| GET | `/api/games/<id>/state` | Current question and counters |
| POST | `/api/games/<id>/answer`, `hint`, `next`, `previous`, `pause`, `resume`, `exit`, `finish`, `bookmark` | Gameplay actions |
| GET, POST | `/api/feedback` | List and submit your feedback |
| GET | `/api/achievements` | Your achievements |
| POST | `/api/preferences/theme` | Save dark mode |

**Administrator** (`ADMIN_USERNAMES`)

| Method | Path | Description |
|---|---|---|
| GET | `/admin/questions` | Management page |
| GET | `/api/admin/questions/counts`, `/list`, `/csv/template`, `/csv/export` | Counts, browse, template, export |
| POST | `/api/admin/questions/csv/preview`, `/csv/import` | Validate and import a CSV |
| POST | `/api/admin/questions/generate` | Generate with Gemini |
| POST | `/api/admin/generate-questions` | Token-protected variant (`Authorization: Bearer <ADMIN_API_TOKEN>`) |

---

## 11. Testing

```bash
pip install -r requirements-dev.txt
pytest
```

The suite uses SQLite by default and mocks Gemini and the question APIs, so it needs no network or API quota. It covers authentication, quiz rules, scoring and hints, progress pointers, daily limits and streaks, concurrency and duplicate requests, statistics pages, achievements, CSV import and export, Gemini generation, mode isolation and database upgrades.

**Run against PostgreSQL** (this drops and recreates the `public` schema of that database, so use a throwaway one):

```bash
TEST_DATABASE_URL=postgresql+psycopg2://user:password@localhost/quiztest pytest
```

**Browser-side checks** run the real JavaScript in a DOM and are skipped when jsdom is missing:

```bash
npm install jsdom        # in any folder
NODE_PATH=<that folder>/node_modules pytest tests/test_quiz_ui.py tests/test_question_management.py
```

---

## 12. Deployment on Render

1. Push the repository to GitHub (see below).
2. In Render choose **New + > Web Service**, connect the repository (or **New + > Blueprint** to use `render.yaml`).
3. Settings:

   | Setting | Value |
   |---|---|
   | Runtime | Python 3 (`PYTHON_VERSION` = `3.12.3`) |
   | Build command | `pip install -r requirements.txt` |
   | Start command | `gunicorn run:app --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT` |
   | Health check path | `/healthz` |

4. Add environment variables: `SECRET_KEY`, `DATABASE_URL`, `FLASK_ENV=production`, `APP_TIMEZONE`, `GEMINI_API_KEY`, `GEMINI_MODEL` and `ADMIN_USERNAMES`.
5. Deploy. All data lives in PostgreSQL, so restarts and redeployments lose nothing.

The long Gunicorn timeout allows a full Gemini request from the admin page. Each worker keeps its own in-memory rate-limit counters; set `RATELIMIT_STORAGE_URI` to Redis for shared limits.

### Updating the site

```bash
git add -A
git commit -m "Describe your change"
git push
```

Render redeploys automatically. Before pushing, run `git status` and confirm that `.env`, `.venv/` and any `*.sqlite3` file are **not** listed (they are in `.gitignore`).

### Post-deploy checklist

- `/healthz` returns `{"status": "ok"}`.
- Registration, login and a full quiz save work.
- `ADMIN_USERNAMES` is set and **Manage Questions** appears for that account.
- Row Level Security is enabled in Supabase (see [section 7](#7-database-and-migrations)).

---

## 13. Security

- Passwords are hashed (scrypt via Werkzeug); plaintext is never stored. Login errors never reveal whether an account exists.
- CSRF protection on all forms and JSON requests; the session is renewed on login; logout is POST-only.
- Session cookies are `HttpOnly`, `SameSite=Lax` and `Secure` in production.
- Login, registration, feedback and admin requests are rate limited.
- Scoring, hints, timing, progress, daily limits and achievements are decided on the server. Correct answers are never sent before a question is resolved.
- Every game and statistics query is scoped to the logged-in user.
- A strict Content Security Policy (no inline JavaScript or CSS), `X-Frame-Options`, `nosniff` and HSTS in production.
- The Gemini key and database credentials stay on the server and are never logged or returned. Provider errors are never shown to users.
- Administrator access is limited to the usernames in `ADMIN_USERNAMES`.
- Production refuses to start without `SECRET_KEY` and `DATABASE_URL`, and refuses SQLite.

**If a secret is ever exposed** (committed `.env`, shared password, pasted key), treat it as compromised: create a new Gemini key, reset the Supabase database password, generate a new `SECRET_KEY` and change affected passwords. Removing a file does not remove it from Git history.

---

## 14. Troubleshooting

| Problem | Cause and fix |
|---|---|
| `Could not parse SQLAlchemy URL` | `DATABASE_URL` still holds the placeholder or is malformed. Use a real PostgreSQL URL, or for local testing set `FLASK_ENV=development` with an empty `DATABASE_URL` |
| `SECRET_KEY environment variable is required in production` | `FLASK_ENV=production` without a key. Set `SECRET_KEY`, or use `FLASK_ENV=development` locally |
| "Request expired" after login or register | The session cookie was not stored. Locally use `python run.py` with `http://localhost:5000`, clear the site's cookies, and avoid mixing `http`/`https` or `127.0.0.1` with `localhost`. Check the terminal for the `CSRF rejected:` log line |
| **Manage Questions** missing | Open `/admin/questions`: the page states whether no administrator is configured or which account you are signed in as. Check `ADMIN_USERNAMES` matches your username, that it is in the same folder as `run.py` (`.env`) or in Render's Environment, and restart/redeploy |
| Only 2 questions per category | Only the starter bank exists. Import a CSV, set `GEMINI_API_KEY` and generate, or use the CLI tools in [section 8](#8-question-management-csv--gemini) |
| A category shows **Play Again** | Every stored question was completed. Add questions, or start over |
| Gemini errors or quota messages | Check `GEMINI_API_KEY`, the `GEMINI_MODEL` name and your free-tier limits; stored questions keep working meanwhile |
| Cannot connect to Supabase from Render | Use the pooler connection string (IPv4) and URL-encode the password |
| Render is slow on the first request | Free instances sleep when idle and start slowly |
| CSV rejected | Check the exact 8-column header, UTF-8 encoding, uppercase `A`-`D` answers and valid category names; the preview lists a reason for every row |

---

## 15. Known limitations

- Rate limits are per worker unless a shared storage (Redis) is configured.
- AI-generated questions are validated for structure, language and duplicates, **not for factual accuracy**. Review generated content before relying on it.
- The duplicate and near-duplicate checks are heuristics.
- The starter bank is small (two questions per category per mode); populate the bank for real use.
- Gemini model names and quotas change; verify them in Google AI Studio.

---

## 16. Licensing and attribution

No license file has been added to this repository yet. Add a `LICENSE` file that matches how you want the code to be used.

Optional question sources have their own terms; check them before public use:

- **Open Trivia DB**: CC BY-SA 4.0 (attribution required).
- **The Trivia API**: free for non-commercial use only.

---

*Quiz Master Game | 2026*
