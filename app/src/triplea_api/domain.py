from uuid import UUID

from asgiref.sync import sync_to_async
from connexion import request
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError

from triplea_api.utils import paginate_result
from triplea.models import Domain
from triplea.serializers import DomainSerializer
from triplea.utils import user_has_permission_for_domain, get_user_domains


ITEM_NOT_FOUND = "Item not found for id: {}."


async def post(body, user, token_info, **kwargs):
    user = token_info["user"]

    parent_id = body.pop("parent", None)
    if parent_id:
        # Connexion doesn't validate UUID's yet
        try:
            UUID(parent_id)
        except ValueError:
            return {"message": "%s is not a valid UUID." % parent_id}, 400

        if not await user_has_permission_for_domain(user.pk, "create", parent_id):
            return {
                "message": "You do not have permission to create this item with this parent."
            }, 403

        body["parent_id"] = parent_id

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    try:
        obj = Domain(**body)
        await sync_to_async(obj.full_clean)()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Actually create and persist an object
    try:
        obj = await sync_to_async(Domain.objects.create)(**body, owner=user)
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    return await DomainSerializer(instance=obj).adata, 201


async def get(id, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = await Domain.objects.aget(id=id)
    except Domain.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_domain(user.pk, "read", id):
        return {"message": "You do not have permission to read this item."}, 403

    return await DomainSerializer(instance=obj).adata, 200


async def put(id, body, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = await Domain.objects.aget(id=id)
    except Domain.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_domain(user.pk, "update", id):
        return {"message": "You do not have permission to update this item."}, 403

    parent_id = body.pop("parent", None)
    if parent_id:
        # Connexion doesn't validate UUID's yet
        try:
            UUID(parent_id)
        except ValueError:
            return {"message": "%s is not a valid UUID." % parent_id}, 400

        # If you are allowed to create within the parent then we assume you may re-parent this item
        if not await user_has_permission_for_domain(user.pk, "create", parent_id):
            return {
                "message": "You do not have permission to update this item with this parent."
            }, 403

        body["parent_id"] = parent_id

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

    return await DomainSerializer(instance=obj).adata, 200


async def delete(id, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = await Domain.objects.aget(id=id)
    except Domain.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_domain(user.pk, "delete", id):
        return {"message": "You do not have permission to delete this item."}, 403

    try:
        await obj.adelete()
    except ProtectedError:
        return {
            "message": "Cannot delete item because other items are dependent on it. You must delete those items first."
        }, 422

    return {"message": "Item deleted successfully"}, 204


async def search(user, token_info, **kwargs):
    user = token_info["user"]

    # TODO: get_user_domains does not do permission checks. The user needs the read permission
    # for the domain. That is a separate check that is expensive.
    domains = await get_user_domains(user)
    return await paginate_result(domains, DomainSerializer)

