from django_registration.forms import RegistrationFormUniqueEmail

from triplea.models import User


class RegistrationForm(RegistrationFormUniqueEmail):
    """We have a custom user model.
    """

    class Meta(RegistrationFormUniqueEmail.Meta):
        model = User
