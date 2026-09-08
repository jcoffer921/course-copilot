from django.conf import settings
from django.db import migrations


def backfill_active(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    UserSettings = apps.get_model("agent", "UserSettings")

    UserSettings.objects.update(access_status="active")

    existing_user_ids = UserSettings.objects.values_list("user_id", flat=True)
    for user in User.objects.exclude(pk__in=existing_user_ids):
        UserSettings.objects.create(user=user, access_status="active")


def reverse_backfill(apps, schema_editor):
    UserSettings = apps.get_model("agent", "UserSettings")
    UserSettings.objects.update(access_status="pending")


class Migration(migrations.Migration):

    dependencies = [
        ("agent", "0027_usersettings_access_status_usersettings_cohort_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_active, reverse_backfill),
    ]
