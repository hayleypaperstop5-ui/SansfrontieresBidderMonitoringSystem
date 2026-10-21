"""
Context processors for the dashboard app.

Provides the daily moderator performance chart data to any template
that includes it, without needing to touch individual views.

Registered in settings.TEMPLATES[0]["OPTIONS"]["context_processors"].
"""


def weekly_moderator_chats(request):
    """
    Provide `weekly_chart_json` to templates.

    Only computes on pages that are rendered for authenticated users;
    returns None for anonymous users (chart auto-hides).
    """
    # Don't bother for anonymous users or non-dashboard pages
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    try:
        from dashboard.views import _get_weekly_moderator_chats
        import json
        data = _get_weekly_moderator_chats()
        return {"weekly_chart_json": json.dumps(data)}
    except Exception:
        # Never let a chart computation crash a page
        return {"weekly_chart_json": None}

def moderator_weekly_chart_json(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    if getattr(request.user, "role", None) != "MODERATOR":
        return {}
    try:
        from dashboard.views import _get_moderator_weekly_chats
        import json
        return {"moderator_weekly_chart_json": json.dumps(_get_moderator_weekly_chats(request.user))}
    except Exception:
        return {"moderator_weekly_chart_json": None}

def moderator_weekly_earnings_json(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    if getattr(request.user, "role", None) != "MODERATOR":
        return {}
    try:
        from dashboard.views import _get_moderator_weekly_earnings
        import json
        return {"moderator_weekly_earnings_json": json.dumps(_get_moderator_weekly_earnings(request.user))}
    except Exception:
        return {"moderator_weekly_earnings_json": None}
