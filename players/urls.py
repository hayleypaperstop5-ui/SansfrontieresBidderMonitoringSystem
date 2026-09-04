from django.urls import path

from . import views

app_name = "players"

urlpatterns = [
    path(
        "",
        views.player_list,
        name="player_list",
    ),
    path(
        "add/",
        views.player_create,
        name="player_create",
    ),
    path(
        "chat-rates/",
        views.chat_rate_list,
        name="chat_rate_list",
    ),
    path(
        "chat-rates/add/",
        views.chat_rate_create,
        name="chat_rate_create",
    ),
    path(
        "<int:player_id>/edit/",
        views.player_edit,
        name="player_edit",
    ),
    path(
        "<int:player_id>/activate/",
        views.player_activate,
        name="player_activate",
    ),
    path(
        "<int:player_id>/deactivate/",
        views.player_deactivate,
        name="player_deactivate",
    ),
]
