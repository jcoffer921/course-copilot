# Google Accounts (Phase 1: Sign-In + Gating) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Sign in with Google" as OnTrack's only account mechanism — one OAuth consent screen grants both identity and Calendar access, gated by an email allow-list — and require every existing view to be authenticated.

**Architecture:** A new `GoogleAccount` Django model (in the existing `db.sqlite3`, alongside the built-in auth tables) stores one row per signed-in user's Google identity and tokens. `agent/services/google_oauth.py` holds the allow-list check and the OAuth Authorization Code flow helpers (state, token exchange, ID-token verification); `agent/auth_views.py` holds the three plain Django views (login redirect, callback, logout) that use them. `REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]` gates every existing DRF/adrf view in one line; `ontrack_page` gets `@login_required`.

**Tech Stack:** Django (`django.contrib.auth` sessions, already installed), `google-auth` + `google-auth-oauthlib` (new dependencies), pytest + pytest-django.

## Global Constraints

- "Sign in with Google" (OAuth 2.0 Authorization Code flow, requesting `openid`, `email`, `profile`, and the Calendar scope in one consent screen) is the only account mechanism — no password auth, no other providers.
- `ALLOWED_GOOGLE_EMAILS` (comma-separated env var, case-insensitive match) gates account creation. An email not on the list never gets a `User`/`GoogleAccount` row — reject before creating anything. An unset/empty allow-list allows nothing (fail closed).
- `GoogleAccount` lives in the existing `db.sqlite3` (account/auth data only, never course content — per `agent/services/storage.py`'s module docstring, unchanged by this plan).
- **This plan does NOT touch `courses/` storage layout or any `storage.py` function signature.** Every signed-in user still reads/writes the same shared flat-file storage after this plan lands — that is a deliberate, temporary intermediate state. Per-user storage scoping (`courses/<user_id>/<course_id>/...`) and the one-off data migration are a separate follow-on plan against the same design spec (`docs/superpowers/specs/2026-08-20-google-accounts-design.md`) — do not attempt that work here.
- Every existing DRF/adrf `APIView` in `agent/views.py` and the `ontrack_page` view must require authentication once this plan is done.
- Live end-to-end verification against Google's real consent screen requires a real Google Cloud OAuth 2.0 Client (Web application type), with its client ID/secret in `.env` as `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET` — this is a prerequisite the human sets up outside this codebase (same pattern as `ANTHROPIC_API_KEY`). Every task's automated tests and non-live manual verification steps work without it; only the very last manual check in Task 4 needs it, and is explicitly optional if that prerequisite isn't ready yet.

---

## Task 1: `GoogleAccount` model

**Files:**
- Create: `agent/models.py`
- Test: `agent/tests/test_google_account_model.py`

**Interfaces:**
- Produces: `agent.models.GoogleAccount` (fields: `user` (OneToOne to `auth.User`, `related_name="google_account"`), `google_sub`, `email`, `access_token`, `refresh_token`, `token_expiry`)

This is the first Django model this app has ever needed (no `agent/models.py` or `agent/migrations/` exist yet), and the first test in this codebase to touch the database (every existing test uses flat-file storage or mocks; none use `@pytest.mark.django_db`) — both are expected, not a sign something's wrong.

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_google_account_model.py`:

```python
import pytest
from django.contrib.auth.models import User
from django.db.utils import IntegrityError
from django.utils import timezone


@pytest.mark.django_db
def test_creates_google_account_linked_to_user():
    from agent.models import GoogleAccount

    user = User.objects.create_user(username="jordan", email="jordan@example.com")
    account = GoogleAccount.objects.create(
        user=user, google_sub="1234567890", email="jordan@example.com",
        access_token="access-token-value", refresh_token="refresh-token-value",
        token_expiry=timezone.now(),
    )

    assert account.user == user
    assert user.google_account == account
    assert str(account) == "jordan@example.com"


@pytest.mark.django_db
def test_google_sub_must_be_unique():
    from agent.models import GoogleAccount

    user1 = User.objects.create_user(username="jordan")
    user2 = User.objects.create_user(username="alex")
    GoogleAccount.objects.create(
        user=user1, google_sub="dup-sub", email="jordan@example.com",
        access_token="a", refresh_token="r", token_expiry=timezone.now(),
    )

    with pytest.raises(IntegrityError):
        GoogleAccount.objects.create(
            user=user2, google_sub="dup-sub", email="alex@example.com",
            access_token="a", refresh_token="r", token_expiry=timezone.now(),
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_google_account_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.models'` (the import inside each test raises, since `agent/models.py` doesn't exist yet).

- [ ] **Step 3: Create `agent/models.py`**

```python
"""
Django ORM models — account/auth data only, stored in the existing
db.sqlite3 alongside the built-in auth/session/admin tables. Never course
content: that stays flat-file JSON under courses/, per storage.py's
module docstring.
"""

from django.conf import settings
from django.db import models


class GoogleAccount(models.Model):
    """One row per signed-in user's Google identity and OAuth tokens.

    Looked up by google_sub (Google's stable subject id), not email — a
    later email change on the Google side updates this row rather than
    orphaning the account."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google_account")
    google_sub = models.CharField(max_length=255, unique=True)
    email = models.EmailField()
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField()

    def __str__(self):
        return self.email
```

- [ ] **Step 4: Generate and apply the migration**

Run: `venv/Scripts/python.exe manage.py makemigrations agent`
Expected: creates `agent/migrations/__init__.py` and `agent/migrations/0001_initial.py`, output ending with `+ Create model GoogleAccount`.

Run: `venv/Scripts/python.exe manage.py migrate`
Expected: applies `agent.0001_initial` (and any pending built-in migrations) with no errors.

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_google_account_model.py -v`
Expected: PASS (2 passed).

Now run the full suite to confirm nothing else is affected:

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -v`
Expected: all tests PASS (the two new ones plus every pre-existing test, unchanged).

- [ ] **Step 6: Commit**

```bash
git add agent/models.py agent/migrations/ agent/tests/test_google_account_model.py
git commit -m "feat: add GoogleAccount model for Google Sign-In identity + tokens"
```

---

## Task 2: Allow-list checking

**Files:**
- Create: `agent/services/google_oauth.py`
- Test: `agent/tests/test_google_oauth.py`

**Interfaces:**
- Produces: `agent.services.google_oauth.is_email_allowed(email: str) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_google_oauth.py`:

```python
from agent.services import google_oauth


def test_is_email_allowed_matches_case_insensitively(monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "Jordan@Example.com,alex@example.com")

    assert google_oauth.is_email_allowed("jordan@example.com") is True
    assert google_oauth.is_email_allowed("JORDAN@EXAMPLE.COM") is True


def test_is_email_allowed_rejects_unlisted_email(monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")

    assert google_oauth.is_email_allowed("stranger@example.com") is False


def test_is_email_allowed_fails_closed_when_unset(monkeypatch):
    monkeypatch.delenv("ALLOWED_GOOGLE_EMAILS", raising=False)

    assert google_oauth.is_email_allowed("jordan@example.com") is False


def test_is_email_allowed_ignores_whitespace_around_entries(monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", " jordan@example.com , alex@example.com ")

    assert google_oauth.is_email_allowed("alex@example.com") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_google_oauth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.services.google_oauth'`.

- [ ] **Step 3: Create `agent/services/google_oauth.py`**

```python
"""
Google Sign-In: the email allow-list (this file) and, once Task 3 lands,
the OAuth 2.0 Authorization Code flow helpers. Kept separate from
agent/auth_views.py so the Google-specific plumbing isn't tangled up with
the Django view/session code.
"""

import os


def is_email_allowed(email: str) -> bool:
    """Case-insensitive membership check against ALLOWED_GOOGLE_EMAILS (a
    comma-separated env var, e.g. "you@gmail.com,friend@gmail.com"). An
    unset/empty allow-list allows nothing — fail closed, not open."""
    allowed = os.environ.get("ALLOWED_GOOGLE_EMAILS", "")
    allowed_set = {e.strip().lower() for e in allowed.split(",") if e.strip()}
    return email.strip().lower() in allowed_set
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_google_oauth.py -v`
Expected: PASS (4 passed).

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -v`
Expected: all tests PASS, zero failures.

- [ ] **Step 5: Commit**

```bash
git add agent/services/google_oauth.py agent/tests/test_google_oauth.py
git commit -m "feat: add Google email allow-list check"
```

---

## Task 3: OAuth flow + login/callback/logout views

**Files:**
- Modify: `agent/services/google_oauth.py`
- Create: `agent/auth_views.py`
- Create: `agent/templates/agent/not_authorized.html`
- Modify: `config/urls.py`
- Modify: `config/settings.py`
- Modify: `requirements.txt`
- Test: `agent/tests/test_google_oauth.py`, `agent/tests/test_auth_views.py`

**Interfaces:**
- Consumes: `agent.services.google_oauth.is_email_allowed` (Task 2), `agent.models.GoogleAccount` (Task 1)
- Produces: `agent.services.google_oauth.build_flow(redirect_uri, state=None)`, `agent.services.google_oauth.verify_id_token(id_token_jwt)`, `agent.services.google_oauth.get_or_create_account(google_sub, email, credentials)`; Django views `agent.auth_views.google_login`, `google_callback`, `google_logout`; URL names `google-login`, `google-callback`, `google-logout`; setting `LOGIN_URL`

- [ ] **Step 1: Add the new dependencies**

In `requirements.txt`, add after `anthropic>=0.40.0`:

```
google-auth>=2.35.0
google-auth-oauthlib>=1.2.0
```

Run: `venv/Scripts/python.exe -m pip install -r requirements.txt`
Expected: installs `google-auth`, `google-auth-oauthlib`, and their dependencies with no errors.

- [ ] **Step 2: Write the failing tests for `get_or_create_account`**

At the top of `agent/tests/test_google_oauth.py`, add these imports alongside the existing `from agent.services import google_oauth`:

```python
from datetime import datetime
from types import SimpleNamespace

import pytest
```

Then append to the end of the file:

```python
def _fake_credentials(token="tok", refresh_token="refresh", expiry=None):
    """Mimics google.oauth2.credentials.Credentials' relevant attributes.
    Real Credentials.expiry is a naive UTC datetime — reproduced here since
    get_or_create_account must handle that (see Step 4)."""
    return SimpleNamespace(
        token=token, refresh_token=refresh_token,
        expiry=expiry or datetime(2026, 12, 31, 0, 0, 0),
    )


@pytest.mark.django_db
def test_get_or_create_account_creates_new_user_and_account():
    from agent.models import GoogleAccount

    user = google_oauth.get_or_create_account("sub-123", "jordan@example.com", _fake_credentials())

    assert user.email == "jordan@example.com"
    account = GoogleAccount.objects.get(google_sub="sub-123")
    assert account.user == user
    assert account.email == "jordan@example.com"
    assert account.access_token == "tok"
    assert account.token_expiry.tzinfo is not None  # naive google-auth datetime made tz-aware


@pytest.mark.django_db
def test_get_or_create_account_returns_existing_user_on_second_login():
    from agent.models import GoogleAccount

    first = google_oauth.get_or_create_account("sub-123", "jordan@example.com", _fake_credentials(token="old"))
    second = google_oauth.get_or_create_account("sub-123", "jordan@example.com", _fake_credentials(token="new"))

    assert first.pk == second.pk
    assert GoogleAccount.objects.filter(google_sub="sub-123").count() == 1
    assert GoogleAccount.objects.get(google_sub="sub-123").access_token == "new"


@pytest.mark.django_db
def test_get_or_create_account_keeps_existing_refresh_token_if_google_omits_a_new_one():
    from agent.models import GoogleAccount

    google_oauth.get_or_create_account("sub-123", "jordan@example.com", _fake_credentials(refresh_token="original-refresh"))
    google_oauth.get_or_create_account("sub-123", "jordan@example.com", _fake_credentials(refresh_token=None))

    assert GoogleAccount.objects.get(google_sub="sub-123").refresh_token == "original-refresh"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_google_oauth.py -k get_or_create_account -v`
Expected: FAIL — `AttributeError: module 'agent.services.google_oauth' has no attribute 'get_or_create_account'`.

- [ ] **Step 4: Implement the OAuth flow helpers in `agent/services/google_oauth.py`**

Replace the whole file with:

```python
"""
Google Sign-In: the email allow-list, and the OAuth 2.0 Authorization Code
flow helpers (building the consent URL, verifying the returned identity,
and getting-or-creating the local account). Kept separate from
agent/auth_views.py so the Google-specific plumbing (which needs mocking
in tests) isn't tangled up with the Django view/session code.
"""

import os
from datetime import timezone as dt_timezone

from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token
from google_auth_oauthlib.flow import Flow

# Requesting Calendar access alongside identity in the same consent screen
# — per the design spec, one OAuth flow does both jobs, so a later Calendar
# sync feature can reuse the refresh token this flow stores without a
# second consent step.
OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar.events",
]


