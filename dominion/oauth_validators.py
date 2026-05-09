import uuid

from django.contrib.auth import get_user_model
from oauth2_provider.oauth2_validators import OAuth2Validator

from dominion.utils import get_user_domains_sync


class CustomOAuth2Validator(OAuth2Validator):

    def get_additional_claims(self, request):
        # A single API key is too powerful. Implicitly create another user object
        # that is tied to the Oauth2 application. This user has its own API key, and
        # this ensures that external applications can't access domains and resources
        # that fall outside of their scope.
        app_id = request.client.id
        app_user_username = "%s%%%s" % (request.user.username, app_id)
        app_user_email = "%s@dominion.com" % uuid.uuid4()
        User = get_user_model()
        app_user, _ = User.objects.get_or_create(
            username=app_user_username,
            application_id=app_id,
            defaults={"email": app_user_email},
        )
        user_domains = get_user_domains_sync(app_user)
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
