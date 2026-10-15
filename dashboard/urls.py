from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    # Main dashboard.
    # The view decides which dashboard to show based on the user's role.
    path("", views.dashboard, name="home"),
    path(
        "process-payroll/",
        views.process_director_payroll,
        name="process_payroll",
    ),

    # Profile
    path("profile/", views.profile, name="profile"),
    path("password-change/", views.password_change, name="password_change"),

    # Shift management / personal shifts
    path("my-shifts/", views.my_shifts, name="my_shifts"),

    # Coverage history
    path("coverage-history/", views.coverage_history, name="coverage_history"),

    # Development / administration test page
    path("admin-test/", views.admin_test, name="admin_test"),
]
