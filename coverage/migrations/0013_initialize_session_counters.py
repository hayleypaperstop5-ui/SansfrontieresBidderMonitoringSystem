from django.db import migrations


def initialize_session_counters(apps, schema_editor):
    CoverageSession = apps.get_model("coverage", "CoverageSession")
    CoverageSessionCounter = apps.get_model("coverage", "CoverageSessionCounter")

    for session_type, prefix in (
        ("DAY", "SFCMD"),
        ("NIGHT", "SFCMN"),
    ):
        max_number = 0

        for code in CoverageSession.objects.filter(
            session_code__startswith=prefix
        ).values_list("session_code", flat=True):
            try:
                number = int(code[len(prefix):])
            except (TypeError, ValueError):
                continue

            max_number = max(max_number, number)

        calculated_next = max_number + 1

        counter, created = CoverageSessionCounter.objects.get_or_create(
            session_type=session_type,
            defaults={"next_number": calculated_next},
        )

        if not created and counter.next_number < calculated_next:
            counter.next_number = calculated_next
            counter.save(update_fields=["next_number"])


def reverse_initialize_session_counters(apps, schema_editor):
    CoverageSessionCounter = apps.get_model(
        "coverage",
        "CoverageSessionCounter",
    )

    CoverageSessionCounter.objects.filter(
        session_type__in=["DAY", "NIGHT"]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("coverage", "0012_coveragesessioncounter_and_more"),
    ]

    operations = [
        migrations.RunPython(
            initialize_session_counters,
            reverse_initialize_session_counters,
        ),
    ]