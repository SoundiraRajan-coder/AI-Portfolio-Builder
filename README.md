# AI-Powered Portfolio Generator

Initial project foundation for a Flask-based portfolio generator. This stage includes the application shell, landing page, and normalized PostgreSQL schema.

## Stack

- Backend: Python Flask
- Frontend: HTML, CSS, and JavaScript
- Planned database: PostgreSQL on Supabase
- Planned authentication: Google OAuth 2.0
- Planned AI integration: Google Gemini API

## Local setup

### 1. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run this once for the current user or activate the environment from another shell:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 2. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Create local environment settings

```powershell
Copy-Item .env.example .env
```

Keep real credentials in `.env`. It is excluded from Git by `.gitignore`.

### 4. Run the application

```powershell
python run.py
```

Open `http://127.0.0.1:5000` in a browser.

## Supabase database connection

Configure these variables in `.env`:

```env
SECRET_KEY=your-local-flask-secret
SUPABASE_DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@YOUR_HOST:5432/postgres?sslmode=require
```

`SUPABASE_DATABASE_URL` is the PostgreSQL connection string from the Supabase dashboard. Use the Supabase pooler connection string when the dashboard recommends it for your environment. Keep the password in `.env`; never place this value in templates, JavaScript, or committed files. `DATABASE_URL` is also accepted as a fallback for deployment platforms, but `SUPABASE_DATABASE_URL` is the documented local variable.

### Profile image storage

Profile images are stored in Supabase Storage. Configure these server-only environment variables locally and in Vercel:

```bash
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SUPABASE_SERVICE_ROLE_KEY
SUPABASE_STORAGE_BUCKET=portfolio-images
```

Create the configured bucket as a public bucket so portfolio visitors and standalone ZIP exports can retrieve uploaded profile images. Do not expose the service role key in browser code or commit it to Git.

Install the PostgreSQL driver after updating the project:

```powershell
pip install -r requirements.txt
```

With `FLASK_ENV=development`, start Flask and open this URL:

```text
http://127.0.0.1:5000/dev/database-health
```

A successful connection returns JSON with `"status": "ok"`. Missing or invalid configuration returns a generic `503` response and logs the technical error on the server. The endpoint is disabled with a `404` response when Flask is not running in development mode.

## Google OAuth setup

1. In Google Cloud Console, create or select a project.
2. Configure the OAuth consent screen. For local development, `External` is appropriate; add your Google account as a test user if the app is still in testing mode.
3. Create an OAuth client under **APIs & Services > Credentials** and choose **Web application**.
4. Add this exact authorized redirect URI:

```text
http://127.0.0.1:5000/auth/callback
```

5. Copy the generated client ID and client secret into `.env`:

```env
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
```

The application requests the OpenID, email, and profile scopes. It stores the Google subject ID, email, display name, profile image URL, and timestamps in PostgreSQL. It does not store Google passwords or OAuth access/refresh tokens.

Start the app with `python run.py`, visit `http://127.0.0.1:5000/auth/login`, and choose **Continue with Google**. After a successful first login, the local user is created and you are redirected to `/dashboard`; later logins update the existing user. Use `/auth/logout` to clear the local session.

## Database schema

The initial migration is in [`migrations/001_initial_schema.sql`](migrations/001_initial_schema.sql). Apply it through the Supabase project SQL Editor, followed by [`migrations/002_add_profile_phone.sql`](migrations/002_add_profile_phone.sql).

The Flask application connects to PostgreSQL through `SUPABASE_DATABASE_URL`; no database credentials belong in the migration file.

## Current scope

Authenticated users can manage reusable profile information at `http://127.0.0.1:5000/profile`, including profile details, social links, skills, education, work experience, projects, and certifications. Every read, update, and delete operation is scoped to the signed-in user ID.

## Dashboard and portfolio history

The authenticated dashboard is available at `http://127.0.0.1:5000/dashboard`. It shows portfolio statistics and user-scoped portfolio cards. Portfolio management routes include `/portfolios/new`, `/<portfolio_id>/edit`, `/<portfolio_id>/preview`, `/<portfolio_id>/duplicate`, and `/<portfolio_id>/delete`.

The portfolio builder is available at `/portfolios/<portfolio_id>/builder`. It keeps reusable profile records separate from portfolio metadata, supports portfolio-specific content overrides, section visibility and ordering, selected profile records, and a live preview state that future templates can consume.

The builder preview is served through `POST /portfolios/<portfolio_id>/preview/live` inside a sandboxed iframe. It renders unsaved builder state without persisting it, supports desktop/tablet/mobile sizes, and uses a no-script Content Security Policy. The saved full preview remains available at `GET /portfolios/<portfolio_id>/preview`.

## Gemini AI content generation

Configure Gemini only in `.env`:

```env
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-2.0-flash
```

The builder Content Assistant sends task-specific input to `POST /portfolios/<portfolio_id>/ai/generate`. The backend validates ownership and input, builds the task prompt in [`app/services/gemini_service.py`](app/services/gemini_service.py), requests structured JSON from Gemini, and returns a draft. The API key never reaches the browser.

Generated text is shown for review. `Use Generated Content` calls `POST /portfolios/<portfolio_id>/ai/accept`, which stores an audit row in `portfolio_ai_content` and a portfolio-scoped `ai_overrides` value. `Discard` makes no database change. Rate limits return `429`; missing configuration returns `503`; malformed provider responses and provider failures return safe `502` messages. Gemini cannot execute code or modify the database directly.

The AI Design Studio is available at `http://127.0.0.1:5000/ai-design`. Its Gemini request is restricted to a controlled design specification with allowlisted values for theme, layout, navigation, hero, project layout, experience layout, skills, palette, typography, animation, and card style. The original prompt and validated specification are stored in `portfolio_design_specs`; generated code, CSS, and JavaScript are never accepted or executed.

## AI-generated portfolios

The application uses a single AI-first builder flow: the wizard supplies the facts and design direction, Gemini returns a structured content-and-design specification, and the application safely renders the result on the separate preview page.

Gemini integration, AI custom design generation, and ZIP export remain deferred to later stages.
