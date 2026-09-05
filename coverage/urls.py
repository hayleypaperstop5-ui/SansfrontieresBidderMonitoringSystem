from django.urls import path

from .views import manager_coverage_alerts

app_name = "coverage"

urlpatterns = [
    path(
        "manager/alerts/",
        manager_coverage_alerts,
        name="manager_coverage_alerts",
    ),
]
