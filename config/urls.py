from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("players/", include("players.urls")),
    path("shifts/", include("shifts.urls")),
    path("reports/", include("reports.urls")),
    path("notifications/", include("notifications.urls")),
    path("coverage/", include("coverage.urls")),
    path("payments/", include("payments.urls")),
    path("bonuses/", include("bonuses.urls")),
]


