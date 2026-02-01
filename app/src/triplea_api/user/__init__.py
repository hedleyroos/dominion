from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from flask import request

from triplea.serializers import UserSerializer


ITEM_NOT_FOUND = "Item not found for id: {}."


def post(body, user, token_info, **kwargs):
    user = token_info["user"]

    User = get_user_model()
    body["created_by"] = user

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    try:
        obj = User(**body)
        obj.full_clean()
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Actually create and persist an object
    try:
        obj = User.objects.create(**body)
    except ValidationError as e:
        if hasattr(e, "error_dict"):
            return e.message_dict, 422
        else:
            return {"message": e.messages[0]}, 422

    # Set password
    obj.set_password(body["password"])
    obj.save(update_fields=["password"])

    return UserSerializer(instance=obj).data, 201
