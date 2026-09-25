import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


PRIVATE_MODELS = (
    "FlashcardProgress",
    "GradeItem",
    "CalendarSyncRecord",
    "CustomEvent",
    "Notification",
    "SavedSite",
    "QuizAttempt",
    "MasteryScore",
    "CourseSession",
)


def reject_unowned_private_rows(apps, schema_editor):
    counts = {}
    for model_name in PRIVATE_MODELS:
        model = apps.get_model("agent", model_name)
        count = model.objects.filter(user__isnull=True).count()
        if count:
            counts[model_name] = count
    if counts:
        summary = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
        raise RuntimeError(
            "Cannot require private-state ownership while anonymous rows remain: "
            f"{summary}. Review and explicitly migrate or delete them first."
        )


def owner_field(related_name):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.CASCADE,
        related_name=related_name,
        to=settings.AUTH_USER_MODEL,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("agent", "0010_delete_anonymous_seeded_saved_site"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.RunPython(reject_unowned_private_rows, migrations.RunPython.noop),
        migrations.AlterField(model_name="flashcardprogress", name="user", field=owner_field("flashcard_progress")),
        migrations.AlterField(model_name="gradeitem", name="user", field=owner_field("grade_items")),
        migrations.AlterField(model_name="calendarsyncrecord", name="user", field=owner_field("calendar_sync_records")),
        migrations.AlterField(model_name="customevent", name="user", field=owner_field("custom_events")),
        migrations.AlterField(model_name="notification", name="user", field=owner_field("notifications")),
        migrations.AlterField(model_name="savedsite", name="user", field=owner_field("saved_sites")),
        migrations.AlterField(model_name="quizattempt", name="user", field=owner_field("quiz_attempts")),
        migrations.AlterField(model_name="masteryscore", name="user", field=owner_field("mastery_scores")),
        migrations.AlterField(model_name="coursesession", name="user", field=owner_field("course_sessions")),
        migrations.RemoveConstraint(model_name="savedsite", name="unique_saved_site_anonymous"),
        migrations.RemoveConstraint(model_name="savedsite", name="unique_saved_site_per_user"),
        migrations.AddConstraint(
            model_name="savedsite",
            constraint=models.UniqueConstraint(
                fields=("course_id", "user", "url"),
                name="unique_saved_site_per_user",
            ),
        ),
    ]
