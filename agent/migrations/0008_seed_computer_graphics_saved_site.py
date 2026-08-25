from django.db import migrations


COURSE_ID = "computer-graphics-algorithms"
SITES = [
    {
        "title": "WebGL Programming Guide Chapter 2",
        "url": "https://sites.google.com/site/webglbook/home/chapter-2",
        "user_email": None,
    },
    {
        "title": "Course Book",
        "url": "https://sites.google.com/site/webglbook/home",
        "user_email": "jcoffer921@gmail.com",
    },
]


def seed_saved_sites(apps, schema_editor):
    SavedSite = apps.get_model("agent", "SavedSite")
    User = apps.get_model("auth", "User")

    for site in SITES:
        user = None
        if site["user_email"]:
            user = User.objects.filter(email=site["user_email"]).first()
        SavedSite.objects.update_or_create(
            course_id=COURSE_ID,
            user=user,
            url=site["url"],
            defaults={"title": site["title"]},
        )


def unseed_saved_sites(apps, schema_editor):
    SavedSite = apps.get_model("agent", "SavedSite")
    urls = [site["url"] for site in SITES]
    SavedSite.objects.filter(course_id=COURSE_ID, url__in=urls).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("agent", "0007_savedsite"),
    ]

    operations = [
        migrations.RunPython(seed_saved_sites, unseed_saved_sites),
    ]
