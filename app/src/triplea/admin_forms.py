from django.forms import ModelForm

from triplea import models


class DomainManageRolesPermissionsForm(ModelForm):
    """We abuse ModelForm a bit to avoid manual scaffolding.
    """

    class Meta:
        model = models.Domain
        fields = []

    def save(self, commit=False):
        # TODO: smart deltas to prevent unnecessary object creation

        # Parse form data
        permission_ids = []
        role_permissions = {}
        for k, v in self.data.items():
            if k.startswith("permission_"):
                dc1, permission_id, dc2 = k.split("_")
                permission_ids.append(int(permission_id))
            if k.startswith("role_"):
                dc1, role_id, dc2, permission_id, dc3 = k.split("_")
                role_id = int(role_id)
                permission_id = int(permission_id)
                if role_id not in role_permissions:
                    role_permissions[role_id] = []
                role_permissions[role_id].append(permission_id)

        # Any domain permission that *is* in data gets a corresponding object with inherit=True
        for permission_id in permission_ids:
            obj, created = models.DomainPermission.objects.get_or_create(domain=self.instance, permission__id=permission_id, permission_id=permission_id)
            obj.inherit = True
            obj.save()

        # Any domain permission that is *not* in data gets a corresponding object with inherit=False
        all_permission_ids = [o.permission.id for o in models.DomainPermission.objects.filter(domain=self.instance)]
        for permission_id in (set(all_permission_ids) - set(permission_ids)):
            obj, created = models.DomainPermission.objects.get_or_create(domain=self.instance, permission__id=permission_id, permission_id=permission_id)
            obj.inherit = False
            obj.save()

        # Recreate the role permissions
        models.DomainRolePermission.objects.filter(domain=self.instance).delete()
        for role_id, permission_ids in role_permissions.items():
            for permission_id in permission_ids:
                models.DomainRolePermission.objects.create(domain=self.instance, role_id=role_id, permission_id=permission_id)

        return self.instance


class ResourceManageRolesPermissionsForm(ModelForm):
    """We abuse ModelForm a bit to avoid manual scaffolding.
    """

    class Meta:
        model = models.Resource
        fields = []

    def save(self, commit=False):
        # TODO: smart deltas to prevent unnecessary object creation

        # Parse form data
        permission_ids = []
        role_permissions = {}
        for k, v in self.data.items():
            if k.startswith("permission_"):
                dc1, permission_id, dc2 = k.split("_")
                permission_ids.append(int(permission_id))
            if k.startswith("role_"):
                dc1, role_id, dc2, permission_id, dc3 = k.split("_")
                role_id = int(role_id)
                permission_id = int(permission_id)
                if role_id not in role_permissions:
                    role_permissions[role_id] = []
                role_permissions[role_id].append(permission_id)

        # Any resource permission that *is* in data gets a corresponding object with inherit=True
        for permission_id in permission_ids:
            obj, created = models.ResourcePermission.objects.get_or_create(resource=self.instance, permission__id=permission_id, permission_id=permission_id)
            obj.inherit = True
            obj.save()

        # Any resource permission that is *not* in data gets a corresponding object with inherit=False
        all_permission_ids = [o.permission.id for o in models.ResourcePermission.objects.filter(resource=self.instance)]
        for permission_id in (set(all_permission_ids) - set(permission_ids)):
            obj, created = models.ResourcePermission.objects.get_or_create(resource=self.instance, permission__id=permission_id, permission_id=permission_id)
            obj.inherit = False
            obj.save()

        # Recreate the role permissions
        models.ResourceRolePermission.objects.filter(resource=self.instance).delete()
        for role_id, permission_ids in role_permissions.items():
            for permission_id in permission_ids:
                models.ResourceRolePermission.objects.create(resource=self.instance, role_id=role_id, permission_id=permission_id)

        return self.instance


