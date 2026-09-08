from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0030_llmusage")]

    operations = [
        migrations.AddField(model_name="usersettings", name="bio", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="usersettings", name="university", field=models.CharField(blank=True, default="", max_length=150)),
        migrations.AddField(model_name="usersettings", name="major", field=models.CharField(blank=True, default="", max_length=150)),
        migrations.AddField(model_name="usersettings", name="graduation_year", field=models.PositiveSmallIntegerField(blank=True, null=True)),
    ]
