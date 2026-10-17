from django.urls import path

from . import views


app_name = "payments"

urlpatterns = [
    path("payroll/settle-moderator/<int:moderator_id>/", views.settle_moderator_payments, name="settle_moderator_payments"),
    path("moderator/<int:moderator_id>/reset-mpesa/", views.reset_moderator_mpesa, name="reset_moderator_mpesa"),
    path("moderator/<int:moderator_id>/set-mpesa/", views.set_moderator_mpesa, name="set_moderator_mpesa"),
    path("moderator/<int:moderator_id>/request-mpesa/", views.request_mpesa_notification, name="request_mpesa_notification"),
    path("payroll/payments/", views.payment_console, name="payment_console"),
    path("export/payments.csv", views.export_payments_csv, name="export_payments_csv"),
    path("payroll/settle/<int:payment_id>/pdf/", views.download_payment_statement_pdf, name="download_payment_statement_pdf"),
    path("my-payments/", views.my_payments, name="my_payments"),
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
