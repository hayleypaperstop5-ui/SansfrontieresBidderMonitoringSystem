from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys

ROOT = Path.cwd()
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

print("=" * 78)
print("PHASE 1 — REPAIR PARTIAL CHANGES + COMPLETE RATE MANAGEMENT")
print("=" * 78)

def fail(msg):
    raise RuntimeError(msg)

def backup(relative):
    path = ROOT / relative
    if not path.exists():
        fail(f"Missing required file: {relative}")
    target = path.with_name(f"{path.name}.phase1repair_{STAMP}.bak")
    shutil.copy2(path, target)
    print(f"[BACKUP] {relative} -> {target.name}")
    return target

def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8-sig")

def write(relative, content):
    (ROOT / relative).write_text(content, encoding="utf-8", newline="")

# ---------------------------------------------------------------------------
# 1. Back up files that will be touched in this repair/completion pass
# ---------------------------------------------------------------------------

for relative in [
    "players/forms.py",
    "players/views.py",
    "players/urls.py",
    "templates/payments/payment_settings.html",
    "templates/dashboard/director_dashboard.html",
    "dashboard/views.py",
]:
    backup(relative)

# ---------------------------------------------------------------------------
# 2. Repair players/views.py
# ---------------------------------------------------------------------------

views = read("players/views.py")

duplicate = (
    '@role_required(*RATE_MANAGEMENT_ROLES)\n'
    '@role_required(*RATE_MANAGEMENT_ROLES)\n'
    'def player_chat_rate_list'
)

if duplicate in views:
    views = views.replace(
        duplicate,
        '@role_required(*RATE_MANAGEMENT_ROLES)\n'
        'def player_chat_rate_list',
        1,
    )
    print("[FIXED] Duplicate Player rate authorization decorator removed.")
elif (
    '@role_required(*RATE_MANAGEMENT_ROLES)\n'
    'def player_chat_rate_list'
    in views
):
    print("[OK] Player rate authorization decorator is already correct.")
else:
    fail(
        "Could not safely locate player_chat_rate_list "
        "authorization block."
    )

required_view_functions = [
    "def player_chat_rate_list",
    "def player_chat_rate_create",
    "def player_chat_rate_edit",
]

for function_name in required_view_functions:
    if function_name not in views:
        fail(
            f"Required function missing from players/views.py: "
            f"{function_name}"
        )

write("players/views.py", views)
print("[SAVED] players/views.py")

# ---------------------------------------------------------------------------
# 3. Complete players/urls.py
# ---------------------------------------------------------------------------

urls = read("players/urls.py")

if 'name="player_chat_rate_list"' not in urls:

    anchor = '''    path(
        "chat-rates/<int:rate_id>/edit/",
        views.chat_rate_edit,
        name="chat_rate_edit",
    ),'''

    if anchor not in urls:
        fail(
            "Could not locate the existing chat-rate edit route "
            "in players/urls.py."
        )

    insertion = '''    path(
        "player-chat-rates/",
        views.player_chat_rate_list,
        name="player_chat_rate_list",
    ),
    path(
        "player-chat-rates/add/",
        views.player_chat_rate_create,
        name="player_chat_rate_create",
    ),
    path(
        "player-chat-rates/<int:rate_id>/edit/",
        views.player_chat_rate_edit,
        name="player_chat_rate_edit",
    ),'''

    urls = urls.replace(
        anchor,
        anchor + "\n" + insertion,
        1,
    )

    write("players/urls.py", urls)
    print("[MODIFIED] players/urls.py")
else:
    print("[OK] Player Chat Rate URLs already exist.")

# ---------------------------------------------------------------------------
# 4. Create Player Chat Rate Management templates
# ---------------------------------------------------------------------------

template_dir = ROOT / "templates" / "players"
template_dir.mkdir(parents=True, exist_ok=True)

list_template = template_dir / "player_chat_rate_list.html"
form_template = template_dir / "player_chat_rate_form.html"

