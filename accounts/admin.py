from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import StaffProfile, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):

    fieldsets = UserAdmin.fieldsets + (
        (
            "Sansfrontieres Role",
            {
                "fields": ("role",),
            },
        ),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Sansfrontieres Role",
            {
                "fields": ("role",),
            },
        ),
    )

    list_display = (
        "username",
        "first_name",
        "last_name",
        "email",
        "role",
        "is_active",
        "is_staff",
    )

    list_filter = (
        "role",
        "is_active",
        "is_staff",
    )


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):

    list_display = (
        "user",
        "employee_number",
        "phone_number",
        "status",
        "joined_date",
    )

    list_filter = (
        "status",
    )

    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
        "phone_number",
        "employee_number",
    )

    list_select_related = (
        "user",
    )
