from pathlib import Path

# ============================================================
# 1. notifications/models.py
# ============================================================

path = Path("notifications/models.py")
text = path.read_text(encoding="utf-8")

if "class AlertLevel(models.TextChoices):" not in text:
    marker = '''        GENERAL = (
            "GENERAL",
            "General Notification",
        )

'''

    replacement = '''        GENERAL = (
            "GENERAL",
            "General Notification",
        )


    class AlertLevel(models.TextChoices):
        NORMAL = (
            "NORMAL",
            "Normal",
        )
        IMPORTANT = (
            "IMPORTANT",
            "Important",
        )
        CRITICAL = (
            "CRITICAL",
            "Critical",
        )

'''

    if marker not in text:
        raise SystemExit(
            "ERROR: Could not find the GENERAL notification type block."
        )

    text = text.replace(marker, replacement, 1)


if "alert_level = models.CharField(" not in text:
    marker = '''    notification_type = models.CharField(
        max_length=40,
        choices=NotificationType.choices,
        default=NotificationType.GENERAL,
    )

'''

    replacement = '''    notification_type = models.CharField(
        max_length=40,
        choices=NotificationType.choices,
        default=NotificationType.GENERAL,
    )

    alert_level = models.CharField(
        max_length=20,
        choices=AlertLevel.choices,
        default=AlertLevel.NORMAL,
    )

'''

    if marker not in text:
        raise SystemExit(
            "ERROR: Could not find notification_type field."
        )

    text = text.replace(marker, replacement, 1)


path.write_text(text, encoding="utf-8")
print("OK: notifications/models.py")


# ============================================================
# 2. notifications/views.py
# ============================================================

path = Path("notifications/views.py")
text = path.read_text(encoding="utf-8")

if "notification_status" not in text:

    if "from django.http import HttpResponseRedirect" in text:
        text = text.replace(
            "from django.http import HttpResponseRedirect",
            "from django.http import HttpResponseRedirect, JsonResponse",
            1,
        )
    elif "from django.http import" in text:
        text = text.replace(
            "from django.http import",
            "from django.http import JsonResponse,",
            1,
        )
    else:
        text = (
            "from django.http import JsonResponse\n"
            + text
        )


    if "require_GET" not in text:
        text = text.replace(
            "from django.views.decorators.http import require_POST",
            "from django.views.decorators.http import require_GET, require_POST",
            1,
        )


    addition = '''

@login_required
@require_GET
def notification_status(request):
    """
    Return unread notifications for the logged-in user.

    This endpoint is used by the browser alert engine.
    """

    notifications = list(
        Notification.objects.filter(
            recipient=request.user,
            is_read=False,
        ).order_by("-created_at")[:10]
    )

    return JsonResponse(
        {
            "unread_count": len(notifications),
            "notifications": [
                {
                    "id": notification.id,
                    "title": notification.title,
                    "message": notification.message,
                    "notification_type": notification.notification_type,
                    "alert_level": notification.alert_level,
                    "created_at": notification.created_at.isoformat(),
                }
                for notification in notifications
            ],
        }
    )
'''

    text = text.rstrip() + addition + "\n"

    path.write_text(text, encoding="utf-8")

    print("OK: notifications/views.py")
else:
    print("SKIP: notification_status already exists")


# ============================================================
# 3. notifications/urls.py
# ============================================================

path = Path("notifications/urls.py")
text = path.read_text(encoding="utf-8")

if 'name="status"' not in text:

    marker = "urlpatterns = ["

    if marker not in text:
        raise SystemExit(
            "ERROR: Could not find urlpatterns."
        )

    replacement = '''urlpatterns = [
    path(
        "status/",
        views.notification_status,
        name="status",
    ),'''

    text = text.replace(
        marker,
        replacement,
        1,
    )

    path.write_text(text, encoding="utf-8")

    print("OK: notifications/urls.py")
else:
    print("SKIP: status URL already exists")


# ============================================================
# 4. static/js/notification_alerts.js
# ============================================================

static_dir = Path("static/js")
static_dir.mkdir(
    parents=True,
    exist_ok=True,
)

path = static_dir / "notification_alerts.js"

