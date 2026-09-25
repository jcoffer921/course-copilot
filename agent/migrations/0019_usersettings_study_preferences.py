import agent.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0018_customevent_location_notes")]

    operations = [
        migrations.AddField(model_name="usersettings", name="timezone", field=models.CharField(default="America/New_York", max_length=64)),
        migrations.AddField(model_name="usersettings", name="preferred_session_minutes", field=models.PositiveSmallIntegerField(default=45)),
        migrations.AddField(model_name="usersettings", name="available_study_days", field=models.JSONField(blank=True, default=agent.models.default_available_study_days)),
        migrations.AddField(model_name="usersettings", name="reminder_lead_minutes", field=models.PositiveSmallIntegerField(default=15)),
    ]
