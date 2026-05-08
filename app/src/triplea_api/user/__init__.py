from uuid import UUID

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from triplea.serializers import UserSerializer


ITEM_NOT_FOUND = "Item not found for id: {}."


async def post(body, user, token_info, **kwargs):
    current_user = token_info["user"]

    User = get_user_model()
    body["created_by"] = current_user

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    try:
        obj = User(**body)
        await sync_to_async(obj.full_clean)()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Actually create and persist an object
    try:
        obj = await User.objects.acreate(**body)
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Set password
    await sync_to_async(obj.set_password)(body["password"])
    await obj.asave(update_fields=["password"])

    return await UserSerializer(instance=obj).adata, 201
