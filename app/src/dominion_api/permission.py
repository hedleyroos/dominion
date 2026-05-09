from uuid import UUID

from asgiref.sync import sync_to_async
from connexion import request
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db.models.deletion import ProtectedError

from dominion_api.constants import DEFAULT_PERMISSIONS_Q
from dominion_api.utils import paginate_result
from dominion.models import Permission
from dominion.serializers import PermissionSerializer
from dominion.utils import user_has_permission_for_domain, get_user_domains


ITEM_NOT_FOUND = "Item not found for id: {}."


async def post(body, user, token_info, **kwargs):
    user = token_info["user"]

    domain_id = body.pop("domain")
    # Connexion doesn't validate UUID's yet
    try:
        UUID(domain_id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % domain_id}, 400

    if not await user_has_permission_for_domain(user.pk, "create", domain_id):
        return {
            "message": "You do not have permission to create this item for this domain."
        }, 403

    body["domain_id"] = domain_id

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    try:
        obj = Permission(**body)
        await sync_to_async(obj.full_clean)()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Actually create and persist an object
    try:
        obj = await Permission.objects.acreate(**body)
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    return await PermissionSerializer(instance=obj).adata, 201


async def get(code, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = await Permission.objects.aget(code=code)
    except Permission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(code)}, 404

    if not obj.domain_id or not await user_has_permission_for_domain(user.pk, "read", obj.domain_id):
        return {"message": "You do not have permission to read this item."}, 403

    return await PermissionSerializer(instance=obj).adata, 200


async def put(code, body, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = await Permission.objects.aget(code=code)
    except Permission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(code)}, 404

    if not obj.domain_id or not await user_has_permission_for_domain(user.pk, "update", obj.domain_id):
        return {"message": "You do not have permission to update this item."}, 403

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

    return await PermissionSerializer(instance=obj).adata, 200


async def delete(code, user, token_info, **kwargs):
    user = token_info["user"]

    try:
        obj = await Permission.objects.aget(code=code)
    except Permission.DoesNotExist:
        return {"message": ITEM_NOT_FOUND.format(code)}, 404

    if not obj.domain_id or not await user_has_permission_for_domain(user.pk, "delete", obj.domain_id):
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
    root_domains = (await get_user_domains(user)).filter(parent__isnull=True)
    return await paginate_result(
        Permission.objects.filter(Q(domain__in=root_domains) | DEFAULT_PERMISSIONS_Q).select_related("domain").order_by("code"),
        PermissionSerializer
    )

