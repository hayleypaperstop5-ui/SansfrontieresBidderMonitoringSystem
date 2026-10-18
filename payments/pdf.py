"""
PDF payment statement generation for ModeratorPayment records.

Uses ReportLab (pure Python) to render a moderated PDF with:
  - Moderator header (name, M-Pesa, period)
  - Earnings summary
  - Per-player breakdown
  - Source sessions
  - Carried-forward
  - Payment status / audit trail
"""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
)


def _fmt(value):
    if value is None:
        return "0.00"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _date_str(d):
    if d is None:
        return "—"
    return d.strftime("%d %b %Y")


def _datetime_str(dt):
    if dt is None:
        return "—"
    from django.utils import timezone
    try:
        dt = timezone.localtime(dt)
    except Exception:
        pass
    return dt.strftime("%d %b %Y %H:%M")


def build_payment_statement_pdf(payment, rows, breakdown_display, carried_display):
    """Return a BytesIO containing the PDF for the given payment."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18*mm,
        rightMargin=18*mm,
        topMargin=18*mm,
        bottomMargin=18*mm,
        title=f"Payment Statement #{payment.id}",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, spaceAfter=4, alignment=1)  # 1 = centered
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=6)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, textColor=colors.grey)
    body = styles["Normal"]
    body.fontSize = 10

    story = []

    # ---------- Header ----------
    moderator = payment.moderator
    mod_name = moderator.get_full_name() or moderator.username
    story.append(Paragraph("Sansfrontieres Chat Moderations Payment Statement", h1))
    subtitle_style = ParagraphStyle(
        "subtitle", parent=small, alignment=1, spaceAfter=8,
    )
    story.append(Paragraph(
        f"Statement #{payment.id} &nbsp;|&nbsp; "
        f"Issued {_date_str(payment.payment_date)}",
        subtitle_style,
    ))
    story.append(Spacer(1, 8))

    header_data = [
        ["Moderator", mod_name],
        ["Username", moderator.username],
        ["M-Pesa Number", getattr(getattr(moderator, "staff_profile", None), "mpesa_number", "") or "Not set"],
        ["Period", f"{_date_str(payment.payment_week_start)} to {_date_str(payment.payment_week_end)}"],
        ["Rate Method", payment.get_rate_method_display()],
        ["Status", payment.get_status_display()],
    ]
    header_table = Table(header_data, colWidths=[45*mm, 120*mm])
    header_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(header_table)

    # ---------- Earnings Summary ----------
    story.append(Paragraph("Earnings Summary", h2))
    earnings_data = [
        ["Payable Chats", "Chat Earnings", "Bonus", "Total Earned"],
        [_fmt(payment.payable_chats), f"KES {_fmt(payment.earned_amount - (payment.bonus_earned or 0))}",
         f"KES {_fmt(payment.bonus_earned)}", f"KES {_fmt(payment.earned_amount)}"],
    ]
    earnings_table = Table(earnings_data, colWidths=[40*mm, 40*mm, 40*mm, 45*mm])
    earnings_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(earnings_table)

    # ---------- Per-Player Breakdown ----------
    # If the payment has been recalculated, the historical player_chat_rate_breakdown
    # is now stale. Show a single-row breakdown using the current rate instead.
    has_recalculation = bool(
        payment.rate_reconciliation and 
        isinstance(payment.rate_reconciliation, dict) and 
        payment.rate_reconciliation.get("entries")
    )

    if has_recalculation:
        # Show current-rate breakdown
        story.append(Paragraph("Current Rate Breakdown", h2))
        bp_data = [["Payable Chats", "Rate", "Subtotal"]]
        bp_data.append([
            str(payment.payable_chats),
            _fmt(payment.rate_per_chat),
            f"KES {_fmt(payment.earned_amount - (payment.bonus_earned or 0))}",
        ])
        bp_table = Table(bp_data, colWidths=[50*mm, 30*mm, 50*mm])
        bp_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ]))
        story.append(bp_table)
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "<i>This payment was recalculated at current rates. The original "
            "per-player breakdown is preserved in the audit log.</i>", 
            small
        ))
    elif breakdown_display:
        story.append(Paragraph("Per-Player Rate Breakdown", h2))
        bp_data = [["Player", "Qualifying Chats", "Rate", "Subtotal"]]
        for r in breakdown_display:
            bp_data.append([
                r["player_label"],
                _fmt(r["qualifying_chats"]),
                _fmt(r["rate_per_chat"]),
                f"KES {_fmt(r['chat_earnings'])}",
            ])
        bp_table = Table(bp_data, colWidths=[65*mm, 35*mm, 25*mm, 40*mm])
        bp_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(bp_table)

    # ---------- Source Sessions ----------
    if rows:
        story.append(Paragraph("Source Sessions", h2))
        sess_data = [["Session Code", "Player", "Operating Date", "Submitted", "Chats", "Processed"]]
        for r in rows:
            sess_data.append([
                r.get("session_code") or str(r.get("session_id") or "—"),
                str(r["player"]),
                f"{_date_str(r['operating_date'])} ({r['session_type']})",
                _datetime_str(r["submitted_at"]) if r["submitted_at"] else "—",
                str(r["chats_responded"]),
                str(r["payroll_processed_chats"]),
            ])
        sess_table = Table(sess_data, colWidths=[25*mm, 32*mm, 38*mm, 32*mm, 18*mm, 20*mm])
        sess_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(sess_table)

    # ---------- Carried Forward ----------
    if carried_display:
        story.append(Paragraph("Chats Carried Forward", h2))
        cf_data = [["Player", "Submitted This Week", "Accumulated Unpaid", "Threshold", "Remaining"]]
        for r in carried_display:
            cf_data.append([
                r["player_label"],
                str(r["submitted_this_week"]),
                str(r["accumulated_unpaid"]),
                str(r["threshold"]),
                str(r["remaining_to_qualify"]),
            ])
        cf_table = Table(cf_data, colWidths=[55*mm, 30*mm, 30*mm, 20*mm, 25*mm])
        cf_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(cf_table)

    # ---------- Payment Record / Settlement ----------
    from payments.models import PaymentSettings as _PS
    from datetime import date as _date_cls, timedelta as _td

    # Compute "next pay day" — only shown when this moderator has no other unpaid records
    other_unpaid_exists = False
    if payment.status == "PAID":
        # Check if the moderator has OTHER unpaid records
        other_unpaid_exists = (
            type(payment).objects
            .filter(moderator=payment.moderator)
            .exclude(pk=payment.pk)
            .exclude(status="PAID")
            .exists()
        )

    settings_obj = _PS.objects.first()
    pay_day_num = settings_obj.payment_day if settings_obj else 3
    _weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    def _next_pay_day(from_date):
        days_ahead = (pay_day_num - from_date.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return from_date + _td(days=days_ahead)

    if payment.status == "PAID":
        # Full settlement receipt
        story.append(Paragraph("Payment Settlement (Paid in Full)", h2))
        next_pd = _next_pay_day(_date_cls.today())
        pay_data = [
            ["Amount Paid", f"KES {_fmt(payment.amount_paid)}"],
            ["M-Pesa Reference", payment.mpesa_reference or "—"],
            ["Paid On", _datetime_str(payment.paid_at)],
            ["Paid By", (payment.paid_by.get_full_name() or payment.paid_by.username) if payment.paid_by else "—"],
            ["Status", "PAID"],
            ["Outstanding on this record", "KES 0.00"],
        ]
        if other_unpaid_exists:
            pay_data.append(["Note", "You have other unpaid records — see your consolidated statement."])
        else:
            pay_data.append(["Next Pay Day", f"{_weekday_names[next_pd.weekday()]}, {next_pd.strftime('%d %b %Y')}"])

    elif payment.status == "PARTIALLY_PAID":
        # Partial settlement receipt
        story.append(Paragraph("Payment Settlement (Partially Paid)", h2))
        next_pd = _next_pay_day(_date_cls.today())
        pay_data = [
            ["Amount Paid", f"KES {_fmt(payment.amount_paid)}"],
            ["M-Pesa Reference", payment.mpesa_reference or "—"],
            ["Paid On", _datetime_str(payment.paid_at)],
            ["Paid By", (payment.paid_by.get_full_name() or payment.paid_by.username) if payment.paid_by else "—"],
            ["Status", "PARTIALLY PAID"],
            ["Pending Amount", f"KES {_fmt(payment.outstanding_amount)}"],
        ]
        if other_unpaid_exists:
            pay_data.append(["Note", "You have additional unpaid records — see your consolidated statement."])
        else:
            pay_data.append(["Next Pay Day", f"{_weekday_names[next_pd.weekday()]}, {next_pd.strftime('%d %b %Y')}"])

    else:
        # Not yet paid — keep the original presentation
        story.append(Paragraph("Payment Record", h2))
        pay_data = [
            ["Outstanding", f"KES {_fmt(payment.outstanding_amount)}"],
            ["Status", "Not yet paid"],
        ]

    pay_table = Table(pay_data, colWidths=[55*mm, 110*mm])
    pay_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(pay_table)

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "This statement is computer-generated and reflects the records in the "
        "Sansfrontieres Monitoring System at the time of download.",
        small,
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer

def _record_count_label(records):
    """Return a status-aware count label, e.g. '3 unpaid record(s)' or '2 paid record(s)'."""
    if not records:
        return "0 records"
    unpaid = [r for r in records if r.status not in ("PAID", "PARTIALLY_PAID")]
    paid = [r for r in records if r.status == "PAID"]
    partial = [r for r in records if r.status == "PARTIALLY_PAID"]
    parts = []
    if unpaid:
        parts.append(f"{len(unpaid)} unpaid")
    if partial:
        parts.append(f"{len(partial)} partially paid")
    if paid:
        parts.append(f"{len(paid)} paid")
    label = " + ".join(parts) if parts else f"{len(records)}"
    return f"{label} record(s)"


def build_moderator_statement_pdf(moderator, unpaid_payments):
    """
    Build a single consolidated PDF for all UNPAID / PARTIALLY_PAID
    ModeratorPayment records for one moderator.
    """
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )
    from decimal import Decimal
    from datetime import date as _date

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18*mm,
        rightMargin=18*mm,
        topMargin=18*mm,
        bottomMargin=18*mm,
        title=f"Payment Statement for {moderator.get_full_name() or moderator.username}",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, spaceAfter=4, alignment=1)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=6)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, textColor=colors.grey)

    story = []

    mod_name = moderator.get_full_name() or moderator.username
    profile = getattr(moderator, "staff_profile", None)
    mpesa = (profile.mpesa_number or "") if profile else ""

    # Header
    story.append(Paragraph("Sansfrontieres Chat Moderations Payment Statement", h1))
    subtitle_style = ParagraphStyle("subtitle", parent=small, alignment=1, spaceAfter=8)
    story.append(Paragraph(
        f"Statement for {mod_name} &nbsp;|&nbsp; Issued {_date.today().strftime('%d %b %Y')}",
        subtitle_style,
    ))
    story.append(Spacer(1, 8))

    header_data = [
        ["Moderator", mod_name],
        ["Username", moderator.username],
        ["M-Pesa Number", mpesa or "Not set"],
        ["Statement Covers", _record_count_label(unpaid_payments)],
    ]
    header_table = Table(header_data, colWidths=[45*mm, 120*mm])
    header_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(header_table)

    # Summary
    total_chats = sum((mp.payable_chats or 0) for mp in unpaid_payments)
    total_earned = sum((mp.earned_amount or Decimal("0.00")) for mp in unpaid_payments)
    total_paid = sum((mp.amount_paid or Decimal("0.00")) for mp in unpaid_payments)
    total_outstanding = sum((mp.outstanding_amount or Decimal("0.00")) for mp in unpaid_payments)

    story.append(Paragraph("Summary", h2))
    summary_data = [
        ["Total Records", "Total Chats", "Total Earned", "Total Paid", "Outstanding"],
        [
            str(len(unpaid_payments)),
            _fmt(total_chats),
            f"KES {_fmt(total_earned)}",
            f"KES {_fmt(total_paid)}",
            f"KES {_fmt(total_outstanding)}",
        ],
    ]
    summary_table = Table(summary_data, colWidths=[30*mm, 30*mm, 40*mm, 35*mm, 35*mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(summary_table)

    # Per-record breakdown
    story.append(Paragraph("Per-Record Breakdown", h2))
    record_data = [["Period", "Payable Chats", "Rate", "Earned", "Paid", "Outstanding"]]
    for mp in unpaid_payments:
        record_data.append([
            f"{mp.payment_week_start.strftime('%d %b')} – {mp.payment_week_end.strftime('%d %b %Y')}",
            str(mp.payable_chats),
            _fmt(mp.rate_per_chat),
            f"KES {_fmt(mp.earned_amount)}",
            f"KES {_fmt(mp.amount_paid)}",
            f"KES {_fmt(mp.outstanding_amount)}",
        ])
    record_table = Table(record_data, colWidths=[48*mm, 22*mm, 18*mm, 27*mm, 25*mm, 30*mm])
    record_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(record_table)

    # ---------- Source Sessions ----------
    from payments.models import PaymentRecord
    from coverage.models import EndOfSessionReport
    from players.models import Player
    from payments.models import PaymentSettings

    payment_ids = [mp.id for mp in unpaid_payments]
    source_records_qs = (
        PaymentRecord.objects
        .filter(consumed_by_id__in=payment_ids)
        .select_related("coverage_session", "coverage_session__player")
        .order_by("coverage_session__operating_date", "coverage_session__id")
    )
    source_records = list(source_records_qs)

    session_ids = [pr.coverage_session_id for pr in source_records]
    submitted_map = dict(
        EndOfSessionReport.objects
        .filter(coverage_session_id__in=session_ids)
        .values_list("coverage_session_id", "submitted_at")
    )

    # Detect which payments lack consumed_by (historical)
    payments_with_sessions = set(
        pr.consumed_by_id for pr in source_records
    )
    historical_payments = [
        mp for mp in unpaid_payments if mp.id not in payments_with_sessions
    ]

    if source_records:
        story.append(Paragraph("Source Sessions", h2))
        sess_data = [["Session Code", "Player", "Operating Date", "Submitted", "Chats", "Processed"]]
        for pr in source_records:
            session = pr.coverage_session
            submitted_at = submitted_map.get(session.id)
            sess_data.append([
                session.session_code or str(session.id),
                str(session.player),
                f"{session.operating_date.strftime('%d %b %Y')} ({session.get_session_type_display()})",
                submitted_at.strftime("%d %b %Y %H:%M") if submitted_at else "—",
                str(pr.chats_responded),
                str(pr.payroll_processed_chats),
            ])
        sess_table = Table(sess_data, colWidths=[22*mm, 30*mm, 40*mm, 32*mm, 18*mm, 20*mm])
        sess_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(sess_table)
        story.append(Spacer(1, 6))

    if historical_payments:
        historical_ids = ", ".join(f"#{mp.id}" for mp in historical_payments)
        story.append(Paragraph(
            f"<i>Source session details not available for historical record(s): "
            f"{historical_ids} (created before session linkage).</i>",
            small,
        ))
        story.append(Spacer(1, 6))

    # ---------- Chats Carried Forward ----------
    # Per distinct player from source records: submitted this week, accumulated unpaid, threshold
    settings_obj = PaymentSettings.objects.first()
    threshold = settings_obj.minimum_chats_per_player if settings_obj else 700

    if source_records:
        player_ids = list(set(pr.coverage_session.player_id for pr in source_records))
        players = {p.id: p for p in Player.objects.filter(id__in=player_ids)}

        # Determine the "this week" bounds from the most recent unpaid record
        max_week_end = max(mp.payment_week_end for mp in unpaid_payments)
        from datetime import timedelta as _td
        min_week_start = max_week_end - _td(days=6)

        carried_data = [["Player", "Submitted This Week", "Accumulated Unpaid", "Threshold", "Remaining"]]
        from django.db.models import Sum as _Sum, F as _F
        for pid in player_ids:
            player = players.get(pid)
            if not player:
                continue
            week_agg = (
                PaymentRecord.objects
                .filter(
                    coverage_session__player_id=pid,
                    coverage_session__operating_date__gte=min_week_start,
                    coverage_session__operating_date__lte=max_week_end,
                )
                .aggregate(total=_Sum("chats_responded"))
            )
            submitted_this_week = week_agg["total"] or 0

            unpaid_agg = (
                PaymentRecord.objects
                .filter(
                    coverage_session__player_id=pid,
                    chats_responded__gt=_F("payroll_processed_chats"),
                )
                .aggregate(total=_Sum(_F("chats_responded") - _F("payroll_processed_chats")))
            )
            accumulated = unpaid_agg["total"] or 0

            carried_data.append([
                str(player),
                str(submitted_this_week),
                str(accumulated),
                str(threshold),
                str(max(0, threshold - accumulated)),
            ])

        story.append(Paragraph("Chats Carried Forward", h2))
        carried_table = Table(carried_data, colWidths=[55*mm, 30*mm, 30*mm, 20*mm, 25*mm])
        carried_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(carried_table)

    # Rate reconciliation notes
    reconciliation_notes = []
    for mp in unpaid_payments:
        log = mp.rate_reconciliation or {}
        entries = log.get("entries", []) if isinstance(log, dict) else []
        for entry in entries:
            reconciliation_notes.append(
                f"Record #{mp.id} ({mp.payment_week_start.strftime('%d %b')} – {mp.payment_week_end.strftime('%d %b %Y')}): "
                f"rate {entry.get('old_rate')} -> {entry.get('new_rate')}, "
                f"earned {entry.get('old_earned')} -> {entry.get('new_earned')}"
            )

    if reconciliation_notes:
        story.append(Paragraph("Rate Reconciliation Notes", h2))
        for note in reconciliation_notes:
            story.append(Paragraph(f"&bull; {note}", small))
            story.append(Spacer(1, 4))

    # Footer
    story.append(Spacer(1, 12))
    has_unpaid = any(r.status not in ("PAID", "PARTIALLY_PAID") for r in unpaid_payments)
    has_paid = any(r.status == "PAID" for r in unpaid_payments)
    has_partial = any(r.status == "PARTIALLY_PAID" for r in unpaid_payments)
    if has_unpaid and (has_paid or has_partial):
        footer_text = (
            "This statement covers all selected payroll records for this moderator "
            "(unpaid and paid). Computer-generated at the time of download."
        )
    elif has_paid:
        footer_text = (
            "This statement covers paid payroll records for this moderator. "
            "Computer-generated at the time of download."
        )
    else:
        footer_text = (
            "This statement covers all unpaid payroll records for this moderator. "
            "Computer-generated at the time of download."
        )
    story.append(Paragraph(footer_text, small))

    doc.build(story)
    buffer.seek(0)
    return buffer
