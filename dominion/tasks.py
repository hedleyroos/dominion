from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from dominion.conf.celery import app


@app.task
def vacuum():
    """Delete user accounts that have not been activated after a week.
    """
    start = timezone.now() - timedelta(days=7)
    User = get_user_model()
    User.objects.filter(is_active=False, activation_date__isnull=True, date_joined__lte=start).delete()
