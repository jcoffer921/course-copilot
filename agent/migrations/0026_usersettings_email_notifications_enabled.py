from django.db import migrations, models


def preserve_existing_email_preferences(apps, schema_editor):
    UserSettings = apps.get_model("agent", "UserSettings")
    UserSettings.objects.filter(notifications_enabled=True).update(email_notifications_enabled=True)


class Migration(migrations.Migration):
    dependencies = [("agent", "0025_contactrequest_alter_pilotfeedback_user")]

    operations = [
        migrations.AddField(
            model_name="usersettings",
            name="email_notifications_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(preserve_existing_email_preferences, migrations.RunPython.noop),
    ]
