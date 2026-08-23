# Branded Login/Signup Page — Design

## Problem

`google_login` (`/accounts/login/`) currently redirects straight to Google's
consent screen with zero rendered page — there is no branded landing spot.
When a signed-in Google account isn't on `ALLOWED_GOOGLE_EMAILS`,
`google_callback` renders `agent/templates/agent/not_authorized.html`, a
plain unstyled page with no path back into the app.

OnTrack has no traditional signup form — an account is created automatically
on first successful, allow-listed Google sign-in (Task 1–3 of the Google
accounts plan). "Login" and "signup" are therefore the same user action.

## Decisions

- **One shared page**, not two. `/accounts/login/` serves both new and
  returning users — same headline works for either ("Welcome to OnTrack" +
  "Sign in with your Google account to get started.").
- **Rejected sign-in redirects back to this same page**, with an inline
  message via Django's messages framework (already installed:
  `django.contrib.messages` in `INSTALLED_APPS`, middleware active) — not a
  separate "not authorized" page. `not_authorized.html` is removed.
- **Splitting the current `google_login` view in two**, since it currently
  conflates "show the page" with "start the OAuth redirect":
  - `google_login_page` — `GET /accounts/login/` (URL name `google-login`,
    unchanged — this is what `LOGIN_URL` and `@login_required` already
    point at). Renders `agent/templates/agent/login.html`. If the visitor
    is already authenticated, redirects straight to `ontrack` instead of
    showing the page.
  - `google_login_start` — `GET /accounts/login/start/` (new URL name
    `google-login-start`). Contains the OAuth-redirect logic
    `google_login` has today: `build_flow`, `authorization_url`, save
    state, redirect to Google. The page's "Sign in with Google" button
    links here.
- **Visual design**: matches the "Organic" design system used by
  `ontrack.html` (same `styles.css` tokens: Caprasimo/Figtree fonts,
  cream/terracotta/olive palette, pill buttons, rounded cards). Centered
  card on the page background, the real OnTrack app-icon mark
  (`agent/static/agent/images/ontrack-trans.png`) above it, headline,
  subtext, an optional error banner (styled like the existing dashboard
  error cards — `--color-accent-100` background), a full-width white
  "Sign in with Google" button carrying Google's official multicolor "G"
  mark (kept undisguised, deliberately outside the terracotta palette, for
  OAuth trust/recognizability), and a small footnote ("Only approved
  accounts can sign in.").
- **Asset fix**: `agent/static/agent/images/ontrack-trans.png` had no alpha
  channel — its "transparent" background was a checkerboard baked into
  actual RGB pixels. Regenerated with a real alpha channel (chroma-keyed
  the neutral-gray checkerboard out; every real design color — cream,
  terracotta, dark brown, olive — has enough color-channel spread to
  survive the keying untouched).

## Non-goals

- No separate signup form, no separate `/accounts/signup/` route.
- No change to the OAuth flow itself, the allow-list check, or
  `google_callback`'s token/claims handling — only its rejection branch's
  response changes (redirect + message, instead of rendering a template
  directly).
- No change to `google_logout` or the authenticated app (`ontrack.html`).

## Testing

- `GET /accounts/login/` → 200, page renders with the Google button pointing
  at `/accounts/login/start/`.
- `GET /accounts/login/` while already authenticated → redirects to `ontrack`.
- `GET /accounts/login/start/` → existing redirect-to-Google behavior,
  unchanged, just moved (was previously tested against `/accounts/login/`).
- Disallowed-email callback → redirects to `google-login` (not a 403
  template render); the queued message is visible on the resulting page.
