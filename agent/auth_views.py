"""
Google Sign-In views: the login redirect, the OAuth callback, and logout.
Plain Django views (not DRF) — this is a browser-redirect flow, not a
JSON API, so it doesn't belong in agent/views.py alongside the APIViews.
"""

import logging

from django.contrib import messages
from django.contrib.auth import login, logout
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .services import google_oauth

logger = logging.getLogger(__name__)


def _redirect_uri(request) -> str:
    return request.build_absolute_uri("/accounts/callback/")


def google_login_page(request):
    """GET /accounts/login/ — the branded landing page (LOGIN_URL points
    here, so @login_required lands anonymous visitors on this page). An
    already-authenticated visitor skips straight to the app. Django's
    messages framework carries a rejection notice here after a disallowed
    email's callback (see google_callback below)."""
    if request.user.is_authenticated:
        return redirect("ontrack")
    return render(request, "agent/login.html")


def google_login_start(request):
    """GET /accounts/login/start/ — redirects to Google's consent screen.
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

    # State has now been validated as matching — its only job was CSRF
    # protection for this one request, so clear it before attempting the
    # token exchange. That way a failed exchange doesn't leave stale state
    # sitting in the session for a later request to (mis)reuse.
    del request.session["google_oauth_state"]

    flow = google_oauth.build_flow(_redirect_uri(request), state=saved_state)
    try:
        flow.fetch_token(code=request.GET.get("code"))
    except Exception:
        logger.exception("Google OAuth token exchange failed")
        return HttpResponseBadRequest("could not exchange authorization code with Google")

    credentials = flow.credentials
    try:
        claims = google_oauth.verify_id_token(credentials.id_token)
    except Exception:
        logger.exception("Google ID token verification failed")
        return HttpResponseBadRequest("could not verify Google ID token")

    email = claims.get("email")
    google_sub = claims.get("sub")
    if not email or not google_sub:
        return HttpResponseBadRequest("Google did not return the required account information")

    if not claims.get("email_verified"):
        return HttpResponseBadRequest("Google account email is not verified")

    if not google_oauth.is_email_allowed(email):
        messages.error(request, "That Google account isn't on OnTrack's approved list yet. Try a different account, or contact whoever manages this OnTrack instance.")
        return redirect("google-login")

    user = google_oauth.get_or_create_account(google_sub, email, credentials)
    login(request, user)
    return redirect("ontrack")


@require_POST
def google_logout(request):
    """POST /accounts/logout/ — standard Django session logout.
    POST-only (with CSRF protection from CsrfViewMiddleware) so a
    third-party page can't force a logout via e.g. an <img> tag."""
    logout(request)
    return redirect("ontrack")