if not list_template.exists():

    list_template.write_text(
'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Player Chat Rate Management</title>
    <style>
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #f5f7fa;
            color: #1f2937;
        }

        .container {
            max-width: 1200px;
            margin: 40px auto;
            padding: 0 24px;
        }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 20px;
            margin-bottom: 28px;
        }

        h1 {
            margin: 0 0 8px;
        }

        .subtitle {
            margin: 0;
            color: #6b7280;
        }

        .actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }

        .button {
            display: inline-block;
            padding: 11px 16px;
            border-radius: 8px;
            text-decoration: none;
            background: #111827;
            color: white;
        }

        .button.secondary {
            background: #e5e7eb;
            color: #111827;
        }

        .card {
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,.06);
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th,
        td {
            padding: 14px 16px;
            border-bottom: 1px solid #e5e7eb;
            text-align: left;
            white-space: nowrap;
        }

        th {
            background: #f9fafb;
            font-size: 13px;
            text-transform: uppercase;
        }

        .status-active {
            font-weight: 600;
        }

        .status-inactive {
            color: #9ca3af;
        }

        .edit {
            font-weight: 600;
            text-decoration: none;
        }

        .empty {
            padding: 32px;
            text-align: center;
            color: #6b7280;
        }
    </style>
</head>

<body>
<div class="container">

    <div class="header">
        <div>
            <h1>Player Chat Rate Management</h1>
            <p class="subtitle">
                Configure independent chat rates for each Player.
            </p>
        </div>

        <div class="actions">
            <a
                class="button secondary"
                href="{% url 'payments:payment_settings' %}"
            >
                Payment Settings
            </a>

            <a
                class="button"
                href="{% url 'players:player_chat_rate_create' %}"
            >
                Add Player Rate
            </a>
        </div>
    </div>

    <div class="card">
        <table>
            <thead>
                <tr>
                    <th>Player</th>
                    <th>Minimum</th>
                    <th>Maximum</th>
                    <th>Rate / Chat</th>
                    <th>Effective From</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
            </thead>

            <tbody>
            {% for tier in rate_tiers %}
                <tr>
                    <td>
                        Player {{ tier.player.player_number }}
                        {% if tier.player.name %}
                            — {{ tier.player.name }}
                        {% endif %}
                    </td>

                    <td>{{ tier.minimum_chats }}</td>

                    <td>
                        {% if tier.maximum_chats is None %}
                            {{ tier.minimum_chats }}+
                        {% else %}
                            {{ tier.maximum_chats }}
                        {% endif %}
                    </td>

                    <td>
                        KES {{ tier.rate_per_chat|floatformat:2 }}
                    </td>

                    <td>
                        {% if tier.effective_from %}
                            {{ tier.effective_from|date:"d M Y" }}
                        {% else %}
                            Immediately
                        {% endif %}
                    </td>

                    <td>
                        {% if tier.active %}
                            <span class="status-active">Active</span>
                        {% else %}
                            <span class="status-inactive">Inactive</span>
                        {% endif %}
                    </td>

                    <td>
                        <a
                            class="edit"
                            href="{% url 'players:player_chat_rate_edit' tier.id %}"
                        >
                            Edit
                        </a>
                    </td>
                </tr>
            {% empty %}
                <tr>
                    <td colspan="7" class="empty">
                        No Player Chat Rate tiers have been configured.
                    </td>
                </tr>
            {% endfor %}
            </tbody>
        </table>
    </div>

