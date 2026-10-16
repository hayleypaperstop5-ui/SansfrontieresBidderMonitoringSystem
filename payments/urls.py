from django.urls import path

from . import views


app_name = "payments"

urlpatterns = [
    path("payroll/settle/<int:payment_id>/", views.settle_payment, name="settle_payment"),
    path("settings/", views.payment_settings, name="payment_settings"),
path(
    "payroll/review/",
    views.payroll_review,
    name="payroll_review",
),
path(
    "payroll/process/",
    views.process_payroll,
    name="payroll_process",
),
path(
    "payroll/results/",
    views.payroll_results,
    name="payroll_results",
),
    path("", views.payment_history, name="history"),
    path("moderator-payments/<int:payment_id>/settle/", views.settle_moderator_payment_view, name="settle_moderator_payment"),
]
