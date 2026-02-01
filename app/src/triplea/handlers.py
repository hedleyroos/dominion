from django.utils import timezone
from django_registration.signals import user_activated


def on_user_activated(sender, **kwargs):
    """A user has been activated through django_registration machinery."""

    user = kwargs["user"]
    user.activation_date = timezone.now()
    user.save(update_fields=["activation_date"])


user_activated.connect(on_user_activated)

