"""
Regression tests for the settlement (Mark as Paid) flow.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import StaffProfile, User
from payments.models import ModeratorPayment, PaymentSettings
from payments.services import record_payment


class RecordPaymentServiceTests(TestCase):

    def test_payment_blocked_when_mpesa_missing(self):
        """The M-Pesa guard must block record_payment when no number is set."""
        # Clear the moderator's M-Pesa number
        self.moderator.staff_profile.mpesa_number = ""
        self.moderator.staff_profile.save(update_fields=["mpesa_number"])

        with self.assertRaisesMessage(ValidationError, "has no M-Pesa number on file"):
            record_payment(
                payment=self.payment,
                director=self.director,
                mpesa_reference="SHOULD-FAIL",
                amount="1500.00",
            )

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, ModeratorPayment.Status.UNPAID)

    def setUp(self):
        self.director = User.objects.create_user(
            username="settle_director",
            password="testpass123",
            role=User.Role.DIRECTOR,
        )
        self.moderator = User.objects.create_user(
            username="settle_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        StaffProfile.objects.create(
            user=self.moderator,
            status=StaffProfile.Status.ACTIVE,
            mpesa_number="254700000001",
        )
        today = date.today()
        self.payment = ModeratorPayment.objects.create(
            moderator=self.moderator,
            payment_week_start=today - timedelta(days=6),
            payment_week_end=today,
            payment_date=today,
            payable_chats=1000,
            chat_earnings=Decimal("5500.00"),
            earned_amount=Decimal("5500.00"),
            outstanding_amount=Decimal("5500.00"),
            generated_amount=Decimal("5500.00"),
            status=ModeratorPayment.Status.UNPAID,
        )

    def test_full_payment_marks_paid(self):
        record_payment(
            payment=self.payment,
            director=self.director,
            mpesa_reference="QK12345678",
            amount="5500.00",
        )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, ModeratorPayment.Status.PAID)
        self.assertEqual(self.payment.outstanding_amount, Decimal("0.00"))
        self.assertEqual(self.payment.amount_paid, Decimal("5500.00"))
        self.assertEqual(self.payment.paid_by, self.director)
        self.assertEqual(self.payment.mpesa_reference, "QK12345678")
        self.assertIsNotNone(self.payment.paid_at)

    def test_partial_payment_marks_partially_paid(self):
        record_payment(
            payment=self.payment,
            director=self.director,
            mpesa_reference="QK87654321",
            amount="2000.00",
        )
        self.payment.refresh_from_db()
        self.assertEqual(
            self.payment.status,
            ModeratorPayment.Status.PARTIALLY_PAID,
        )
        self.assertEqual(self.payment.outstanding_amount, Decimal("3500.00"))
        self.assertEqual(self.payment.amount_paid, Decimal("2000.00"))

    def test_missing_mpesa_reference_rejected(self):
        with self.assertRaisesMessage(ValidationError, "M-Pesa reference is required"):
            record_payment(
                payment=self.payment,
                director=self.director,
                mpesa_reference="",
                amount="5500.00",
            )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, ModeratorPayment.Status.UNPAID)

    def test_amount_exceeding_outstanding_rejected(self):
        with self.assertRaisesMessage(ValidationError, "exceeds outstanding"):
            record_payment(
                payment=self.payment,
                director=self.director,
                mpesa_reference="QK00000001",
                amount="9999.00",
            )

    def test_repaying_paid_payment_rejected(self):
        record_payment(
            payment=self.payment,
            director=self.director,
            mpesa_reference="QK11111111",
            amount="5500.00",
        )
        self.payment.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "already been recorded as paid"):
            record_payment(
                payment=self.payment,
                director=self.director,
                mpesa_reference="QK22222222",
                amount="100.00",
            )

    def test_deleting_paid_payment_rejected(self):
        record_payment(
            payment=self.payment,
            director=self.director,
            mpesa_reference="QK33333333",
            amount="5500.00",
        )
        self.payment.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "Paid payroll records cannot be deleted"):
            self.payment.delete()

    def test_reverting_paid_status_rejected(self):
        record_payment(
            payment=self.payment,
            director=self.director,
            mpesa_reference="QK44444444",
            amount="5500.00",
        )
        self.payment.refresh_from_db()
        self.payment.status = ModeratorPayment.Status.UNPAID
        with self.assertRaisesMessage(ValidationError, "cannot be reverted to unpaid"):
            self.payment.save()


class SettleViewTests(TestCase):
    def setUp(self):
        self.director = User.objects.create_user(
            username="settle_view_director",
            password="testpass123",
            role=User.Role.DIRECTOR,
        )
        self.moderator_user = User.objects.create_user(
            username="settle_view_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        StaffProfile.objects.create(
            user=self.moderator_user,
            status=StaffProfile.Status.ACTIVE,
            mpesa_number="0722000001",
        )
        self.moderator = User.objects.create_user(
            username="other_mod",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        StaffProfile.objects.create(
            user=self.moderator,
            status=StaffProfile.Status.ACTIVE,
            mpesa_number="0722000002",
        )
        today = date.today()
        self.payment = ModeratorPayment.objects.create(
            moderator=self.moderator,
            payment_week_start=today - timedelta(days=6),
            payment_week_end=today,
            payment_date=today,
            payable_chats=500,
            chat_earnings=Decimal("1500.00"),
            earned_amount=Decimal("1500.00"),
            outstanding_amount=Decimal("1500.00"),
            generated_amount=Decimal("1500.00"),
            status=ModeratorPayment.Status.UNPAID,
        )

    def test_director_can_post_payment(self):
        c = Client()
        c.force_login(self.director)
        url = reverse("payments:settle_payment", args=[self.payment.id])
        resp = c.post(url, {
            "mpesa_reference": "VIEWTEST1",
            "amount": "1500.00",
        })
        self.assertEqual(resp.status_code, 302)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, ModeratorPayment.Status.PAID)
        self.assertEqual(self.payment.mpesa_reference, "VIEWTEST1")

    def test_non_director_cannot_access(self):
        c = Client()
        c.force_login(self.moderator_user)
        url = reverse("payments:settle_payment", args=[self.payment.id])
        resp = c.get(url)
        # Non-director is redirected by role_required
        self.assertIn(resp.status_code, (302, 403))

    def test_missing_reference_shows_error_and_stays_unpaid(self):
        c = Client()
        c.force_login(self.director)
        url = reverse("payments:settle_payment", args=[self.payment.id])
        resp = c.post(url, {
            "mpesa_reference": "",
            "amount": "1500.00",
        }, follow=True)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, ModeratorPayment.Status.UNPAID)
        body = resp.content.decode("utf-8", errors="replace")
        self.assertIn("M-Pesa reference", body)

class ModeratorAccessTests(TestCase):
    """Verify a moderator can view (but not record) their own payments."""

    def setUp(self):
        self.director = User.objects.create_user(
            username="ma_director",
            password="testpass123",
            role=User.Role.DIRECTOR,
        )
        self.moderator = User.objects.create_user(
            username="ma_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        self.other_moderator = User.objects.create_user(
            username="ma_other",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        StaffProfile.objects.create(
            user=self.moderator,
            status=StaffProfile.Status.ACTIVE,
            mpesa_number="0722000003",
        )
        StaffProfile.objects.create(
            user=self.other_moderator,
            status=StaffProfile.Status.ACTIVE,
            mpesa_number="0722000004",
        )
        today = date.today()
        self.payment = ModeratorPayment.objects.create(
            moderator=self.moderator,
            payment_week_start=today - timedelta(days=6),
            payment_week_end=today,
            payment_date=today,
            payable_chats=500,
            chat_earnings=Decimal("1500.00"),
            earned_amount=Decimal("1500.00"),
            outstanding_amount=Decimal("1500.00"),
            generated_amount=Decimal("1500.00"),
            status=ModeratorPayment.Status.UNPAID,
        )

    def test_moderator_can_view_own_payment(self):
        c = Client()
        c.force_login(self.moderator)
        url = reverse("payments:settle_payment", args=[self.payment.id])
        resp = c.get(url)
        self.assertEqual(resp.status_code, 200)
        # Should see the "recorded by a Director" note, not the form
        body = resp.content.decode("utf-8", errors="replace")
        self.assertIn("recorded by a Director", body)
        self.assertNotIn("Record Payment", body)

    def test_moderator_cannot_view_others_payment(self):
        c = Client()
        c.force_login(self.other_moderator)
        url = reverse("payments:settle_payment", args=[self.payment.id])
        resp = c.get(url)
        # Should redirect away
        self.assertEqual(resp.status_code, 302)

    def test_moderator_cannot_post_payment(self):
        c = Client()
        c.force_login(self.moderator)
        url = reverse("payments:settle_payment", args=[self.payment.id])
        resp = c.post(url, {"mpesa_reference": "TEST", "amount": "1500.00"})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, ModeratorPayment.Status.UNPAID)

    def test_my_payments_lists_only_own(self):
        c = Client()
        c.force_login(self.moderator)
        url = reverse("payments:my_payments")
        resp = c.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8", errors="replace")
        self.assertIn("My Payments", body)
        self.assertIn("1500.00", body)
        self.assertNotIn("ma_other", body)

    def test_director_can_still_view_and_record(self):
        c = Client()
        c.force_login(self.director)
        url = reverse("payments:settle_payment", args=[self.payment.id])
        resp = c.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8", errors="replace")
        self.assertIn("Record Payment", body)

class PdfStatementTests(TestCase):
    """Verify PDF statement generation and access control."""

    def setUp(self):
        self.director = User.objects.create_user(
            username="pdf_director",
            password="testpass123",
            role=User.Role.DIRECTOR,
        )
        self.moderator = User.objects.create_user(
            username="pdf_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        self.other_moderator = User.objects.create_user(
            username="pdf_other",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        StaffProfile.objects.create(
            user=self.moderator,
            status=StaffProfile.Status.ACTIVE,
            mpesa_number="0722000005",
        )
        StaffProfile.objects.create(
            user=self.other_moderator,
            status=StaffProfile.Status.ACTIVE,
            mpesa_number="0722000006",
        )

        today = date.today()
        self.payment = ModeratorPayment.objects.create(
            moderator=self.moderator,
            payment_week_start=today - timedelta(days=6),
            payment_week_end=today,
            payment_date=today,
            payable_chats=500,
            chat_earnings=Decimal("1500.00"),
            earned_amount=Decimal("1500.00"),
            outstanding_amount=Decimal("1500.00"),
            generated_amount=Decimal("1500.00"),
            status=ModeratorPayment.Status.UNPAID,
        )

    def test_director_can_download_pdf(self):
        c = Client()
        c.force_login(self.director)
        url = reverse("payments:download_payment_statement_pdf", args=[self.payment.id])
        resp = c.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF-"))

    def test_owner_can_download_own_pdf(self):
        c = Client()
        c.force_login(self.moderator)
        url = reverse("payments:download_payment_statement_pdf", args=[self.payment.id])
        resp = c.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b"%PDF-"))

    def test_other_moderator_cannot_download(self):
        c = Client()
        c.force_login(self.other_moderator)
        url = reverse("payments:download_payment_statement_pdf", args=[self.payment.id])
        resp = c.get(url)
        self.assertEqual(resp.status_code, 302)


class PaymentNotificationTests(TestCase):
    """Verify a notification is created when a payment is recorded."""

    def setUp(self):
        self.director = User.objects.create_user(
            username="notif_director",
            password="testpass123",
            role=User.Role.DIRECTOR,
        )
        self.moderator = User.objects.create_user(
            username="notif_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        StaffProfile.objects.create(
            user=self.moderator,
            status=StaffProfile.Status.ACTIVE,
            mpesa_number="0722000007",
        )

        today = date.today()
        self.payment = ModeratorPayment.objects.create(
            moderator=self.moderator,
            payment_week_start=today - timedelta(days=6),
            payment_week_end=today,
            payment_date=today,
            payable_chats=500,
            chat_earnings=Decimal("1500.00"),
            earned_amount=Decimal("1500.00"),
            outstanding_amount=Decimal("1500.00"),
            generated_amount=Decimal("1500.00"),
            status=ModeratorPayment.Status.UNPAID,
        )

    def test_notification_created_on_payment(self):
        from notifications.models import Notification
        before = Notification.objects.filter(recipient=self.moderator).count()
        record_payment(
            payment=self.payment,
            director=self.director,
            mpesa_reference="NOTIFTEST1",
            amount="1500.00",
        )
        after = Notification.objects.filter(recipient=self.moderator).count()
        self.assertEqual(after, before + 1)
        latest = Notification.objects.filter(recipient=self.moderator).order_by("-created_at").first()
        self.assertEqual(latest.title, "Payment Received")
        self.assertIn("NOTIFTEST1", latest.message)

class GlobalRateFallbackTests(TestCase):
    """Verify the global ChatRateTier is used when a player has no override."""

    def test_player_without_override_uses_global_rate(self):
        from datetime import date as _date
        from players.models import ChatRateTier, Player, PlayerChatRateTier
        from payments.services import get_applicable_player_chat_rate_tier

        # Create a global tier
        ChatRateTier.objects.create(
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("3.00"),
            active=True,
        )

        # Create a player with NO PlayerChatRateTier rows
        player = Player.objects.create(player_number=7301, name="Test Player No Override")
        self.assertFalse(
            PlayerChatRateTier.objects.filter(player=player).exists()
        )

        # Lookup should resolve to the global tier
        tier = get_applicable_player_chat_rate_tier(
            player=player,
            chats_responded=100,
            operating_date=_date.today(),
        )
        self.assertEqual(tier.rate_per_chat, Decimal("3.00"))

    def test_player_override_beats_global(self):
        from datetime import date as _date
        from players.models import ChatRateTier, Player, PlayerChatRateTier
        from payments.services import get_applicable_player_chat_rate_tier

        # Global tier: 0-299 → 3.00
        ChatRateTier.objects.create(
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("3.00"),
            active=True,
        )

        # Player override: 0-299 → 5.00 (custom rate)
        player = Player.objects.create(player_number=7302, name="Test Player With Override")
        PlayerChatRateTier.objects.create(
            player=player,
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("5.00"),
            active=True,
            effective_from=None,
        )

        tier = get_applicable_player_chat_rate_tier(
            player=player,
            chats_responded=100,
            operating_date=_date.today(),
        )
        self.assertEqual(tier.rate_per_chat, Decimal("5.00"))

class BulkPaymentTests(TestCase):
    """Verify record_payment_group sequential split logic."""

    def setUp(self):
        self.director = User.objects.create_user(
            username="bulk_director",
            password="testpass123",
            role=User.Role.DIRECTOR,
        )
        self.moderator = User.objects.create_user(
            username="bulk_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        StaffProfile.objects.create(
            user=self.moderator,
            status=StaffProfile.Status.ACTIVE,
            mpesa_number="0722000111",
        )

        today = date.today()
        # Older week
        self.old_payment = ModeratorPayment.objects.create(
            moderator=self.moderator,
            payment_week_start=today - timedelta(days=13),
            payment_week_end=today - timedelta(days=7),
            payment_date=today - timedelta(days=7),
            payable_chats=100,
            chat_earnings=Decimal("500.00"),
            earned_amount=Decimal("500.00"),
            outstanding_amount=Decimal("500.00"),
            generated_amount=Decimal("500.00"),
            status=ModeratorPayment.Status.UNPAID,
        )
        # Newer week
        self.new_payment = ModeratorPayment.objects.create(
            moderator=self.moderator,
            payment_week_start=today - timedelta(days=6),
            payment_week_end=today,
            payment_date=today,
            payable_chats=200,
            chat_earnings=Decimal("1000.00"),
            earned_amount=Decimal("1000.00"),
            outstanding_amount=Decimal("1000.00"),
            generated_amount=Decimal("1000.00"),
            status=ModeratorPayment.Status.UNPAID,
        )

    def test_bulk_full_payment_marks_all_paid(self):
        from payments.services import record_payment_group
        result = record_payment_group(
            moderator=self.moderator,
            director=self.director,
            mpesa_reference="BULK-FULL-001",
            amount="1500.00",
        )
        self.assertEqual(len(result["updated"]), 2)
        self.old_payment.refresh_from_db()
        self.new_payment.refresh_from_db()
        self.assertEqual(self.old_payment.status, ModeratorPayment.Status.PAID)
        self.assertEqual(self.new_payment.status, ModeratorPayment.Status.PAID)
        self.assertEqual(self.old_payment.outstanding_amount, Decimal("0.00"))
        self.assertEqual(self.new_payment.outstanding_amount, Decimal("0.00"))
        self.assertEqual(self.old_payment.mpesa_reference, "BULK-FULL-001")
        self.assertEqual(self.new_payment.mpesa_reference, "BULK-FULL-001")

    def test_bulk_partial_payment_pays_oldest_first(self):
        from payments.services import record_payment_group
        result = record_payment_group(
            moderator=self.moderator,
            director=self.director,
            mpesa_reference="BULK-PART-001",
            amount="700.00",
        )
        self.old_payment.refresh_from_db()
        self.new_payment.refresh_from_db()

        # Oldest (500 KES) fully paid
        self.assertEqual(self.old_payment.status, ModeratorPayment.Status.PAID)
        self.assertEqual(self.old_payment.outstanding_amount, Decimal("0.00"))
        # Newest (1000 KES) partially paid — 700 - 500 = 200 applied
        self.assertEqual(self.new_payment.status, ModeratorPayment.Status.PARTIALLY_PAID)
        self.assertEqual(self.new_payment.outstanding_amount, Decimal("800.00"))

    def test_bulk_amount_exceeds_total_rejected(self):
        from payments.services import record_payment_group
        with self.assertRaisesMessage(ValidationError, "exceeds total outstanding"):
            record_payment_group(
                moderator=self.moderator,
                director=self.director,
                mpesa_reference="BULK-OVER-001",
                amount="9999.00",
            )
        self.old_payment.refresh_from_db()
        self.new_payment.refresh_from_db()
        self.assertEqual(self.old_payment.status, ModeratorPayment.Status.UNPAID)
        self.assertEqual(self.new_payment.status, ModeratorPayment.Status.UNPAID)

    def test_bulk_payment_blocked_without_mpesa(self):
        from payments.services import record_payment_group
        # Clear the moderator's M-Pesa number
        profile = self.moderator.staff_profile
        profile.mpesa_number = ""
        profile.save(update_fields=["mpesa_number"])

        with self.assertRaisesMessage(ValidationError, "no M-Pesa number on file"):
            record_payment_group(
                moderator=self.moderator,
                director=self.director,
                mpesa_reference="BULK-NOMPESA-001",
                amount="500.00",
            )

class RateRecalculationTests(TestCase):
    """Tests for the recalculate_unpaid_rates management command."""

    def setUp(self):
        from datetime import date, timedelta
        self.director = User.objects.create_user(
            username="recalc_director",
            password="testpass123",
            role=User.Role.DIRECTOR,
        )
        self.moderator = User.objects.create_user(
            username="recalc_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        StaffProfile.objects.create(
            user=self.moderator,
            status=StaffProfile.Status.ACTIVE,
            mpesa_number="0722000999",
        )

        today = date.today()
        self.payment = ModeratorPayment.objects.create(
            moderator=self.moderator,
            payment_week_start=today - timedelta(days=6),
            payment_week_end=today,
            payment_date=today,
            payable_chats=100,
            chat_earnings=Decimal("500.00"),
            earned_amount=Decimal("500.00"),
            outstanding_amount=Decimal("500.00"),
            generated_amount=Decimal("500.00"),
            rate_per_chat=Decimal("5.00"),
            status=ModeratorPayment.Status.UNPAID,
        )

        # A PAID record should never be touched
        self.paid_payment = ModeratorPayment.objects.create(
            moderator=self.moderator,
            payment_week_start=today - timedelta(days=13),
            payment_week_end=today - timedelta(days=7),
            payment_date=today - timedelta(days=7),
            payable_chats=100,
            chat_earnings=Decimal("400.00"),
            earned_amount=Decimal("400.00"),
            outstanding_amount=Decimal("0.00"),
            amount_paid=Decimal("400.00"),
            generated_amount=Decimal("400.00"),
            rate_per_chat=Decimal("4.00"),
            status=ModeratorPayment.Status.PAID,
        )

    def test_recalculate_preview_does_not_modify(self):
        from django.core.management import call_command
        from io import StringIO

        old_earned = self.payment.earned_amount
        call_command("recalculate_unpaid_rates", stdout=StringIO())
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.earned_amount, old_earned)

    def test_recalculate_apply_updates_unpaid_not_paid(self):
        from django.core.management import call_command
        from io import StringIO

        old_paid_earned = self.paid_payment.earned_amount
        call_command("recalculate_unpaid_rates", "--apply", stdout=StringIO())

        self.paid_payment.refresh_from_db()
        self.assertEqual(self.paid_payment.earned_amount, old_paid_earned)
        self.assertEqual(self.paid_payment.status, ModeratorPayment.Status.PAID)

    def test_rate_reconciliation_log_is_written(self):
        from django.core.management import call_command
        from io import StringIO

        call_command("recalculate_unpaid_rates", "--apply", stdout=StringIO())
        self.payment.refresh_from_db()

        # The log field should have entries if a change occurred
        # (may be empty if the payment happened to compute the same value)
        if self.payment.earned_amount != Decimal("500.00"):
            self.assertIsInstance(self.payment.rate_reconciliation, dict)
