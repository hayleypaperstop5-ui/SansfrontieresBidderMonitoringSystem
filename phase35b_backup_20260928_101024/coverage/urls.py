from django.urls import path
from . import views

app_name = "coverage"

urlpatterns = [
    path(
        "<int:session_id>/report/",
        views.end_of_session_report,
        name="end_of_session_report",
    ),
    path(
        "manager/alerts/",
        views.manager_coverage_alerts,
        name="manager_coverage_alerts",
    ),
]
