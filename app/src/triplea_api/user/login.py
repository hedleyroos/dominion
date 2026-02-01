from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from flask import request

from triplea.serializers import UserSerializer


def post(body, **kwargs):
    # Authenticate user using Django's auth system
    User = get_user_model()
    try:
        user = User.objects.get(email=body["email"])
    except User.DoesNotExist:
        return {"message": "Invalid credentials"}, 401

    if not user.is_active:
        return {"message": "Account is not activated"}, 401

    if not user.check_password(body["password"]):
        return {"message": "Invalid credentials"}, 401

    return UserSerializer(instance=user).data, 200
