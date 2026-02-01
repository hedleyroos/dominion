from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django_registration.backends.activation.views import RegistrationView
from flask import request

from triplea.serializers import UserSerializer


def post(body, **kwargs):
    User = get_user_model()
    body["is_active"] = False

    # Create an in-memory object so we can run checks without attempting to save to the database.
    # This provides us with clean error messages.
    # import pdb; pdb.set_trace()
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

    # Reuse the Django registration view. It's a bit painful.
    dr = HttpRequest()
    dr.META = dict(request.headers)
    dr.META["SERVER_NAME"], dr.META["SERVER_PORT"] = request.server
    view = RegistrationView(request=dr)
    view.send_activation_email(obj)

    return UserSerializer(instance=obj).data, 201
