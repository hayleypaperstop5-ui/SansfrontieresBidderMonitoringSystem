from django.contrib import admin

from .models import ShiftReport


@admin.register(ShiftReport)
class ShiftReportAdmin(admin.ModelAdmin):
    list_display = (
        "shift",
        "worker",
        "player",
        "chats_responded",
        "account_rating",
        "submitted_at",
    )

    list_filter = (
        "player",
        "submitted_at",
    )

    search_fields = (
        "worker__username",
        "worker__first_name",
        "worker__last_name",
        "player__name",
    )

    ordering = (
        "-submitted_at",
    )
