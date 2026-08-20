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
