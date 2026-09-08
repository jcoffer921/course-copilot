from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0017_exam_plan")]

    operations = [
        migrations.AddField(
            model_name="customevent",
            name="location",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="customevent",
            name="notes",
            field=models.TextField(blank=True, default=""),
        ),
    ]