def is_email_allowed(email: str) -> bool:
    """Case-insensitive membership check against ALLOWED_GOOGLE_EMAILS (a
    comma-separated env var, e.g. "you@gmail.com,friend@gmail.com"). An
    unset/empty allow-list allows nothing — fail closed, not open."""
    allowed = os.environ.get("ALLOWED_GOOGLE_EMAILS", "")
    allowed_set = {e.strip().lower() for e in allowed.split(",") if e.strip()}
    return email.strip().lower() in allowed_set


def _client_config() -> dict:
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET environment variables are not set")
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def build_flow(redirect_uri: str, state: str = None) -> Flow:
    """Constructs a google_auth_oauthlib Flow for the authorization-code
    exchange. state=None when starting a new login (Flow generates one);
    pass the saved state back in on the callback leg."""
    flow = Flow.from_client_config(_client_config(), scopes=OAUTH_SCOPES, state=state)
    flow.redirect_uri = redirect_uri
    return flow


def verify_id_token(id_token_jwt: str) -> dict:
    """Verifies a Google-issued ID token and returns its claims dict
    (contains at least 'sub' and 'email'). Raises (via the underlying
    google-auth library) if the token is invalid or expired."""
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    return google_id_token.verify_oauth2_token(id_token_jwt, google_auth_requests.Request(), client_id)


