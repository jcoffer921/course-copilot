import logging

logger = logging.getLogger("ontrack.metrics")
ALLOWED_METADATA = {"grounded", "mode", "duration_minutes", "material_type", "status"}


def record(user, event, *, course_id="", metadata=None):
    from agent.models import ProductMetric
    safe_metadata = {
        key: value for key, value in (metadata or {}).items()
        if key in ALLOWED_METADATA and isinstance(value, (str, int, float, bool, type(None)))
    }
    try:
        return ProductMetric.objects.create(
            user=user, event=event[:64], course_id=str(course_id or "")[:64], metadata=safe_metadata,
        )
    except Exception:
        logger.exception("metric.record_failed", extra={"user_id": getattr(user, "pk", None)})
        return None
