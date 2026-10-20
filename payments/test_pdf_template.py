from io import BytesIO
from django.test import TestCase
from pypdf import PdfReader
from payments.models import ModeratorPayment
from payments.pdf import (
    build_payment_statement_pdf,
    draw_brand_header, draw_footer, draw_pdf_watermark, _on_page,
)

class PdfTemplateRegressionTest(TestCase):
    def test_helpers_present(self):
        for fn in (draw_brand_header, draw_footer, draw_pdf_watermark, _on_page,
                   build_payment_statement_pdf):
            self.assertTrue(callable(fn))

    def test_payment_statement_text_markers(self):
        # Build a minimal, in-memory payment so this test runs in CI without
        # requiring seeded production-like data.
        from accounts.models import User
        from datetime import date
        from decimal import Decimal

        mod, _ = User.objects.get_or_create(
            username="pdf_test_mod",
            defaults={"role": User.Role.MODERATOR, "email": "pdf_test_mod@example.test"},
        )
        p = ModeratorPayment.objects.create(
            moderator=mod,
            payment_week_start=date(2026, 1, 5),
            payment_week_end=date(2026, 1, 11),
            payment_date=date(2026, 1, 12),
            payable_chats=0,
            earned_amount=Decimal("0.00"),
            rate_per_chat=Decimal("0.00"),
            rate_method="PLAYER_CHAT_RATE",
            status="UNPAID",
        )

        data = build_payment_statement_pdf(p, [], [], []).getvalue()
        reader = PdfReader(BytesIO(data))
        page1 = reader.pages[0].extract_text() or ""
        for marker in (
            "Sansfrontieres",
            "Chat Moderation Payment Statement",
            "Payment Statement",
            "computer-generated and reflects the records",
            "Sansfrontieres Monitoring System",
            "Page 1",
        ):
            self.assertIn(marker, page1)