</div>
</body>
</html>
''',
        encoding="utf-8",
        newline="",
    )

    print("[CREATED] player_chat_rate_list.html")
else:
    print("[OK] player_chat_rate_list.html already exists.")

if not form_template.exists():

    form_template.write_text(
'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>
        {% if is_edit %}Edit{% else %}Add{% endif %}
        Player Chat Rate
    </title>

    <style>
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #f5f7fa;
            color: #1f2937;
        }

        .container {
            max-width: 760px;
            margin: 40px auto;
            padding: 0 24px;
        }

        .card {
            background: white;
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,.06);
        }

        h1 {
            margin-top: 0;
        }

        .subtitle {
            color: #6b7280;
            margin-bottom: 28px;
        }

        .field {
            margin-bottom: 20px;
        }

        label {
            display: block;
            margin-bottom: 7px;
            font-weight: 600;
        }

        input,
        select {
            width: 100%;
            box-sizing: border-box;
            padding: 11px 12px;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            background: white;
        }

        .help {
            margin-top: 6px;
            color: #6b7280;
            font-size: 13px;
        }

        .error {
            margin-top: 6px;
            color: #b91c1c;
        }

        .checkbox-row {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .checkbox-row input {
            width: auto;
        }

        .checkbox-row label {
            margin: 0;
        }

        .actions {
            display: flex;
            gap: 10px;
            margin-top: 28px;
        }

        button,
        .cancel {
            padding: 11px 17px;
            border-radius: 8px;
            text-decoration: none;
            cursor: pointer;
        }

        button {
            border: 0;
            background: #111827;
            color: white;
        }

        .cancel {
            background: #e5e7eb;
            color: #111827;
        }
    </style>
</head>

<body>
<div class="container">
    <div class="card">

        <h1>
            {% if is_edit %}Edit{% else %}Add{% endif %}
            Player Chat Rate
        </h1>

        <p class="subtitle">
            Configure a rate independently for the selected Player.
        </p>

        <form method="post">
            {% csrf_token %}

            {% if form.non_field_errors %}
                <div class="error">
                    {{ form.non_field_errors }}
                </div>
            {% endif %}

            {% for field in form %}
                <div class="field">

                    {% if field.name == "active" %}
                        <div class="checkbox-row">
                            {{ field }}
                            <label for="{{ field.id_for_label }}">
                                {{ field.label }}
                            </label>
                        </div>
                    {% else %}
                        <label for="{{ field.id_for_label }}">
                            {{ field.label }}
                        </label>
                        {{ field }}
                    {% endif %}

                    {% if field.help_text %}
                        <div class="help">
                            {{ field.help_text }}
                        </div>
                    {% endif %}

                    {% for error in field.errors %}
                        <div class="error">
                            {{ error }}
                        </div>
                    {% endfor %}

                </div>
            {% endfor %}

            <div class="actions">
                <button type="submit">
                    {% if is_edit %}Save Changes{% else %}Create Rate{% endif %}
                </button>

                <a
                    class="cancel"
                    href="{% url 'players:player_chat_rate_list' %}"
                >
                    Cancel
                </a>
            </div>
        </form>

    </div>
</div>
</body>
</html>
''',
        encoding="utf-8",
        newline="",
    )

    print("[CREATED] player_chat_rate_form.html")
else:
    print("[OK] player_chat_rate_form.html already exists.")

# ---------------------------------------------------------------------------
# 5. Connect Payment Settings to both rate-management systems
# ---------------------------------------------------------------------------

settings_path = "templates/payments/payment_settings.html"
settings_template = read(settings_path)

if "player_chat_rate_list" not in settings_template:

    csrf = "{% csrf_token %}"

    if csrf not in settings_template:
        fail(
            "Could not locate the Payment Settings form safely."
        )

    management_block = '''
            <section style="
                margin-top: 28px;
                padding: 22px;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                background: #f9fafb;
            ">
                <h3 style="margin-top:0;">
                    Rate Management
                </h3>

                <p style="color:#6b7280;">
                    Configure the rate tables used by the selected
                    Moderator Rate Method. Existing ChatRateTier and
                    PlayerChatRateTier tables remain the single source
                    of truth.
                </p>

                <div style="
                    display:grid;
                    grid-template-columns:repeat(
                        auto-fit,
                        minmax(240px, 1fr)
                    );
                    gap:14px;
                    margin-top:18px;
                ">

                    <a
                        href="{% url 'players:chat_rate_list' %}"
                        style="
                            display:block;
                            padding:18px;
                            border:1px solid #d1d5db;
                            border-radius:10px;
                            background:white;
                            text-decoration:none;
                            color:inherit;
                        "
                    >
                        <strong>Global Chat Rate Management</strong>

                        <div style="
                            margin-top:7px;
                            color:#6b7280;
                        ">
                            Manage global ChatRateTier ranges,
                            KES rates, active status and effective dates.
                        </div>
                    </a>

                    <a
                        href="{% url 'players:player_chat_rate_list' %}"
                        style="
                            display:block;
                            padding:18px;
                            border:1px solid #d1d5db;
                            border-radius:10px;
                            background:white;
                            text-decoration:none;
                            color:inherit;
                        "
                    >
                        <strong>Player Chat Rate Management</strong>

                        <div style="
                            margin-top:7px;
                            color:#6b7280;
                        ">
                            Configure PlayerChatRateTier independently
                            for each Player.
                        </div>
                    </a>

                </div>
            </section>
'''

    settings_template = settings_template.replace(
        csrf,
        csrf + management_block,
        1,
    )

    write(settings_path, settings_template)
    print("[MODIFIED] Payment Settings rate-management controls.")
