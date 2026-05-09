from uuid import UUID

from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError

from dominion.api.utils import paginate_result
from dominion.models import Resource
from dominion.serializers import ResourceSerializer
from dominion.utils import user_has_permission_for_domain, user_has_permission_for_resource, \
    get_user_domains


ITEM_NOT_FOUND = "Item not found for id: {}."


async def post(body, user, token_info, **kwargs):
    user = token_info["user"]

    parent_id = body.pop("parent", None)
    domain_id = body.pop("domain", None)

    if parent_id:
        # Connexion doesn't validate UUID's yet
        try:
            UUID(parent_id)
        except ValueError:
            return {"message": "%s is not a valid UUID." % parent_id}, 400

        if not await user_has_permission_for_resource(user.pk, "create", parent_id):
            return {
                "message": "You do not have permission to create this item with this parent."
            }, 403

        body["parent_id"] = parent_id

    if domain_id:
        # Connexion doesn't validate UUID's yet
        try:
            UUID(domain_id)
        except ValueError:
            return {"message": "%s is not a valid UUID." % domain_id}, 400

        if not parent_id and not await user_has_permission_for_domain(user.pk, "create", domain_id):
            return {
                "message": "You do not have permission to create this item with this domain."
            }, 403

        body["domain_id"] = domain_id

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    try:
        obj = Resource(**body)
        await sync_to_async(obj.full_clean)()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    if kwargs.get("dryrun", False):
        return await ResourceSerializer(instance=obj).adata, 201

    # Actually create and persist an object
    try:
        obj = await sync_to_async(Resource.objects.create)(**body, owner=user)
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    return await ResourceSerializer(instance=obj).adata, 201


async def get(id, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = await Resource.objects.aget(id=id)
    except Resource.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_resource(user.pk, "read", id):
        return {"message": "You do not have permission to read this item."}, 403

    return await ResourceSerializer(instance=obj).adata, 200


async def put(id, body, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % id}, 400

    try:
        obj = await Resource.objects.aget(id=id)
    except Resource.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_resource(user.pk, "update", id):
        return {"message": "You do not have permission to update this item."}, 403

    parent_id = body.pop("parent", None)
    domain_id = body.pop("domain", None)

    if parent_id:
        # Connexion doesn't validate UUID's yet
        try:
            UUID(parent_id)
        except ValueError:
            return {"message": "%s is not a valid UUID." % parent_id}, 400

        # If you are allowed to create within the parent then we assume you may re-parent this item
        if not await user_has_permission_for_resource(user.pk, "create", parent_id):
            return {
                "message": "You do not have permission to update this item with this parent."
            }, 403

        body["parent_id"] = parent_id

    if domain_id:
        # Connexion doesn't validate UUID's yet
        try:
            UUID(domain_id)
        except ValueError:
            return {"message": "%s is not a valid UUID." % domain_id}, 400

        if not parent_id and not await user_has_permission_for_domain(user.pk, "create", domain_id):
            return {
                "message": "You do not have permission to update this item with this domain."
            }, 403

        body["domain_id"] = domain_id

    for k, v in body.items():
        setattr(obj, k, v)
    try:
        await sync_to_async(obj.full_clean)()
        if not kwargs.get("dryrun", False):
            await obj.asave()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    return await ResourceSerializer(instance=obj).adata, 200


async def delete(id, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = await Resource.objects.aget(id=id)
    except Resource.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(id)}, 404

    if not await user_has_permission_for_resource(user.pk, "delete", id):
        return {"message": "You do not have permission to delete this item."}, 403

    if kwargs.get("dryrun", False):
        return None, 204

    try:
        await obj.adelete()
    except ProtectedError:
        return {
            "message": "Cannot delete item because other items are dependent on it. You must delete those items first."
        }, 422

    return None, 204


async def search(user, token_info, **kwargs):
    user = token_info["user"]

    # Resources can be arbitrarily many. It is not our job to return the client's resources. They
    # have their own set.
    raise NotImplementedError

