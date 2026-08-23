from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


def normalize_deadline_types(apps, schema_editor):
    CustomEvent = apps.get_model("agent", "CustomEvent")
    mapping = {
        "assignment": "hw",
        "homework": "hw",
        "exam": "test_quiz",
        "test": "test_quiz",
        "quiz": "test_quiz",
        "reading": "class",
        "lesson": "class",
    }
    valid = {"hw", "project", "test_quiz", "class", "other"}
    for event in CustomEvent.objects.all():
        raw = (event.type or "other").strip().lower().replace("-", "_").replace(" ", "_")
        event.type = mapping.get(raw, raw) if mapping.get(raw, raw) in valid else "other"
        event.save(update_fields=["type"])


class Migration(migrations.Migration):

    dependencies = [
        ("agent", "0005_customevent_replaces_syllabus_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="customevent",
            name="end_time",
            field=models.CharField(blank=True, max_length=5, null=True),
        ),
        migrations.AddField(
            model_name="customevent",
            name="completed",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(normalize_deadline_types, migrations.RunPython.noop),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("notification_key", models.CharField(max_length=255)),
                ("kind", models.CharField(max_length=64)),
                ("title", models.CharField(max_length=255)),
                ("body", models.TextField(blank=True)),
                ("course_id", models.CharField(blank=True, max_length=64, null=True)),
                ("deadline_id", models.CharField(blank=True, max_length=64, null=True)),
                ("due_date", models.CharField(blank=True, max_length=10, null=True)),
                ("category", models.CharField(blank=True, max_length=32)),
                ("read", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="notification",
            constraint=models.UniqueConstraint(fields=("user", "notification_key"), name="unique_notification_per_user_key"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "read", "created_at"], name="agent_notif_user_id_07b8f0_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "kind"], name="agent_notif_user_id_8cfca3_idx"),
        ),
    ]