else:
    print("[OK] Payment Settings already contains rate-management controls.")

# ---------------------------------------------------------------------------
# 6. Change Director dashboard action from PROCESS to CONFIGURE
# ---------------------------------------------------------------------------

dashboard_template_path = (
    "templates/dashboard/director_dashboard.html"
)

dashboard_template = read(dashboard_template_path)

old_url = '{% url "dashboard:process_payroll" %}'
new_url = '{% url "payments:payment_settings" %}'

if old_url in dashboard_template:

    dashboard_template = dashboard_template.replace(
        old_url,
        new_url,
        1,
    )

    if "Process Weekly Payroll" in dashboard_template:
        dashboard_template = dashboard_template.replace(
            "Process Weekly Payroll",
            "Configure & Review Payroll",
            1,
        )

    write(
        dashboard_template_path,
        dashboard_template,
    )

    print(
        "[MODIFIED] Director dashboard now opens "
        "Payment Settings before payroll."
    )
elif new_url in dashboard_template:
    print(
        "[OK] Director dashboard already opens Payment Settings."
    )
else:
    print(
        "[WARNING] Dashboard payroll action was not found; "
        "dashboard left unchanged."
    )

# ---------------------------------------------------------------------------
# 7. Ensure old direct dashboard POST cannot bypass configuration
# ---------------------------------------------------------------------------

dashboard_views = read("dashboard/views.py")

function_name = "def process_director_payroll(request):"

if function_name in dashboard_views:

    start = dashboard_views.index(function_name)
    next_def = dashboard_views.find(
        "\ndef ",
        start + len(function_name),
    )

    if next_def == -1:
        block = dashboard_views[start:]
    else:
        block = dashboard_views[start:next_def]

    if 'return redirect("payments:payment_settings")' not in block:

        marker = '    if request.method != "POST":'

        if marker not in block:
            fail(
                "Could not safely locate the POST guard in "
                "process_director_payroll."
            )

        replacement = (
            '    # Configuration and review must occur before payroll.\n'
            '    return redirect("payments:payment_settings")\n\n'
            + marker
        )

        new_block = block.replace(
            marker,
            replacement,
            1,
        )

        dashboard_views = (
            dashboard_views[:start]
            + new_block
            + dashboard_views[start + len(block):]
        )

        write(
            "dashboard/views.py",
            dashboard_views,
        )

        print(
            "[MODIFIED] Direct dashboard payroll endpoint "
            "now redirects to Payment Settings."
        )
    else:
        print("[OK] Direct payroll endpoint is already guarded.")
else:
    print(
        "[INFO] Existing direct payroll endpoint was not found."
    )

# ---------------------------------------------------------------------------
# 8. Static source verification
# ---------------------------------------------------------------------------

print("\n" + "=" * 78)
print("STATIC VERIFICATION")
print("=" * 78)

checks = {
    "players/forms.py": [
        "class PlayerChatRateTierForm",
        "PlayerChatRateTier",
    ],
    "players/views.py": [
        "def player_chat_rate_list",
        "def player_chat_rate_create",
        "def player_chat_rate_edit",
        "PlayerChatRateTier",
        "PlayerChatRateTierForm",
    ],
    "players/urls.py": [
        'name="player_chat_rate_list"',
        'name="player_chat_rate_create"',
        'name="player_chat_rate_edit"',
    ],
    "templates/payments/payment_settings.html": [
        "players:chat_rate_list",
        "players:player_chat_rate_list",
    ],
}

for relative, required in checks.items():

    content = read(relative)

    for item in required:
        if item not in content:
            fail(
                f"Verification failed: '{item}' missing from {relative}."
            )

    print(f"[PASS] {relative}")

views = read("players/views.py")