js = r'''
(function () {
    "use strict";

    const POLL_INTERVAL = 10000;
    const CRITICAL_REPEAT_INTERVAL = 30000;

    let audioContext = null;
    let knownNotificationIds = new Set();
    let criticalTimer = null;
    let initialized = false;


    function soundsEnabled() {
        return (
            localStorage.getItem(
                "sf_alert_sounds_enabled"
            ) === "true"
        );
    }


    function setSoundsEnabled(enabled) {
        localStorage.setItem(
            "sf_alert_sounds_enabled",
            enabled ? "true" : "false"
        );
    }


    function getAudioContext() {
        if (!audioContext) {
            const AudioContext =
                window.AudioContext ||
                window.webkitAudioContext;

            if (!AudioContext) {
                return null;
            }

            audioContext = new AudioContext();
        }

        if (audioContext.state === "suspended") {
            audioContext.resume().catch(function () {});
        }

        return audioContext;
    }


    function tone(
        frequency,
        duration,
        delay,
        volume
    ) {
        const context = getAudioContext();

        if (!context || !soundsEnabled()) {
            return;
        }

        const oscillator =
            context.createOscillator();

        const gain =
            context.createGain();

        oscillator.type = "sine";
        oscillator.frequency.value = frequency;

        const start =
            context.currentTime + delay;

        gain.gain.setValueAtTime(
            0,
            start
        );

        gain.gain.linearRampToValueAtTime(
            volume,
            start + 0.02
        );

        gain.gain.exponentialRampToValueAtTime(
            0.001,
            start + duration
        );

        oscillator.connect(gain);
        gain.connect(context.destination);

        oscillator.start(start);

        oscillator.stop(
            start + duration + 0.05
        );
    }


    function playNormalSound() {
        tone(880, 0.18, 0, 0.10);
    }


    function playImportantSound() {
        tone(880, 0.18, 0, 0.13);
        tone(1046, 0.22, 0.24, 0.13);
    }


    function playCriticalSound() {
        tone(880, 0.18, 0, 0.18);
        tone(880, 0.18, 0.24, 0.18);
        tone(1046, 0.30, 0.48, 0.18);
    }


    function playAlertSound(level) {
        if (level === "CRITICAL") {
            playCriticalSound();
        } else if (level === "IMPORTANT") {
            playImportantSound();
        } else {
            playNormalSound();
        }
    }


    function requestBrowserPermission() {
        if (
            "Notification" in window &&
            Notification.permission === "default"
        ) {
            Notification.requestPermission()
                .catch(function () {});
        }
    }


    function showBrowserNotification(notification) {
        if (
            !("Notification" in window) ||
            Notification.permission !== "granted"
        ) {
            return;
        }

        try {
            const browserNotification =
                new Notification(
                    notification.title,
                    {
                        body: notification.message,
                        tag:
                            "sf-notification-" +
                            notification.id,
                        requireInteraction:
                            notification.alert_level ===
                            "CRITICAL"
                    }
                );

            browserNotification.onclick =
                function () {
                    window.focus();
                    browserNotification.close();
                };

        } catch (error) {
            // Browser may reject notification creation.
        }
    }


    function stopCriticalRepeat() {
        if (criticalTimer) {
            clearInterval(
                criticalTimer
            );

            criticalTimer = null;
        }
    }


    function startCriticalRepeat() {
        stopCriticalRepeat();

        criticalTimer =
            setInterval(
                function () {
                    if (soundsEnabled()) {
                        playCriticalSound();
                    }
                },
                CRITICAL_REPEAT_INTERVAL
            );
    }


    function processNotifications(data) {
        const notifications =
            data.notifications || [];

        const currentIds =
            new Set(
                notifications.map(
                    function (notification) {
                        return String(
                            notification.id
                        );
                    }
                )
            );


        /*
         * Existing unread notifications should
         * not all make noise on initial page load.
         */
        if (!initialized) {
            knownNotificationIds =
                currentIds;

            initialized = true;

            return;
        }


        notifications.forEach(
            function (notification) {

                const id =
                    String(notification.id);

                if (
                    !knownNotificationIds.has(id)
                ) {

                    playAlertSound(
                        notification.alert_level
                    );

                    showBrowserNotification(
                        notification
                    );

                    if (
                        notification.alert_level ===
                        "CRITICAL"
                    ) {
                        startCriticalRepeat();
                    }
                }
            }
        );


        knownNotificationIds =
            currentIds;


        const criticalExists =
            notifications.some(
                function (notification) {
                    return (
                        notification.alert_level ===
                        "CRITICAL"
                    );
                }
            );


        if (!criticalExists) {
            stopCriticalRepeat();
        }
    }


    async function pollNotifications() {

        try {

            const response =
                await fetch(
                    "/notifications/status/",
                    {
                        method: "GET",
                        credentials: "same-origin",
                        headers: {
                            "X-Requested-With":
                                "XMLHttpRequest"
                        },
                        cache: "no-store"
                    }
                );


            if (!response.ok) {
                return;
            }


            const data =
                await response.json();

            processNotifications(data);

        } catch (error) {
            /*
             * Alert polling must never
             * break the application.
             */
        }
    }


    function createSoundControl() {

        if (
            document.getElementById(
                "sf-alert-sound-control"
            )
        ) {
            return;
        }


        const container =
            document.createElement("div");

        container.id =
            "sf-alert-sound-control";

        container.style.position =
            "fixed";

        container.style.right =
            "20px";

        container.style.bottom =
            "20px";

        container.style.zIndex =
            "99999";


        const button =
            document.createElement("button");

        button.type = "button";

        button.className =
            "btn btn-primary shadow";

        button.style.borderRadius =
            "999px";

        button.style.fontWeight =
            "600";


        function updateButton() {

            if (soundsEnabled()) {

                button.innerHTML =
                    "🔊 Alert sounds ON";

                button.className =
                    "btn btn-success shadow";

            } else {

                button.innerHTML =
                    "🔇 Enable alert sounds";

                button.className =
                    "btn btn-primary shadow";
            }
        }


        button.addEventListener(
            "click",
            function () {

                getAudioContext();

                const enabled =
                    !soundsEnabled();

                setSoundsEnabled(
                    enabled
                );

                requestBrowserPermission();

                updateButton();


                if (enabled) {
                    playNormalSound();
                }
            }
        );


        updateButton();

        container.appendChild(button);

        document.body.appendChild(
            container
        );
    }


    function initialize() {

        createSoundControl();

        requestBrowserPermission();

        pollNotifications();


        setInterval(
            pollNotifications,
            POLL_INTERVAL
        );


        document.addEventListener(
            "visibilitychange",
            function () {

                if (!document.hidden) {
                    pollNotifications();
                }

            }
        );
    }


    if (
        document.readyState ===
        "loading"
    ) {

        document.addEventListener(
            "DOMContentLoaded",
            initialize
        );

    } else {

        initialize();
    }

})();
'''

