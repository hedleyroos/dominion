import threading
import pickle

from django.core.mail.backends.filebased import EmailBackend as FileEmailBackend
from django.core.mail.backends.locmem import EmailBackend as LocMemEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SmtpEmailBackend
from django_ses import SESBackend

from triplea.mail.models import EmailMessage
from triplea.mail.tasks import send_mail


class Mixin:
    def send_messages(self, email_messages, immediate=False):
        # The immediate flag is how we know when to actually send the mails instead
        # of queuing them.
        if immediate:
            return super().send_messages(email_messages)
        for email_message in email_messages:
            obj = EmailMessage.objects.create(pickled=pickle.dumps(email_message))
            send_mail.apply_async(args=[obj.id], countdown=5)
        # The return value is not really useful when queuing, but it is required
        return len(email_messages)

    def __getstate__(self):
        state = self.__dict__.copy()
        del state["_lock"]
        return state

    def __setstate__(self, state):
        self.__dict__ = state
        self._lock = threading.RLock()


class CelerySmtpBackend(Mixin, SmtpEmailBackend):
    pass


class CeleryFileBackend(Mixin, FileEmailBackend):
    pass


class CeleryLocMemBackend(Mixin, LocMemEmailBackend):
    """Only used by unit tests.
    """
    pass


class CelerySESBackend(Mixin, SESBackend):
    pass
