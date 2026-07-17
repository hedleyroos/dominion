"""A5 — save-then-validate semantics.

The model save() methods call super().save() *before* clean()/full_clean() so the
counter-cache signals can populate the descendant/resource counters that the limit
checks read. When clean() then fails, the already-inserted row must not survive.

These tests use TransactionTestCase (no enclosing rolled-back transaction) so we can
observe the *committed* state after a ValidationError, and they run on whichever
backend tox selected (sqlite or postgres) so both are covered by CI.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TransactionTestCase, override_settings

from dominion import create_initial_data, models


class SaveValidationLeakTestCase(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        create_initial_data()
        User = get_user_model()
        self.owner = User.objects.create(username="owner_a5")

    def test_domain_with_ancestor_title_clash_does_not_leak(self):
        """A child domain whose title clashes with an ancestor must not persist."""
        root = models.Domain.objects.create(title="Root A5", owner=self.owner)
        before = models.Domain.objects.count()
        with self.assertRaises(ValidationError):
            # Same title as the parent -> clean() raises.
            models.Domain.objects.create(title="Root A5", owner=self.owner, parent=root)
        after = models.Domain.objects.count()
        self.assertEqual(
            after, before,
            "Invalid child domain was committed despite ValidationError (backend leaks "
            "the pre-validation insert).",
        )

    def test_over_limit_domain_does_not_leak(self):
        """Exceeding the descendant limit must not leave the offending row behind."""
        root = models.Domain.objects.create(title="LimitRoot", owner=self.owner)
        with override_settings(DOMINION_MAX_DESCENDANT_DOMAINS=1):
            # root already counts as 1 descendant; adding a child pushes count to 2 > 1.
            before = models.Domain.objects.count()
            with self.assertRaises(ValidationError):
                models.Domain.objects.create(title="LimitChild", owner=self.owner, parent=root)
            after = models.Domain.objects.count()
        self.assertEqual(after, before, "Over-limit domain was committed despite ValidationError.")

    def test_resource_cross_domain_parent_does_not_leak(self):
        """A resource whose parent belongs to another domain must not persist."""
        domain_a = models.Domain.objects.create(title="ResDomA", owner=self.owner)
        domain_b = models.Domain.objects.create(title="ResDomB", owner=self.owner)
        parent = models.Resource.objects.create(urn="a5:parent", domain=domain_a, owner=self.owner)
        before = models.Resource.objects.count()
        with self.assertRaises(ValidationError):
            # Child in domain_b but parent in domain_a -> clean() raises.
            models.Resource.objects.create(
                urn="a5:child", domain=domain_b, parent=parent, owner=self.owner
            )
        after = models.Resource.objects.count()
        self.assertEqual(after, before, "Cross-domain resource was committed despite ValidationError.")

    def test_valid_domain_still_persists_and_counts(self):
        """Sanity: valid saves persist and counters increment (no over-correction)."""
        root = models.Domain.objects.create(title="ValidRoot", owner=self.owner)
        child = models.Domain.objects.create(title="ValidChild", owner=self.owner, parent=root)
        root.refresh_from_db()
        self.assertEqual(root.descendant_count, 2)
        self.assertTrue(models.Domain.objects.filter(id=child.id).exists())

    def test_domain_create_at_exactly_the_limit_succeeds(self):
        """The last child that reaches the limit is allowed; the next one over is not."""
        root = models.Domain.objects.create(title="EdgeRoot", owner=self.owner)
        with override_settings(DOMINION_MAX_DESCENDANT_DOMAINS=2):
            # root counts as 1; one child brings the total to exactly 2 (== limit).
            child = models.Domain.objects.create(title="EdgeChild", owner=self.owner, parent=root)
            self.assertTrue(models.Domain.objects.filter(id=child.id).exists())
            # A second child would be 3 > 2 and must be rejected before insert.
            before = models.Domain.objects.count()
            with self.assertRaises(ValidationError):
                models.Domain.objects.create(title="EdgeChild2", owner=self.owner, parent=root)
            self.assertEqual(models.Domain.objects.count(), before)

    def test_update_existing_domain_does_not_trip_limit(self):
        """Re-saving an existing domain must not count itself again and falsely fail."""
        root = models.Domain.objects.create(title="UpdRoot", owner=self.owner)
        child = models.Domain.objects.create(title="UpdChild", owner=self.owner, parent=root)
        # root now has descendant_count == 2. With the limit set to that exact value,
        # updating the existing child (not adding) must still be allowed.
        with override_settings(DOMINION_MAX_DESCENDANT_DOMAINS=2):
            child.title = "UpdChildRenamed"
            child.save()  # must not raise
        child.refresh_from_db()
        self.assertEqual(child.title, "UpdChildRenamed")

    def test_resource_create_at_exactly_the_limit_succeeds(self):
        domain = models.Domain.objects.create(title="ResEdgeDom", owner=self.owner)
        with override_settings(DOMINION_MAX_RESOURCES_PER_DOMAIN=1):
            r1 = models.Resource.objects.create(urn="edge:r1", domain=domain, owner=self.owner)
            self.assertTrue(models.Resource.objects.filter(id=r1.id).exists())
            before = models.Resource.objects.count()
            with self.assertRaises(ValidationError):
                models.Resource.objects.create(urn="edge:r2", domain=domain, owner=self.owner)
            self.assertEqual(models.Resource.objects.count(), before)
