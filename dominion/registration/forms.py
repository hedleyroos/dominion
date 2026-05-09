from django_registration.forms import RegistrationFormUniqueEmail

from dominion.models import User


class RegistrationForm(RegistrationFormUniqueEmail):
    """We have a custom user model.
    """

    class Meta(RegistrationFormUniqueEmail.Meta):
        model = User
