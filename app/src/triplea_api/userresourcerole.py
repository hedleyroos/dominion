import logging
from uuid import UUID

from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError

from triplea.models import Role, UserResourceRole
from triplea.serializers import UserResourceRoleSerializer
from triplea.utils import user_has_permission_for_resource, invalidate_user_permissions, get_user_resources
from triplea_api.utils import paginate_result


ITEM_NOT_FOUND = "Item not found for id: {}."
logger = logging.getLogger("triplea.audit")


async def post(body, user, token_info, **kwargs):
    user = token_info["user"]

    user_id = body.pop("user")
    resource_id = body.pop("resource")
    role_code = body.pop("role")

    # Connexion doesn't validate UUID's yet
    for id in (user_id, resource_id):
        try:
            UUID(id)
        except ValueError:
            return {"message": "%s is not a valid UUID." % id}, 400

    if not await user_has_permission_for_resource(user.pk, "manage_roles", resource_id):
        return {
            "message": "You do not have permission to create user roles for this resource."
        }, 403

    body["user_id"] = user_id
    body["resource_id"] = resource_id

    try:
        role = await Role.objects.aget(code=role_code)
        body["role_id"] = role.id
    except Role.DoesNotExist:
        return {"message": "%s is not a valid role" % role_code}, 404

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    try:
        obj = UserResourceRole(**body)
        await sync_to_async(obj.full_clean)()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Actually create and persist an object
    try:
        obj = await UserResourceRole.objects.acreate(**body)
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    obj = await UserResourceRole.objects.select_related("role", "resource", "user").aget(id=obj.id)
    await invalidate_user_permissions(str(user_id))
    logger.debug("action=create object_type=UserResourceRole object_id=%s user=%s", obj.id, user.pk)
    return await UserResourceRoleSerializer(instance=obj).adata, 201


async def get(id, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = await UserResourceRole.objects.select_related("role", "resource", "user").aget(id=id)
    except UserResourceRole.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_resource(user.pk, "manage_roles", obj.resource.id):
        return {"message": "You do not have permission to read this item."}, 403

    return await UserResourceRoleSerializer(instance=obj).adata, 200


async def put(id, body, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = await UserResourceRole.objects.select_related("resource").aget(id=id)
    except UserResourceRole.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_resource(user.pk, "manage_roles", obj.resource.id):
        return {"message": "You do not have permission to update this item."}, 403

    user_id = body.pop("user", None)
    resource_id = body.pop("resource", None)
    role_code = body.pop("role", None)

    # Connexion doesn't validate UUID's yet
    for check_id in (user_id, resource_id):
        if check_id:
            try:
                UUID(check_id)
            except ValueError:
                return {"message": "%s is not a valid UUID." % check_id}, 400

    if resource_id and not await user_has_permission_for_resource(user.pk, "manage_roles", resource_id):
        return {
            "message": "You do not have permission to update user roles for this resource."
        }, 403

    if user_id:
        body["user_id"] = user_id
    if resource_id:
        body["resource_id"] = resource_id

    if role_code:
        try:
            role = await Role.objects.aget(code=role_code)
            body["role_id"] = role.id
        except Role.DoesNotExist:
            return {"message": "%s is not a valid role" % role_code}, 404

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

    obj = await UserResourceRole.objects.select_related("role", "resource", "user").aget(id=obj.id)
    if user_id:
        await invalidate_user_permissions(str(user_id))
    logger.debug("action=update object_type=UserResourceRole object_id=%s user=%s", obj.id, user.pk)
    return await UserResourceRoleSerializer(instance=obj).adata, 200


async def delete(id, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = await UserResourceRole.objects.select_related("resource").aget(id=id)
    except UserResourceRole.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_resource(user.pk, "manage_roles", obj.resource.id):
        return {"message": "You do not have permission to delete user roles for this resource."}, 403

    try:
        await obj.adelete()
    except ProtectedError:
        return {
            "message": "Cannot delete item because other items are dependent on it. You must delete those items first."
        }, 422

    await invalidate_user_permissions(str(obj.user_id))
    logger.debug("action=delete object_type=UserResourceRole object_id=%s user=%s", id, user.pk)
    return {"message": "Item deleted successfully"}, 204


async def search(user, token_info, **kwargs):
    user = token_info["user"]
    user_resources = await get_user_resources(user)
    return await paginate_result(
        UserResourceRole.objects.filter(resource__in=user_resources).select_related("role", "resource", "user"),
        UserResourceRoleSerializer
    )

