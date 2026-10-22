from django.conf.urls.static import static
from django.conf import settings
from django.contrib import admin
from django.views.generic import RedirectView
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
    path("", RedirectView.as_view(url="/login/", permanent=False)),
]

# Serve static files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
