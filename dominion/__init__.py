from django.db.utils import OperationalError

from dominion.conf.celery import app as celery_app  # noqa: F401

__all__ = ("celery_app",)


def create_initial_data():
    from dominion import models  # noqa

    for code, title in (
        ("anonymous", "Anonymous"),
        ("authenticated", "Authenticated"),
        ("manager", "Manager"),
        ("owner", "Owner"),
        ("access_checker", "Access checker"),
    ):
        try:
            models.Role.objects.get_or_create(code=code, title=title)
        except OperationalError:
            pass

    for code, title in (
        ("create", "Create"),
        ("read", "Read"),
        ("update", "Update"),
        ("delete", "Delete"),
        ("check_access", "Check access"),
        ("manage_roles", "Manage roles"),
        ("view", "View as public"),
    ):
        try:
            models.Permission.objects.get_or_create(code=code, title=title)
        except OperationalError:
            pass
