from django.test import TestCase
from django.urls import reverse

from accounts.models import StaffProfile, User
from coverage.models import CoverageSession
from .models import Player


class PlayerCoverageStatusTests(TestCase):

    def setUp(self):
        self.manager = User.objects.create_user(
            username="player_manager",
            password="testpass123",
            role=User.Role.MANAGER,
        )

        StaffProfile.objects.create(
            user=self.manager,
            status=StaffProfile.Status.ACTIVE,
        )

        self.player = Player.objects.create(
            player_number=1,
            name="Player One",
            status=Player.Status.ACTIVE,
        )

        self.client.force_login(self.manager)

    def test_active_player_without_coverage_can_be_deactivated(self):
        response = self.client.post(
            reverse(
                "players:player_deactivate",
                args=[self.player.id],
            )
        )

        self.assertEqual(response.status_code, 302)

        self.player.refresh_from_db()

        self.assertEqual(
            self.player.status,
            Player.Status.INACTIVE,
        )

    def test_player_with_open_coverage_cannot_be_deactivated(self):
        CoverageSession.objects.create(
            player=self.player,
            moderator=User.objects.create_user(
                username="coverage_moderator",
                password="testpass123",
                role=User.Role.MODERATOR,
            ),
            operating_date=self.player.created_at.date(),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.OPEN,
        )

        response = self.client.post(
            reverse(
                "players:player_deactivate",
                args=[self.player.id],
            )
        )

        self.assertEqual(response.status_code, 302)

        self.player.refresh_from_db()

        self.assertEqual(
            self.player.status,
            Player.Status.ACTIVE,
        )
