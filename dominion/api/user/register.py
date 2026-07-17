from asgiref.sync import sync_to_async
from connexion import request
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django_registration.backends.activation.views import RegistrationView

from dominion.serializers import UserSerializer
from dominion.api.utils import check_rate_limit


async def post(body, **kwargs):
    if await check_rate_limit("user_register", "5/h"):
        return {"message": "Too many requests."}, 429

    User = get_user_model()
    body["is_active"] = False

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

    # Reuse the Django registration view. Build a minimal Django HttpRequest from the Starlette request.
    starlette_request = request._starlette_request
    dr = HttpRequest()
    dr.META = dict(starlette_request.headers)
    dr.META["SERVER_NAME"] = starlette_request.url.hostname
    dr.META["SERVER_PORT"] = str(starlette_request.url.port or 443)
    view = RegistrationView(request=dr)
    await sync_to_async(view.send_activation_email)(obj)

    return await UserSerializer(instance=obj).adata, 201

