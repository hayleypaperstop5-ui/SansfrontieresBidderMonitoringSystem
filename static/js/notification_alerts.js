
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
