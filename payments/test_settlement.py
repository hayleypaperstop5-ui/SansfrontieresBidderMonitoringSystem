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
        )
        self.moderator = User.objects.create_user(
            username="other_mod",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        StaffProfile.objects.create(
            user=self.moderator,
            status=StaffProfile.Status.ACTIVE,
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
