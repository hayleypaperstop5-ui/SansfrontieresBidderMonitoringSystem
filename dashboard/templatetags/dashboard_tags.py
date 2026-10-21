from django import template

from coverage.models import CoverageSession

from players.models import Player

from accounts.models import User



register = template.Library()



@register.inclusion_tag("dashboard/includes/coverage_table.html")

def render_coverage_table():

    active_sessions = CoverageSession.objects.filter(status="ACTIVE").select_related("player", "moderator")

    covered_players = {s.player_id: s for s in active_sessions}

    all_players = Player.objects.filter(status="ACTIVE").order_by("player_number")

    

    # Fetch active moderators for the "Assign" dropdown

    moderators = User.objects.filter(role=User.Role.MODERATOR, is_active=True).order_by("first_name", "username")

    

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

            mod_name = "—"

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



    return {

        "coverage_rows": coverage_rows,

        "moderators": moderators,

    }

