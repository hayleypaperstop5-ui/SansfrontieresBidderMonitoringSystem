from django.test import TestCase
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.urls import reverse

from accounts.models import StaffProfile, User
from coverage.models import CoverageSession
from .models import Player, PlayerChatRateTier


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


class PlayerChatRateTierTests(TestCase):

    def setUp(self):
        self.player_one = Player.objects.create(
            player_number=1,
            name="Player One",
            status=Player.Status.ACTIVE,
        )

        self.player_two = Player.objects.create(
            player_number=2,
            name="Player Two",
            status=Player.Status.ACTIVE,
        )

    def test_valid_player_chat_rate_tier_can_be_created(self):
        tier = PlayerChatRateTier.objects.create(
            player=self.player_one,
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
        )

        self.assertEqual(tier.player, self.player_one)
        self.assertEqual(tier.rate_per_chat, Decimal("2.00"))

    def test_invalid_chat_range_is_rejected(self):
        tier = PlayerChatRateTier(
            player=self.player_one,
            minimum_chats=300,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
        )

        with self.assertRaises(ValidationError):
            tier.full_clean()

    def test_overlapping_active_tiers_for_same_player_are_rejected(self):
        PlayerChatRateTier.objects.create(
            player=self.player_one,
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
        )

        overlapping = PlayerChatRateTier(
            player=self.player_one,
            minimum_chats=200,
            maximum_chats=399,
            rate_per_chat="3.00",
        )

        with self.assertRaises(ValidationError):
            overlapping.full_clean()

    def test_same_range_is_allowed_for_different_players(self):
        PlayerChatRateTier.objects.create(
            player=self.player_one,
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
        )

        tier = PlayerChatRateTier(
            player=self.player_two,
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
        )

        tier.full_clean()

    def test_inactive_overlapping_tier_is_allowed(self):
        PlayerChatRateTier.objects.create(
            player=self.player_one,
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
        )

        tier = PlayerChatRateTier(
            player=self.player_one,
            minimum_chats=200,
            maximum_chats=399,
            rate_per_chat="3.00",
            active=False,
        )

        tier.full_clean()



class PlayerChatRateManagementTests(TestCase):

    def setUp(self):
        self.director = User.objects.create_user(
            username="rate_director",
            password="testpass123",
            role=User.Role.DIRECTOR,
        )

        self.moderator = User.objects.create_user(
            username="rate_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )

        self.player = Player.objects.create(
            player_number=10,
            name="Rate Test Player",
            status=Player.Status.ACTIVE,
        )

    def test_director_can_create_player_chat_rate(self):
        self.client.force_login(self.director)

        response = self.client.post(
            reverse("players:player_chat_rate_create"),
            {
                "player": self.player.id,
                "minimum_chats": 0,
                "maximum_chats": 299,
                "rate_per_chat": "2.50",
                "active": True,
                "effective_from": "2026-01-01",
            },
        )

        self.assertEqual(response.status_code, 302)

        tier = PlayerChatRateTier.objects.get(
            player=self.player,
        )

        self.assertEqual(tier.minimum_chats, 0)
        self.assertEqual(tier.maximum_chats, 299)
        self.assertEqual(
            tier.rate_per_chat,
            Decimal("2.50"),
        )
        self.assertTrue(tier.active)
        self.assertEqual(
            tier.effective_from.isoformat(),
            "2026-01-01",
        )

    def test_director_can_edit_player_chat_rate(self):
        tier = PlayerChatRateTier.objects.create(
            player=self.player,
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
            active=True,
            effective_from="2026-01-01",
        )

        self.client.force_login(self.director)

        response = self.client.post(
            reverse(
                "players:player_chat_rate_edit",
                args=[tier.id],
            ),
            {
                "player": self.player.id,
                "minimum_chats": 0,
                "maximum_chats": 399,
                "rate_per_chat": "3.00",
                "active": False,
                "effective_from": "2026-09-21",
            },
        )

        self.assertEqual(response.status_code, 302)

        tier.refresh_from_db()

        self.assertEqual(tier.maximum_chats, 399)
        self.assertEqual(
            tier.rate_per_chat,
            Decimal("3.00"),
        )
        self.assertFalse(tier.active)
        self.assertEqual(
            tier.effective_from.isoformat(),
            "2026-09-21",
        )

    def test_moderator_cannot_manage_player_chat_rates(self):
        self.client.force_login(self.moderator)

        urls = [
            reverse("players:player_chat_rate_list"),
            reverse("players:player_chat_rate_create"),
        ]

        tier = PlayerChatRateTier.objects.create(
            player=self.player,
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
        )

        urls.append(
            reverse(
                "players:player_chat_rate_edit",
                args=[tier.id],
            )
        )

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(
                    response.status_code,
                    302,
                )
                self.assertEqual(
                    response.url,
                    "/dashboard/",
                )
