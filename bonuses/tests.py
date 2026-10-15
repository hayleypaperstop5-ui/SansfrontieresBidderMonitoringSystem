from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone


def create_completed_session(*, player, moderator, signed_in_at, signed_out_at):
    """Create a CoverageSession using the current production model fields."""
    return CoverageSession.objects.create(
        player=player,
        moderator=moderator,
        operating_date=signed_in_at.date(),
        session_type="DAY",
        signed_in_at=signed_in_at,
        signed_out_at=signed_out_at,
        status=CoverageSession.Status.COMPLETED,
    )


def create_report(*, session, moderator, chats_responded, submitted_at, comments):
    """
    Create an EndOfSessionReport and explicitly set submitted_at.

    submitted_at is auto_now_add=True in production, so passing it to
    objects.create() does not preserve the requested test timestamp.
    """
    report = EndOfSessionReport.objects.create(
        coverage_session=session,
        moderator=moderator,
        player=session.player,
        chats_responded=chats_responded,
        account_rating=10,
        comments=comments,
    )

    EndOfSessionReport.objects.filter(pk=report.pk).update(
        submitted_at=submitted_at
    )

    report.refresh_from_db()
    return report

from coverage.models import CoverageSession, EndOfSessionReport
from players.models import Player

from .models import BonusAward, ChatBonusTier
from .services import (
    QUALIFYING_WINDOW_HOURS,
    calculate_chats_within_window,
    determine_daily_moderator_bonuses,
    evaluate_all_moderator_bonuses,
    evaluate_moderator_bonus,
    get_applicable_bonus_tier,
    get_reports_within_window,
)

User = get_user_model()


class BonusModelTests(TestCase):
    def setUp(self):
        self.moderator = User.objects.create_user(
            username="mod1",
            email="mod1@example.com",
            password="password",
            role=User.Role.MODERATOR,
        )

        self.player = Player.objects.create(
            name="Player A",
            player_number=1,
        )

        self.session = create_completed_session(
            player=self.player,
            moderator=self.moderator,
            signed_in_at=timezone.now() - timedelta(hours=4),
            signed_out_at=timezone.now() - timedelta(hours=1),
        )

        self.report = create_report(
            session=self.session,
            moderator=self.moderator,
            chats_responded=550,
            submitted_at=timezone.now() - timedelta(hours=1),
            comments="Completed session",
        )

        self.tier = ChatBonusTier.objects.create(
            minimum_chats=500,
            maximum_chats=699,
            bonus_amount=Decimal("200.00"),
            qualifying_window_hours=24,
            active=True,
        )

    def test_tier_clean_validates_max_greater_than_min(self):
        invalid_tier = ChatBonusTier(
            minimum_chats=500,
            maximum_chats=400,
            bonus_amount=Decimal("100.00"),
            qualifying_window_hours=24,
            active=True,
        )

        with self.assertRaises(ValidationError):
            invalid_tier.clean()

    def test_tier_clean_detects_overlapping_ranges(self):
        overlapping_tier = ChatBonusTier(
            minimum_chats=450,
            maximum_chats=550,
            bonus_amount=Decimal("150.00"),
            qualifying_window_hours=24,
            active=True,
        )

        with self.assertRaises(ValidationError):
            overlapping_tier.clean()

    def test_award_clean_validates_window_dates(self):
        now = timezone.now()
        invalid_award = BonusAward(
            moderator=self.moderator,
            player=self.player,
            qualifying_report=self.report,
            bonus_tier=self.tier,
            bonus_date=timezone.localdate(),
            qualifying_window_start=now,
            qualifying_window_end=now - timedelta(hours=1),
            chats_counted=550,
            minimum_chats_snapshot=500,
            maximum_chats_snapshot=699,
            qualifying_window_hours_snapshot=24,
            bonus_amount=Decimal("200.00"),
        )

        with self.assertRaises(ValidationError):
            invalid_award.clean()

    def test_award_clean_validates_chats_counted_against_minimum(self):
        now = timezone.now()
        invalid_award = BonusAward(
            moderator=self.moderator,
            player=self.player,
            qualifying_report=self.report,
            bonus_tier=self.tier,
            bonus_date=timezone.localdate(),
            qualifying_window_start=now - timedelta(hours=24),
            qualifying_window_end=now,
            chats_counted=400,
            minimum_chats_snapshot=500,
            maximum_chats_snapshot=699,
            qualifying_window_hours_snapshot=24,
            bonus_amount=Decimal("200.00"),
        )

        with self.assertRaises(ValidationError):
            invalid_award.clean()


