from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path(
        "shift/<int:shift_id>/submit/",
        views.shift_report_submit,
        name="shift_report_submit",
    ),
]
