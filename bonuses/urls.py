from django.urls import path

from . import views


app_name = "bonuses"


urlpatterns = [
    path(
        "",
        views.bonus_settings,
        name="bonus_settings",
    ),
    path(
        "add/",
        views.bonus_settings_create,
        name="bonus_settings_create",
    ),
    path(
        "<int:bonus_id>/edit/",
        views.bonus_settings_edit,
        name="bonus_settings_edit",
    ),
]
