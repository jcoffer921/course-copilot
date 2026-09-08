from django.db import migrations


def delete_seeded_anonymous_site(apps, schema_editor):
    SavedSite = apps.get_model("agent", "SavedSite")
    SavedSite.objects.filter(
        user__isnull=True,
        course_id="computer-graphics-algorithms",
        url__in=[
            "https://sites.google.com/site/webglbook/home/chapter-2",
            "https://sites.google.com/site/webglbook/home",
        ],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("agent", "0009_separate_calendar_connection")]
    operations = [migrations.RunPython(delete_seeded_anonymous_site, migrations.RunPython.noop)]
