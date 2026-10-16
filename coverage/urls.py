from django.urls import path
from . import views

app_name = "coverage"

urlpatterns = [
    path("opportunities/", views.coverage_opportunities, name="opportunities"),
    path("opportunities/<int:player_id>/apply/", views.apply_for_coverage, name="apply_for_coverage"),
    path("moderator/", views.moderator_coverage, name="moderator_coverage"),
    path(
        "<int:session_id>/report/",
        views.end_of_session_report,
        name="end_of_session_report",
    ),
    path(
        "reports/<int:report_id>/evidence/",
        views.download_report_evidence,
        name="download_report_evidence",
    ),
    path(
        "manager/alerts/",
        views.manager_coverage_alerts,
        name="manager_coverage_alerts",
    ),
    path(
        "credentials/<int:disclosure_id>/acknowledge/",
        views.acknowledge_credential,
        name="acknowledge_credential",
    ),
    path(
        "players/<int:player_id>/credentials/",
        views.player_credentials_view,
        name="player_credentials",
    ),
]
