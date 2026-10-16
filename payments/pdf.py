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
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=6)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, textColor=colors.grey)
    body = styles["Normal"]
    body.fontSize = 10

    story = []

    # ---------- Header ----------
    moderator = payment.moderator
    mod_name = moderator.get_full_name() or moderator.username
    story.append(Paragraph("Sansfrontieres &mdash; Payment Statement", h1))
    story.append(Paragraph(
        f"Statement #{payment.id} &nbsp;|&nbsp; "
        f"Issued {_date_str(payment.payment_date)}",
        small,
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
        [_fmt(payment.payable_chats), f"KES {_fmt(payment.chat_earnings)}",
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
    if breakdown_display:
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

    # ---------- Payment Record ----------
    story.append(Paragraph("Payment Record", h2))
    if payment.status in ("PAID", "PARTIALLY_PAID"):
        pay_data = [
            ["Amount Paid", f"KES {_fmt(payment.amount_paid)}"],
            ["Outstanding", f"KES {_fmt(payment.outstanding_amount)}"],
            ["M-Pesa Reference", payment.mpesa_reference or "—"],
            ["Recorded At", _datetime_str(payment.paid_at)],
            ["Recorded By", (payment.paid_by.get_full_name() or payment.paid_by.username) if payment.paid_by else "—"],
        ]
    else:
        pay_data = [
            ["Outstanding", f"KES {_fmt(payment.outstanding_amount)}"],
            ["Status", "Not yet paid"],
        ]
    pay_table = Table(pay_data, colWidths=[50*mm, 115*mm])
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
