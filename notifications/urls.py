from django.urls import path

from . import views


app_name = "notifications"

urlpatterns = [
    path(
        "status/",
        views.notification_status,
        name="status",
    ),
    path("", views.notification_list, name="list"),
    path(
        "<int:notification_id>/mark-as-read/",
        views.mark_as_read,
        name="mark_as_read",
    ),
]
