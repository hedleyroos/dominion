from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from flask import request

from triplea_api.constants import DEFAULT_ROLES_Q, DEFAULT_PERMISSIONS_Q
from triplea_api.utils import paginate_result
from triplea.models import Role, Permission, Resource, ResourceRolePermission, ResourcePermission
from triplea.serializers import ResourceRolePermissionSerializer
from triplea.utils import user_has_permission_for_resource


ITEM_NOT_FOUND = "Item not found for id: {}."


def post(body, user, token_info, **kwargs):
    user = token_info["user"]

    # Resource
    resource_id = body.pop("resource")
    try:
        UUID(resource_id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % resource_id}, 400

    if not user_has_permission_for_resource(user.pk, "create", resource_id):
        return {
            "message": "You do not have permission to create this item for this resource."
        }, 403

    try:
        resource = Resource.objects.get(id=resource_id)
    except Resource.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    body["resource_id"] = resource_id

    # Role
    role_code = body.pop("role")
    try:
        role = Role.objects.filter(
            Q(domain=resource.domain.root)|DEFAULT_ROLES_Q
        ).get(code=role_code)
    except Role.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(role_code)}, 404
    body["role_id"] = role.id

    # Permission
    permission_code = body.pop("permission")
    try:
        permission = Permission.objects.filter(
            Q(domain=resource.domain.root)|DEFAULT_PERMISSIONS_Q
        ).get(code=permission_code)
    except Permission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(permission_code)}, 404
    body["permission_id"] = permission.id

    inherit = body.pop("inherit", True)

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    try:
        obj = ResourceRolePermission(**body)
        obj.full_clean()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Actually create and persist an object
    try:
        obj = ResourceRolePermission.objects.create(**body)
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # If inherit is set to false then we create an extra object
    if not inherit:
        ResourcePermission.objects.create(resource=obj.resource, permission=obj.permission, inherit=False)

    return ResourceRolePermissionSerializer(instance=obj).data, 201


def get(id, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = ResourceRolePermission.objects.get(id=id)
    except Role.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not user_has_permission_for_resource(user.pk, "read", obj.resource_id):
        return {"message": "You do not have permission to read this item."}, 403

    return ResourceRolePermissionSerializer(instance=obj).data, 200


def put(id, body, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = ResourceRolePermission.objects.get(id=id)
    except ResourceRolePermission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not user_has_permission_for_resource(user.pk, "update", obj.resource_id):
        return {"message": "You do not have permission to update this item."}, 403

    # Role
    role_code = body.pop("role", None)
    if role_code:
        try:
            role = Role.objects.filter(
                Q(domain=obj.resource.domain.root)|DEFAULT_ROLES_Q
            ).get(code=role_code)
        except Role.DoesNotExist:
            return {"message": ITEM_NOT_FOUND.format(role_code)}, 404
        body["role_id"] = role.id

    # Permission
    permission_code = body.pop("permission", None)
    if permission_code:
        try:
            permission = Permission.objects.filter(
                Q(domain=obj.resource.domain.root)|DEFAULT_PERMISSIONS_Q
            ).get(code=permission_code)
        except Permission.DoesNotExist:
            return {"message": ITEM_NOT_FOUND.format(permission_code)}, 404
        body["permission_id"] = permission.id

    inherit = body.pop("inherit", True)

    for k, v in body.items():
        setattr(obj, k, v)
    try:
        obj.full_clean()
        obj.save()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Recreate resource permission if applicable
    # TODO: optimize to avoid the forced delete
    ResourcePermission.objects.filter(resource=obj.resource, permission=obj.permission).delete()
    if not inherit:
        ResourcePermission.objects.create(resource=obj.resource, permission=obj.permission, inherit=False)

    return ResourceRolePermissionSerializer(instance=obj).data, 200


def delete(id, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = ResourceRolePermission.objects.get(id=id)
    except ResourceRolePermission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not user_has_permission_for_resource(user.pk, "delete", obj.resource_id):
        return {"message": "You do not have permission to delete this item."}, 403

    try:
        obj.delete()
    except ProtectedError:
        return {
            "message": "Cannot delete item because other items are dependent on it. You must delete those items first."
        }, 422

    return {"message": "Item deleted successfully"}, 204


def search(user, token_info, **kwargs):
    user = token_info["user"]

    # Resource is a required parameter
    resource_id = kwargs.get("resource")
    try:
        UUID(resource_id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % resource_id}, 400

    if not user_has_permission_for_resource(user.pk, "read", resource_id):
        return {"message": "You do not have permission to read this item."}, 403

    return paginate_result(ResourceRolePermission.objects.filter(resource_id=resource_id), ResourceRolePermissionSerializer, request)
