from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0022_usersettings_study_reminder_time")]
    operations = [
        migrations.CreateModel(
            name="ServiceHeartbeat",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=64, unique=True)),
                ("status", models.CharField(default="ok", max_length=16)),
                ("detail", models.CharField(blank=True, max_length=255)),
                ("checked_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
