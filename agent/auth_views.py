"""
Google Sign-In views: the login redirect, the OAuth callback, and logout.
Plain Django views (not DRF) — this is a browser-redirect flow, not a
JSON API, so it doesn't belong in agent/views.py alongside the APIViews.
"""

import logging
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
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
    # Calendar OAuth must use one stable URI that exactly matches the Google
    # Cloud client configuration. Do not derive it from the incoming Host
    # header (localhost vs 127.0.0.1, proxy hosts, and ports would drift).
    return f"{settings.ONTRACK_BASE_URL}/accounts/calendar/callback/"


def _safe_next(request, candidate):
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return ""


def google_login_page(request, mode="login"):
    """GET /accounts/login/ — the branded landing page (LOGIN_URL points
    here, so @login_required lands anonymous visitors on this page). An
    already-authenticated visitor skips straight to the app. Django's
    messages framework carries a rejection notice here after a disallowed
    email's callback (see google_callback below)."""
    if request.user.is_authenticated:
        return redirect("dashboard-page")
    return render(request, "agent/login.html", {
        "auth_mode": mode,
        "next_destination": _safe_next(request, request.GET.get("next", "")),
    })


def google_signup_page(request):
    return google_login_page(request, mode="signup")


@login_required
def pending_access_page(request):
    """GET /accounts/pending/ — where a signed-in, not-yet-active user
    lands (see AccessStatusMiddleware). An already-active user hitting this
    URL directly is sent straight to the app instead of seeing a stale
    pending message."""
    from .authentication import user_access_status
    from .models import UserSettings

    if user_access_status(request.user) == UserSettings.ACCESS_ACTIVE:
        return redirect("dashboard-page")
    return render(request, "agent/pending.html")


def google_login_start(request):
    """GET /accounts/login/start/ — begin identity-only Google sign-in."""
    if request.user.is_authenticated:
        return redirect("dashboard-page")
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
    safe_next = _safe_next(request, request.GET.get("next", ""))
    if safe_next:
        request.session["google_oauth_next"] = safe_next
    else:
        request.session.pop("google_oauth_next", None)
    # Signup-only pre-signup field (see agent/templates/agent/login.html).
    # Stashed in the session the same way as state/next, since the browser
    # goes to Google and back before google_callback can apply it — only
    # used if this turns out to be a brand-new account (see UserSettings
    # creation in google_callback below); a stale value from an abandoned
    # attempt is never carried into an unrelated later sign-in.
    cohort = request.GET.get("cohort", "").strip()[:100]
    if cohort:
        request.session["signup_cohort"] = cohort
    else:
        request.session.pop("signup_cohort", None)
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

    user = google_oauth.get_or_create_account(google_sub, email, name=claims.get("name"))

    from .models import UserSettings

    # Bootstrap path only: an email on the admission list gets an
    # already-active row the moment its account is first created, so the
    # developer and any pre-approved accounts still work with no manual
    # admin step. Everyone else gets UserSettings' pending default. The
    # cohort field (see google_login_start above) is likewise applied only
    # here — get_or_create's defaults only take effect on first creation, so
    # a returning user's row (access_status, tier, cohort — active, pending,
    # or suspended) is never touched by signing in again.
    defaults = {"cohort": request.session.pop("signup_cohort", "")}
    if google_oauth.is_email_allowed(email):
        defaults["access_status"] = UserSettings.ACCESS_ACTIVE
    UserSettings.objects.get_or_create(user=user, defaults=defaults)

    login(request, user)
    return redirect(request.session.pop("google_oauth_next", None) or "dashboard-page")


@login_required
def google_calendar_connect(request):
    """Begin a separate, explicit Calendar-only consent flow."""
    flow = google_calendar_oauth.build_flow(_calendar_redirect_uri(request))
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    request.session["google_calendar_oauth_state"] = state
    request.session["google_calendar_oauth_code_verifier"] = flow.code_verifier
    # Round-trips through Google back to wherever the student actually was
    # (a Deadlines-tab card, the Calendar page) rather than always dumping
    # them on Settings — connecting/reconnecting is meant to be a small
    # detour, not a context switch away from the task they were doing.
    safe_next = _safe_next(request, request.GET.get("next", ""))
    if safe_next:
        request.session["google_calendar_oauth_next"] = safe_next
    else:
        request.session.pop("google_calendar_oauth_next", None)
    return redirect(auth_url)


@login_required
def google_calendar_callback(request):
    saved_state = request.session.pop("google_calendar_oauth_state", None)
    returned_state = request.GET.get("state")
    saved_verifier = request.session.pop("google_calendar_oauth_code_verifier", None)
    next_url = request.session.pop("google_calendar_oauth_next", None) or "settings-apps-page"
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
    except Exception as exc:
        # Do not log the exception message: OAuth errors can contain sensitive
        # response details. The class is enough to diagnose the failure safely.
        logger.warning(
            "Google Calendar OAuth connection failed",
            extra={"oauth_error_type": type(exc).__name__},
        )
        messages.error(
            request,
            "Google Calendar couldn't be connected. Please try again.",
        )
        return redirect(next_url)
    messages.success(request, "Google Calendar connected.")
    return redirect(next_url)


@require_POST
@login_required
def google_calendar_disconnect(request):
    google_calendar_oauth.disconnect(request.user)
    messages.success(request, "Google Calendar disconnected.")
    return redirect("settings-apps-page")


@require_POST
def google_logout(request):
    """POST /accounts/logout/ — standard Django session logout.
    POST-only (with CSRF protection from CsrfViewMiddleware) so a
    third-party page can't force a logout via e.g. an <img> tag."""
    logout(request)
    return redirect("ontrack")
