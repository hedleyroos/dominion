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
from dominion.models import Role, Permission, Domain, DomainRolePermission, DomainPermission
from dominion.serializers import DomainRolePermissionSerializer
from dominion.utils import user_has_permission_for_domain, get_user_domains, invalidate_rules_permissions


ITEM_NOT_FOUND = "Item not found for id: {}."
logger = logging.getLogger("dominion.audit")


async def post(body, user, token_info, **kwargs):
    user = token_info["user"]

    # Domain
    domain_id = body.pop("domain")
    try:
        UUID(domain_id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % domain_id}, 400

    if not await user_has_permission_for_domain(user.pk, "create", domain_id):
        return {
            "message": "You do not have permission to create this item for this domain."
        }, 403

    try:
        domain = await Domain.objects.aget(id=domain_id)
    except Domain.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(domain_id)}, 404

    body["domain_id"] = domain_id

    # Role
    role_code = body.pop("role")
    domain_root = await sync_to_async(lambda: domain.root)()
    try:
        role = await Role.objects.filter(
            Q(domain=domain_root) | DEFAULT_ROLES_Q
        ).aget(code=role_code)
    except Role.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(role_code)}, 404
    body["role_id"] = role.id

    # Permission
    permission_code = body.pop("permission")
    try:
        permission = await Permission.objects.filter(
            Q(domain=domain_root) | DEFAULT_PERMISSIONS_Q
        ).aget(code=permission_code)
    except Permission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(permission_code)}, 404
    body["permission_id"] = permission.id

    inherit = body.pop("inherit", True)

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    try:
        obj = DomainRolePermission(**body)
        await sync_to_async(obj.full_clean)()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Actually create and persist an object
    try:
        obj = await DomainRolePermission.objects.acreate(**body)
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422
    except IntegrityError:
        # unique_together fired — duplicate mapping or a concurrent create race.
        return {"message": "This role already has this permission on this domain."}, 409

    # If inherit is set to false then we create an extra object
    if not inherit:
        await DomainPermission.objects.acreate(domain_id=obj.domain_id, permission_id=obj.permission_id, inherit=False)

    obj = await DomainRolePermission.objects.select_related("role", "permission", "domain").aget(id=obj.id)
    await invalidate_rules_permissions()
    logger.debug("action=create object_type=DomainRolePermission object_id=%s user=%s", obj.id, user.pk)
    return await DomainRolePermissionSerializer(instance=obj).adata, 201


async def get(id, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = await DomainRolePermission.objects.select_related("role", "permission", "domain").aget(id=id)
    except DomainRolePermission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_domain(user.pk, "read", obj.domain_id):
        return {"message": "You do not have permission to read this item."}, 403

    return await DomainRolePermissionSerializer(instance=obj).adata, 200


async def put(id, body, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = await DomainRolePermission.objects.select_related("domain__parent", "role", "permission").aget(id=id)
    except DomainRolePermission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_domain(user.pk, "update", obj.domain_id):
        return {"message": "You do not have permission to update this item."}, 403

    # Role
    role_code = body.pop("role", None)
    if role_code:
        domain_root = await sync_to_async(lambda: obj.domain.root)()
        try:
            role = await Role.objects.filter(
                Q(domain=domain_root) | DEFAULT_ROLES_Q
            ).aget(code=role_code)
        except Role.DoesNotExist:
            return {"message": ITEM_NOT_FOUND.format(role_code)}, 404
        body["role_id"] = role.id

    # Permission
    permission_code = body.pop("permission", None)
    if permission_code:
        domain_root = await sync_to_async(lambda: obj.domain.root)()
        try:
            permission = await Permission.objects.filter(
                Q(domain=domain_root) | DEFAULT_PERMISSIONS_Q
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

    # Recreate domain permission if applicable.
    await DomainPermission.objects.filter(domain_id=obj.domain_id, permission_id=obj.permission_id).adelete()
    if not inherit:
        await DomainPermission.objects.acreate(domain_id=obj.domain_id, permission_id=obj.permission_id, inherit=False)

    obj = await DomainRolePermission.objects.select_related("role", "permission", "domain").aget(id=obj.id)
    await invalidate_rules_permissions()
    logger.debug("action=update object_type=DomainRolePermission object_id=%s user=%s", obj.id, user.pk)
    return await DomainRolePermissionSerializer(instance=obj).adata, 200


async def delete(id, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = await DomainRolePermission.objects.aget(id=id)
    except DomainRolePermission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_domain(user.pk, "delete", obj.domain_id):
        return {"message": "You do not have permission to delete this item."}, 403

    try:
        await obj.adelete()
    except ProtectedError:
        return {
            "message": "Cannot delete item because other items are dependent on it. You must delete those items first."
        }, 422

    await invalidate_rules_permissions()
    logger.debug("action=delete object_type=DomainRolePermission object_id=%s user=%s", id, user.pk)
    return None, 204


async def search(user, token_info, **kwargs):
    user = token_info["user"]

    # Domain is a required parameter
    domain_id = kwargs.get("domain")
    try:
        UUID(domain_id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % domain_id}, 400

    if not await user_has_permission_for_domain(user.pk, "read", domain_id):
        return {"message": "You do not have permission to read this item."}, 403

    return await paginate_result(
        DomainRolePermission.objects.filter(domain_id=domain_id).select_related("role", "permission", "domain"),
        DomainRolePermissionSerializer
    )

