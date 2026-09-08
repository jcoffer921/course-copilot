from django.core.management.base import BaseCommand, CommandError

from agent.services import email_domain


class Command(BaseCommand):
    help = "Validate the configured sender's SPF, DKIM, and DMARC readiness."

    def handle(self, *args, **options):
        results = email_domain.check_sender_domain()
        for result in results:
            style = self.style.SUCCESS if result["status"] == "ok" else self.style.WARNING if result["status"] == "warning" else self.style.ERROR
            self.stdout.write(style(f"{result['status'].upper():7} {result['name']}: {result['detail']}"))
        if any(result["status"] == "error" for result in results):
            raise CommandError("Sender-domain validation failed.")
