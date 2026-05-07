from django.utils.decorators import method_decorator
from django_registration.backends.activation.views import RegistrationView as BaseRegistrationView
from django_ratelimit.decorators import ratelimit

from triplea.registration import forms


@method_decorator(ratelimit(key="ip", rate="5/h", block=True), name="dispatch")
class RegistrationView(BaseRegistrationView):
    form_class = forms.RegistrationForm
