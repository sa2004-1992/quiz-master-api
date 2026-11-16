# Quiz Master

Flask + Supabase PostgreSQL + Google Gemini quiz site with three independent quiz types
(Category quizzes, All Quiz, Daily Challenge), server-side scoring, hints, timers, history,
leaderboard, profile, achievements, bookmarks and feedback.

> **Provenance note:** no existing project files were available when this was built (the upload
> folder was empty), so this is a fresh implementation. Nothing from an earlier site was preserved;
> to keep your old look, port your CSS into `app/static/css/style.css` (all colours are CSS variables).

## Project layout

```
run.py                      Gunicorn/Flask entry point (variable `app`)
config.py                   Environment-driven configuration + production fail-fast checks
render.yaml                 Optional Render blueprint
migrations/                 001_initial_schema.sql (generated for PostgreSQL) + generator script
app/__init__.py             Application factory, CSRF, rate limiting, security headers, CLI
app/models.py, database.py  SQLAlchemy models / engine & session handling
app/categories.py           The 56 categories in the required order
app/auth/                   Register, login, logout, validation, login_required
app/routes/                 pages.py (HTML pages), quiz.py (start + gameplay API), admin.py
app/services/               ai_question_generator, question_validator, quiz_engine, scoring,
                            progress, daily_streak, reports, user_data, seed
app/data/seed_questions.py  Starter bank: 2 real questions per category (Kannada in Kannada)
app/templates, app/static   Jinja templates, CSS, JS (no inline scripts/styles; strict CSP)
tests/                      70 automated tests (Gemini always mocked)
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env             # Windows: copy .env.example .env   (never commit .env)
python run.py                    # http://localhost:5000
```

Edit `.env` first. Quickest local test (no Supabase yet): set `FLASK_ENV=development` and leave
`DATABASE_URL=` empty to use a local SQLite file. Lines still starting with `replace_with` are
treated as unset. For real use set `DATABASE_URL` to your Supabase connection string.

With no `GEMINI_API_KEY` the site starts normally and plays the stored/seeded questions;
a warning is logged. With no `DATABASE_URL` it uses a local SQLite file **in development only**;
in production the app refuses to start without PostgreSQL.

> `python run.py` always serves plain HTTP for local testing, so session cookies are not marked Secure
> there. Under Gunicorn/HTTPS (Render) they are Secure. Override with `SESSION_COOKIE_SECURE=true|false`.

## 1. Supabase PostgreSQL

1. Create a project at supabase.com and wait for it to provision.
2. Open **Connect** in the dashboard and copy a **pooler** connection string
   (Render's free tier is IPv4-only; Supabase's direct connection host may be IPv6-only, so
   use the Session pooler (port 5432) or Transaction pooler (port 6543) string - check the
   dashboard for the current wording).
3. Put it in `DATABASE_URL`. `postgres://` and `postgresql://` prefixes are converted
   automatically and `sslmode=require` is added for non-local hosts. URL-encode special characters
   in the password.
4. Create tables - either let the app do it (tables are created on startup if missing; nothing
   is ever dropped) or paste `migrations/001_initial_schema.sql` into the Supabase SQL editor.
   Run `flask --app run init-db` to create tables and seed categories + starter questions.
5. Schema changes later: add a new numbered SQL file under `migrations/` with additive
   `ALTER TABLE ... ADD COLUMN` statements. Never drop production tables.

## 2. Gemini API key

1. Go to https://aistudio.google.com/apikey, sign in, **Create API key**.
2. Set `GEMINI_API_KEY` (server-side only; it is never sent to the browser or logged).
3. Set `GEMINI_MODEL`. The default is `gemini-3.1-flash-lite`, which Google's model documentation
   listed as stable and free-tier eligible when this was written. Model availability changes
   (the Gemini 2.5 family was reported as scheduled for retirement in October 2026), so check
   https://ai.google.dev/gemini-api/docs/models and your AI Studio rate-limit page, and change
   the variable if needed - no code change is required.
4. Note: on the free tier Google may use prompts/responses to improve its products. The prompts
   here contain only category names and recent question texts - no user data.

Pre-generate questions (recommended; first-time play otherwise only has the 2-per-category seed):

```bash
flask --app run generate-questions --category "Python" --batches 3
flask --app run generate-questions --batches 2            # all 56 categories (watch the free-tier quota)
flask --app run generate-questions --pool all --batches 3        # All Quiz dataset
flask --app run generate-questions --pool daily --batches 5      # Daily Quiz dataset
```

Import ready-made questions (free, no API key; stored in the same table and reused):

