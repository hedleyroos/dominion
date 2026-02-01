from rest_framework import serializers

from triplea import models
from triplea import utils


class UserSerializer(serializers.ModelSerializer):
    domains = serializers.SerializerMethodField()

    class Meta:
        model = models.User
        fields = ["id", "username", "email", "first_name", "last_name", "api_key", "domains"]

    def get_domains(self, obj):
        result = []
        for domain in utils.get_user_domains(obj):
            result.append(DomainSerializer(instance=domain).data)
        return result


class DomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Domain
        fields = ["id", "title", "parent"]


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Role
        fields = ["code", "title", "domain"]


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Permission
        fields = ["code", "title", "domain"]


class ResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Resource
        fields = ["id", "urn", "parent", "domain"]


class DomainRolePermissionSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    permission = serializers.SerializerMethodField()
    inherit = serializers.SerializerMethodField()

    class Meta:
        model = models.DomainRolePermission
        fields = ["id", "domain", "role", "permission", "inherit"]

    def get_role(self, obj):
        return obj.role.code

    def get_permission(self, obj):
        return obj.permission.code

    def get_inherit(self, obj):
        try:
            return models.DomainPermission.objects.get(domain=obj.domain, permission=obj.permission).inherit
        except models.DomainPermission.DoesNotExist:
            return True


class ResourceRolePermissionSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    permission = serializers.SerializerMethodField()
    inherit = serializers.SerializerMethodField()

    class Meta:
        model = models.ResourceRolePermission
        fields = ["id", "resource", "role", "permission", "inherit"]

    def get_role(self, obj):
        return obj.role.code

    def get_permission(self, obj):
        return obj.permission.code

    def get_inherit(self, obj):
        try:
            return models.ResourcePermission.objects.get(resource=obj.resource, permission=obj.permission).inherit
        except models.ResourcePermission.DoesNotExist:
            return True

class UserDomainRoleSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = models.UserDomainRole
        fields = ["id", "user", "domain", "role"]

    def get_role(self, obj):
        return obj.role.code


class UserResourceRoleSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = models.UserResourceRole
        fields = ["id", "user", "resource", "role"]

    def get_role(self, obj):
        return obj.role.code