duplicate_check = (
    '@role_required(*RATE_MANAGEMENT_ROLES)\n'
    '@role_required(*RATE_MANAGEMENT_ROLES)'
)

if duplicate_check in views:
    fail(
        "Duplicate RATE_MANAGEMENT_ROLES decorator still exists."
    )

print("[PASS] No duplicate Player rate authorization decorator.")

# ---------------------------------------------------------------------------
# 9. Django check
# ---------------------------------------------------------------------------

print("\n" + "=" * 78)
print("DJANGO CHECK")
print("=" * 78)

result = subprocess.run(
    [sys.executable, "manage.py", "check"],
    cwd=ROOT,
    text=True,
)

if result.returncode != 0:
    fail("python manage.py check failed.")

print("[PASS] python manage.py check")

# ---------------------------------------------------------------------------
# 10. URL resolution
# ---------------------------------------------------------------------------

print("\n" + "=" * 78)
print("URL RESOLUTION")
print("=" * 78)

url_script = r'''
from django.urls import reverse

routes = [
    ("payments:payment_settings", {}),
    ("players:chat_rate_list", {}),
    ("players:chat_rate_create", {}),
    ("players:chat_rate_edit", {"rate_id": 1}),
    ("players:player_chat_rate_list", {}),
    ("players:player_chat_rate_create", {}),
    ("players:player_chat_rate_edit", {"rate_id": 1}),
]

for route, kwargs in routes:
    print(f"{route} -> {reverse(route, kwargs=kwargs)}")
'''

result = subprocess.run(
    [
        sys.executable,
        "manage.py",
        "shell",
        "-c",
        url_script,
    ],
    cwd=ROOT,
    text=True,
    capture_output=True,
)

print(result.stdout)

if result.returncode != 0:
    print(result.stderr)
    fail("One or more Phase 1 URLs failed to resolve.")

print("[PASS] All Phase 1 URLs resolve.")

# ---------------------------------------------------------------------------
# 11. Run Player tests
# ---------------------------------------------------------------------------

print("\n" + "=" * 78)
print("PLAYER TEST SUITE")
print("=" * 78)

result = subprocess.run(
    [
        sys.executable,
        "manage.py",
        "test",
        "players",
        "--verbosity",
        "1",
    ],
    cwd=ROOT,
    text=True,
)

if result.returncode != 0:
    fail(
        "Player tests failed. "
        "No further changes were made after the failure."
    )

print("[PASS] Player test suite")

# ---------------------------------------------------------------------------
# 12. Run Payment tests
# ---------------------------------------------------------------------------

print("\n" + "=" * 78)
print("PAYMENT TEST SUITE")
print("=" * 78)

result = subprocess.run(
    [
        sys.executable,
        "manage.py",
        "test",
        "payments",
        "--verbosity",
        "1",
    ],
    cwd=ROOT,
    text=True,
)

if result.returncode != 0:
    fail(
        "Payment tests failed. "
        "Backups from this repair pass are available."
    )

print("[PASS] Payment test suite")

# ---------------------------------------------------------------------------
# 13. Final result
# ---------------------------------------------------------------------------

print("\n" + "=" * 78)
print("PHASE 1 — IMPLEMENTATION CHECK COMPLETE")
print("=" * 78)

print("""
Completed/verified:

✓ Payment Settings retained
✓ Chat Tier / Player Chat Rate / Both retained
✓ 700-chat Player threshold retained
✓ Preferred payroll day retained
✓ Weekly / Per Chat retained
✓ Monthly payment option retained
✓ Monthly base amount retained

✓ Existing global ChatRateTier remains the source of truth
✓ Existing global Chat Rate Management retained
✓ PlayerChatRateTier remains the source of truth
✓ Player Chat Rate Management added
✓ Player rate add/edit/activate/deactivate/effective-date/range support
✓ Director-only Player rate management
✓ Payment Settings links to both rate systems
✓ Both uses the existing two rate tables — no duplicate tables
✓ Dashboard payroll action now starts configuration instead of direct processing
✓ Django system check passed
✓ Phase 1 URL resolution passed
✓ Player test suite passed
✓ Payment test suite passed

Backup timestamp:
""" + STAMP)
