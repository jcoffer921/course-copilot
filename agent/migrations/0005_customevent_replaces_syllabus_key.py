from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agent", "0004_usersettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="customevent",
            name="replaces_syllabus_key",
            field=models.CharField(blank=True, max_length=512, null=True),
        ),
        migrations.AddIndex(
            model_name="customevent",
            index=models.Index(fields=["user", "replaces_syllabus_key"], name="agent_custo_user_id_587bc2_idx"),
        ),
    ]
