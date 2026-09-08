import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

logger = logging.getLogger(__name__)


def notify_support(contact_request):
    recipient = getattr(settings, "ONTRACK_SUPPORT_EMAIL", "").strip()
    if not recipient:
        return False
    body = (
        f"New OnTrack contact request #{contact_request.pk}\n\n"
        f"Topic: {contact_request.get_topic_display()}\n"
        f"From: {contact_request.name} <{contact_request.email}>\n"
        f"Subject: {contact_request.subject}\n"
        f"Request ID: {contact_request.request_id or 'not available'}\n\n"
        f"{contact_request.message}"
    )
    try:
        EmailMessage(
            subject=f"[OnTrack support] {contact_request.subject}",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
            reply_to=[contact_request.email],
        ).send(fail_silently=False)
    except Exception:
        logger.exception("Could not email stored contact request", extra={"contact_request_id": contact_request.pk})
        return False
    contact_request.emailed_at = timezone.now()
    contact_request.save(update_fields=["emailed_at"])
    return True