def get_or_create_account(google_sub: str, email: str, credentials):
    """Gets or creates the User + GoogleAccount for this Google identity,
    keyed by google_sub (stable across email changes), not email. Always
    updates the stored tokens/email to the latest from this login, whether
    the account is new or returning. Returns the User."""
    from django.contrib.auth.models import User

    from agent.models import GoogleAccount

    # google-auth's Credentials.expiry is a naive UTC datetime, not
    # timezone-aware — make it aware before it hits a DateTimeField with
    # USE_TZ=True, or Django raises a naive-datetime warning/inconsistency.
    expiry = credentials.expiry
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=dt_timezone.utc)

    try:
        account = GoogleAccount.objects.select_related("user").get(google_sub=google_sub)
        account.email = email
        account.access_token = credentials.token
        account.refresh_token = credentials.refresh_token or account.refresh_token
        account.token_expiry = expiry
        account.save()
        return account.user
    except GoogleAccount.DoesNotExist:
        user = User.objects.create_user(username=google_sub, email=email)
        GoogleAccount.objects.create(
            user=user, google_sub=google_sub, email=email,
            access_token=credentials.token,
            refresh_token=credentials.refresh_token or "",
            token_expiry=expiry,
        )
        return user
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_google_oauth.py -v`
Expected: PASS (7 passed: the 4 from Task 2 plus the 3 new `get_or_create_account` tests).

- [ ] **Step 6: Write the failing tests for the Django views**

Create `agent/tests/test_auth_views.py`:

```python
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent.models import GoogleAccount