```bash
flask --app run import-questions --source all --rounds 5
flask --app run import-questions --source opentdb --pool all --rounds 3     # --pool category | all | daily
```
Open Trivia DB allows 50 questions per request and one request every 5 seconds, so imports are slow
by design. Each run returns a random sample, so repeat it with `--rounds`; duplicates are skipped.
These sources are English-only, cover only some categories (see `OPENTDB_MAP` / `TRIVIA_API_MAP` in
`app/services/question_sources.py`), and give no explanations (a short "The correct answer is ..." is stored).
Licensing: Open Trivia DB is CC BY-SA 4.0 (attribution is required if you use these questions publicly; the footer no longer shows it); The Trivia API is free
for non-commercial use only. Check both providers' current terms before launching publicly.

Optional HTTP trigger: set `ADMIN_API_TOKEN`, then
`POST /api/admin/generate-questions` with `Authorization: Bearer <token>` and JSON
`{"category": "Python", "pool": "category"}`.

## 3. Deploy on Render

1. Push to GitHub (see below). In Render: **New + > Web Service**, connect the repo
   (or **New + > Blueprint** to use `render.yaml`).
2. Runtime **Python 3**, Build command: `pip install -r requirements.txt`
3. Start command: `gunicorn run:app --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT`
   (`run.py` exposes `app`; the long timeout allows a Gemini batch during a request.)
4. Health check path: `/healthz`
5. Environment variables: `SECRET_KEY` (long random string), `DATABASE_URL`, `GEMINI_API_KEY`,
   `GEMINI_MODEL`, `APP_TIMEZONE` (e.g. `Asia/Kolkata`), `FLASK_ENV=production`,
   optional `ADMIN_API_TOKEN`, `PYTHON_VERSION=3.12.3`.
6. Deploy. All data lives in Supabase, so restarts and redeployments lose nothing.

Generate a secret key: `python -c "import secrets; print(secrets.token_hex(32))"`

## 4. GitHub

