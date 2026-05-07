from datetime import timedelta

from django.core.mail import get_connection
from django.utils import timezone

from app.celery import app
from triplea.mail.models import EmailMessage


@app.task(bind=True)
def send_mail(context, email_message_id):
    # Atomic compare-and-set: only the worker that flips sent=True proceeds.
    updated = EmailMessage.objects.filter(id=email_message_id, sent=False).update(sent=True)
    if not updated:
        return
    email_message = EmailMessage.objects.get(id=email_message_id)
    message = email_message.unpickled
    if message is None:
        return
    success = get_connection().send_messages([message], immediate=True)
    if not success:
        EmailMessage.objects.filter(id=email_message_id).update(sent=False)


@app.task
def send_unsent_mails():
    """Periodically send unsent mails.
    """
    for email_message in EmailMessage.objects.filter(sent=False):
        send_mail.delay(email_message.id)

@app.task
def vacuum():
    """Delete old mails.
    """
    start = timezone.now() - timedelta(days=14)
    EmailMessage.objects.filter(created__lte=start).delete()