def _mock_flow_with_credentials():
    """A MagicMock Flow whose .credentials has real (non-Mock) values for
    every attribute get_or_create_account touches — a bare MagicMock()
    there would fail when Django tries to save token_expiry to the DB."""
    mock_flow = MagicMock()
    mock_flow.credentials = MagicMock(
        id_token="fake-id-token", token="access-tok", refresh_token="refresh-tok",
        expiry=datetime(2026, 12, 31, 0, 0, 0),
    )
    return mock_flow


@pytest.mark.django_db
def test_google_login_redirects_to_google_and_saves_state(client):
    with patch("agent.auth_views.google_oauth.build_flow") as build_flow:
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?mock=1", "state-xyz")
        build_flow.return_value = mock_flow

        response = client.get("/accounts/login/")

    assert response.status_code == 302
    assert response.url.startswith("https://accounts.google.com/")
    assert client.session["google_oauth_state"] == "state-xyz"


@pytest.mark.django_db
def test_google_callback_rejects_mismatched_state(client):
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()

    response = client.get("/accounts/callback/?state=wrong-state&code=abc")

    assert response.status_code == 400


@pytest.mark.django_db
def test_google_callback_creates_account_and_logs_in_allowed_email(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()

    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = _mock_flow_with_credentials()
        verify_id_token.return_value = {"sub": "sub-123", "email": "jordan@example.com"}

        response = client.get("/accounts/callback/?state=expected-state&code=abc")

    assert response.status_code == 302
    assert response.url == "/"
    assert GoogleAccount.objects.filter(google_sub="sub-123").exists()
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_google_callback_rejects_disallowed_email_and_creates_no_account(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()

    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = _mock_flow_with_credentials()
        verify_id_token.return_value = {"sub": "sub-999", "email": "stranger@example.com"}

        response = client.get("/accounts/callback/?state=expected-state&code=abc")

    assert response.status_code == 403
    assert not GoogleAccount.objects.filter(google_sub="sub-999").exists()
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_google_logout_clears_session(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()
    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = _mock_flow_with_credentials()
        verify_id_token.return_value = {"sub": "sub-123", "email": "jordan@example.com"}
        client.get("/accounts/callback/?state=expected-state&code=abc")
    assert "_auth_user_id" in client.session

    response = client.get("/accounts/logout/")

    assert response.status_code == 302
    assert "_auth_user_id" not in client.session
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_auth_views.py -v`
Expected: FAIL — 404s on `/accounts/login/`, `/accounts/callback/`, `/accounts/logout/` (routes don't exist yet) and `ModuleNotFoundError: No module named 'agent.auth_views'`.

- [ ] **Step 8: Create `agent/templates/agent/not_authorized.html`**

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Not authorized — OnTrack</title>
</head>
<body style="font-family:sans-serif;max-width:480px;margin:80px auto;text-align:center">
  <h1>Not authorized</h1>
  <p>The Google account <strong>{{ email }}</strong> is not on OnTrack's approved list.</p>
  <p>If you think this is a mistake, contact whoever manages this OnTrack instance.</p>
</body>
</html>
```

- [ ] **Step 9: Create `agent/auth_views.py`**

```python
"""
Google Sign-In views: the login redirect, the OAuth callback, and logout.
Plain Django views (not DRF) — this is a browser-redirect flow, not a
JSON API, so it doesn't belong in agent/views.py alongside the APIViews.
"""

from django.contrib.auth import login, logout
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render

from .services import google_oauth


def _redirect_uri(request) -> str:
    return request.build_absolute_uri("/accounts/callback/")


def google_login(request):
    """GET /accounts/login/ — redirects to Google's consent screen.
    access_type=offline + prompt=consent guarantee a refresh token on
    every login (Google only returns one on the very first consent
    otherwise), per the design spec's edge-case notes."""
    flow = google_oauth.build_flow(_redirect_uri(request))
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    request.session["google_oauth_state"] = state
    return redirect(auth_url)


def google_callback(request):
    """GET /accounts/callback/ — Google redirects here after consent."""
    saved_state = request.session.get("google_oauth_state")
    returned_state = request.GET.get("state")
    if not saved_state or saved_state != returned_state:
        return HttpResponseBadRequest("invalid or expired OAuth state")

    flow = google_oauth.build_flow(_redirect_uri(request), state=saved_state)
    flow.fetch_token(code=request.GET.get("code"))
    del request.session["google_oauth_state"]

    credentials = flow.credentials
    claims = google_oauth.verify_id_token(credentials.id_token)
    email = claims["email"]
    google_sub = claims["sub"]

    if not google_oauth.is_email_allowed(email):
        return render(request, "agent/not_authorized.html", {"email": email}, status=403)

    user = google_oauth.get_or_create_account(google_sub, email, credentials)
    login(request, user)
    return redirect("ontrack")


def google_logout(request):
    """GET /accounts/logout/ — standard Django session logout."""
    logout(request)
    return redirect("ontrack")
```

- [ ] **Step 10: Wire up the URLs in `config/urls.py`**

Replace the whole file:

```python
from django.contrib import admin
from django.urls import include, path

from agent.auth_views import google_callback, google_login, google_logout
from agent.views import ontrack_page

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", google_login, name="google-login"),
    path("accounts/callback/", google_callback, name="google-callback"),
    path("accounts/logout/", google_logout, name="google-logout"),
    path("api/", include("agent.urls")),
    path("", ontrack_page, name="ontrack"),
]
```

- [ ] **Step 11: Add `LOGIN_URL` in `config/settings.py`**

After the `AUTH_PASSWORD_VALIDATORS` block, add:

```python
# Used by @login_required (added to ontrack_page in Task 4) to know where
# to send an anonymous visitor — the URL name defined in config/urls.py.
LOGIN_URL = "google-login"
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_auth_views.py -v`
Expected: PASS (5 passed).

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -v`
Expected: all tests PASS, zero failures.

- [ ] **Step 13: Commit**

```bash
git add requirements.txt agent/services/google_oauth.py agent/auth_views.py agent/templates/agent/not_authorized.html config/urls.py config/settings.py agent/tests/test_google_oauth.py agent/tests/test_auth_views.py
git commit -m "feat: add Google OAuth login/callback/logout flow"
```

---

## Task 4: Gate the app behind login + show the signed-in user

**Files:**
- Modify: `config/settings.py`
- Modify: `agent/views.py`
- Modify: `agent/templates/agent/ontrack.html`
- Modify: `agent/tests/test_views.py`

**Interfaces:**
- Consumes: `LOGIN_URL` (Task 3), URL name `google-logout` (Task 3)
- Produces: every existing `APIView` in `agent/views.py` now requires authentication; `ontrack_page` requires authentication; the `api_client` pytest fixture in `test_views.py` is now pre-authenticated

Only `agent/tests/test_views.py` uses DRF's `APIClient` anywhere in this test suite — every other test file calls service functions directly and never touches the view/HTTP layer, so this task's fixture change is contained to one file.

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_views.py`:

```python
def test_anonymous_request_to_api_is_rejected(isolated_courses_dir):
    from rest_framework.test import APIClient
    anonymous_client = APIClient()  # deliberately not the (soon-to-be authenticated) api_client fixture

    response = anonymous_client.get("/api/courses/cs101/syllabus/")

    assert response.status_code == 401


def test_anonymous_request_to_ontrack_page_redirects_to_login(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_views.py -k anonymous -v`
Expected: FAIL — `test_anonymous_request_to_api_is_rejected` fails because the endpoint currently returns 200 (no auth required yet, gets a 404 for the nonexistent syllabus instead of 401); `test_anonymous_request_to_ontrack_page_redirects_to_login` fails because `/` currently returns 200 directly with no redirect.

- [ ] **Step 3: Gate every DRF/adrf view in `config/settings.py`**

In the `REST_FRAMEWORK` dict, add one new key:

```python
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}
```

This gates all 23 existing `APIView` subclasses in `agent/views.py` at once (and any future one, by default) — nothing in `agent/views.py` itself needs to change; `SessionAuthentication` is already DRF's default authentication class, and Django's session middleware is already installed.

- [ ] **Step 4: Gate `ontrack_page` in `agent/views.py`**

Add the import at the top of the file, alongside the existing imports:

```python
from django.contrib.auth.decorators import login_required
```

Then change:

```python
def ontrack_page(request):
```

to:

```python
@login_required
def ontrack_page(request):
```

- [ ] **Step 5: Run tests — confirm the new tests pass and the rest of the file now fails (expected)**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_views.py -v`
Expected: the 2 new `anonymous`-prefixed tests PASS. Every other test in this file now FAILS with 401, because the `api_client` fixture (`return APIClient()`) is not authenticated. This is the correct intermediate state — it proves the gate actually blocks unauthenticated requests. Fixed in the next step.

- [ ] **Step 6: Authenticate the `api_client` fixture**

In `agent/tests/test_views.py`, change:

```python
@pytest.fixture
def api_client():
    return APIClient()
```

to:

```python
@pytest.fixture
def api_client(django_user_model):
    user = django_user_model.objects.create_user(username="test-user")
    client = APIClient()
    client.force_authenticate(user=user)
    return client
```

- [ ] **Step 7: Run tests to verify everything passes again**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_views.py -v`
Expected: all tests PASS, zero failures.

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -v`
Expected: all tests PASS, zero failures — confirms no other test file was affected (none of them touch the view/HTTP layer).

- [ ] **Step 8: Add the server → JS bridge for the signed-in user's email**

In `agent/templates/agent/ontrack.html`, change:

```html
<body>
{% csrf_token %}
<x-dc>
```

to:

```html
<body>
{% csrf_token %}
<script>window.CURRENT_USER_EMAIL = "{{ user.email|escapejs }}";</script>
<x-dc>
```

- [ ] **Step 9: Seed `currentUserEmail` in the component's initial state**

Search for the `state = {` class field (search by content — do not trust a specific line number, since prior tasks in this file have shifted it repeatedly). Change its first line:

```javascript
  state = {
    tab: 'dashboard', course: 'all',
```

to:

```javascript
  state = {
    currentUserEmail: window.CURRENT_USER_EMAIL,
    tab: 'dashboard', course: 'all',
```

- [ ] **Step 10: Replace the sidebar's hardcoded "Jordan C." footer with the real signed-in user**

Search for this exact block (search by content):

```html
    <div style="margin-top:auto;padding-top:var(--space-6);border-top:1px solid var(--color-neutral-200);display:flex;align-items:center;gap:10px">
      <div style="width:30px;height:30px;border-radius:999px;background:var(--color-accent-2-200);color:var(--color-accent-2-800);display:flex;align-items:center;justify-content:center;font-family:var(--font-heading);font-size:13px;flex:none">J</div>
      <div style="font-size:13px;line-height:1.3">
        <div style="font-weight:600">Jordan C.</div>
        <div style="opacity:.55;font-size:12px">Fall 2026</div>
      </div>
    </div>
```

Replace with:

```html
    <div style="margin-top:auto;padding-top:var(--space-6);border-top:1px solid var(--color-neutral-200);display:flex;align-items:center;gap:10px">
      <div style="width:30px;height:30px;border-radius:999px;background:var(--color-accent-2-200);color:var(--color-accent-2-800);display:flex;align-items:center;justify-content:center;font-family:var(--font-heading);font-size:13px;flex:none">{{ userInitial }}</div>
      <div style="font-size:13px;line-height:1.3;flex:1;min-width:0">
        <div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ currentUserEmail }}</div>
        <a href="/accounts/logout/" style="font-size:12px">Sign out</a>
      </div>
    </div>
```

- [ ] **Step 11: Expose `currentUserEmail`/`userInitial` from `renderVals()`**

Find `renderVals()`'s `return {` statement (search by content — currently the third `return {` in the file, after the two inside `parseInlineBlocks`/other helper functions earlier in the file). Change:

```javascript
    return {
      isDashboard: s.tab === 'dashboard',
```

to:

```javascript
    return {
      currentUserEmail: s.currentUserEmail,
      userInitial: s.currentUserEmail ? s.currentUserEmail[0].toUpperCase() : '?',
      isDashboard: s.tab === 'dashboard',
```

- [ ] **Step 12: Manual verification — without live Google credentials (required)**

Start the dev server on a free port: `venv/Scripts/python.exe -m uvicorn config.asgi:application --port 8031`

1. Visit `http://127.0.0.1:8031/` in a browser with no session cookie (a fresh/incognito window). Confirm you're redirected to `/accounts/login/`, which itself redirects — since `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET` aren't set yet in this environment, confirm this fails loudly with the `ValueError` message from `google_oauth._client_config()` (visible as a Django debug error page, since `DEBUG=true` in dev) rather than silently proceeding — this proves the "fail loudly if unset" behavior from Step 4 of Task 3.
2. Create a real local test user and log in as them directly (bypassing Google, to verify the gated app itself works without needing real OAuth credentials yet):
   ```bash
   venv/Scripts/python.exe manage.py shell -c "from django.contrib.auth.models import User; User.objects.filter(username='manual-test').delete(); User.objects.create_user(username='manual-test', email='manual-test@example.com')"
   ```
   Then use the Django admin (`http://127.0.0.1:8031/admin/`) or `manage.py shell`'s session tools to establish a logged-in session as this user, OR temporarily add `client.force_login()` via a one-off script — whichever is fastest in your environment. Confirm: the app loads at `/`, the sidebar footer shows `manual-test@example.com` (not "Jordan C."), the avatar circle shows `M`, and clicking "Sign out" redirects back through `/accounts/login/` (which then fails loudly again per point 1, since there's still no real Google client configured — expected).
3. Delete the manual test user afterward: `venv/Scripts/python.exe manage.py shell -c "from django.contrib.auth.models import User; User.objects.filter(username='manual-test').delete()"`.

Stop the dev server when done.

- [ ] **Step 13: Manual verification — with live Google credentials (optional, do this once you've set up a real Google Cloud OAuth Client)**

Set `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, and `ALLOWED_GOOGLE_EMAILS` (including your own real Google email) in `.env`, restart the dev server, and:

1. Visit `/` anonymously — confirm you land on Google's real consent screen, requesting the app's name and the Calendar scope.
2. Approve — confirm you're redirected back to `/` fully logged in, with your real email in the sidebar footer.
3. Click "Sign out" — confirm you're bounced straight back to Google's consent screen (expected: `ontrack_page` is login-gated, so logging out and landing on `/` immediately triggers `@login_required` again).
4. Temporarily remove your own email from `ALLOWED_GOOGLE_EMAILS`, restart the server, and repeat the sign-in — confirm you land on the "Not authorized" page instead, and that `GoogleAccount.objects.count()` in `manage.py shell` did not grow. Restore your email to `ALLOWED_GOOGLE_EMAILS` afterward.

- [ ] **Step 14: Commit**

```bash
git add config/settings.py agent/views.py agent/templates/agent/ontrack.html agent/tests/test_views.py
git commit -m "feat: require authentication on every view, show signed-in user in the sidebar"
```

---

## Self-Review Notes

- **Spec coverage:** this plan implements the "OAuth flow," "Data model," and "Access enforcement" sections of `docs/superpowers/specs/2026-08-20-google-accounts-design.md` in full. The spec's "Per-user course storage" and "Migration of existing data" sections are deliberately deferred to a follow-on plan (see Global Constraints) — after this plan, the app is genuinely multi-user for *authentication* (distinct people can sign in, and only allow-listed ones), but still single-shared-storage for *course data* until that follow-on plan lands. This phasing is called out explicitly so it isn't mistaken for an oversight.
- **Placeholder scan:** no TBDs; every step has complete code. The one Non-goal explicitly carried into this plan from the spec is unchanged: no self-service account management UI, no other sign-in providers, no rate limiting.
- **Type consistency checked:** `GoogleAccount` (Task 1) is referenced identically in Task 3's `get_or_create_account` and its tests, and Task 3's `test_auth_views.py` tests. `google_oauth.is_email_allowed`/`build_flow`/`verify_id_token`/`get_or_create_account` are defined once (Tasks 2 and 3, same file, no redefinition) and consumed identically by `agent/auth_views.py`. The URL names `google-login`/`google-callback`/`google-logout` defined in Task 3's `config/urls.py` are the same strings `LOGIN_URL` (Task 3) and Task 4's manual verification/template markup rely on.
- **Test-suite blast radius confirmed narrow:** verified via `grep -rl APIClient agent/tests/` that `agent/tests/test_views.py` is the *only* test file using DRF's `APIClient` — every other test file (grades, dashboard, mastery, quiz, storage, etc.) calls service functions directly and never touches the HTTP/view layer, so Task 4's authentication gate and fixture change cannot silently break any test outside that one file. This was confirmed by direct inspection before writing Task 4, not assumed.
- **Deferred to the follow-on plan** (recorded here so it isn't lost): per-user `courses/<user_id>/<course_id>/...` storage scoping (touches `storage.py`'s ~25 functions and every caller in the service layer, `views.py`, and every `manage.py` CLI command), the `manage.py migrate_courses_to_user` command, and updating `CLAUDE.md`'s "single-user"/"personal-use" framing (several places) once the app is *actually* multi-user end-to-end rather than just gated.
