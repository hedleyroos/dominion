from django.db import models


class EmailMessage(models.Model):
    """Stores an outbound email message as structured fields for async dispatch by Celery.

    The original pickle-based storage has been replaced to eliminate the pickle
    RCE surface (P3.2).  A data migration populates these fields from the old
    pickled column for any rows that existed before this migration.
    """
    created = models.DateTimeField(auto_now_add=True, editable=False, db_index=True)
    sent = models.BooleanField(default=False, db_index=True)

    subject = models.CharField(max_length=998, default="")
    body = models.TextField(default="")
    from_email = models.CharField(max_length=256, default="")
    to = models.JSONField(default=list)
    cc = models.JSONField(default=list)
    bcc = models.JSONField(default=list)
    reply_to = models.JSONField(default=list)
    headers = models.JSONField(default=dict)
