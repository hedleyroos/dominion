from adrf import serializers
from rest_framework import serializers as drf_serializers

from dominion import models
from dominion import utils


class UserSerializer(serializers.ModelSerializer):
    domains = drf_serializers.SerializerMethodField()

    class Meta:
        model = models.User
        fields = ["id", "username", "email", "first_name", "last_name", "api_key", "domains"]

    async def ato_representation(self, instance):
        representation = await super().ato_representation(instance)
        domains = await utils.get_user_domains(instance)
        representation["domains"] = [
            await DomainSerializer(instance=domain).ato_representation(domain)
            async for domain in domains
        ]
        return representation

    def to_representation(self, instance):
        # Sync fallback — domains omitted as get_user_domains is async-only in normal flow.
        representation = super().to_representation(instance)
        representation["domains"] = []
        return representation

    def get_domains(self, obj):
        return []


class DomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Domain
        fields = ["id", "title", "parent"]

    async def ato_representation(self, instance):
        return await super().ato_representation(instance)

    def to_representation(self, instance):
        return super().to_representation(instance)


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Role
        fields = ["code", "title", "domain"]

    async def ato_representation(self, instance):
        return await super().ato_representation(instance)

    def to_representation(self, instance):
        return super().to_representation(instance)


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Permission
        fields = ["code", "title", "domain"]

    async def ato_representation(self, instance):
        return await super().ato_representation(instance)

    def to_representation(self, instance):
        return super().to_representation(instance)


class ResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Resource
        fields = ["id", "urn", "parent", "domain"]

    async def ato_representation(self, instance):
        return await super().ato_representation(instance)

    def to_representation(self, instance):
        return super().to_representation(instance)


class DomainRolePermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.DomainRolePermission
        fields = ["id", "domain", "role", "permission"]

    async def ato_representation(self, instance):
        representation = await super().ato_representation(instance)
        representation["role"] = instance.role.code
        representation["permission"] = instance.permission.code
        try:
            domain_permission = await models.DomainPermission.objects.aget(
                domain=instance.domain, permission=instance.permission
            )
            representation["inherit"] = domain_permission.inherit
        except models.DomainPermission.DoesNotExist:
            representation["inherit"] = True
        return representation

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["role"] = instance.role.code
        representation["permission"] = instance.permission.code
        try:
            representation["inherit"] = models.DomainPermission.objects.get(
                domain=instance.domain, permission=instance.permission
            ).inherit
        except models.DomainPermission.DoesNotExist:
            representation["inherit"] = True
        return representation


class ResourceRolePermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ResourceRolePermission
        fields = ["id", "resource", "role", "permission"]

    async def ato_representation(self, instance):
        representation = await super().ato_representation(instance)
        representation["role"] = instance.role.code
        representation["permission"] = instance.permission.code
        try:
            resource_permission = await models.ResourcePermission.objects.aget(
                resource=instance.resource, permission=instance.permission
            )
            representation["inherit"] = resource_permission.inherit
        except models.ResourcePermission.DoesNotExist:
            representation["inherit"] = True
        return representation

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["role"] = instance.role.code
        representation["permission"] = instance.permission.code
        try:
            representation["inherit"] = models.ResourcePermission.objects.get(
                resource=instance.resource, permission=instance.permission
            ).inherit
        except models.ResourcePermission.DoesNotExist:
            representation["inherit"] = True
        return representation


class UserDomainRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.UserDomainRole
        fields = ["id", "user", "domain", "role"]

    async def ato_representation(self, instance):
        representation = await super().ato_representation(instance)
        representation["role"] = instance.role.code
        return representation

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["role"] = instance.role.code
        return representation


class UserResourceRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.UserResourceRole
        fields = ["id", "user", "resource", "role"]

    async def ato_representation(self, instance):
        representation = await super().ato_representation(instance)
        representation["role"] = instance.role.code
        return representation

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["role"] = instance.role.code
        return representation


