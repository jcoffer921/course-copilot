import datetime

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0021_notification_delivery")]

    operations = [
        migrations.AddField(
            model_name="usersettings",
            name="study_reminder_time",
            field=models.TimeField(default=datetime.time(9, 0)),
        ),
    ]
