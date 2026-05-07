from django.core.exceptions import ValidationError
from django.test import override_settings

from tests.base import BaseTestCase
from triplea import models
from triplea.utils import user_has_permission_for_domain, user_has_permission_for_resource


class ModelsTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()

    def test_domaina_read(self):
        self.assertTrue(user_has_permission_for_domain(self.owner.id, "read", self.domaina.id))

        self.assertFalse(user_has_permission_for_domain(self.piet.id, "read", self.domaina.id))

        self.assertTrue(user_has_permission_for_domain(self.jan.id, "read", self.domaina.id))

    def test_domainaa_read(self):
        self.assertTrue(user_has_permission_for_domain(self.owner.id, "read", self.domainaa.id))

        self.assertFalse(user_has_permission_for_domain(self.piet.id, "read", self.domainaa.id))

        self.assertTrue(user_has_permission_for_domain(self.jan.id, "read", self.domainaa.id))

    def test_domaina_resourcea_read(self):
        self.assertTrue(
            user_has_permission_for_resource(self.owner.id, "read", self.domaina_resourcea.id)
        )

        self.assertFalse(
            user_has_permission_for_resource(self.piet.id, "read", self.domaina_resourcea.id)
        )

        self.assertTrue(
            user_has_permission_for_resource(self.jan.id, "read", self.domaina_resourcea.id)
        )

    def test_domaina_resourceaa_read(self):
        """Nobody can read domaina_resourceaa."""
        self.assertFalse(
            user_has_permission_for_resource(self.owner.id, "read", self.domaina_resourceaa.id)
        )

        self.assertFalse(
            user_has_permission_for_resource(self.jan.id, "read", self.domaina_resourceaa.id)
        )

    def test_domaina_resourceb_read(self):
        self.assertTrue(
            user_has_permission_for_resource(self.owner.id, "read", self.domaina_resourceb.id)
        )

        self.assertTrue(
            user_has_permission_for_resource(self.piet.id, "read", self.domaina_resourceb.id)
        )
        self.assertFalse(
            user_has_permission_for_resource(self.piet.id, "update", self.domaina_resourceb.id)
        )

        self.assertTrue(
            user_has_permission_for_resource(self.jan.id, "read", self.domaina_resourceb.id)
        )

    def test_domaina_resourceba_read(self):
        self.assertTrue(
            user_has_permission_for_resource(self.owner.id, "read", self.domaina_resourceba.id)
        )

        self.assertTrue(
            user_has_permission_for_resource(self.jan.id, "read", self.domaina_resourceba.id)
        )

        self.assertTrue(
            user_has_permission_for_resource(self.piet.id, "read", self.domaina_resourceba.id)
        )

    def test_domaina_resourceca_read(self):
        self.assertTrue(
            user_has_permission_for_resource(self.owner.id, "read", self.domaina_resourceca.id)
        )

        self.assertTrue(
            user_has_permission_for_resource(self.piet.id, "read", self.domaina_resourceca.id)
        )

    def test_domainaa_resourcea_read(self):
        self.assertTrue(
            user_has_permission_for_resource(self.owner.id, "read", self.domainaa_resourcea.id)
        )

        self.assertFalse(
            user_has_permission_for_resource(self.piet.id, "read", self.domainaa_resourcea.id)
        )

        self.assertTrue(
            user_has_permission_for_resource(self.jan.id, "read", self.domainaa_resourcea.id)
        )

    def test_domaina_resourcea_create(self):
        """Create a new resource contained by domaina_resourcea."""
        self.assertTrue(
            user_has_permission_for_resource(self.owner.id, "create", self.domaina_resourcea.id)
        )

        self.assertFalse(
            user_has_permission_for_resource(self.piet.id, "create", self.domaina_resourcea.id)
        )

        self.assertFalse(
            user_has_permission_for_resource(self.jan.id, "create", self.domaina_resourcea.id)
        )

    def test_karen_domaina_resourced_roles_and_permissions(self):
        self.assertTrue(
            user_has_permission_for_resource(self.karen.id, "update", self.domaina_resourced.id)
        )

        # Remember, we set Manager role on domaina_resourced to be able to delete
        self.assertTrue(
            user_has_permission_for_resource(self.karen.id, "delete", self.domaina_resourced.id)
        )

    def test_karen_domainab_roles_and_permissions(self):
        self.assertTrue(user_has_permission_for_domain(self.karen.id, "update", self.domainab.id))

        # Remember, we set Manager role on domainab to be able to delete
        self.assertTrue(user_has_permission_for_domain(self.karen.id, "delete", self.domainab.id))

    def test_domainaa_root(self):
        self.assertEqual(self.domainaa.root, self.domaina)

    @override_settings(TRIPLEA_MAX_DESCENDANT_DOMAINS=10)
    def test_domain_limit(self):
        with self.assertRaises(ValidationError):
            for i in range(20):
                domain = models.Domain.objects.create(title="Domain %s" % i, parent=self.domaina, owner=self.owner)
                domain.full_clean()

    @override_settings(TRIPLEA_MAX_RESOURCES_PER_DOMAIN=10)
    def test_resource_limit(self):
        with self.assertRaises(ValidationError):
            for i in range(20):
                resource = models.Resource.objects.create(urn="resource:%s" % i, domain=self.domainaa, owner=self.owner)
                resource.full_clean()
