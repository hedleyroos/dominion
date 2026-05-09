# Data migration: populate structured email fields from the old pickled column.
# Rows that cannot be unpickled retain their default empty values.

import pickle

from django.db import migrations


def populate_structured_fields(apps, schema_editor):
    EmailMessage = apps.get_model("dominion_mail", "EmailMessage")
    for message in EmailMessage.objects.all():
        raw = bytes(message.pickled)
        try:
            unpickled = pickle.loads(raw)  # noqa: S301 — historical data only
            message.subject = unpickled.subject or ""
            message.body = unpickled.body or ""
            message.from_email = unpickled.from_email or ""
            message.to = list(unpickled.to or [])
            message.cc = list(unpickled.cc or [])
            message.bcc = list(unpickled.bcc or [])
            message.reply_to = list(unpickled.reply_to or [])
            message.headers = dict(unpickled.extra_headers or {})
            message.save()
        except Exception:
            # Unpickling failed — leave the row with empty defaults rather than
            # blocking the migration.
            pass


class Migration(migrations.Migration):
    """Step 2 of 3: populate the new structured fields from the pickled column."""

    dependencies = [
        ("dominion_mail", "0004_emailmessage_structured_fields"),
    ]

    operations = [
        migrations.RunPython(populate_structured_fields, migrations.RunPython.noop),
    ]
