from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("agent", "0024_pilotfeedback_productmetric")]
    operations = [
        migrations.AlterField(
            model_name="pilotfeedback",
            name="user",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pilot_feedback", to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name="ContactRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150)),
                ("email", models.EmailField(max_length=254)),
                ("topic", models.CharField(choices=[("account", "Account or sign-in"), ("technical", "Technical problem"), ("privacy", "Privacy or data request"), ("partnership", "Pilot or partnership"), ("other", "Something else")], max_length=20)),
                ("subject", models.CharField(max_length=160)),
                ("message", models.TextField(max_length=4000)),
                ("status", models.CharField(default="new", max_length=16)),
                ("request_id", models.CharField(blank=True, max_length=80)),
                ("emailed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="contact_requests", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
