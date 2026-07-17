import logging
from uuid import UUID

from asgiref.sync import sync_to_async
from connexion import request
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError

from dominion.models import Role, UserDomainRole
from dominion.serializers import UserDomainRoleSerializer
from dominion.utils import user_has_permission_for_domain, get_user_domains, invalidate_user_permissions
from dominion.api.utils import paginate_result


ITEM_NOT_FOUND = "Item not found for id: {}."
logger = logging.getLogger("dominion.audit")


async def post(body, user, token_info, **kwargs):
    user = token_info["user"]

    user_id = body.pop("user")
    domain_id = body.pop("domain")
    role_code = body.pop("role")

    # Connexion doesn't validate UUID's yet
    for id in (user_id, domain_id):
        try:
            UUID(id)
        except ValueError:
            return {"message": "%s is not a valid UUID." % id}, 400

    if not await user_has_permission_for_domain(user.pk, "manage_roles", domain_id):
        return {
            "message": "You do not have permission to create user roles for this domain."
        }, 403

    body["user_id"] = user_id
    body["domain_id"] = domain_id

    try:
        role = await Role.objects.aget(code=role_code)
        body["role_id"] = role.id
    except Role.DoesNotExist:
        return {"message": "%s is not a valid role" % role_code}, 404

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    try:
        obj = UserDomainRole(**body)
        await sync_to_async(obj.full_clean)()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Actually create and persist an object
    try:
        obj = await UserDomainRole.objects.acreate(**body)
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422
    except IntegrityError:
        # The unique_together constraint fired — either a duplicate assignment or a
        # concurrent create that raced past the in-memory full_clean() check above.
        return {"message": "This user already has this role on this domain."}, 409

    obj = await UserDomainRole.objects.select_related("role", "domain", "user").aget(id=obj.id)
    await invalidate_user_permissions(str(user_id))
    logger.debug("action=create object_type=UserDomainRole object_id=%s user=%s", obj.id, user.pk)
    return await UserDomainRoleSerializer(instance=obj).adata, 201


async def get(id, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = await UserDomainRole.objects.select_related("role", "domain", "user").aget(id=id)
    except UserDomainRole.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_domain(user.pk, "manage_roles", obj.domain.id):
        return {"message": "You do not have permission to read this item."}, 403

    return await UserDomainRoleSerializer(instance=obj).adata, 200


async def put(id, body, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = await UserDomainRole.objects.select_related("domain").aget(id=id)
    except UserDomainRole.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_domain(user.pk, "manage_roles", obj.domain.id):
        return {"message": "You do not have permission to update this item."}, 403

    user_id = body.pop("user", None)
    domain_id = body.pop("domain", None)
    role_code = body.pop("role", None)

    # Connexion doesn't validate UUID's yet
    for check_id in (user_id, domain_id):
        if check_id:
            try:
                UUID(check_id)
            except ValueError:
                return {"message": "%s is not a valid UUID." % check_id}, 400

    if domain_id and not await user_has_permission_for_domain(user.pk, "manage_roles", domain_id):
        return {
            "message": "You do not have permission to update user roles for this domain."
        }, 403

    if user_id:
        body["user_id"] = user_id
    if domain_id:
        body["domain_id"] = domain_id

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

    obj = await UserDomainRole.objects.select_related("role", "domain", "user").aget(id=obj.id)
    if user_id:
        await invalidate_user_permissions(str(user_id))
    logger.debug("action=update object_type=UserDomainRole object_id=%s user=%s", obj.id, user.pk)
    return await UserDomainRoleSerializer(instance=obj).adata, 200


async def delete(id, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = await UserDomainRole.objects.select_related("domain").aget(id=id)
    except UserDomainRole.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_domain(user.pk, "manage_roles", obj.domain.id):
        return {"message": "You do not have permission to delete user roles for this domain."}, 403

    try:
        await obj.adelete()
    except ProtectedError:
        return {
            "message": "Cannot delete item because other items are dependent on it. You must delete those items first."
        }, 422

    await invalidate_user_permissions(str(obj.user_id))
    logger.debug("action=delete object_type=UserDomainRole object_id=%s user=%s", id, user.pk)
    return None, 204


async def search(user, token_info, **kwargs):
    user = token_info["user"]
    user_domains = await get_user_domains(user)
    return await paginate_result(
        UserDomainRole.objects.filter(domain__in=user_domains).select_related("role", "domain", "user"),
        UserDomainRoleSerializer
    )

