import uuid

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from oauth2_provider.oauth2_validators import OAuth2Validator

from triplea.utils import get_user_domains


class CustomOAuth2Validator(OAuth2Validator):

    def get_additional_claims(self, request):
        # A single API key is too powerful. Implicitly create another user object
        # that is tied to the Oauth2 application. This user has its own API key, and
        # this ensures that external applications can't access domains and resources
        # that fall outside of their scope.
        app_id = request.client.id
        app_user_username = "%s%%%s" % (request.user.username, app_id)
        app_user_email = "%s@triplea.com" % uuid.uuid4()
        User = get_user_model()
        try:
            app_user = User.objects.get(username=app_user_username, application_id=app_id)
        except User.DoesNotExist:
            app_user = User.objects.create(
                username=app_user_username, email=app_user_email,
                application_id=app_id,
            )
        user_domains = async_to_sync(get_user_domains)(app_user)
        return {
            "given_name": request.user.first_name,
            "family_name": request.user.last_name,
            "name": ' '.join([request.user.first_name, request.user.last_name]),
            "preferred_username": request.user.username,
            "email": request.user.email,
            "uuid": str(app_user.id),
            "domains": [{"uuid": str(o.id), "title": o.title} for o in user_domains],
            "api_key": str(app_user.api_key),
        }

    def validate_silent_login(self, request):
        if not getattr(request, "user", None):
            return False

        if request.user.is_anonymous:
            return False

        return True
