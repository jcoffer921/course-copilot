from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0019_usersettings_study_preferences")]

    operations = [
        migrations.AddField(
            model_name="studysession",
            name="state",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