```bash
git init && git add . && git commit -m "Quiz Master"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```
Later updates: `git add -A && git commit -m "..." && git push` - Render auto-deploys.
`.env` is git-ignored; verify with `git status` before pushing.

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                   # SQLite, ~35 s
TEST_DATABASE_URL=postgresql+psycopg2://user:pw@localhost/quiztest pytest   # real PostgreSQL
```
Optional browser-side tests (they run the real `quiz.js` in a DOM and are skipped if jsdom is missing):
`npm install jsdom` in any folder, then `NODE_PATH=<that folder>/node_modules pytest tests/test_quiz_ui.py`.

(The Postgres run drops and recreates the `public` schema of that database - use a throwaway DB.)

## Rules as implemented

* **Scoring:** +10 correct, -5 incorrect, hint 0. The running score never goes below 0
  (floor applied after each answer). Calculated only on the server from stored answers.
* **Hints:** 10 per Category/All game, 5 per Daily; stored in the database and checked on the server.
  A hint reveals the answer, resolves the question, never scores.
* **Timer:** server timestamps; paused time excluded; clients never send elapsed time.
* **Quiz Type 1:** pointer per user + category into the category's questions ordered by id; a game has
  `QUESTIONS_PER_GAME` (10) questions; the pointer advances by the number resolved on Finish & Save only, so the next
  Start loads the next unseen questions and never repeats completed ones. Near the end of the stored list the app asks
  Gemini for more. When every stored question is completed, Start is refused with a message and the card shows
  **Play Again**, an explicit restart from the beginning (saved history is kept). Exiting without saving changes nothing.
* **Quiz Type 2:** one counter per user. Position *g* -> category `g mod 56` (required order), round
  `g div 56`, question `round mod n`. One game = `ALL_QUIZ_QUESTIONS` (56) positions, i.e. one question
  per category. Categories with no stored questions are skipped.
* **Quiz Type 3:** a shared question set per calendar day (from a separate `daily` question pool,
  excluding Kannada), up to 50 questions. `UNIQUE(user_id, quiz_date)` allows one record per day; a
  completed day cannot be restarted. The challenge counts as *completed* only when every question is
  resolved and Finish & Save is pressed. Exit discards it (no streak change) and may be restarted the same day.
  Day boundaries and streaks use `APP_TIMEZONE`.
* **Streak:** consecutive days +1; a missed day resets to 1 on the next completion; longest is kept
  until Clear All Data. The Home page shows 0 if the streak has already lapsed.
* **Leaderboard:** ONE combined, user-wise ranking over saved games of all three modes (Category, All Quiz, Daily);
  each saved game is one row in `quiz_games`, so it is counted once. Columns: total score, total questions played
  (correct + wrong; hints excluded), total games, total time (pauses excluded). Order: total score desc, total correct
  answers desc, total questions played desc, total time asc, then username - so ranks are unique. Ranges (All Time /
  This Month / This Week (Monday start) / Today) use `APP_TIMEZONE`. Only usernames are exposed. 20 players per page.
* **History columns:** *Game* = Category Quiz / All Quiz / Daily Quiz; *Category Name* = the category
  name, or All Quiz / Daily Quiz.
* **Clear All Data** (type DELETE to confirm): removes the user's games, answers, pointers, daily
  records, streak and bookmarks; keeps the account, preferences, questions and everyone else's data.
  Because daily records are removed, today's Daily Challenge can be played again afterwards.

## Question management (CSV import + Gemini) - three separate datasets

Every question belongs to exactly **one quiz mode**, stored in `questions.pool` (also exposed as `Question.quiz_mode`):
`category` = Quiz 1 (Category Quizzes), `all` = Quiz 2 (All Quiz), `daily` = Quiz 3 (Daily Quiz). Each quiz reads only its
own mode, so a question imported or generated for one mode never appears in another (nothing is copied automatically; the
built-in 2-per-category starter bank is seeded once into each mode). Duplicates are prevented **per mode and category**.
The category is stored as `category_id` (a foreign key to `categories`); the CSV and the admin page use `category_name`.

**Who can manage questions:** set `ADMIN_USERNAMES` (comma-separated usernames, e.g. `ADMIN_USERNAMES=sagar123`). Those users
see **Manage Questions** in the sidebar (nobody else does) at `/admin/questions`. With the variable unset the tools are off.

**Kannada in datasets:** the website always calls the category **Kannada** (same id, slug and relationships - nothing
changes on any page). Only *datasets* use the Kannada-script name `ಕನ್ನಡ` in the `category_name` column: CSV upload and
preview, the downloaded template, the CSV export (admin page: *Export CSV* in "Browse stored questions", or the
download link after a Gemini run) and Gemini-generated datasets. Uploads still accept the old name `Kannada`; both map
to the one existing category, and no second category is created.

**CSV import** (works without Gemini). Header must be exactly `question_text,option_a,option_b,option_c,option_d,correct_answer,explanation,category_name`
(UTF-8, Kannada supported; no `id`, no `quiz_mode`; `correct_answer` is exactly A-D; `category_name` is one of the 56
categories). On the page: 1) pick the **quiz mode**; for *Category Quiz* also pick a category (or "Use category_name from each
row" - a chosen category must match every row); *All Quiz* and *Daily Quiz* use each row's `category_name`; 2) choose or
drag in the file; 3) **Validate & Preview** (valid / invalid / duplicate counts, per-row reasons - nothing is saved yet);
4) **Confirm Import** - the file is validated again on the server and only valid rows are saved. Limits: `CSV_MAX_BYTES`
(2 MB) and `CSV_MAX_ROWS` (2000). Daily Quiz imports go into the unused Daily pool and follow the existing scheduler
(max 50 per day); they never change a daily set that was already created.

**Gemini generation** (needs `GEMINI_API_KEY`, `GEMINI_MODEL`; the key stays on the server). Pick the mode (category for
Category Quiz), the number of questions (1-`ADMIN_MAX_GENERATE`, default 30; 10 per Gemini call) and the language
(Auto: Kannada for the Kannada category, English otherwise). *All Quiz* / *Daily Quiz* generation fills the categories that
have the fewest stored questions first (Daily excludes Kannada unless you pick Kannada). Kannada questions need the
question, all four options and the explanation in Kannada. Results are shown only after the questions are saved; quota,
network and invalid-response problems are reported without internal details. Generation is rate limited
(`ADMIN_GENERATE_RATE_LIMIT`, default 6 per minute). Gunicorn's `--timeout 120` covers a full 30-question request.

**Duplicates:** text is normalised (case, spaces, punctuation) and hashed for exact matches; a reworded question is flagged
when its wording is nearly identical, its numbers are the same **and** its correct answer is the same. It is a heuristic,
not a guarantee, and existing questions are never deleted or changed.

**Upgrading an existing database** is automatic and non-destructive (`migrations/004_question_modes.sql` has the same SQL
for PostgreSQL): the `questions` constraints are extended to allow the `all` mode and to detect duplicates per mode +
category; no rows, ids, games, answers, progress pointers or daily assignments change. On SQLite (local development) the
table is rebuilt with all rows and ids copied. **Note:** All Quiz now reads its *own* dataset, so on an existing site it starts with the 2-per-category
starter bank until you import or generate All Quiz questions (category questions are intentionally not copied).

**Testing the three datasets:** the admin page shows stored counts per mode and category, and *Browse stored questions*
lists one mode (and category) at a time. `pytest tests/test_question_management.py` covers CSV (all three modes, validation,
Kannada, duplicates), mocked Gemini (all three modes, failures, quota), isolation and the database upgrade.

## Quiz mode separation (statistics)

* **All Quiz page** = Quiz 2 only: games with `quiz_type = 'all'` (the play-all mode), completed, for the logged-in user.
  Its Clear All Data deletes only those games, their answers and the Play All progress pointer.
* **Profile page** = Quiz 1 (Category Quizzes) only. Daily Quiz data is stored and drives the Daily card/streak on Home,
  but is not mixed into Profile or All Quiz statistics. Home and My Performance still show per-user summaries.
* Each saved game stores user, mode, answered/correct/wrong counts, score, active playing time (pauses excluded)
  and completion time in `quiz_games` (no duplicate tables). Older databases are upgraded automatically at
  startup (`answered_count`, `wrong_count` added and backfilled; see `migrations/002_add_game_answer_counts.sql`).

## My Performance

Combined stats (games, score, best game, fastest game time, accuracy = correct / answered) come from the user's
saved games of all three modes; the *By Quiz Type* table keeps Category Quizzes, All Quiz and Daily Quiz separate.
The *Last 10 Game Scores* charts are drawn client-side as plain SVG (`app/static/js/performance.js`, no library) and
nothing is rendered until Bar or Pie is chosen. The chart data is the user's latest 10 saved games, oldest first.

## Achievements & Badges

43 achievements (`app/services/achievements.py`, exact names/requirements/order) are evaluated on the server from the
user's saved games across all three modes, right after each game is saved and again when the page is opened (so older
history is picked up). Awards live in `user_achievements` (unique per user + achievement, with the earned date) and are
never revoked - not even by Clear All Data. Rules: correct-answer streaks run across modes in saved-game order, a wrong
answer resets them and a hint-revealed question neither extends nor resets; "different categories" counts the categories
of questions the user answered; Perfect Round needs 5+ answered questions and no wrong answer in one saved game;
daily streaks count consecutive Asia/Kolkata calendar days.
The 12 newer ones: Hint-Free Hero (5 saved games with 0 hints), Speed Solver (a saved game under 120 s),
Accuracy Expert (>= 90% in one game with >= 20 answered questions), No Mistakes (>= 20 answered, 0 wrong),
Marathon Player (>= 100 answered in one game), Knowledge Collector (1,000 answered overall), Perfect Ten (10 correct in a
row inside one game), Hint Saver (10 saved games with <= 1 hint), Category Expert (100 correct answers in one category,
across modes), Daily Perfectionist (a saved Daily Challenge with no wrong answer), Comeback Champion (>= 5 correct
answers after a wrong answer in the same game), Quiz Marathon (10 saved games on one Asia/Kolkata day).
"Questions" in these rules means answered questions (hint-revealed ones are not answers). A failure while awarding never blocks saving a game.

## Feedback

`/feedback`: required 1-5 star rating and message (validated on the server; whitespace-only is rejected). The page sends
`POST /api/feedback` and re-renders *My Submitted Feedback* from the response without a reload; without JavaScript the
plain form still works. Rows are stored in `feedback` (user id, rating, message, created time) and listed newest first,
only for the logged-in user, in the app timezone.

## Security

Hashed passwords (scrypt via Werkzeug), CSRF on all forms and JSON requests, session renewal on login,
HttpOnly/SameSite/Secure cookies in production, POST-only logout, login/register/feedback rate limits,
generic login errors, ownership checks on every game/history query, strict CSP (no inline JS/CSS),
HSTS in production, no stack traces or provider errors in responses, correct answers never sent
before a question is resolved.

## Known limitations

* **Not verified live:** real Gemini calls, a real Supabase project and a Render deployment were not
  available here. Gemini is exercised only through mocks; PostgreSQL was verified on a local PostgreSQL 16.
* The browser UI (JavaScript) was syntax-checked and its server API fully tested, but it was not run
  in a real browser.
* Rate limits use in-memory storage per Gunicorn worker. For strict global limits set
  `RATELIMIT_STORAGE_URI` to a Redis URL.
* The seed bank has only 2 questions per category. Pre-generate questions as shown above. On days when
  fewer than 50 unused daily questions exist, the first Daily start may call Gemini (slow) or reuse
  the least recently used questions.
* AI facts cannot be verified automatically; validation checks structure, duplicates, language and
  rejects time-sensitive wording, not truthfulness. Review generated questions for critical use.
* Gemini model names/quotas change; see section 2.
