from tests.base import BaseTestCase
from dominion import models
from dominion.admin_forms import DomainManageRolesPermissionsForm, ResourceManageRolesPermissionsForm


class DomainManageRolesPermissionsFormTestCase(BaseTestCase):
    def _form_data(self, permission_ids=None, role_permission_pairs=None):
        """Build the POST data dict that the form expects.

        Permissions are submitted as  permission_{id}_on  keys.
        Role-permission pairs as       role_{role_id}_on_{permission_id}_on  keys.
        """
        data = {}
        for permission_id in (permission_ids or []):
            data[f"permission_{permission_id}_on"] = "on"
        for role_id, permission_id in (role_permission_pairs or []):
            data[f"role_{role_id}_on_{permission_id}_on"] = "on"
        return data

    def test_save_creates_domain_permission_with_inherit_true(self):
        permission_read = models.Permission.objects.get(code="read")
        data = self._form_data(permission_ids=[permission_read.id])
        form = DomainManageRolesPermissionsForm(data=data, instance=self.domaina)
        self.assertTrue(form.is_valid())
        form.save()

        obj = models.DomainPermission.objects.get(domain=self.domaina, permission=permission_read)
        self.assertTrue(obj.inherit)

    def test_save_creates_role_permission(self):
        permission_read = models.Permission.objects.get(code="read")
        role_manager = models.Role.objects.get(code="manager")
        data = self._form_data(
            permission_ids=[permission_read.id],
            role_permission_pairs=[(role_manager.id, permission_read.id)],
        )
        form = DomainManageRolesPermissionsForm(data=data, instance=self.domaina)
        form.is_valid()
        form.save()

        self.assertTrue(
            models.DomainRolePermission.objects.filter(
                domain=self.domaina, role=role_manager, permission=permission_read
            ).exists()
        )

    def test_save_removes_previous_role_permissions(self):
        # The form always recreates role-permission records from scratch.
        permission_read = models.Permission.objects.get(code="read")
        # Verify the customviewer role-permission exists (created in BaseTestCase).
        role_customviewer = models.Role.objects.get(code="customviewer")
        self.assertTrue(
            models.DomainRolePermission.objects.filter(
                domain=self.domaina, role=role_customviewer, permission=permission_read
            ).exists()
        )

        # Submit form without that role-permission — it should be deleted.
        data = self._form_data(permission_ids=[permission_read.id])
        form = DomainManageRolesPermissionsForm(data=data, instance=self.domaina)
        form.is_valid()
        form.save()

        self.assertFalse(
            models.DomainRolePermission.objects.filter(
                domain=self.domaina, role=role_customviewer, permission=permission_read
            ).exists()
        )

    def test_save_empty_data_removes_all_role_permissions(self):
        data = self._form_data()
        form = DomainManageRolesPermissionsForm(data=data, instance=self.domaina)
        form.is_valid()
        form.save()

        count = models.DomainRolePermission.objects.filter(domain=self.domaina).count()
        self.assertEqual(count, 0)

    def test_returns_domain_instance(self):
        data = self._form_data()
        form = DomainManageRolesPermissionsForm(data=data, instance=self.domaina)
        form.is_valid()
        result = form.save()
        self.assertEqual(result, self.domaina)


class ResourceManageRolesPermissionsFormTestCase(BaseTestCase):
    def _form_data(self, permission_ids=None, role_permission_pairs=None):
        data = {}
        for permission_id in (permission_ids or []):
            data[f"permission_{permission_id}_on"] = "on"
        for role_id, permission_id in (role_permission_pairs or []):
            data[f"role_{role_id}_on_{permission_id}_on"] = "on"
        return data

    def test_save_creates_resource_permission_with_inherit_true(self):
        permission_read = models.Permission.objects.get(code="read")
        data = self._form_data(permission_ids=[permission_read.id])
        form = ResourceManageRolesPermissionsForm(data=data, instance=self.domaina_resourcea)
        form.is_valid()
        form.save()

        obj = models.ResourcePermission.objects.get(
            resource=self.domaina_resourcea, permission=permission_read
        )
        self.assertTrue(obj.inherit)

    def test_save_creates_resource_role_permission(self):
        permission_delete = models.Permission.objects.get(code="delete")
        role_manager = models.Role.objects.get(code="manager")
        data = self._form_data(
            permission_ids=[permission_delete.id],
            role_permission_pairs=[(role_manager.id, permission_delete.id)],
        )
        form = ResourceManageRolesPermissionsForm(data=data, instance=self.domaina_resourcea)
        form.is_valid()
        form.save()

        self.assertTrue(
            models.ResourceRolePermission.objects.filter(
                resource=self.domaina_resourcea, role=role_manager, permission=permission_delete
            ).exists()
        )

    def test_save_removes_previous_resource_role_permissions(self):
        # domaina_resourced already has ResourceRolePermission(manager, delete) from BaseTestCase.
        permission_delete = models.Permission.objects.get(code="delete")
        role_manager = models.Role.objects.get(code="manager")
        self.assertTrue(
            models.ResourceRolePermission.objects.filter(
                resource=self.domaina_resourced, role=role_manager, permission=permission_delete
            ).exists()
        )

        # Submit form without that pair — it should be removed.
        data = self._form_data()
        form = ResourceManageRolesPermissionsForm(data=data, instance=self.domaina_resourced)
        form.is_valid()
        form.save()

        self.assertFalse(
            models.ResourceRolePermission.objects.filter(
                resource=self.domaina_resourced, role=role_manager, permission=permission_delete
            ).exists()
        )

    def test_returns_resource_instance(self):
        data = self._form_data()
        form = ResourceManageRolesPermissionsForm(data=data, instance=self.domaina_resourcea)
        form.is_valid()
        result = form.save()
        self.assertEqual(result, self.domaina_resourcea)
