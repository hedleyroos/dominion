import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from dominion.utils import user_has_permission_for_domain


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    api_key = models.UUIDField(default=uuid.uuid4, db_index=True)
    created_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    activation_date = models.DateTimeField(null=True, blank=True, db_index=True)
    application_id = models.PositiveIntegerField(default=0, db_index=True)


class DomainManager(models.Manager):
    def create(self, title, owner, parent=None, parent_id=None, id=None):
        instance = super().create(id=id if id else uuid.uuid4(), title=title, parent_id=parent.id if parent else parent_id)

        if instance.parent is None:
            role_anonymous = Role.objects.get(code="anonymous")
            role_authenticated = Role.objects.get(code="authenticated")
            role_manager = Role.objects.get(code="manager")
            role_owner = Role.objects.get(code="owner")
            role_access_checker = Role.objects.get(code="access_checker")
            permission_create = Permission.objects.get(code="create")
            permission_read = Permission.objects.get(code="read")
            permission_update = Permission.objects.get(code="update")
            permission_delete = Permission.objects.get(code="delete")
            permission_check_access = Permission.objects.get(code="check_access")
            permission_manage_roles = Permission.objects.get(code="manage_roles")
            permission_view = Permission.objects.get(code="view")
            DomainRolePermission.objects.create(
                domain=instance, role=role_authenticated, permission=permission_view
            )
            DomainRolePermission.objects.create(
                domain=instance, role=role_manager, permission=permission_create
            )
            DomainRolePermission.objects.create(
                domain=instance, role=role_manager, permission=permission_read
            )
            DomainRolePermission.objects.create(
                domain=instance, role=role_manager, permission=permission_update
            )
            DomainRolePermission.objects.create(
                domain=instance, role=role_manager, permission=permission_manage_roles
            )
            DomainRolePermission.objects.create(
                domain=instance, role=role_owner, permission=permission_create
            )
            DomainRolePermission.objects.create(
                domain=instance, role=role_owner, permission=permission_read
            )
            DomainRolePermission.objects.create(
                domain=instance, role=role_owner, permission=permission_update
            )
            DomainRolePermission.objects.create(
                domain=instance, role=role_owner, permission=permission_delete
            )
            DomainRolePermission.objects.create(
                domain=instance, role=role_owner, permission=permission_manage_roles
            )
            DomainRolePermission.objects.create(
                domain=instance, role=role_access_checker, permission=permission_check_access
            )
            UserDomainRole.objects.create(user=owner, domain=instance, role=role_owner)
            UserDomainRole.objects.create(user=owner, domain=instance, role=role_access_checker)

        return instance


class Domain(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=256)
    parent = models.ForeignKey("Domain", null=True, blank=True, on_delete=models.PROTECT)

    # Computed fields
    root = models.ForeignKey("Domain", null=True, blank=True, editable=False, on_delete=models.PROTECT, related_name="domain_root")

    # Counter caches — maintained via post_save / post_delete signals.
    # descendant_count: total domains that share this domain as their root (including self).
    # resource_count: total resources whose domain FK points to this domain.
    descendant_count = models.PositiveIntegerField(default=0, editable=False)
    resource_count = models.PositiveIntegerField(default=0, editable=False)

    objects = DomainManager()

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        root = self
        while root.parent is not None:
            root = root.parent
        self.root = root
        super().save(*args, **kwargs)
        self.full_clean()

    def clean(self):
        if self.parent_id:
            if self.parent == self:
                raise ValidationError({"parent": "Parent may not point to itself."})
            parent = self.parent
            while parent is not None:
                if parent.title == self.title:
                    raise ValidationError({"title": "The title is already in use by an ancestor."})
                parent = parent.parent

        # Check the descendant counter on the root domain.  The counter is incremented
        # by the post_save signal before full_clean() runs, so a fresh DB read reflects
        # the just-inserted row.  Skip this check on unsaved (in-memory) objects where
        # root_id has not been set yet.
        if self.root_id is not None:
            limit = settings.DOMINION_MAX_DESCENDANT_DOMAINS
            root_count = Domain.objects.values_list("descendant_count", flat=True).get(id=self.root_id)
            if root_count > limit:
                raise ValidationError("The root domain may not contain more than %s child domains." % limit)

        # TODO: limit number of root domains owned by the same user. Hard because we don't store a single
        # owner, rather a set of people with the owner role.


class Role(models.Model):
    code = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=256)
    domain = models.ForeignKey(Domain, null=True, blank=True, on_delete=models.PROTECT)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # TODO: disallow changing domain for existing instance
        super().save(*args, **kwargs)
        self.full_clean()

    def clean(self):
        if (self.domain is not None) and (self.domain.parent is not None):
            raise ValidationError({"domain": "A role may only be set for a root domain."})


class Permission(models.Model):
    code = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=256)
    domain = models.ForeignKey(Domain, null=True, blank=True, on_delete=models.PROTECT)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # TODO: disallow changing domain for existing instance
        super().save(*args, **kwargs)
        self.full_clean()

    def clean(self):
        if (self.domain is not None) and (self.domain.parent is not None):
            raise ValidationError({"domain": "A permission may only be set for a root domain."})


class ResourceManager(models.Manager):
    def create(self, urn, owner, parent=None, parent_id=None, domain=None, domain_id=None):
        instance = super().create(
            urn=urn,
            parent_id=parent.id if parent else parent_id,
            domain_id=domain.id if domain else domain_id
        )

        if instance.parent is None:
            role_owner = Role.objects.get(code="owner")
            UserResourceRole.objects.create(user=owner, resource=instance, role=role_owner)

        return instance


