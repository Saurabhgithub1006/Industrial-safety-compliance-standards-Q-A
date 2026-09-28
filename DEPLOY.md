# Deploying the web app

The backend (FastAPI + PostgreSQL) is built and tested locally against SQLite —
see `backend/` and `tests/test_backend.py`. Everything up to this point is done.
What's left needs your own Fly.io account, which nothing here can do for you.

## What's already done for you
- `flyctl` is installed (`C:\Users\<you>\.fly\bin\flyctl.exe` — add that folder
  to your `PATH`, or use the full path, or just open a new terminal since the
  installer already tried to add it).
- `Dockerfile`, `.dockerignore`, and `fly.toml` are ready to deploy as-is.
- The app auto-ingests the corpus into whatever `DATABASE_URL` it's given on
  first boot against an empty database — no separate migration step needed.

## Steps you run yourself

1. **Log in** (opens a browser):
   ```
   flyctl auth login
   ```

2. **Create the app** (from the repo root — `fly.toml` already exists, so this
   attaches to it rather than generating a new one):
   ```
   flyctl launch --no-deploy
   ```
   It'll ask to confirm the app name (`industrial-safety-qa` in `fly.toml` —
   change that file first if it's taken) and region. Say no to adding a
   database here; we'll create one explicitly next so it's a real Postgres
   instance, not whatever default it proposes.

3. **Create PostgreSQL and attach it** (this is the part that sets `DATABASE_URL`
   automatically as an app secret — you never type a connection string
   yourself):
   ```
   flyctl postgres create --name industrial-safety-qa-db
   flyctl postgres attach industrial-safety-qa-db --app industrial-safety-qa
   ```

4. **Set your LLM API key as a secret** — never put this in any file:
   ```
   flyctl secrets set MOONSHOT_API_KEY=your-key-here --app industrial-safety-qa
   ```
   (or `ANTHROPIC_API_KEY=...` if you switch `LLM_PROVIDER` in `fly.toml` to
   `anthropic`.)

5. **Deploy:**
   ```
   flyctl deploy
   ```
   First build takes a while — it bakes the ~440MB embedding model into the
   image so the running app never needs to download it. Subsequent deploys
   reuse Docker's layer cache and are much faster unless `pyproject.toml`
   changes.

6. **Check it's alive:**
   ```
   flyctl status
   curl https://industrial-safety-qa.fly.dev/api/health
   ```
   Should return `{"status":"ok","corpus_loaded":true,"clause_count":135}`.

7. Open `https://industrial-safety-qa.fly.dev/` in a browser — that's the app.

## If something's wrong
```
flyctl logs
```
The most likely first-deploy issue is `MOONSHOT_API_KEY` not being set before
the first real question is asked — `/api/health` will still report healthy
(it doesn't call the LLM), but `/api/ask` will fail until the secret is set.

## Cost note
`fly.toml` sets `min_machines_running = 0` — the app scales to zero when idle,
which keeps this free on Fly's allowance but means the first request after a
quiet period pays a cold-start cost (the model still needs loading into memory,
just not re-downloading, since it's baked into the image). Change that to `1`
in `fly.toml` and redeploy if you'd rather keep it always-warm.
