from django.db import transaction
from coverage.models import CoverageSession
from coverage.forms import EndOfSessionReportForm
from payments.services import create_payment_record
from bonuses.services import award_bonus_for_report

session = CoverageSession.objects.get(id=32)

print("Session:", session.id)
print("Status:", session.status)
print("Moderator:", session.moderator)
print("Operating date:", session.operating_date)

form = EndOfSessionReportForm(data={
    "chats_responded": "10",
    "account_rating": "8",
    "comments": "Diagnostic test",
})

print("Form valid:", form.is_valid())
print("Form errors:", form.errors.as_json())

if form.is_valid():
    try:
        with transaction.atomic():
            report = form.save(commit=False)
            report.coverage_session = session
            report.moderator = session.moderator
            report.player = session.player
            report.save()

            print("Report save: OK")

            payment = create_payment_record(
                coverage_session=session,
                chats_responded=report.chats_responded,
            )

            print("Payment creation: OK")
            print("Payment:", payment)

            bonus = award_bonus_for_report(
                report=report,
                bonus_date=session.operating_date,
            )

            print("Bonus creation: OK")
            print("Bonus:", bonus)

            raise RuntimeError("ROLLBACK_TEST")

    except Exception as exc:
        print("EXCEPTION TYPE:", type(exc).__name__)
        print("EXCEPTION:", exc)
