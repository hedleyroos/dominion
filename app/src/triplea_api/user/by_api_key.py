from django.contrib.auth import get_user_model

from triplea.serializers import UserSerializer


async def get(api_key, **kwargs):
    User = get_user_model()

    user = await User.objects.filter(api_key=api_key).afirst()
    if user is None:
        return {"message": "Account not found"}, 404

    if not user.is_active:
        return {"message": "Account is not activated"}, 401

    return await UserSerializer(instance=user).adata, 200

