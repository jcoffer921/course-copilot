from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("agent", "0020_studysession_state")]
    operations = [
        migrations.AddField(model_name="notification", name="action_url", field=models.CharField(blank=True, max_length=1024)),
        migrations.AddField(model_name="notification", name="emailed_at", field=models.DateTimeField(blank=True, null=True)),
    ]
