from django.test import TestCase

from triplea.mail.models import EmailMessage


class EmailMessageModelTestCase(TestCase):
    def _make_db_message(self, subject="Hello", body="World"):
        return EmailMessage.objects.create(
            subject=subject,
            body=body,
            from_email="from@example.com",
            to=["to@example.com"],
        )

    def test_create_stores_structured_fields(self):
        obj = self._make_db_message(subject="Test", body="Content")
        self.assertIsNotNone(obj.id)
        self.assertEqual(obj.subject, "Test")
        self.assertEqual(obj.body, "Content")
        self.assertEqual(obj.from_email, "from@example.com")
        self.assertEqual(obj.to, ["to@example.com"])

    def test_sent_defaults_to_false(self):
        obj = self._make_db_message()
        self.assertFalse(obj.sent)

    def test_json_list_fields_default_to_empty_list(self):
        obj = EmailMessage.objects.create(
            subject="s", body="b", from_email="f@example.com", to=["t@example.com"]
        )
        self.assertEqual(obj.cc, [])
        self.assertEqual(obj.bcc, [])
        self.assertEqual(obj.reply_to, [])

    def test_headers_defaults_to_empty_dict(self):
        obj = self._make_db_message()
        self.assertEqual(obj.headers, {})

    def test_sent_can_be_set_true(self):
        obj = self._make_db_message()
        obj.sent = True
        obj.save(update_fields=["sent"])
        obj.refresh_from_db()
        self.assertTrue(obj.sent)

    def test_created_is_auto_set(self):
        from django.utils import timezone
        before = timezone.now()
        obj = self._make_db_message()
        after = timezone.now()
        self.assertGreaterEqual(obj.created, before)
        self.assertLessEqual(obj.created, after)
