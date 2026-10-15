from uuid import uuid4
from django.db import migrations


def populate_session_codes(apps, schema_editor):
    CoverageSession = apps.get_model("coverage", "CoverageSession")
    
    queryset = CoverageSession.objects.filter(session_code__isnull=True)
    batch = []
    
    for session in queryset.iterator(chunk_size=1000):
        session.session_code = uuid4()
        batch.append(session)
        if len(batch) >= 1000:
            CoverageSession.objects.bulk_update(batch, ["session_code"])
            batch.clear()
            
    if batch:
        CoverageSession.objects.bulk_update(batch, ["session_code"])


def reverse_session_codes(apps, schema_editor):
    CoverageSession = apps.get_model("coverage", "CoverageSession")
    CoverageSession.objects.update(session_code=None)


class Migration(migrations.Migration):

    dependencies = [
        ("coverage", "0010_coveragesession_session_code"),
    ]

    operations = [
        migrations.RunPython(
            populate_session_codes,
            reverse_session_codes,
        ),
    ]
