import logging
import re
import time
import uuid

from django.shortcuts import redirect

from .authentication import is_access_active

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
logger = logging.getLogger("ontrack.requests")

# Paths a signed-in-but-not-active user must still be able to reach: the API
# (gated separately by ActiveAccessPermission), the OAuth/logout/pending
# flow itself (or a pending user could never reach the pending page or sign
# out), Django admin (an operator promoting others must not be locked out
# of it by their own pre-promotion status), static assets, and the public
# marketing pages.
ACCESS_GATE_EXEMPT_PREFIXES = ("/api/", "/accounts/", "/admin/", "/static/", "/privacy/", "/contact/")


class AccessStatusMiddleware:
    """Single enforcement point for browser pages: a signed-in user whose
    UserSettings.access_status isn't 'active' is redirected to the pending
    page instead of reaching the requested view. Must run after
    AuthenticationMiddleware (needs request.user) and does nothing for
    anonymous requests — @login_required on each page view still handles
    those. See agent/authentication.py's ActiveAccessPermission for the
    equivalent gate on the JSON API."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and not request.path.startswith(ACCESS_GATE_EXEMPT_PREFIXES)
            and not is_access_active(request.user)
        ):
            return redirect("pending-page")
        return self.get_response(request)


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if REQUEST_ID_RE.fullmatch(supplied) else uuid.uuid4().hex
        request.request_id = request_id
        started = time.monotonic()
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        logger.info(
            "request.complete",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "user_id": (
                    None if getattr(request, "_ontrack_anonymous_feedback", False)
                    else request.user.pk if getattr(request.user, "is_authenticated", False)
                    else None
                ),
            },
        )
        return response
