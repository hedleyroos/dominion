from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from flask import request

from triplea.serializers import UserSerializer


def get(api_key, **kwargs):
    User = get_user_model()
    try:
        user = User.objects.get(api_key=api_key)
    except User.DoesNotExist:
        return {"message": "Account not found"}, 404

    if not user.is_active:
        return {"message": "Account is not activated"}, 401

    return UserSerializer(instance=user).adata, 200
