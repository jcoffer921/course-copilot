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


def build_flow(redirect_uri: str, state: str = None, code_verifier: str = None) -> Flow:
    """Constructs a google_auth_oauthlib Flow for the authorization-code
    exchange. state=None when starting a new login (Flow generates one);
    pass the saved state back in on the callback leg.

    code_verifier: the login-start leg and the callback leg build two
    SEPARATE Flow objects (the first is discarded after redirecting to
    Google). Flow auto-generates a PKCE code_verifier inside
    authorization_url() when none is supplied, so without passing the same
    value back in here, the callback's fetch_token() sends no verifier and
    Google's token endpoint rejects the exchange with
    'invalid_grant: Missing code verifier'. Callers must persist
    flow.code_verifier (set only after authorization_url() runs) themselves
    — e.g. in the session, alongside state — and pass it back in here."""
    flow = Flow.from_client_config(_client_config(), scopes=OAUTH_SCOPES, state=state, code_verifier=code_verifier)
    flow.redirect_uri = redirect_uri
    return flow


def verify_id_token(id_token_jwt: str) -> dict:
    """Verifies a Google-issued ID token and returns its claims dict
    (contains at least 'sub' and 'email'). Raises (via the underlying
    google-auth library) if the token is invalid or expired."""
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    return google_id_token.verify_oauth2_token(id_token_jwt, google_auth_requests.Request(), client_id)


def get_or_create_account(google_sub: str, email: str, credentials, name: str = None):
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
        user = account.user
        user.email = email
        if name and not user.first_name:
            user.first_name = name
        user.save(update_fields=["email", "first_name"])
        return account.user
    except GoogleAccount.DoesNotExist:
        user = User.objects.create_user(username=google_sub, email=email, first_name=name or "")
        GoogleAccount.objects.create(
            user=user, google_sub=google_sub, email=email,
            access_token=credentials.token,
            refresh_token=credentials.refresh_token or "",
            token_expiry=expiry,
        )
        return user
