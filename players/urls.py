from django.urls import path
from django.views.generic import RedirectView

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
    ),    path(
        "chat-rates/<int:rate_id>/edit/",
        views.chat_rate_edit,
        name="chat_rate_edit",
    ),
    path(
        "player-chat-rates/",
        RedirectView.as_view(
            pattern_name="players:chat_rate_list",
            permanent=False,
        ),
        name="player_chat_rate_list_redirect",
    ),
    path(
        "player-chat-rates/add/",
        RedirectView.as_view(
            pattern_name="players:chat_rate_create",
            permanent=False,
        ),
        name="player_chat_rate_create_redirect",
    ),
    path(
        "player-chat-rates/<int:rate_id>/edit/",
        RedirectView.as_view(
            url="/players/chat-rates/",
            permanent=False,
        ),
        name="player_chat_rate_edit_redirect",
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

