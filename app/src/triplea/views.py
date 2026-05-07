import datetime

from django.http import HttpResponse
from django.views.generic import TemplateView, View
from oauth2_provider.views import AuthorizationView as BaseAuthorizationView


class HomeView(TemplateView):
    template_name = "triplea/home.html"


class HealthView(View):
    def get(self, request, *args, **kwargs):
        return HttpResponse("ok")


class AuthorizationView(BaseAuthorizationView):
    """Custom view so we can inject a cookie. See middleware.py for full explanation.
    """

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)

        if not self.request.user.is_authenticated:
            redirect_next = self.request.build_absolute_uri()
            if redirect_next:
                expires = datetime.datetime.now() + datetime.timedelta(days=365)
                response.set_cookie("oauth_redirect_next", redirect_next, expires=expires)

        return response

