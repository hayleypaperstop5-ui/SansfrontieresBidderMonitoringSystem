from django.test import TestCase

from accounts.models import User

# Create your tests here.

class DashboardRenderTests(TestCase):
    """Verify the dashboard renders without errors for each role."""

    def setUp(self):
        from accounts.models import StaffProfile
        self.director = User.objects.create_user(
            username="render_director",
            password="testpass123",
            role=User.Role.DIRECTOR,
        )
        self.manager = User.objects.create_user(
            username="render_manager",
            password="testpass123",
            role=User.Role.MANAGER,
        )
        self.admin = User.objects.create_user(
            username="render_admin",
            password="testpass123",
            role=User.Role.ADMIN,
        )
        self.moderator = User.objects.create_user(
            username="render_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        StaffProfile.objects.create(
            user=self.moderator, status=StaffProfile.Status.ACTIVE,
        )

    def _get_dashboard(self, user):
        from django.test import Client
        c = Client()
        c.force_login(user)
        return c.get("/dashboard/")

    def test_director_dashboard_renders(self):
        response = self._get_dashboard(self.director)
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.content), 10000)

    def test_manager_dashboard_renders(self):
        response = self._get_dashboard(self.manager)
        self.assertEqual(response.status_code, 200)

    def test_admin_dashboard_renders(self):
        response = self._get_dashboard(self.admin)
        self.assertEqual(response.status_code, 200)

    def test_moderator_dashboard_renders(self):
        response = self._get_dashboard(self.moderator)
        self.assertEqual(response.status_code, 200)
