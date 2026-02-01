from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from flask import request

from triplea_api.constants import DEFAULT_ROLES_Q, DEFAULT_PERMISSIONS_Q
from triplea_api.utils import paginate_result
from triplea.models import Role, Permission, Domain, DomainRolePermission, DomainPermission
from triplea.serializers import DomainRolePermissionSerializer
from triplea.utils import user_has_permission_for_domain, get_user_domains


ITEM_NOT_FOUND = "Item not found for id: {}."


def post(body, user, token_info, **kwargs):
    user = token_info["user"]

    # Domain
    domain_id = body.pop("domain")
    try:
        UUID(domain_id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % domain_id}, 400

    if not user_has_permission_for_domain(user.pk, "create", domain_id):
        return {
            "message": "You do not have permission to create this item for this domain."
        }, 403

    try:
        domain = Domain.objects.get(id=domain_id)
    except Domain.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    body["domain_id"] = domain_id

    # Role
    role_code = body.pop("role")
    try:
        role = Role.objects.filter(
            Q(domain=domain.root)|DEFAULT_ROLES_Q
        ).get(code=role_code)
    except Role.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(role_code)}, 404
    body["role_id"] = role.id

    # Permission
    permission_code = body.pop("permission")
    try:
        permission = Permission.objects.filter(
            Q(domain=domain.root)|DEFAULT_PERMISSIONS_Q
        ).get(code=permission_code)
    except Permission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(permission_code)}, 404
    body["permission_id"] = permission.id

    inherit = body.pop("inherit", True)

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    try:
        obj = DomainRolePermission(**body)
        obj.full_clean()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Actually create and persist an object
    try:
        obj = DomainRolePermission.objects.create(**body)
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # If inherit is set to false then we create an extra object
    if not inherit:
        DomainPermission.objects.create(domain=obj.domain, permission=obj.permission, inherit=False)

    return DomainRolePermissionSerializer(instance=obj).data, 201


def get(id, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = DomainRolePermission.objects.get(id=id)
    except Role.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not user_has_permission_for_domain(user.pk, "read", obj.domain_id):
        return {"message": "You do not have permission to read this item."}, 403

    return DomainRolePermissionSerializer(instance=obj).data, 200


def put(id, body, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = DomainRolePermission.objects.get(id=id)
    except DomainRolePermission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not user_has_permission_for_domain(user.pk, "update", obj.domain_id):
        return {"message": "You do not have permission to update this item."}, 403

    # Role
    role_code = body.pop("role", None)
    if role_code:
        try:
            role = Role.objects.filter(
                Q(domain=obj.domain.root)|DEFAULT_ROLES_Q
            ).get(code=role_code)
        except Role.DoesNotExist:
            return {"message": ITEM_NOT_FOUND.format(role_code)}, 404
        body["role_id"] = role.id

    # Permission
    permission_code = body.pop("permission", None)
    if permission_code:
        try:
            permission = Permission.objects.filter(
                Q(domain=obj.domain.root)|DEFAULT_PERMISSIONS_Q
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

    # Recreate domain permission if applicable
    # TODO: optimize to avoid the forced delete
    DomainPermission.objects.filter(domain=obj.domain, permission=obj.permission).delete()
    if not inherit:
        DomainPermission.objects.create(domain=obj.domain, permission=obj.permission, inherit=False)

    return DomainRolePermissionSerializer(instance=obj).data, 200


def delete(id, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = DomainRolePermission.objects.get(id=id)
    except DomainRolePermission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not user_has_permission_for_domain(user.pk, "delete", obj.domain_id):
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

    # Domain is a required parameter
    domain_id = kwargs.get("domain")
    try:
        UUID(domain_id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % domain_id}, 400

    if not user_has_permission_for_domain(user.pk, "read", domain_id):
        return {"message": "You do not have permission to read this item."}, 403

    return paginate_result(DomainRolePermission.objects.filter(domain_id=domain_id), DomainRolePermissionSerializer, request)
