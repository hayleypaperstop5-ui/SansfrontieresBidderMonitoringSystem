from django import template

register = template.Library()


@register.filter
def coverage_duration(start, end):
    if not start or not end:
        return "-"

    total_seconds = int((end - start).total_seconds())

    if total_seconds < 0:
        return "-"

    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60

    if hours and minutes:
        return f"{hours} hr {minutes} min"
    if hours:
        return f"{hours} hr"
    return f"{minutes} min"
