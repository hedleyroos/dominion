import os

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model


async def basic_auth(username, password, required_scopes=None):
    User = get_user_model()

    user = await User.objects.filter(username=username).afirst()
    if user is None:
        return None

    password_ok = await sync_to_async(user.check_password)(password)
    if not password_ok:
        return None

    return {"uid": username, "scope": "", "user": user}


async def apikey_auth(api_key, required_scopes=None):
    User = get_user_model()

    user = await User.objects.filter(api_key=api_key).afirst()
    if user is None:
        return None

    return {"uid": user.username, "scope": "", "user": user}
