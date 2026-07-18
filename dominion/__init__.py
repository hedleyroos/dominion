import logging

from dominion.conf.celery import app as celery_app  # noqa: F401

__all__ = ("celery_app",)

logger = logging.getLogger("dominion")


def create_initial_data():
    """Create minimum required system roles and permissions.
    """
    from dominion import models  # noqa

    for code, title in (
        ("anonymous", "Anonymous"),
        ("authenticated", "Authenticated"),
        ("manager", "Manager"),
        ("owner", "Owner"),
        ("access_checker", "Access checker"),
    ):
        models.Role.objects.get_or_create(code=code, title=title)

    for code, title in (
        ("create", "Create"),
        ("read", "Read"),
        ("update", "Update"),
        ("delete", "Delete"),
        ("check_access", "Check access"),
        ("manage_roles", "Manage roles"),
        ("view", "View as public"),
    ):
        models.Permission.objects.get_or_create(code=code, title=title)
