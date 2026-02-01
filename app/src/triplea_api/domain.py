from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from flask import request

from triplea_api.utils import paginate_result
from triplea.models import Domain
from triplea.serializers import DomainSerializer
from triplea.utils import user_has_permission_for_domain, get_user_domains


ITEM_NOT_FOUND = "Item not found for id: {}."


def post(body, user, token_info, **kwargs):
    user = token_info["user"]

    parent_id = body.pop("parent", None)
    if parent_id:
        # Connexion doesn't validate UUID's yet
        try:
            UUID(parent_id)
        except ValueError:
            return {"message": "%s is not a valid UUID." % parent_id}, 400

        if not user_has_permission_for_domain(user.pk, "create", parent_id):
            return {
                "message": "You do not have permission to create this item with this parent."
            }, 403

        body["parent_id"] = parent_id

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    try:
        obj = Domain(**body)
        obj.full_clean()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Actually create and persist an object
    try:
        obj = Domain.objects.create(**body, owner=user)
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    return DomainSerializer(instance=obj).data, 201


def get(id, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = Domain.objects.get(id=id)
    except Domain.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not user_has_permission_for_domain(user.pk, "read", id):
        return {"message": "You do not have permission to read this item."}, 403

    return DomainSerializer(instance=obj).data, 200


def put(id, body, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = Domain.objects.get(id=id)
    except Domain.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not user_has_permission_for_domain(user.pk, "update", id):
        return {"message": "You do not have permission to update this item."}, 403

    parent_id = body.pop("parent", None)
    if parent_id:
        # Connexion doesn't validate UUID's yet
        try:
            UUID(parent_id)
        except ValueError:
            return {"message": "%s is not a valid UUID." % parent_id}, 400

        # If you are allowed to create within the parent then we assume you may re-parent this item
        if not user_has_permission_for_domain(user.pk, "create", parent_id):
            return {
                "message": "You do not have permission to update this item with this parent."
            }, 403

        body["parent_id"] = parent_id

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

    return DomainSerializer(instance=obj).data, 200


def delete(id, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = Domain.objects.get(id=id)
    except Domain.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not user_has_permission_for_domain(user.pk, "delete", id):
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

    # TODO: get_user_domains does not do permission checks. The user needs the read permission 
    # for the domain. That is a separate check that is expensive.
    # XXX: not sure if this endpoint should even be offered
    return paginate_result(get_user_domains(user), DomainSerializer, request)
