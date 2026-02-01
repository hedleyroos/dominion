from django.db.models import Q


DEFAULT_ROLES_Q = Q(code__in=("anonymous", "authenticated", "manager", "owner", "access_checker"))
DEFAULT_PERMISSIONS_Q = Q(code__in=("create", "read", "update", "delete", "check_access", "manage_roles", "view"))
