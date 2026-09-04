from django.urls import path

from . import views

app_name = "monitoring"

urlpatterns = [
    path(
        "submit/",
        views.submit_chat,
        name="submit_chat",
    ),
]
