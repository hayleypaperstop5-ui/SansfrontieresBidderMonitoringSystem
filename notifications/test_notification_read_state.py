from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .models import Notification


class NotificationReadStateTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="notification_test_user",
            password="test-password-123",
        )

        if hasattr(self.user, "role"):
            self.user.role = "MODERATOR"
            self.user.save(update_fields=["role"])

        self.client.force_login(self.user)
        self.request_factory = RequestFactory()

    def create_notification(self, *, is_read=False, recipient=None):
        return Notification.objects.create(
            recipient=recipient or self.user,
            notification_type=Notification.NotificationType.GENERAL,
            title="Test notification",
            message="Test notification message.",
            is_read=is_read,
        )

    def get_notification_context(self):
        from .context_processors import notification_context

        request = self.request_factory.get(
            reverse("notifications:list")
        )
        request.user = self.user

        return notification_context(request)

    def test_notification_context_processor_exposes_unread_count(self):
        self.create_notification(is_read=False)
        self.create_notification(is_read=True)

        context = self.get_notification_context()

        self.assertEqual(
            context["unread_notification_count"],
            1,
        )

    def test_mark_as_read_marks_owned_notification(self):
        notification = self.create_notification(is_read=False)

        response = self.client.post(
            reverse(
                "notifications:mark_as_read",
                args=[notification.id],
            )
        )

        self.assertEqual(response.status_code, 302)

        notification.refresh_from_db()

        self.assertTrue(notification.is_read)

    def test_mark_as_read_removes_notification_from_unread_count(self):
        notification = self.create_notification(is_read=False)

        context = self.get_notification_context()

        self.assertEqual(
            context["unread_notification_count"],
            1,
        )

        response = self.client.post(
            reverse(
                "notifications:mark_as_read",
                args=[notification.id],
            )
        )

        self.assertEqual(response.status_code, 302)

        context = self.get_notification_context()

        self.assertEqual(
            context["unread_notification_count"],
            0,
        )

        notification.refresh_from_db()

        self.assertTrue(notification.is_read)

    def test_user_cannot_mark_another_users_notification_as_read(self):
        User = get_user_model()

        other_user = User.objects.create_user(
            username="another_notification_user",
            password="test-password-123",
        )

        notification = self.create_notification(
            is_read=False,
            recipient=other_user,
        )

        response = self.client.post(
            reverse(
                "notifications:mark_as_read",
                args=[notification.id],
            )
        )

        self.assertEqual(response.status_code, 404)

        notification.refresh_from_db()

        self.assertFalse(notification.is_read)
