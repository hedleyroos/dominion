from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from flask import request

from triplea.models import Role, UserDomainRole
from triplea.serializers import UserDomainRoleSerializer
from triplea.utils import user_has_permission_for_domain


ITEM_NOT_FOUND = "Item not found for id: {}."


def post(body, user, token_info, **kwargs):
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

    if not user_has_permission_for_domain(user.pk, "manage_roles", domain_id):
        return {
            "message": "You do not have permission to create user roles for this domain."
        }, 403

    body["user_id"] = user_id
    body["domain_id"] = domain_id

    try:
        body["role_id"] = Role.objects.get(code=role_code).id
    except Role.DoesNotExist:
        return {"message": "%s is not a valid role" % role_code}, 404

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    try:
        obj = UserDomainRole(**body)
        obj.full_clean()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Actually create and persist an object
    try:
        obj = UserDomainRole.objects.create(**body)
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    return UserDomainRoleSerializer(instance=obj).data, 201


def get(id, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = UserDomainRole.objects.get(id=id)
    except UserDomainRole.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not user_has_permission_for_domain(user.pk, "manage_roles", obj.domain.id):
        return {"message": "You do not have permission to read this item."}, 403

    return UserDomainRoleSerializer(instance=obj).data, 200


def put(id, body, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = UserDomainRole.objects.get(id=id)
    except UserDomainRole.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not user_has_permission_for_domain(user.pk, "manage_roles", obj.domain.id):
        return {"message": "You do not have permission to update this item."}, 403

    user_id = body.pop("user", None)
    domain_id = body.pop("domain", None)
    role_code = body.pop("role", None)

    # Connexion doesn't validate UUID's yet
    for id in (user_id, domain_id):
        if id:
            try:
                UUID(id)
            except ValueError:
                return {"message": "%s is not a valid UUID." % id}, 400

    if domain_id and not user_has_permission_for_domain(user.pk, "manage_roles", domain_id):
        return {
            "message": "You do not have permission to update user roles for this domain."
        }, 403

    if not user_has_permission_for_domain(user.pk, "manage_roles", obj.domain.id):
        return {
            "message": "You do not have permission to update user roles for this domain."
        }, 403

    if user_id:
        body["user_id"] = user_id
    if domain_id:
        body["domain_id"] = domain_id

    if role_code:
        try:
            body["role_id"] = Role.objects.get(code=role_code).id
        except Role.DoesNotExist:
            return {"message": "%s is not a valid role" % role_code}, 404

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

    return UserDomainRoleSerializer(instance=obj).data, 200


def delete(id, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = UserDomainRole.objects.get(id=id)
    except UserDomainRole.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not user_has_permission_for_domain(user.pk, "manage_roles", obj.domain.id):
        return {"message": "You do not have permission to delete user roles for this domain."}, 403

    try:
        obj.delete()
    except ProtectedError:
        return {
            "message": "Cannot delete item because other items are dependent on it. You must delete those items first."
        }, 422

    return {"message": "Item deleted successfully"}, 204


def search(user, token_info, **kwargs):
    user = token_info["user"]
    return paginate_result(UserDomainRole.objects.filter(domain__in=get_user_domains(user)), UserDomainRoleSerializer, request)
