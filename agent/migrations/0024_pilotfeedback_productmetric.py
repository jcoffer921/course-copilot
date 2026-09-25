from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("agent", "0023_serviceheartbeat"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="PilotFeedback",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(choices=[("bug", "Something is broken"), ("confusing", "Something is confusing"), ("idea", "Idea or request"), ("other", "Other")], max_length=16)),
                ("message", models.TextField(max_length=2000)),
                ("page", models.CharField(blank=True, max_length=255)),
                ("status", models.CharField(default="new", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pilot_feedback", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="ProductMetric",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event", models.CharField(db_index=True, max_length=64)),
                ("course_id", models.CharField(blank=True, max_length=64)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="product_metrics", to=settings.AUTH_USER_MODEL)),
            ],
            options={"indexes": [models.Index(fields=["event", "created_at"], name="agent_metric_event_created_idx")]},
        ),
    ]
