from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import StaffProfile, User
from players.models import Player

from .models import CoverageSession, EndOfSessionReport
from .services import (
    end_coverage_session,
    get_uncovered_players,
    request_replacement,
    start_coverage_session,
    assign_replacement,
)


class CoverageServiceTests(TestCase):

    def setUp(self):
        self.moderator_one = User.objects.create_user(
            username="moderator_one",
            password="testpass123",
            role=User.Role.MODERATOR,
            first_name="Moderator",
            last_name="One",
        )

        self.moderator_two = User.objects.create_user(
            username="moderator_two",
            password="testpass123",
            role=User.Role.MODERATOR,
            first_name="Moderator",
            last_name="Two",
        )

        StaffProfile.objects.create(
            user=self.moderator_one,
            status=StaffProfile.Status.ACTIVE,
        )

        StaffProfile.objects.create(
            user=self.moderator_two,
            status=StaffProfile.Status.ACTIVE,
        )

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

        self.moment = timezone.localtime()

    def test_moderator_can_start_coverage(self):
        session = start_coverage_session(
            moderator=self.moderator_one,
            player=self.player_one,
            moment=self.moment,
        )

        self.assertEqual(session.status, CoverageSession.Status.ACTIVE)
        self.assertEqual(session.moderator, self.moderator_one)
        self.assertEqual(session.player, self.player_one)

    def test_moderator_cannot_cover_two_players_at_once(self):
        start_coverage_session(
            moderator=self.moderator_one,
            player=self.player_one,
            moment=self.moment,
        )

        with self.assertRaises(ValidationError):
            start_coverage_session(
                moderator=self.moderator_one,
                player=self.player_two,
                moment=self.moment,
            )

    def test_player_cannot_have_two_moderators_at_once(self):
        start_coverage_session(
            moderator=self.moderator_one,
            player=self.player_one,
            moment=self.moment,
        )

        with self.assertRaises(ValidationError):
            start_coverage_session(
                moderator=self.moderator_two,
                player=self.player_one,
                moment=self.moment,
            )

    def test_normal_sign_out_is_blocked(self):
        session = start_coverage_session(
            moderator=self.moderator_one,
            player=self.player_one,
            moment=self.moment,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "You cannot sign out while covering this Player.",
        ):
            end_coverage_session(
                session=session,
                moderator=self.moderator_one,
                moment=self.moment + timedelta(minutes=10),
            )

        session.refresh_from_db()

        self.assertEqual(
            session.status,
            CoverageSession.Status.ACTIVE,
        )

    def test_moderator_can_request_replacement(self):
        session = start_coverage_session(
            moderator=self.moderator_one,
            player=self.player_one,
            moment=self.moment,
        )

        request_replacement(
            session=session,
            moderator=self.moderator_one,
            moment=self.moment + timedelta(minutes=10),
        )

        session.refresh_from_db()

        self.assertEqual(
            session.status,
            CoverageSession.Status.REPLACEMENT_REQUESTED,
        )

        self.assertIsNotNone(session.replacement_requested_at)

    def test_uncovered_player_is_detected(self):
        uncovered = list(
            get_uncovered_players(
                moment=self.moment,
            )
        )

        self.assertEqual(
            [player.id for player in uncovered],
            [self.player_one.id, self.player_two.id],
        )

    def test_covered_player_is_not_uncovered(self):
        start_coverage_session(
            moderator=self.moderator_one,
            player=self.player_one,
            moment=self.moment,
        )

        uncovered = list(
            get_uncovered_players(
                moment=self.moment,
            )
        )

        self.assertNotIn(
            self.player_one.id,
            [player.id for player in uncovered],
        )

        self.assertIn(
            self.player_two.id,
            [player.id for player in uncovered],
        )

    def test_inactive_moderator_cannot_start_coverage(self):
        profile = self.moderator_one.staff_profile
        profile.status = StaffProfile.Status.INACTIVE
        profile.save()

        with self.assertRaises(ValidationError):
            start_coverage_session(
                moderator=self.moderator_one,
                player=self.player_one,
                moment=self.moment,
            )

    def test_inactive_player_cannot_receive_coverage(self):
        self.player_one.status = Player.Status.INACTIVE
        self.player_one.save()

        with self.assertRaises(ValidationError):
            start_coverage_session(
                moderator=self.moderator_one,
                player=self.player_one,
                moment=self.moment,
            )

    def test_non_moderator_cannot_start_coverage(self):
        manager = User.objects.create_user(
            username="manager_one",
            password="testpass123",
            role=User.Role.MANAGER,
        )

        StaffProfile.objects.create(
            user=manager,
            status=StaffProfile.Status.ACTIVE,
        )

        with self.assertRaises(ValidationError):
            start_coverage_session(
                moderator=manager,
                player=self.player_one,
                moment=self.moment,
            )

    def test_moderator_cannot_request_replacement_for_another_moderator(self):
        session = start_coverage_session(
            moderator=self.moderator_one,
            player=self.player_one,
            moment=self.moment,
        )

        with self.assertRaises(ValidationError):
            request_replacement(
                session=session,
                moderator=self.moderator_two,
                moment=self.moment + timedelta(minutes=5),
            )

    def test_manager_can_override_end_coverage(self):
        manager = User.objects.create_user(
            username="manager_override",
            password="testpass123",
            role=User.Role.MANAGER,
        )

        StaffProfile.objects.create(
            user=manager,
            status=StaffProfile.Status.ACTIVE,
        )

        session = start_coverage_session(
            moderator=self.moderator_one,
            player=self.player_one,
            moment=self.moment,
        )

        override_time = self.moment + timedelta(minutes=30)

        from .services import manager_override_end_coverage

        result = manager_override_end_coverage(
            session=session,
            manager=manager,
            moment=override_time,
        )

        result.refresh_from_db()

        self.assertEqual(
            result.status,
            CoverageSession.Status.COMPLETED,
        )
        self.assertEqual(
            result.signed_out_at,
            override_time,
        )
        self.assertEqual(
            result.closure_reason,
            CoverageSession.ClosureReason.MANAGER_OVERRIDE,
        )

    def test_moderator_cannot_use_manager_override(self):
        session = start_coverage_session(
            moderator=self.moderator_one,
            player=self.player_one,
            moment=self.moment,
        )

        from .services import manager_override_end_coverage

        with self.assertRaises(ValidationError):
            manager_override_end_coverage(
                session=session,
                manager=self.moderator_two,
                moment=self.moment + timedelta(minutes=10),
            )

        session.refresh_from_db()

        self.assertEqual(
            session.status,
            CoverageSession.Status.ACTIVE,
        )

    def _create_signed_out_session(self):
        session = start_coverage_session(
            moderator=self.moderator_one,
            player=self.player_one,
            moment=self.moment,
        )

        request_replacement(
            session=session,
            moderator=self.moderator_one,
            moment=self.moment + timedelta(minutes=5),
        )

        assign_replacement(
            session=session,
            replacement_moderator=self.moderator_two,
            moment=self.moment + timedelta(minutes=10),
        )

        session.refresh_from_db()
        return session

    def test_end_of_session_report_page_loads_for_signed_out_session(self):
        session = self._create_signed_out_session()

        self.client.force_login(self.moderator_one)

        response = self.client.get(
            reverse(
                "coverage:end_of_session_report",
                args=[session.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "End-of-Session Report")
        self.assertContains(response, "Player One")

    def test_moderator_cannot_report_on_another_moderators_session(self):
        session = self._create_signed_out_session()

        self.client.force_login(self.moderator_two)

        response = self.client.get(
            reverse(
                "coverage:end_of_session_report",
                args=[session.id],
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:home"))

        self.assertEqual(
            EndOfSessionReport.objects.count(),
            0,
        )

    def test_report_cannot_be_submitted_before_sign_out(self):
        session = start_coverage_session(
            moderator=self.moderator_one,
            player=self.player_one,
            moment=self.moment,
        )

        self.client.force_login(self.moderator_one)

        response = self.client.get(
            reverse(
                "coverage:end_of_session_report",
                args=[session.id],
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:home"))

    def test_moderator_can_submit_end_of_session_report(self):
        session = self._create_signed_out_session()

        self.client.force_login(self.moderator_one)

        response = self.client.post(
            reverse(
                "coverage:end_of_session_report",
                args=[session.id],
            ),
            {
                "chats_responded": 725,
                "account_rating": "8.50",
                "comments": "Session completed successfully.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:home"))

        report = EndOfSessionReport.objects.get(
            coverage_session=session,
        )

        self.assertEqual(report.moderator, self.moderator_one)
        self.assertEqual(report.player, self.player_one)
        self.assertEqual(report.chats_responded, 725)
        self.assertEqual(str(report.account_rating), "8.50")
        self.assertEqual(
            report.comments,
            "Session completed successfully.",
        )

        session.refresh_from_db()

        self.assertEqual(
            session.status,
            CoverageSession.Status.COMPLETED,
        )

    def test_duplicate_end_of_session_report_is_blocked(self):
        session = self._create_signed_out_session()

        EndOfSessionReport.objects.create(
            coverage_session=session,
            moderator=self.moderator_one,
            player=self.player_one,
            chats_responded=700,
            account_rating="9.00",
            comments="Existing report.",
        )

        self.client.force_login(self.moderator_one)

        response = self.client.get(
            reverse(
                "coverage:end_of_session_report",
                args=[session.id],
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:home"))

        self.assertEqual(
            EndOfSessionReport.objects.count(),
            1,
        )
