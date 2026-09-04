from django.urls import path

from . import views

app_name = "shifts"

urlpatterns = [
    path("", views.shift_list, name="shift_list"),
    path("add/", views.shift_create, name="shift_create"),
    path(
        "<int:shift_id>/assign-substitute/",
        views.shift_assign_substitute,
        name="shift_assign_substitute",
    ),
    path(
        "<int:shift_id>/sign-in/",
        views.shift_sign_in,
        name="shift_sign_in",
    ),
    path(
        "<int:shift_id>/sign-out/",
        views.shift_sign_out,
        name="shift_sign_out",
    ),
]
