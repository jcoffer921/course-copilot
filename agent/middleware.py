import logging
import re
import time
import uuid

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
logger = logging.getLogger("ontrack.requests")


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
