from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from triplea.serializers import UserSerializer


async def post(body, **kwargs):
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

