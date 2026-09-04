from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    path(
        "staff/",
        views.staff_list,
        name="staff_list",
    ),

    path(
        "staff/add/",
        views.staff_create,
        name="staff_create",
    ),

    path(
        "staff/<int:staff_id>/edit/",
        views.staff_edit,
        name="staff_edit",
    ),

    path(
        "staff/<int:staff_id>/activate/",
        views.staff_activate,
        name="staff_activate",
    ),

    path(
        "staff/<int:staff_id>/suspend/",
        views.staff_suspend,
        name="staff_suspend",
    ),

    path(
        "staff/<int:staff_id>/terminate/",
        views.staff_terminate,
        name="staff_terminate",
    ),
]
