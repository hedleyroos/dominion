from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from dominion.serializers import UserSerializer
from dominion.api.utils import check_rate_limit


async def post(body, **kwargs):
    if await check_rate_limit("user_login", "10/5m"):
        return {"message": "Too many requests."}, 429

    User = get_user_model()

    user = await User.objects.filter(email=body["email"]).afirst()
    if user is None:
        return {"message": "Invalid credentials"}, 401

    if not user.is_active:
        return {"message": "Account is not activated"}, 401

    password_ok = await sync_to_async(user.check_password)(body["password"])
    if not password_ok:
        return {"message": "Invalid credentials"}, 401

    return await UserSerializer(instance=user).adata, 200

