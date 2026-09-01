from django.contrib import admin

from .models import ContactRequest, PilotFeedback


@admin.register(PilotFeedback)
class PilotFeedbackAdmin(admin.ModelAdmin):
    list_display = ("id", "category", "identity", "status", "page", "created_at")
    list_filter = ("category", "status", "created_at")
    search_fields = ("message", "page", "user__email")
    readonly_fields = ("created_at",)

    @admin.display(description="Submitted by")
    def identity(self, obj):
        return obj.user.email if obj.user_id else "Anonymous"


@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "topic", "email", "status", "created_at")
    list_filter = ("topic", "status", "created_at")
    search_fields = ("name", "email", "subject", "message")
    readonly_fields = ("created_at", "emailed_at", "request_id")
