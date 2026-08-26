"""
Google Sign-In views: the login redirect, the OAuth callback, and logout.
Plain Django views (not DRF) — this is a browser-redirect flow, not a
JSON API, so it doesn't belong in agent/views.py alongside the APIViews.
"""

import logging
import os

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .services import google_oauth
from .services import google_calendar_oauth

logger = logging.getLogger(__name__)


def _login_rate_limited(request) -> bool:
    """Small per-IP guard for the OAuth start endpoint.

    REMOTE_ADDR is intentionally used instead of an untrusted forwarded header.
    Deployments can provide stronger proxy/edge throttling as an additional layer.
    """
    limit = int(os.environ.get("ONTRACK_LOGIN_RATE_LIMIT", "10"))
    window = int(os.environ.get("ONTRACK_LOGIN_RATE_WINDOW_SECONDS", "300"))
    key = f"ontrack:google-login:{request.META.get('REMOTE_ADDR', 'unknown')}"
    if cache.add(key, 1, timeout=window):
        return False
    try:
        return cache.incr(key) > limit
    except ValueError:
        cache.set(key, 1, timeout=window)
        return False


def _redirect_uri(request) -> str:
    return request.build_absolute_uri("/accounts/callback/")


def _calendar_redirect_uri(request) -> str:
    return request.build_absolute_uri("/accounts/calendar/callback/")


def google_login_page(request):
    """GET /accounts/login/ — the branded landing page (LOGIN_URL points
    here, so @login_required lands anonymous visitors on this page). An
    already-authenticated visitor skips straight to the app. Django's
    messages framework carries a rejection notice here after a disallowed
    email's callback (see google_callback below)."""
    if request.user.is_authenticated:
        return redirect("dashboard-page")
    return render(request, "agent/login.html")


def google_login_start(request):
    """GET /accounts/login/start/ — begin identity-only Google sign-in."""
    if _login_rate_limited(request):
        return HttpResponse("Too many sign-in attempts. Please try again later.", status=429)
    flow = google_oauth.build_flow(_redirect_uri(request))
    auth_url, state = flow.authorization_url()
    request.session["google_oauth_state"] = state
    # PKCE: Flow generates a code_verifier during authorization_url() above.
    # This Flow object is discarded once we redirect — the callback builds
    # a separate one — so the verifier must round-trip through the session
    # (alongside state) or Google's token endpoint rejects the exchange.
    request.session["google_oauth_code_verifier"] = flow.code_verifier
    return redirect(auth_url)


def google_callback(request):
    """GET /accounts/callback/ — Google redirects here after consent."""
    saved_state = request.session.get("google_oauth_state")
    returned_state = request.GET.get("state")
    if not saved_state or saved_state != returned_state:
        return HttpResponseBadRequest("invalid or expired OAuth state")

    # State has now been validated as matching — its only job was CSRF
    # protection for this one request, so clear it (and the paired PKCE
    # code_verifier) before attempting the token exchange. That way a
    # failed exchange doesn't leave stale state sitting in the session for
    # a later request to (mis)reuse.
    del request.session["google_oauth_state"]
    saved_code_verifier = request.session.pop("google_oauth_code_verifier", None)
    if not saved_code_verifier:
        return HttpResponseBadRequest("invalid or expired OAuth PKCE verifier")

    flow = google_oauth.build_flow(_redirect_uri(request), state=saved_state, code_verifier=saved_code_verifier)
    try:
        flow.fetch_token(code=request.GET.get("code"))
    except Exception:
        # OAuth provider exceptions can contain sensitive response details.
        logger.warning("Google OAuth token exchange failed")
        return HttpResponseBadRequest("could not exchange authorization code with Google")

    credentials = flow.credentials
    try:
        claims = google_oauth.verify_id_token(credentials.id_token)
    except Exception:
        logger.warning("Google ID token verification failed")
        return HttpResponseBadRequest("could not verify Google ID token")

    email = claims.get("email")
    google_sub = claims.get("sub")
    if not email or not google_sub:
        return HttpResponseBadRequest("Google did not return the required account information")

    if not claims.get("email_verified"):
        return HttpResponseBadRequest("Google account email is not verified")

    if not google_oauth.is_email_allowed(email):
        logger.warning("Google sign-in denied by admission policy", extra={"google_sub": google_sub})
        messages.error(request, "That Google account isn't on OnTrack's approved list yet. Try a different account, or contact whoever manages this OnTrack instance.")
        return redirect("google-login")

    user = google_oauth.get_or_create_account(google_sub, email, name=claims.get("name"))
    login(request, user)
    return redirect("dashboard-page")


@login_required
def google_calendar_connect(request):
    """Begin a separate, explicit Calendar-only consent flow."""
    flow = google_calendar_oauth.build_flow(_calendar_redirect_uri(request))
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    request.session["google_calendar_oauth_state"] = state
    request.session["google_calendar_oauth_code_verifier"] = flow.code_verifier
    return redirect(auth_url)


@login_required
def google_calendar_callback(request):
    saved_state = request.session.pop("google_calendar_oauth_state", None)
    returned_state = request.GET.get("state")
    saved_verifier = request.session.pop("google_calendar_oauth_code_verifier", None)
    if not saved_state or saved_state != returned_state or not saved_verifier:
        return HttpResponseBadRequest("invalid or expired Calendar OAuth state")

    flow = google_calendar_oauth.build_flow(
        _calendar_redirect_uri(request),
        state=saved_state,
        code_verifier=saved_verifier,
    )
    try:
        flow.fetch_token(code=request.GET.get("code"))
        google_calendar_oauth.save_connection(request.user, flow.credentials)
    except Exception:
        logger.warning("Google Calendar OAuth connection failed")
        return HttpResponseBadRequest("could not connect Google Calendar")
    messages.success(request, "Google Calendar connected.")
    return redirect("settings-page")


@require_POST
@login_required
def google_calendar_disconnect(request):
    google_calendar_oauth.disconnect(request.user)
    messages.success(request, "Google Calendar disconnected.")
    return redirect("settings-page")


@require_POST
def google_logout(request):
    """POST /accounts/logout/ — standard Django session logout.
    POST-only (with CSRF protection from CsrfViewMiddleware) so a
    third-party page can't force a logout via e.g. an <img> tag."""
    logout(request)
    return redirect("google-login")
