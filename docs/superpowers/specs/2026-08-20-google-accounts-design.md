# Google accounts (multi-user) — design

## Context

OnTrack is currently single-user: `courses/<course_id>/*.json` is shared flat-file storage with no notion of who it belongs to, and there is no login — Django's `django.contrib.auth`/`sessions` apps are installed (for `db.sqlite3`'s built-in admin/session tables) but unused for actual sign-in.

Google Calendar sync (deferred in `CLAUDE.md`, blocked on a user-provided OAuth client) needs per-user Google OAuth consent and a stored refresh token — which only makes sense once there's an actual notion of "a user." Rather than bolt a single hardcoded OAuth token onto the existing single-user app, this design turns OnTrack into a real multi-user app: people sign in with Google, and each person's course data is scoped to them. Calendar sync itself is **not** part of this design — it's a later, separate feature that consumes the `GoogleAccount` refresh token this design stores.

## Goals

- "Sign in with Google" is the only account mechanism — no separate username/password system. One OAuth consent screen grants both identity (who is this) and Calendar access (for later use) in a single flow.
- Access is gated by an allow-list of approved emails (env-var driven, matching this project's existing `.env` config pattern) — an unapproved Google account can authenticate with Google but is rejected before an OnTrack account is created.
- Each user's course data is fully separate: `courses/<user_id>/<course_id>/...` instead of today's shared `courses/<course_id>/...`. Two different users can both have a course called `cs101` without collision.
- Existing course data (`cs101`, `psyc201`, `database-design`) is migrated, once, under your own account via an explicit one-off management command.
- Every existing HTTP view and CLI command that reads/writes course data keeps working, now scoped to a user.

## Non-goals (explicitly out of scope)

- **Calendar sync itself.** This design only gets a `GoogleAccount` row with a refresh token into the database. `calendar_sync.py` (dry-run by default, per-event confirmation, no bulk-add — per `CLAUDE.md`) is a separate future spec.
- **Self-service account management UI** (changing your email, revoking your own access, admin UI for editing the allow-list). The allow-list is a config value you edit and redeploy with, not a feature users interact with.
- **Sharing course data between users.** Each account's courses are private to that account; there is no notion of a shared/team course in this design.
- **Any non-Google sign-in method.** No password auth, no other OAuth providers.
- **Rate limiting / abuse protection on the login endpoint.** Out of scope for a personal, allow-listed tool.

## Architecture

### OAuth flow

Standard OAuth 2.0 Authorization Code flow against Google, requesting `openid email profile` plus the Calendar scope in one consent screen (not the lighter "Sign In with Google" identity-only widget, since a single flow needs to produce both identity and a Calendar refresh token):

1. `GET /accounts/login/` — builds the Google authorization URL (client ID from `.env`, same pattern as `ANTHROPIC_API_KEY`) with a random `state` value stored in the session, and redirects the browser to Google.
2. User consents on Google's own page.
3. `GET /accounts/callback/?code=...&state=...` — validates `state` against the session (CSRF protection for the OAuth flow itself), exchanges `code` for tokens via Google's token endpoint, and verifies the returned ID token to get the user's `email` and `sub` (Google's stable subject id).
4. **Allow-list check** (case-insensitive comparison against `ALLOWED_GOOGLE_EMAILS`, a comma-separated env var): if the email isn't listed, render a plain "not authorized" page and stop — no `User`/`GoogleAccount` row is created, nothing is written to disk.
5. If allowed: get-or-create a Django `User` (looked up by the `GoogleAccount.google_sub`, not by email, so a later email change on the Google side doesn't orphan the account) and its `GoogleAccount`, storing/updating `access_token`, `refresh_token` (Google only returns a refresh token on the *first* consent unless `prompt=consent` is forced — the callback always passes `access_type=offline&prompt=consent` so a refresh token is guaranteed every time), and `token_expiry`. Then `django.contrib.auth.login(request, user)` — standard Django session auth from here on, nothing custom.
6. `GET /accounts/logout/` — standard `django.contrib.auth.logout`.

### Data model

New Django model in `agent/models.py` (new file — the app currently has none, since it's had no need for one):

```python
class GoogleAccount(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    google_sub = models.CharField(max_length=255, unique=True)
    email = models.EmailField()
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField()
```

Lives in the existing `db.sqlite3` alongside the built-in auth tables — this is account/auth data, not course content, so it doesn't touch `storage.py`'s "no relational DB for course content" rule (`storage.py`'s own module docstring, unchanged by this design).

### Per-user course storage

Today, `storage._course_dir(course_id)` is the single choke point resolving `courses/<course_id>` (with a path-traversal guard on `course_id`). This design changes its signature to `_course_dir(user_id: int, course_id: str) -> Path`, resolving `courses/<user_id>/<course_id>` — `user_id` is Django's own auto-increment `User.id` (a plain integer, never user-supplied text, so it needs no separate validation regex the way `course_id` does). Every other function in `storage.py` (there are ~25: `read_syllabus`, `write_grades`, `read_notes`, etc. — see `storage.py`'s function list) gains a leading `user_id` parameter and threads it into whichever `_course_dir`/`_lecture_path`/`_reference_path` call it already makes. No other change to any function's logic.

This ripples outward:
- Every service module (`syllabus_extraction.py`, `chunk_notes.py`, `ask.py`, `quiz.py`, `mastery.py`, `reminders.py`, `grades.py`) that calls into `storage.py` gains a `user_id` parameter it just passes through.
- Every DRF/adrf view in `views.py` resolves `user_id = request.user.id` (available for free once the view requires authentication — see below) and passes it into the service call.
- Every `manage.py` CLI command (`extract_syllabus`, `chunk_notes`, `references`, `ask`, `domains`, `sessions`, `quiz`, `mastery`, `reminders`, `grades`) gains a required `--user <email>` flag; the command resolves it to a `User.id` via `GoogleAccount.objects.get(email__iexact=...)` and errors out clearly (not a stack trace) if no such account exists. CLI commands have no session, so there's no implicit "current user" to fall back to.

`reminders.py`'s "read-only deadline digest **across all courses**" (per `CLAUDE.md`) becomes "across all of the current user's courses" — it already takes no `course_id` (it scans `COURSES_DIR`), so it changes to scan `COURSES_DIR / str(user_id)` instead of `COURSES_DIR` directly.

### Access enforcement

- `agent.views.ontrack_page` (the view serving `ontrack.html`) gets `@login_required`, redirecting anonymous visits to `/accounts/login/`.
- Every DRF/adrf `APIView` in `views.py` sets `permission_classes = [IsAuthenticated]` (currently unset, i.e. open). Session auth already works for these views — the frontend already sends `X-CSRFToken` on writes (wired up during the grading-setup work), so no new frontend plumbing is needed for CSRF.
- The frontend (`ontrack.html`) gets a small header addition: "Signed in as `<email>` · Sign out" once logged in — no other UI change; an anonymous visit never reaches the SPA at all (server-side redirect, not a client-side check).

### Migration of existing data

A one-off management command, `manage.py migrate_courses_to_user --email you@gmail.com`: looks up the `User`/`GoogleAccount` for that email (must already exist, i.e. you must have logged in once first), then moves each top-level entry currently under `courses/` (`cs101/`, `psyc201/`, `database-design/`) into `courses/<user_id>/`. Refuses to run (clear error, no partial move) if `courses/<user_id>/` already has a directory with the same name as one being moved, to avoid silently clobbering data. Not run automatically on startup or on every request — an explicit, one-time step.

## Alternatives considered

- **"Sign In with Google" identity widget + a separate later "connect Calendar" step.** Rejected per your answer — you want one flow to do both jobs; a second separate consent step for Calendar is unnecessary complexity for a tool only you and a few allow-listed people use.
- **Traditional username/password accounts.** Rejected per your answer — no reason to build/maintain password storage and reset flows when every real user already has a Google account, and Calendar access requires Google OAuth regardless.
- **Flat storage with a `user_id` field inside each JSON file instead of directory nesting.** Rejected — would force `course_id` to be globally unique across every user (two people both wanting `cs101` would collide), which is an artificial constraint the directory-nesting approach avoids entirely.
- **A database table indexing course_id → folder path, decoupled from the directory layout.** Rejected — introduces a second source of truth that can drift from what's actually on disk (a DB row pointing at a deleted folder, or a folder with no DB row), contradicting `storage.py`'s existing "flat files are the source of truth" design.
- **Open sign-up (any Google account).** Rejected per your answer — this is a personal/small-group tool; an allow-list avoids strangers creating accounts and course data on your instance.
- **Automatic/implicit data migration on first login instead of an explicit command.** Rejected — moving directories is a one-time, slightly destructive-if-wrong operation; an explicit command you run once (and that refuses to run twice into a collision) is safer than logic that fires as a side effect of logging in.

## Edge cases

- **A Google account not on the allow-list tries to sign in.** Google's own consent screen still shows (OnTrack has no way to prevent that — the allow-list check happens after Google redirects back), but the callback rejects it before creating any `User`/`GoogleAccount` row or touching `courses/`. Clear "not authorized" page, not a generic error.
- **Same person's Google email changes** (rare, but Google allows it on Workspace accounts). Lookup is by `google_sub` (Google's stable subject id), not email, so this doesn't orphan the account; `GoogleAccount.email` is updated to the new value on next login for display purposes only.
- **Google doesn't return a refresh token** (happens if the app already has one and `prompt=consent` isn't forced). Avoided by always passing `prompt=consent` on the authorization request — costs the user one extra click reconfirming consent on every login, which is an acceptable tradeoff for guaranteeing a refresh token is always available.
- **A CLI command is run with `--user` set to an email with no matching `GoogleAccount`.** Errors out immediately with a clear message ("no account found for <email> — that person must sign in via the web UI at least once first"), not a stack trace or a silently-created directory.
- **`manage.py migrate_courses_to_user` run twice, or targeting a user who already has a `courses/<user_id>/cs101` directory.** Refuses to run for that course, reporting exactly which directory already exists — never silently overwrites.
- **An authenticated user's session expires mid-use.** Standard Django session behavior: the next API call 401s (page-serving view redirects to login on next full page load); no special handling needed beyond what `IsAuthenticated` already provides.

## Testing

- `GoogleAccount` model: basic field/constraint tests (`google_sub` uniqueness).
- Allow-list matching: case-insensitivity, exact-match rejection of unlisted emails — pure function, easy to unit test without hitting Google.
- OAuth callback view: Google's token-verification call is mocked (this project's existing convention for anything hitting a live third-party API without a key — same pattern as syllabus extraction's live-API tests skipping cleanly without `ANTHROPIC_API_KEY`). Tests cover: allowed email creates account + logs in; disallowed email is rejected and creates nothing; a second login for an existing `google_sub` updates tokens rather than creating a duplicate account.
- `@login_required`/`IsAuthenticated` gating: anonymous request to `ontrack_page` redirects; anonymous request to any API view 401s.
- `storage.py`'s existing test suite (`agent/tests/test_storage_*.py`) grows a `user_id` argument across its existing calls — mechanical but touches every test in that suite. New tests confirm two different `user_id`s can each have a course named `cs101` without collision, and that `_course_dir` still rejects path-traversal attempts in `course_id` (existing guard, unchanged, just re-verified with the new signature).
- No automated test for the live Google consent screen — same manual-verification convention as syllabus extraction. Requires you to create a real Google Cloud OAuth 2.0 Client (Web application type) and put its client ID/secret in `.env` before that manual pass is possible; this is a prerequisite you handle outside this codebase, same as `ANTHROPIC_API_KEY` today.
- Manual verification: full login → allow-list-reject-a-second-email → logout cycle against the real Google consent screen; confirm `courses/<user_id>/` is what gets read/written for every page in the app after login.
