from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from triplea.mail.models import EmailMessage
from triplea.mail.tasks import send_mail, send_unsent_mails, vacuum


def _make_db_message(subject="Subject"):
    return EmailMessage.objects.create(
        subject=subject,
        body="Body",
        from_email="from@example.com",
        to=["to@example.com"],
    )


@override_settings(EMAIL_BACKEND="triplea.mail.backends.CeleryLocMemBackend")
class SendMailTaskTestCase(TestCase):
    def test_send_mail_marks_message_as_sent(self):
        obj = _make_db_message()
        send_mail.apply(args=[obj.id])
        obj.refresh_from_db()
        self.assertTrue(obj.sent)

    def test_send_mail_appends_to_mail_outbox(self):
        obj = _make_db_message(subject="Outbox test")
        send_mail.apply(args=[obj.id])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Outbox test")

    def test_send_mail_skips_already_sent_message(self):
        obj = _make_db_message()
        obj.sent = True
        obj.save(update_fields=["sent"])

        send_mail.apply(args=[obj.id])

        # No message should have been sent (outbox stays empty).
        self.assertEqual(len(mail.outbox), 0)

    def test_send_mail_idempotent_on_second_call(self):
        obj = _make_db_message()
        send_mail.apply(args=[obj.id])
        outbox_count_after_first = len(mail.outbox)

        send_mail.apply(args=[obj.id])

        # Second call is a no-op; outbox count must not increase.
        self.assertEqual(len(mail.outbox), outbox_count_after_first)

    def test_send_mail_preserves_recipients(self):
        obj = EmailMessage.objects.create(
            subject="Multi",
            body="Body",
            from_email="from@example.com",
            to=["a@example.com", "b@example.com"],
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
        )
        send_mail.apply(args=[obj.id])
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["a@example.com", "b@example.com"])
        self.assertEqual(sent.cc, ["cc@example.com"])
        self.assertEqual(sent.bcc, ["bcc@example.com"])


@override_settings(EMAIL_BACKEND="triplea.mail.backends.CeleryLocMemBackend")
class SendUnsentMailsTaskTestCase(TestCase):
    def test_sends_all_unsent_messages(self):
        obj1 = _make_db_message(subject="First")
        obj2 = _make_db_message(subject="Second")

        with patch("triplea.mail.tasks.send_mail") as mock_task:
            mock_task.delay = MagicMock()
            send_unsent_mails.apply()
            dispatched_ids = {call.args[0] for call in mock_task.delay.call_args_list}

        self.assertIn(obj1.id, dispatched_ids)
        self.assertIn(obj2.id, dispatched_ids)

    def test_does_not_dispatch_already_sent_messages(self):
        obj = _make_db_message()
        obj.sent = True
        obj.save(update_fields=["sent"])

        with patch("triplea.mail.tasks.send_mail") as mock_task:
            mock_task.delay = MagicMock()
            send_unsent_mails.apply()

        mock_task.delay.assert_not_called()

    def test_sends_only_unsent_when_mix_exists(self):
        sent_obj = _make_db_message(subject="Already sent")
        sent_obj.sent = True
        sent_obj.save(update_fields=["sent"])

        unsent_obj = _make_db_message(subject="To be sent")

        with patch("triplea.mail.tasks.send_mail") as mock_task:
            mock_task.delay = MagicMock()
            send_unsent_mails.apply()
            dispatched_ids = {call.args[0] for call in mock_task.delay.call_args_list}

        self.assertIn(unsent_obj.id, dispatched_ids)
        self.assertNotIn(sent_obj.id, dispatched_ids)


class VacuumTaskTestCase(TestCase):
    def test_vacuum_deletes_old_messages(self):
        old_obj = _make_db_message()
        # Manually backdate the created timestamp.
        old_time = timezone.now() - timedelta(days=15)
        EmailMessage.objects.filter(id=old_obj.id).update(created=old_time)

        vacuum.apply()

        self.assertFalse(EmailMessage.objects.filter(id=old_obj.id).exists())

    def test_vacuum_preserves_recent_messages(self):
        recent_obj = _make_db_message()

        vacuum.apply()

        self.assertTrue(EmailMessage.objects.filter(id=recent_obj.id).exists())

    def test_vacuum_preserves_messages_exactly_at_boundary(self):
        boundary_obj = _make_db_message()
        # 13 days old — just within the 14-day window.
        boundary_time = timezone.now() - timedelta(days=13)
        EmailMessage.objects.filter(id=boundary_obj.id).update(created=boundary_time)

        vacuum.apply()

        self.assertTrue(EmailMessage.objects.filter(id=boundary_obj.id).exists())
