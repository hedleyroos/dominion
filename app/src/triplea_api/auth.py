import os

from django.contrib.auth import get_user_model


def basic_auth(username, password, required_scopes=None):
    User = get_user_model()

    # We're guaranteed exactly zero or one results. This style is to prevent redundant queries.
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return None

    if not user.check_password(password):
        return None

    return {"uid": username, "scope": "", "user": user}


def apikey_auth(api_key, required_scopes=None):
    User = get_user_model()

    # We're guaranteed exactly zero or one results. This style is to prevent redundant queries.
    try:
        user = User.objects.get(api_key=api_key)
    except User.DoesNotExist:
        return None

    return {"uid": user.username, "scope": "", "user": user}
