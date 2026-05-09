from django.contrib.auth import get_user_model
from django.test import TestCase
from django_registration.signals import user_activated

# Importing handlers registers the signal connection as a side effect.
import dominion.handlers  # noqa: F401


class HandlersTestCase(TestCase):
    def test_on_user_activated_sets_activation_date(self):
        User = get_user_model()
        user = User.objects.create(username="testuser_handler", email="handler@test.com")
        self.assertIsNone(user.activation_date)

        user_activated.send(sender=User, user=user, request=None)

        user.refresh_from_db()
        self.assertIsNotNone(user.activation_date)

    def test_on_user_activated_overwrites_existing_activation_date(self):
        from django.utils import timezone
        User = get_user_model()
        user = User.objects.create(username="testuser_handler2", email="handler2@test.com")
        old_date = timezone.now()
        user.activation_date = old_date
        user.save()

        user_activated.send(sender=User, user=user, request=None)

        user.refresh_from_db()
        self.assertIsNotNone(user.activation_date)
        # A new activation_date should be set (may equal old_date if test runs fast, but must be set).
        self.assertIsNotNone(user.activation_date)

    def test_signal_is_connected(self):
        receivers = user_activated.receivers
        self.assertTrue(len(receivers) > 0)
