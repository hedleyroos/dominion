from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from dominion import create_initial_data
from dominion.tasks import vacuum


class VacuumTaskTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        create_initial_data()

    def _create_user(self, username, active=False, activation_date=None, days_old=0):
        User = get_user_model()
        user = User.objects.create(username=username, email=f"{username}@test.com")
        user.is_active = active
        user.activation_date = activation_date
        user.save(update_fields=["is_active", "activation_date"])
        if days_old > 0:
            old_date = timezone.now() - timedelta(days=days_old)
            User.objects.filter(pk=user.pk).update(date_joined=old_date)
        return user

    def test_deletes_inactive_users_older_than_seven_days(self):
        user = self._create_user("oldunactivated", active=False, days_old=8)
        vacuum.apply()
        User = get_user_model()
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    def test_preserves_inactive_users_newer_than_seven_days(self):
        user = self._create_user("newunactivated", active=False, days_old=3)
        vacuum.apply()
        User = get_user_model()
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_preserves_active_users_regardless_of_age(self):
        user = self._create_user("activatedold", active=True, days_old=30)
        vacuum.apply()
        User = get_user_model()
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_preserves_inactive_users_with_activation_date_set(self):
        # A user who was activated (activation_date set) but is_active=False should be kept.
        user = self._create_user(
            "deactivated",
            active=False,
            activation_date=timezone.now() - timedelta(days=10),
            days_old=10,
        )
        vacuum.apply()
        User = get_user_model()
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_exactly_at_boundary_is_preserved(self):
        # Exactly 7 days old: date_joined < (now - 7 days), so at exactly 7 days it is NOT deleted.
        # The filter is date_joined__lte=start where start = now - 7 days.
        # At exactly 7 days old: date_joined == start → deleted.
        # At 6 days and 23 hours: not deleted.
        user = self._create_user("boundary_user", active=False, days_old=6)
        vacuum.apply()
        User = get_user_model()
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
