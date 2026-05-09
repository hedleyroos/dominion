from dominion.api.constants import DEFAULT_PERMISSIONS_Q, DEFAULT_ROLES_Q
from dominion.models import Permission, Role

from dominion.tests.base import BaseTestCase


class ConstantsTestCase(BaseTestCase):
    def test_default_roles_q_returns_all_default_roles(self):
        roles = Role.objects.filter(DEFAULT_ROLES_Q)
        codes = set(roles.values_list("code", flat=True))
        self.assertEqual(codes, {"anonymous", "authenticated", "manager", "owner", "access_checker"})

    def test_default_permissions_q_returns_all_default_permissions(self):
        permissions = Permission.objects.filter(DEFAULT_PERMISSIONS_Q)
        codes = set(permissions.values_list("code", flat=True))
        self.assertEqual(
            codes,
            {"create", "read", "update", "delete", "check_access", "manage_roles", "view"},
        )

    def test_default_roles_q_excludes_custom_roles(self):
        # BaseTestCase creates a "customviewer" role; it must not be in the default set.
        roles = Role.objects.filter(DEFAULT_ROLES_Q)
        codes = set(roles.values_list("code", flat=True))
        self.assertNotIn("customviewer", codes)
