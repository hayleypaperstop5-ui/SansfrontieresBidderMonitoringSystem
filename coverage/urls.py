from django.urls import path

from .views import end_of_session_report, manager_coverage_alerts

app_name = "coverage"

urlpatterns = [
    path(
        "<int:session_id>/report/",
        end_of_session_report,
        name="end_of_session_report",
    ),
    path(
        "manager/alerts/",
        manager_coverage_alerts,
        name="manager_coverage_alerts",
    ),
]
