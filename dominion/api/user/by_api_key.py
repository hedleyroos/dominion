from django.contrib.auth import get_user_model

from dominion.serializers import UserSerializer
from dominion.api.utils import check_rate_limit


async def get(api_key, **kwargs):
    if await check_rate_limit("user_by_api_key", "30/m"):
        return {"message": "Too many requests."}, 429

    User = get_user_model()

    user = await User.objects.filter(api_key=api_key).afirst()
    if user is None:
        return {"message": "Account not found"}, 404

    if not user.is_active:
        return {"message": "Account is not activated"}, 401

    return await UserSerializer(instance=user).adata, 200

