# Deploying PocketIQ to PythonAnywhere

Replace `YOURUSERNAME` throughout with your PythonAnywhere username.

---

## 1. Push the code

From your machine:

    git add -A
    git commit -m "Your message"
    git push origin main

`.env` and `flask_session/` are gitignored, so no secrets or runtime data go to GitHub.

## 2. Clone on the server

Open a **Bash console** on PythonAnywhere:

    git clone https://github.com/kalashbanthia092-coder/pocketiq-website.git

## 3. Virtualenv and dependencies

Pick Python 3.11 or 3.13. (3.14 is not offered there.)

    mkvirtualenv pocketiq --python=/usr/bin/python3.13
    pip install -r ~/pocketiq-website/requirements.txt

`gunicorn` installs but is unused here; PythonAnywhere uses WSGI, not the Procfile.

## 4. Create the web app

Web tab -> **Add a new web app**:

- **Manual configuration** (NOT the Flask option, which scaffolds a competing app)
- Python **3.13**
- Virtualenv field: `/home/YOURUSERNAME/.virtualenvs/pocketiq`

## 5. Secrets

`.env` is not in the repo. Create `/home/YOURUSERNAME/pocketiq-website/.env`
via the Files tab, using `.env.example` as the guide:

    OPENAI_KEY=sk-...
    SERPAPI_API_KEY=...
    FLASK_SECRET_KEY=<long random string>
    FLASK_ENV=production

Generate a secret key with:

    python -c "import secrets; print(secrets.token_urlsafe(48))"

Do **not** set `FLASK_DEBUG=true` in production.

## 6. WSGI file

Open the WSGI file linked on the Web tab, delete its contents, and paste the
body of `pythonanywhere_wsgi.py` from this repo (replacing `YOURUSERNAME`).

## 7. Static files

Web tab -> **Static files**:

| URL        | Directory                                        |
|------------|--------------------------------------------------|
| `/static/` | `/home/YOURUSERNAME/pocketiq-website/static/`     |

## 8. Reload

Hit the green **Reload** button, then open `https://YOURUSERNAME.pythonanywhere.com`.
Tracebacks go to the **Error log** linked on the Web tab.

---

## Updating after the first deploy

In a Bash console:

    cd ~/pocketiq-website && git pull

Then hit **Reload** on the Web tab. Reload is required; a pull alone changes nothing.

---

## Known constraints

**Free tier blocks the AI features.** PythonAnywhere free accounts reach the
internet only through a proxy allowlist that does not include OpenAI or SerpAPI.
The site still loads and every page renders, because the app has fallbacks
everywhere, but:

- roadmaps fall back to 5 generic steps
- articles fall back to a template
- the Decision coach returns its canned message
- Compare reports prices unavailable

The paid Hacker plan (~$5/month) removes the restriction. Budget for it if you
are demoing the AI features.

**Sessions are stored on disk** in `flask_session/`, created automatically next
to `backend.py`. It must stay writable. Do not commit it. If you ever move to
multiple workers or servers, switch `SESSION_TYPE` to Redis so sessions are
shared rather than per-process.
