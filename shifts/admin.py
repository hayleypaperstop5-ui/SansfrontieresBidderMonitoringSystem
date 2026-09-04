from django.contrib import admin

from .models import Shift


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "player",
        "primary_moderator",
        "substitute",  # Replacement Moderator
        "scheduled_start",
        "scheduled_end",
        "status",
    )

    list_filter = (
        "status",
        "date",
        "player",
    )

    search_fields = (
        "player__name",
        "primary_moderator__username",
        "primary_moderator__first_name",
        "primary_moderator__last_name",
        "substitute__username",
        "substitute__first_name",
        "substitute__last_name",
    )

    ordering = (
        "-date",
        "scheduled_start",
    )
