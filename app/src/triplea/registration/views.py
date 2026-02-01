from django_registration.backends.activation.views import RegistrationView as BaseRegistrationView

from triplea.registration import forms


class RegistrationView(BaseRegistrationView):
    form_class = forms.RegistrationForm
