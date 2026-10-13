# Deploying to Hugging Face Spaces

Reuses the exact same `Dockerfile` as the Fly.io deploy (see `DEPLOY.md`) --
Spaces' Docker SDK just runs any container that listens on the port declared in
`README.md`'s front matter. What's left needs your own Hugging Face account,
which nothing here can do for you.

## What's already done for you
- `README.md` now has the Space front matter Hugging Face requires at its top
  (`sdk: docker`, `app_port: 8080` -- matching the existing `Dockerfile`/`fly.toml`
  port, so neither needed to change).
- `Dockerfile` and `.dockerignore` are reused as-is, no changes needed.
- The app auto-ingests the corpus on first boot against an empty database, same
  as the Fly.io deploy -- no separate migration step.

## Storage note (read before you deploy)
No `DATABASE_URL` is set here, so the app falls back to its default SQLite file
*inside the container*. Spaces' free tier has no persistent disk: every restart
(sleep/wake, or a rebuild) wipes it, and the app just re-ingests the corpus from
scratch on next boot -- fine for the corpus itself, but any HITL review
decisions made against this Space won't survive a restart. If you want that to
persist, set `DATABASE_URL` as a Space secret to an external Postgres (e.g. a
free Neon or Supabase instance) the same way the Fly.io deploy uses Fly Postgres
-- optional, not required to get the app running.

## Steps you run yourself

1. **Create a Hugging Face account** (if you don't have one) at
   https://huggingface.co/join, then create an access token at
   https://huggingface.co/settings/tokens (Write role) -- you'll paste this
   into your own terminal in step 3, never into this chat.

2. **Create the Space** at https://huggingface.co/new-space:
   - SDK: **Docker**
   - Visibility: your choice (public/private)
   - Name it anything -- e.g. `industrial-safety-qa`

3. **Log in locally and add the Space as a git remote** (run from the repo
   root):
   ```
   huggingface-cli login
   git remote add space https://huggingface.co/spaces/<your-username>/<your-space-name>
   ```
   (`huggingface-cli login` prompts for the token from step 1 -- if the `.exe`
   wrapper is blocked by a security policy on your machine, same issue as
   `flyctl`/`uvicorn`, use `python -m huggingface_hub.commands.huggingface_cli login`
   instead.)

4. **Set your LLM API key as a Space secret** -- never put this in any file:
   go to your Space's page -> **Settings** -> **Variables and secrets** -> **New
   secret**, and add `MOONSHOT_API_KEY` (or `ANTHROPIC_API_KEY` if you set
   `LLM_PROVIDER=anthropic` there too as a secret/variable).

5. **Push:**
   ```
   git push space main
   ```
   First build takes a while for the same reason as the Fly.io deploy -- it
   bakes the ~440MB embedding model into the image at build time.

6. **Watch the build** on your Space's page (the "Logs" tab shows the Docker
   build and the app startup). Once it says `Application startup complete`,
   the Space is live at `https://huggingface.co/spaces/<your-username>/<your-space-name>`.

## If something's wrong
Check the Space's **Logs** tab -- it shows both the Docker build output and the
running app's stdout/stderr, same content you'd see from `flyctl logs`. The
most likely first-deploy issue is the same as Fly.io: `MOONSHOT_API_KEY` not
set as a secret before the first real question is asked -- `/api/health` will
still report healthy (it doesn't call the LLM), but `/api/ask` will fail until
the secret is set.
