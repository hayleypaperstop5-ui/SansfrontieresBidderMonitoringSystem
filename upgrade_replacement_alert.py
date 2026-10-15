from pathlib import Path

path = Path("coverage/services.py")
text = path.read_text(encoding="utf-8")

old = '''    Notification.objects.create(
        recipient=session.moderator,
        notification_type=Notification.NotificationType.GENERAL,
        title="Replacement Coverage Assigned",
'''

new = '''    Notification.objects.create(
        recipient=session.moderator,
        notification_type=Notification.NotificationType.GENERAL,
        alert_level=Notification.AlertLevel.CRITICAL,
        title="Replacement Coverage Assigned",
'''

if old not in text:
    raise SystemExit(
        "ERROR: Exact replacement notification block was not found."
    )

text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")

print("OK: Replacement Coverage Assigned notification is now CRITICAL.")
