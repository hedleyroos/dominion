import logging
from uuid import UUID

from asgiref.sync import sync_to_async
from connexion import request
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.db.models.deletion import ProtectedError

from dominion.api.constants import DEFAULT_ROLES_Q, DEFAULT_PERMISSIONS_Q
from dominion.api.utils import paginate_result
from dominion.models import Role, Permission, Resource, ResourceRolePermission, ResourcePermission
from dominion.serializers import ResourceRolePermissionSerializer
from dominion.utils import user_has_permission_for_resource, invalidate_rules_permissions


ITEM_NOT_FOUND = "Item not found for id: {}."
logger = logging.getLogger("dominion.audit")


async def post(body, user, token_info, **kwargs):
    user = token_info["user"]

    # Resource
    resource_id = body.pop("resource")
    try:
        UUID(resource_id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % resource_id}, 400

    if not await user_has_permission_for_resource(user.pk, "create", resource_id):
        return {
            "message": "You do not have permission to create this item for this resource."
        }, 403

    try:
        resource = await Resource.objects.select_related("domain__parent").aget(id=resource_id)
    except Resource.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(resource_id)}, 404

    body["resource_id"] = resource_id

    # Role
    role_code = body.pop("role")
    resource_domain_root = await sync_to_async(lambda: resource.domain.root)()
    try:
        role = await Role.objects.filter(
            Q(domain=resource_domain_root) | DEFAULT_ROLES_Q
        ).aget(code=role_code)
    except Role.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(role_code)}, 404
    body["role_id"] = role.id

    # Permission
    permission_code = body.pop("permission")
    try:
        permission = await Permission.objects.filter(
            Q(domain=resource_domain_root) | DEFAULT_PERMISSIONS_Q
        ).aget(code=permission_code)
    except Permission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(permission_code)}, 404
    body["permission_id"] = permission.id

    inherit = body.pop("inherit", True)

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    try:
        obj = ResourceRolePermission(**body)
        await sync_to_async(obj.full_clean)()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Actually create and persist an object
    try:
        obj = await ResourceRolePermission.objects.acreate(**body)
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422
    except IntegrityError:
        # unique_together fired — duplicate mapping or a concurrent create race.
        return {"message": "This role already has this permission on this resource."}, 409

    # If inherit is set to false then we create an extra object
    if not inherit:
        await ResourcePermission.objects.acreate(resource_id=obj.resource_id, permission_id=obj.permission_id, inherit=False)

    obj = await ResourceRolePermission.objects.select_related("role", "permission", "resource").aget(id=obj.id)
    await invalidate_rules_permissions()
    logger.debug("action=create object_type=ResourceRolePermission object_id=%s user=%s", obj.id, user.pk)
    return await ResourceRolePermissionSerializer(instance=obj).adata, 201


async def get(id, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = await ResourceRolePermission.objects.select_related("role", "permission", "resource").aget(id=id)
    except ResourceRolePermission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_resource(user.pk, "read", obj.resource_id):
        return {"message": "You do not have permission to read this item."}, 403

    return await ResourceRolePermissionSerializer(instance=obj).adata, 200


async def put(id, body, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = await ResourceRolePermission.objects.select_related("resource__domain__parent", "role", "permission").aget(id=id)
    except ResourceRolePermission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_resource(user.pk, "update", obj.resource_id):
        return {"message": "You do not have permission to update this item."}, 403

    # Role
    role_code = body.pop("role", None)
    if role_code:
        resource_domain_root = await sync_to_async(lambda: obj.resource.domain.root)()
        try:
            role = await Role.objects.filter(
                Q(domain=resource_domain_root) | DEFAULT_ROLES_Q
            ).aget(code=role_code)
        except Role.DoesNotExist:
            return {"message": ITEM_NOT_FOUND.format(role_code)}, 404
        body["role_id"] = role.id

    # Permission
    permission_code = body.pop("permission", None)
    if permission_code:
        resource_domain_root = await sync_to_async(lambda: obj.resource.domain.root)()
        try:
            permission = await Permission.objects.filter(
                Q(domain=resource_domain_root) | DEFAULT_PERMISSIONS_Q
            ).aget(code=permission_code)
        except Permission.DoesNotExist:
            return {"message": ITEM_NOT_FOUND.format(permission_code)}, 404
        body["permission_id"] = permission.id

    inherit = body.pop("inherit", True)

    for k, v in body.items():
        setattr(obj, k, v)
    try:
        await sync_to_async(obj.full_clean)()
        await obj.asave()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Recreate resource permission if applicable.
    await ResourcePermission.objects.filter(resource_id=obj.resource_id, permission_id=obj.permission_id).adelete()
    if not inherit:
        await ResourcePermission.objects.acreate(resource_id=obj.resource_id, permission_id=obj.permission_id, inherit=False)

    obj = await ResourceRolePermission.objects.select_related("role", "permission", "resource").aget(id=obj.id)
    await invalidate_rules_permissions()
    logger.debug("action=update object_type=ResourceRolePermission object_id=%s user=%s", obj.id, user.pk)
    return await ResourceRolePermissionSerializer(instance=obj).adata, 200


async def delete(id, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = await ResourceRolePermission.objects.aget(id=id)
    except ResourceRolePermission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_resource(user.pk, "delete", obj.resource_id):
        return {"message": "You do not have permission to delete this item."}, 403

    try:
        await obj.adelete()
    except ProtectedError:
        return {
            "message": "Cannot delete item because other items are dependent on it. You must delete those items first."
        }, 422

    await invalidate_rules_permissions()
    logger.debug("action=delete object_type=ResourceRolePermission object_id=%s user=%s", id, user.pk)
    return None, 204


async def search(user, token_info, **kwargs):
    user = token_info["user"]

    # Resource is a required parameter
    resource_id = kwargs.get("resource")
    try:
        UUID(resource_id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % resource_id}, 400

    if not await user_has_permission_for_resource(user.pk, "read", resource_id):
        return {"message": "You do not have permission to read this item."}, 403

    return await paginate_result(
        ResourceRolePermission.objects.filter(resource_id=resource_id).select_related("role", "permission", "resource"),
        ResourceRolePermissionSerializer
    )

