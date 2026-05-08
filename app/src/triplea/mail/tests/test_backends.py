import pickle
import threading
from unittest.mock import MagicMock, patch

from django.core.mail import EmailMessage as DjangoEmailMessage
from django.test import TestCase, override_settings

from triplea.mail.backends import (
    CeleryFileBackend,
    CeleryLocMemBackend,
    CelerySESBackend,
    CelerySmtpBackend,
    Mixin,
)
from triplea.mail.models import EmailMessage

def _make_django_message():
    return DjangoEmailMessage(
        subject="Subject",
        body="Body",
        from_email="from@example.com",
        to=["to@example.com"],
    )


class MixinSendMessagesTestCase(TestCase):
    @override_settings(EMAIL_BACKEND="triplea.mail.backends.CeleryLocMemBackend")
    def test_immediate_true_delegates_to_super(self):
        backend = CeleryLocMemBackend()
        messages = [_make_django_message()]
        with patch.object(type(backend).__mro__[2], "send_messages", return_value=1) as mock_send:
            backend.send_messages(messages, immediate=True)
        mock_send.assert_called_once_with(messages)

    @override_settings(EMAIL_BACKEND="triplea.mail.backends.CeleryLocMemBackend")
    def test_immediate_false_creates_db_records(self):
        backend = CeleryLocMemBackend()
        messages = [_make_django_message(), _make_django_message()]

        with patch("triplea.mail.backends.send_mail") as mock_task:
            mock_task.apply_async = MagicMock()
            result = backend.send_messages(messages, immediate=False)

        self.assertEqual(result, 2)
        self.assertEqual(EmailMessage.objects.count(), 2)

    @override_settings(EMAIL_BACKEND="triplea.mail.backends.CeleryLocMemBackend")
    def test_immediate_false_calls_apply_async_with_countdown(self):
        backend = CeleryLocMemBackend()
        messages = [_make_django_message()]

        with patch("triplea.mail.backends.send_mail") as mock_task:
            mock_task.apply_async = MagicMock()
            backend.send_messages(messages, immediate=False)
            obj = EmailMessage.objects.first()
            mock_task.apply_async.assert_called_once_with(args=[obj.id], countdown=5)

    @override_settings(EMAIL_BACKEND="triplea.mail.backends.CeleryLocMemBackend")
    def test_immediate_false_returns_message_count(self):
        backend = CeleryLocMemBackend()
        messages = [_make_django_message(), _make_django_message(), _make_django_message()]

        with patch("triplea.mail.backends.send_mail") as mock_task:
            mock_task.apply_async = MagicMock()
            result = backend.send_messages(messages, immediate=False)

        self.assertEqual(result, 3)

    def test_getstate_excludes_lock(self):
        # CelerySmtpBackend inherits from SmtpEmailBackend which sets _lock in __init__.
        backend = CelerySmtpBackend()
        state = backend.__getstate__()
        self.assertNotIn("_lock", state)

    def test_setstate_restores_lock(self):
        backend = CelerySmtpBackend()
        state = backend.__getstate__()
        new_backend = CelerySmtpBackend.__new__(CelerySmtpBackend)
        new_backend.__setstate__(state)
        self.assertIsInstance(new_backend._lock, type(threading.RLock()))

    def test_pickle_round_trip(self):
        backend = CelerySmtpBackend()
        pickled = pickle.dumps(backend)
        restored = pickle.loads(pickled)
        self.assertIsInstance(restored._lock, type(threading.RLock()))


class BackendInheritanceTestCase(TestCase):
    def test_celery_locmem_backend_inherits_mixin(self):
        self.assertTrue(issubclass(CeleryLocMemBackend, Mixin))

    def test_celery_smtp_backend_inherits_mixin(self):
        self.assertTrue(issubclass(CelerySmtpBackend, Mixin))

    def test_celery_file_backend_inherits_mixin(self):
        self.assertTrue(issubclass(CeleryFileBackend, Mixin))

    def test_celery_ses_backend_inherits_mixin(self):
        self.assertTrue(issubclass(CelerySESBackend, Mixin))