path.write_text(
    js,
    encoding="utf-8"
)

print("OK: static/js/notification_alerts.js")


# ============================================================
# 5. Add JS to existing templates
# ============================================================

templates = [
    Path("templates/dashboard/dashboard.html"),
    Path("templates/dashboard/coverage_history.html"),
    Path("templates/payments/payment_history.html"),
    Path("templates/coverage/moderator_coverage.html"),
    Path("templates/coverage/manager_alerts.html"),
    Path("templates/notifications/notification_list.html"),
]


script_tag = (
    "\n<script "
    "src=\"{% static 'js/notification_alerts.js' %}\">"
    "</script>\n"
)


for template in templates:

    if not template.exists():
        print(
            "SKIP MISSING:",
            template
        )
        continue


    content = template.read_text(
        encoding="utf-8"
    )


    if "{% load static %}" not in content:
        content = (
            "{% load static %}\n" +
            content
        )


    if "notification_alerts.js" not in content:

        if "{% endblock %}" in content:
            content = content.replace(
                "{% endblock %}",
                script_tag +
                "{% endblock %}",
                1,
            )
        else:
            content += script_tag


        template.write_text(
            content,
            encoding="utf-8"
        )

        print(
            "OK TEMPLATE:",
            template
        )

    else:
        print(
            "SKIP ALREADY PATCHED:",
            template
        )


print()
print("ALERT ENGINE PATCH COMPLETE")
