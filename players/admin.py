from django.contrib import admin

from .models import Player, ChatRateTier


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):

    list_display = (
        "player_number",
        "name",
        "status",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "status",
    )

    search_fields = (
        "name",
    )

    ordering = (
        "player_number",
    )


@admin.register(ChatRateTier)
class ChatRateTierAdmin(admin.ModelAdmin):

    list_display = (
        "minimum_chats",
        "maximum_chats",
        "rate_per_chat",
        "active",
        "effective_from",
    )

    list_filter = (
        "active",
        "effective_from",
    )

    search_fields = (
        "minimum_chats",
        "maximum_chats",
    )

    ordering = (
        "minimum_chats",
    )