class Resource(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    urn = models.CharField(max_length=256, unique=True, db_index=True)
    parent = models.ForeignKey("Resource", null=True, blank=True, on_delete=models.PROTECT)
    domain = models.ForeignKey(Domain, null=False, blank=False, on_delete=models.PROTECT)

    objects = ResourceManager()

    def __str__(self):
        return self.urn

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.clean()

    def clean(self):
        if self.parent_id:
            if self.parent == self:
                raise ValidationError("Parent may not point to itself.")
            if self.parent.domain != self.domain:
                raise ValidationError("Parent domain does not match instance domain.")

        # Check the resource counter on the owning domain.  The counter is incremented
        # by the post_save signal before clean() runs, so a fresh DB read reflects
        # the just-inserted row.
        limit = settings.DOMINION_MAX_RESOURCES_PER_DOMAIN
        resource_count = Domain.objects.values_list("resource_count", flat=True).get(id=self.domain_id)
        if resource_count > limit:
            raise ValidationError("The domain may not contain more than %s resources." % limit)


class DomainRolePermission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.ForeignKey(Domain, null=False, blank=False, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, null=False, blank=False, on_delete=models.PROTECT)
    permission = models.ForeignKey(Permission, null=False, blank=False, on_delete=models.PROTECT)

    class Meta:
        unique_together = ("domain", "role", "permission")

    def __str__(self):
        return "%s:%s:%s" % (self.domain, self.role, self.permission)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.clean()

    def clean(self):
        if (self.permission.domain is not None) and (self.permission.domain != self.domain.root):
            raise ValidationError({"permission": "Permission domain does not match domain root."})


class DomainPermission(models.Model):
    """Helper class. It is never exposed in any UI.
    """
    domain = models.ForeignKey(Domain, null=False, blank=False, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, null=False, blank=False, on_delete=models.PROTECT)
    inherit = models.BooleanField(default=True)

    class Meta:
        unique_together = ("domain", "permission", "inherit")

    def __str__(self):
        return "%s:%s:%s" % (self.domain, self.permission, self.inherit)


class ResourceRolePermission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resource = models.ForeignKey(Resource, null=False, blank=False, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, null=False, blank=False, on_delete=models.PROTECT)
    permission = models.ForeignKey(Permission, null=False, blank=False, on_delete=models.PROTECT)

    class Meta:
        unique_together = ("resource", "role", "permission")

    def __str__(self):
        return "%s:%s:%s" % (self.resource, self.role, self.permission)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.clean()

    def clean(self):
        if (self.permission.domain is not None) and (self.permission.domain != self.resource.domain.root):
            raise ValidationError({"permission": "Permission domain does not match resource domain root."})


class ResourcePermission(models.Model):
    """Helper class. It is never exposed in any UI.
    """
    resource = models.ForeignKey(Resource, null=False, blank=False, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, null=False, blank=False, on_delete=models.PROTECT)
    inherit = models.BooleanField(default=True)

    class Meta:
        unique_together = ("resource", "permission", "inherit")

    def __str__(self):
        return "%s:%s:%s" % (self.resource, self.permission, self.inherit)


class UserDomainRole(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_index=True)
    domain = models.ForeignKey(Domain, null=False, blank=False, on_delete=models.CASCADE, db_index=True)
    role = models.ForeignKey(Role, null=False, blank=False, on_delete=models.PROTECT)

    class Meta:
        unique_together = ("user", "domain", "role")

    def __str__(self):
        return "%s:%s:%s" % (self.user, self.domain, self.role)


class UserResourceRole(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_index=True)
    resource = models.ForeignKey(Resource, null=False, blank=False, on_delete=models.CASCADE, db_index=True)
    role = models.ForeignKey(Role, null=False, blank=False, on_delete=models.PROTECT)

    class Meta:
        unique_together = ("resource", "role", "user")

    def __str__(self):
        return "%s:%s:%s" % (self.user, self.resource, self.role)


# ---------------------------------------------------------------------------
# Counter-cache signals (P3.3)
# ---------------------------------------------------------------------------
# These signals maintain the `descendant_count` and `resource_count` fields on
# Domain atomically via F() expressions.  The signals fire *inside*
# Model.save() (before full_clean/clean run), so the counters are already
# updated when the limit check in clean() reads them.

@receiver(post_save, sender=Domain)
def _domain_post_save(sender, instance, created, **kwargs):
    if created:
        # Increment the root's descendant count.  When this IS the root domain
        # (root_id == id) the UPDATE targets the just-inserted row, setting
        # it from 0 → 1 correctly.
        Domain.objects.filter(id=instance.root_id).update(
            descendant_count=F("descendant_count") + 1
        )


@receiver(post_delete, sender=Domain)
def _domain_post_delete(sender, instance, **kwargs):
    # Decrement the root's counter.  If the root itself was deleted the UPDATE
    # targets a row that no longer exists and is a safe no-op.
    if instance.root_id and instance.root_id != instance.id:
        Domain.objects.filter(id=instance.root_id).update(
            descendant_count=F("descendant_count") - 1
        )


@receiver(post_save, sender=Resource)
def _resource_post_save(sender, instance, created, **kwargs):
    if created:
        Domain.objects.filter(id=instance.domain_id).update(
            resource_count=F("resource_count") + 1
        )


@receiver(post_delete, sender=Resource)
def _resource_post_delete(sender, instance, **kwargs):
    Domain.objects.filter(id=instance.domain_id).update(
        resource_count=F("resource_count") - 1
    )
