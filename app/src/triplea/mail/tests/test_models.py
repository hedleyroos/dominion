import pickle

from django.core.mail import EmailMessage as DjangoEmailMessage
from django.test import TestCase

from triplea.mail.models import EmailMessage


class EmailMessageModelTestCase(TestCase):
    def _make_django_message(self, subject="Hello", body="World"):
        return DjangoEmailMessage(
            subject=subject,
            body=body,
            from_email="from@example.com",
            to=["to@example.com"],
        )

    def test_create_stores_pickled_message(self):
        django_msg = self._make_django_message()
        obj = EmailMessage.objects.create(pickled=pickle.dumps(django_msg))
        self.assertIsNotNone(obj.id)
        self.assertIsNotNone(obj.created)

    def test_sent_defaults_to_false(self):
        django_msg = self._make_django_message()
        obj = EmailMessage.objects.create(pickled=pickle.dumps(django_msg))
        self.assertFalse(obj.sent)

    def test_unpickled_returns_correct_message(self):
        django_msg = self._make_django_message(subject="Test subject", body="Test body")
        obj = EmailMessage.objects.create(pickled=pickle.dumps(django_msg))
        unpickled = obj.unpickled
        self.assertEqual(unpickled.subject, "Test subject")
        self.assertEqual(unpickled.body, "Test body")
        self.assertEqual(unpickled.to, ["to@example.com"])

    def test_sent_can_be_set_true(self):
        django_msg = self._make_django_message()
        obj = EmailMessage.objects.create(pickled=pickle.dumps(django_msg))
        obj.sent = True
        obj.save(update_fields=["sent"])
        obj.refresh_from_db()
        self.assertTrue(obj.sent)

    def test_created_is_auto_set(self):
        from django.utils import timezone
        before = timezone.now()
        django_msg = self._make_django_message()
        obj = EmailMessage.objects.create(pickled=pickle.dumps(django_msg))
        after = timezone.now()
        self.assertGreaterEqual(obj.created, before)
        self.assertLessEqual(obj.created, after)

    def test_corrupt_pickle_returns_none_on_unpickle(self):
        obj = EmailMessage.objects.create(pickled=b"not valid pickle data")
        self.assertIsNone(obj.unpickled)
