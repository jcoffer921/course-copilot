from django.core.management.base import BaseCommand
from django.utils import timezone

from agent.models import LlmUsage
from agent.services.llm_usage import estimate_cost_usd


class Command(BaseCommand):
    help = "Prints today's per-user Anthropic request/token usage and estimated cost."

    def handle(self, *args, **options):
        today = timezone.localdate()
        rows = LlmUsage.objects.filter(date=today).select_related("user").order_by("-count")

        if not rows:
            self.stdout.write(f"No LLM requests recorded for {today}.")
            return

        for row in rows:
            total_input = sum(model_totals.get("input", 0) for model_totals in row.tokens.values())
            total_output = sum(model_totals.get("output", 0) for model_totals in row.tokens.values())
            total_cost = 0.0
            cost_is_partial = False
            for model, model_totals in row.tokens.items():
                cost = estimate_cost_usd(model, model_totals.get("input", 0), model_totals.get("output", 0))
                if cost is None:
                    cost_is_partial = True
                else:
                    total_cost += cost

            identity = row.user.email or row.user.username
            cost_label = f"~${total_cost:.4f}" + (" (partial — unpriced model)" if cost_is_partial else "")
            self.stdout.write(
                f"{identity}: {row.count} requests, {total_input} input / {total_output} output tokens, {cost_label}"
            )
            for model, model_totals in sorted(row.tokens.items()):
                self.stdout.write(f"    {model}: {model_totals.get('input', 0)} in / {model_totals.get('output', 0)} out")
