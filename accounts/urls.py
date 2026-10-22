from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/password_reset.html",
            email_template_name="accounts/password_reset_email.txt",
            subject_template_name="accounts/password_reset_subject.txt",
            success_url="/password-reset/done/",
        ),
        name="password_reset",
    ),

    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset/confirm/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url="/password-reset/complete/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),    path("logout/", views.logout_view, name="logout"),

    path("staff/", views.staff_list, name="staff_list"),
    path("staff/add/", views.staff_create, name="staff_create"),
    path("staff/invite/<int:invitation_id>/<str:token>/setup/", views.staff_invitation_setup, name="staff_invitation_setup"),
    path("staff/<int:staff_id>/resend-invitation/", views.staff_resend_invitation, name="staff_resend_invitation"),
    path("staff/<int:staff_id>/revoke-invitation/", views.staff_revoke_invitation, name="staff_revoke_invitation"),
    path("staff/<int:staff_id>/edit/", views.staff_edit, name="staff_edit"),
    path("staff/<int:staff_id>/", views.staff_detail, name="staff_detail"),
    path("staff/<int:staff_id>/activate/", views.staff_activate, name="staff_activate"),
    path("staff/<int:staff_id>/suspend/", views.staff_suspend, name="staff_suspend"),
    path("staff/<int:staff_id>/terminate/", views.staff_terminate, name="staff_terminate"),

    path("roles/", views.role_list, name="role_list"),
    path("roles/add/", views.role_create, name="role_create"),
    path("roles/<int:role_id>/toggle/", views.role_toggle, name="role_toggle"),
]





