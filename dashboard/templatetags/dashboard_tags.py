from django import template

from coverage.models import CoverageSession

from players.models import Player

from accounts.models import User



register = template.Library()





@register.inclusion_tag("dashboard/includes/coverage_table.html", takes_context=True)
def render_coverage_table(context):

    # Active coverage sessions (who is currently covering whom)

    active_sessions = CoverageSession.objects.filter(status="ACTIVE").select_related("player", "moderator")

    covered_players = {s.player_id: s for s in active_sessions}



    # All active players, sorted

    all_players = Player.objects.filter(status="ACTIVE").order_by("player_number")



    # Fetch ONLY fully-eligible moderators:

    # 1. Must be MODERATOR role

    # 2. Must be active (is_active=True)

    # 3. Staff profile must be ACTIVE (not suspended/terminated)

    # 4. Must NOT be currently covering a player (no ACTIVE session)

    # 5. Must NOT have a pending End-of-Session Report (no AWAITING_REPORT session)

    active_mod_ids = (

        CoverageSession.objects

        .filter(status="ACTIVE")

        .values_list("moderator_id", flat=True)

    )

    awaiting_report_mod_ids = (

        CoverageSession.objects

        .filter(status="AWAITING_REPORT")

        .values_list("moderator_id", flat=True)

    )

    excluded_ids = set(active_mod_ids) | set(awaiting_report_mod_ids)

    moderators = (

        User.objects

        .filter(

            role=User.Role.MODERATOR,

            is_active=True,

            staff_profile__status="ACTIVE",

        )

        .exclude(id__in=excluded_ids)

        .order_by("first_name", "last_name", "username")

    )



    # Build the coverage rows for the table

    coverage_rows = []

    for player in all_players:

        session = covered_players.get(player.id)

        if session:

            mod = session.moderator

            mod_name = mod.get_full_name() or mod.username

            status = "Covered"

            status_class = "bg-green-50 text-green-700 border-green-200"

            replacement_class = ""

            session_id = session.id

            if getattr(session, "replacement_requested_at", None) is not None:

                replacement_class = '<span class="ml-3 inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-amber-100 text-amber-800 border border-amber-300">Replacement Requested</span>'

        else:

            mod_name = "\u2014"

            status = "Uncovered"

            status_class = "bg-red-50 text-red-700 border-red-200"

            replacement_class = ""

            session_id = None



        coverage_rows.append({

            "player": str(player),

            "player_id": player.id,

            "moderator": mod_name,

            "status": status,

            "status_class": status_class,

            "replacement_badge": replacement_class,

            "session_id": session_id,

            "has_replacement": getattr(session, "replacement_requested_at", None) is not None if session else False,

        })
    # Determine if the current user has management permissions
    user = context.get("request").user if context.get("request") else None
    user_role = getattr(user, "role", None)
    is_management = user_role in ("MANAGER", "DIRECTOR")

    return {
        "coverage_rows": coverage_rows,
        "moderators": moderators,
        "is_management": is_management,
    }