class BonusServiceTests(TestCase):
    def setUp(self):
        self.moderator = User.objects.create_user(
            username="mod1",
            email="mod1@example.com",
            password="password",
            role=User.Role.MODERATOR,
        )

        self.player1 = Player.objects.create(
            name="Player A",
            player_number=1,
        )

        self.player2 = Player.objects.create(
            name="Player B",
            player_number=2,
        )

        self.tier_500 = ChatBonusTier.objects.create(
            minimum_chats=500,
            maximum_chats=699,
            bonus_amount=Decimal("200.00"),
            qualifying_window_hours=24,
            active=True,
        )

        self.tier_700 = ChatBonusTier.objects.create(
            minimum_chats=700,
            maximum_chats=999,
            bonus_amount=Decimal("350.00"),
            qualifying_window_hours=24,
            active=True,
        )

        self.tier_1000 = ChatBonusTier.objects.create(
            minimum_chats=1000,
            maximum_chats=None,
            bonus_amount=Decimal("500.00"),
            qualifying_window_hours=24,
            active=True,
        )

        self.test_date = date(2026, 3, 15)
        self.local_tz = timezone.get_current_timezone()
        self.window_end = timezone.make_aware(
            datetime.combine(self.test_date, time(9, 45)),
            self.local_tz,
        )

    def test_applicable_tier_returns_highest_matching_tier(self):
        tier = get_applicable_bonus_tier(
            chats_counted=750,
            bonus_date=self.test_date,
        )
        self.assertEqual(tier, self.tier_700)

    def test_exactly_500_chats_qualifies_for_200_bonus(self):
        session = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=3),
            signed_out_at=self.window_end - timedelta(hours=1),
        )

        create_report(
            session=session,
            moderator=self.moderator,
            chats_responded=500,
            submitted_at=self.window_end - timedelta(hours=1),
            comments="500 chats hit",
        )

        awards = evaluate_moderator_bonus(
            moderator=self.moderator,
            window_end=self.window_end,
            bonus_date=self.test_date,
        )

        self.assertIsNotNone(awards)
        self.assertEqual(len(awards), 1)
        award = awards[0]
        self.assertEqual(award.bonus_tier, self.tier_500)
        self.assertEqual(award.bonus_amount, Decimal("200.00"))

    def test_700_chats_uses_700_tier(self):
        session = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=5),
            signed_out_at=self.window_end - timedelta(hours=2),
        )

        create_report(
            session=session,
            moderator=self.moderator,
            chats_responded=700,
            submitted_at=self.window_end - timedelta(hours=2),
            comments="700 chats hit",
        )

        awards = evaluate_moderator_bonus(
            moderator=self.moderator,
            window_end=self.window_end,
            bonus_date=self.test_date,
        )

        self.assertEqual(len(awards), 1)
        award = awards[0]
        self.assertEqual(award.bonus_tier, self.tier_700)
        self.assertEqual(award.bonus_amount, Decimal("350.00"))

    def test_1000_chats_uses_open_ended_tier(self):
        session = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=8),
            signed_out_at=self.window_end - timedelta(hours=3),
        )

        create_report(
            session=session,
            moderator=self.moderator,
            chats_responded=1200,
            submitted_at=self.window_end - timedelta(hours=3),
            comments="1200 chats hit",
        )

        awards = evaluate_moderator_bonus(
            moderator=self.moderator,
            window_end=self.window_end,
            bonus_date=self.test_date,
        )

        self.assertEqual(len(awards), 1)
        award = awards[0]
        self.assertEqual(award.bonus_tier, self.tier_1000)
        self.assertEqual(award.bonus_amount, Decimal("500.00"))

    def test_below_minimum_chats_does_not_qualify(self):
        session = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=3),
            signed_out_at=self.window_end - timedelta(hours=1),
        )

        create_report(
            session=session,
            moderator=self.moderator,
            chats_responded=499,
            submitted_at=self.window_end - timedelta(hours=1),
            comments="Only 499 chats",
        )

        awards = evaluate_moderator_bonus(
            moderator=self.moderator,
            window_end=self.window_end,
            bonus_date=self.test_date,
        )

        self.assertEqual(len(awards), 0)

    def test_chats_across_multiple_reports_are_accumulated_per_player(self):
        session1 = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=20),
            signed_out_at=self.window_end - timedelta(hours=16),
        )

        session2 = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=8),
            signed_out_at=self.window_end - timedelta(hours=4),
        )

        create_report(
            session=session1,
            moderator=self.moderator,
            chats_responded=300,
            submitted_at=self.window_end - timedelta(hours=16),
            comments="First session on Player A",
        )

        create_report(
            session=session2,
            moderator=self.moderator,
            chats_responded=250,
            submitted_at=self.window_end - timedelta(hours=4),
            comments="Second session on Player A",
        )

        awards = evaluate_moderator_bonus(
            moderator=self.moderator,
            window_end=self.window_end,
            bonus_date=self.test_date,
        )

        self.assertEqual(len(awards), 1)
        award = awards[0]
        self.assertEqual(award.chats_counted, 550)
        self.assertEqual(award.player, self.player1)
        self.assertEqual(award.bonus_tier, self.tier_500)

    def test_reports_more_than_24_hours_apart_are_not_accumulated(self):
        session_old = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=28),
            signed_out_at=self.window_end - timedelta(hours=25),
        )

        session_new = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=4),
            signed_out_at=self.window_end - timedelta(hours=2),
        )

        create_report(
            session=session_old,
            moderator=self.moderator,
            chats_responded=300,
            submitted_at=self.window_end - timedelta(hours=25),
            comments="Outside 24h window",
        )

        create_report(
            session=session_new,
            moderator=self.moderator,
            chats_responded=300,
            submitted_at=self.window_end - timedelta(hours=2),
            comments="Inside window",
        )

        awards = evaluate_moderator_bonus(
            moderator=self.moderator,
            window_end=self.window_end,
            bonus_date=self.test_date,
        )

        self.assertEqual(len(awards), 0)

    def test_same_report_does_not_receive_duplicate_bonus(self):
        session = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=4),
            signed_out_at=self.window_end - timedelta(hours=1),
        )

        create_report(
            session=session,
            moderator=self.moderator,
            chats_responded=550,
            submitted_at=self.window_end - timedelta(hours=1),
            comments="Qualifies once",
        )

        awards1 = evaluate_moderator_bonus(
            moderator=self.moderator,
            window_end=self.window_end,
            bonus_date=self.test_date,
        )

        awards2 = evaluate_moderator_bonus(
            moderator=self.moderator,
            window_end=self.window_end,
            bonus_date=self.test_date,
        )

        self.assertEqual(len(awards1), 1)
        self.assertEqual(len(awards2), 1)
        self.assertEqual(awards1[0].pk, awards2[0].pk)
        self.assertEqual(BonusAward.objects.count(), 1)

    def test_daily_bonus_determination_evaluates_per_player(self):
        session1 = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=20),
            signed_out_at=self.window_end - timedelta(hours=16),
        )

        session2 = create_completed_session(
            player=self.player2,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=8),
            signed_out_at=self.window_end - timedelta(hours=4),
        )

        create_report(
            session=session1,
            moderator=self.moderator,
            chats_responded=550,
            submitted_at=self.window_end - timedelta(hours=16),
            comments="Player 1 qualifies",
        )

        create_report(
            session=session2,
            moderator=self.moderator,
            chats_responded=750,
            submitted_at=self.window_end - timedelta(hours=4),
            comments="Player 2 qualifies for higher tier",
        )

        awards = determine_daily_moderator_bonuses(
            determination_date=self.test_date,
        )

        self.assertEqual(len(awards), 2)
        p1_award = next(a for a in awards if a.player == self.player1)
        p2_award = next(a for a in awards if a.player == self.player2)

        self.assertEqual(p1_award.chats_counted, 550)
        self.assertEqual(p1_award.bonus_tier, self.tier_500)

        self.assertEqual(p2_award.chats_counted, 750)
        self.assertEqual(p2_award.bonus_tier, self.tier_700)

    def test_daily_bonus_determination_uses_0945_boundary(self):
        session_inside = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=2),
            signed_out_at=self.window_end - timedelta(minutes=10),
        )

        session_outside = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end + timedelta(minutes=5),
            signed_out_at=self.window_end + timedelta(hours=2),
        )

        create_report(
            session=session_inside,
            moderator=self.moderator,
            chats_responded=550,
            submitted_at=self.window_end - timedelta(minutes=5),
            comments="Inside 09:45 boundary",
        )

        create_report(
            session=session_outside,
            moderator=self.moderator,
            chats_responded=550,
            submitted_at=self.window_end + timedelta(minutes=15),
            comments="Outside 09:45 boundary",
        )

        awards = determine_daily_moderator_bonuses(
            determination_date=self.test_date,
        )

        self.assertEqual(len(awards), 1)
        award = awards[0]
        self.assertEqual(award.chats_counted, 550)

    def test_bonus_amount_is_snapshotted(self):
        session = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=4),
            signed_out_at=self.window_end - timedelta(hours=1),
        )

        create_report(
            session=session,
            moderator=self.moderator,
            chats_responded=550,
            submitted_at=self.window_end - timedelta(hours=1),
            comments="Snapshots test",
        )

        awards = evaluate_moderator_bonus(
            moderator=self.moderator,
            window_end=self.window_end,
            bonus_date=self.test_date,
        )

        award = awards[0]

        self.tier_500.bonus_amount = Decimal("999.00")
        self.tier_500.save()

        award.refresh_from_db()
        self.assertEqual(award.bonus_amount, Decimal("200.00"))

    def test_bonus_requires_moderator(self):
        manager = User.objects.create_user(
            username="mgr1",
            email="mgr1@example.com",
            password="password",
            role=User.Role.MANAGER,
        )

        with self.assertRaises(ValidationError):
            get_reports_within_window(
                moderator=manager,
                window_end=self.window_end,
            )

    def test_awarded_at_is_recorded(self):
        session = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=4),
            signed_out_at=self.window_end - timedelta(hours=1),
        )

        create_report(
            session=session,
            moderator=self.moderator,
            chats_responded=550,
            submitted_at=self.window_end - timedelta(hours=1),
            comments="Record time test",
        )

        awards = evaluate_moderator_bonus(
            moderator=self.moderator,
            window_end=self.window_end,
            bonus_date=self.test_date,
        )

        award = awards[0]
        self.assertIsNotNone(award.awarded_at)

    def test_bonus_date_is_recorded(self):
        session = create_completed_session(
            player=self.player1,
            moderator=self.moderator,
            signed_in_at=self.window_end - timedelta(hours=4),
            signed_out_at=self.window_end - timedelta(hours=1),
        )

        create_report(
            session=session,
            moderator=self.moderator,
            chats_responded=550,
            submitted_at=self.window_end - timedelta(hours=1),
            comments="Record bonus date test",
        )

        awards = evaluate_moderator_bonus(
            moderator=self.moderator,
            window_end=self.window_end,
            bonus_date=self.test_date,
        )

        award = awards[0]
        self.assertEqual(award.bonus_date, self.test_date)
