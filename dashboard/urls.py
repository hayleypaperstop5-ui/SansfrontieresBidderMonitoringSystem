from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard, name="home"),
    path("admin-test/", views.admin_test, name="admin_test"),
    path("my-shifts/", views.my_shifts, name="my_shifts"),
]
