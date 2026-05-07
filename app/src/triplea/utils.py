import contextvars
import secrets

from asgiref.sync import sync_to_async
from django.core.cache import cache as django_cache

from triplea import models

# Cross-request permission cache TTL (seconds).
_PERM_CACHE_TTL = 300

# Cache key for the global "rules version" — bumped on any DomainRolePermission /
# ResourceRolePermission mutation so all cached permission results are immediately stale.
_RULES_VER_KEY = "triplea:rv"


def _user_ver_key(user_id: str) -> str:
    return f"triplea:uv:{user_id}"


async def _get_or_create_version(key: str) -> str:
    """Return the version token for *key*, creating one if absent.

    The result is stored in the request-scoped cache so subsequent calls within
    the same request skip the Django cache round-trip.
    """
    request_cache = _cache()
    if key in request_cache:
        return request_cache[key]
    version = await django_cache.aget(key)
    if version is None:
        version = secrets.token_hex(4)
        await django_cache.aset(key, version, _PERM_CACHE_TTL * 2)
    request_cache[key] = version
    return version


async def _cross_request_key(kind: str, user_id, perm_code: str, object_id) -> str:
    """Build a versioned Django cache key for a permission result."""
    rules_ver = await _get_or_create_version(_RULES_VER_KEY)
    user_ver = await _get_or_create_version(_user_ver_key(str(user_id)))
    return f"triplea:p:{rules_ver}:{user_ver}:{kind}:{user_id}:{perm_code}:{object_id}"


async def invalidate_user_permissions(user_id: str) -> None:
    """Invalidate all cross-request permission cache entries for *user_id*.

    Call this after any UserDomainRole or UserResourceRole mutation.
    """
    await django_cache.adelete(_user_ver_key(user_id))


async def invalidate_rules_permissions() -> None:
    """Invalidate all cross-request permission cache entries for all users.

    Call this after any DomainRolePermission or ResourceRolePermission mutation.
    """
    await django_cache.adelete(_RULES_VER_KEY)


# ---------------------------------------------------------------------------
# Shared helper functions
# ---------------------------------------------------------------------------

def _get_user_domains_recursive_ids(domain_ids: list[str]) -> list[str]:
    """Return IDs of descendant domains reachable from *domain_ids* via parent chain."""
    placeholders = ",".join(["%s"] * len(domain_ids))
    query = f"""
    WITH RECURSIVE children (id) AS (
    SELECT triplea_domain.id FROM triplea_domain WHERE id IN ({placeholders})
      UNION ALL
    SELECT triplea_domain.id FROM children, triplea_domain
      WHERE triplea_domain.parent_id = children.id
    )
    SELECT triplea_domain.id
    FROM triplea_domain, children WHERE children.id = triplea_domain.id
    """
    return [o.id for o in models.Domain.objects.raw(query, domain_ids)]


def _set_default_inherit(items: list) -> None:
    """Ensure every item has .inherit=True if not already set."""
    for item in items:
        if not hasattr(item, "inherit"):
            item.inherit = True


def _build_role_permission_mapping(roles: list, permissions: list, active_pairs: set) -> list:
    """Build [[permission, {role_info}, ...], ...] for admin matrix views."""
    rows = []
    for permission in permissions:
        row = [permission]
        for role in roles:
            active = (role.id, permission.id) in active_pairs
            row.append({"permission": permission, "active": active, "role": role})
        rows.append(row)
    return rows


# The queries are complex because the role and permission mappings on domain and resources are sparse to avoid
# database bloat. Resources live within resources, and the top level resource lives in a domain, and
# domains live within domains. This module therefore has a lot of recursive functions.


# Request-scoped permission cache. Each ASGI request gets its own context copy so there is no
# cross-request leakage. The cache eliminates redundant DB round-trips when the same domain/resource
# tree is traversed multiple times within a single request (e.g. checking several permissions).
_request_cache: contextvars.ContextVar[dict | None] = contextvars.ContextVar("_request_cache", default=None)


def _cache() -> dict:
    cache = _request_cache.get()
    if cache is None:
        cache = {}
        _request_cache.set(cache)
    return cache


async def user_has_role_for_domain(user_id, role_code, domain_id):
    cache = _cache()
    key = ("uhr_domain", user_id, role_code, domain_id)
    if key in cache:
        return cache[key]

    if await models.UserDomainRole.objects.filter(user__id=user_id, role__code=role_code, domain__id=domain_id).aexists():
        cache[key] = True
        return True

    domain_key = ("domain", domain_id)
    if domain_key not in cache:
        cache[domain_key] = await models.Domain.objects.aget(id=domain_id)
    domain = cache[domain_key]

    if domain.parent_id:
        result = await user_has_role_for_domain(user_id, role_code, domain.parent_id)
        cache[key] = result
        return result

    cache[key] = False
    return False


async def domain_has_permission_for_role(domain_id, permission_code, role_code):
    cache = _cache()
    key = ("dhp_role", domain_id, permission_code, role_code)
    if key in cache:
        return cache[key]

    if await models.DomainRolePermission.objects.filter(domain__id=domain_id, role__code=role_code, permission__code=permission_code).aexists():
        cache[key] = True
        return True

    # Check acquisition. Only if an item exists and specifically opts out of inherit
    # do we return false.
    cannot_inherit = await models.DomainPermission.objects.filter(
        domain__id=domain_id, permission__code=permission_code, inherit=False
    ).aexists()
    if cannot_inherit:
        cache[key] = False
        return False

    # We can inherit. Traverse upwards.
    domain_key = ("domain", domain_id)
    if domain_key not in cache:
        cache[domain_key] = await models.Domain.objects.aget(id=domain_id)
    domain = cache[domain_key]

    if domain.parent_id:
        result = await domain_has_permission_for_role(domain.parent_id, permission_code, role_code)
        cache[key] = result
        return result

    cache[key] = False
    return False


async def _user_has_permission_for_domain(user_id, permission_code, domain_id, domain_ids):

    # Check for user roles declared on the domain
    user_domain_roles = [
        o.role async for o in models.UserDomainRole.objects.filter(user__id=user_id, domain__id__in=domain_ids).select_related("role")
    ]
    if user_domain_roles:
        for_domain = models.DomainRolePermission.objects.filter(
            domain__id__in=domain_ids, role__in=user_domain_roles, permission__code=permission_code
        )
        if await for_domain.aexists():
            return True

    # Check acquisition. Only if an item exists and specifically opts out of inherit
    # do we return false.
    cannot_inherit = await models.DomainPermission.objects.filter(
        domain__id=domain_id, permission__code=permission_code, inherit=False
    ).aexists()
    if cannot_inherit:
        return False

    # We can inherit. Traverse upwards.
    cache = _cache()
    domain_key = ("domain", domain_id)
    if domain_key not in cache:
        cache[domain_key] = await models.Domain.objects.select_related("parent").aget(id=domain_id)
    domain = cache[domain_key]

    if domain.parent_id is not None:
        return await _user_has_permission_for_domain(user_id, permission_code, domain.parent_id, domain_ids | {domain.parent_id})

    return False


async def user_has_permission_for_domain(user_id, permission_code, domain_id):
    request_cache = _cache()
    request_key = ("uhp_domain", user_id, permission_code, domain_id)
    if request_key in request_cache:
        return request_cache[request_key]

    # Check cross-request (Django) cache before hitting the database.
    cross_key = await _cross_request_key("d", user_id, permission_code, domain_id)
    cached = await django_cache.aget(cross_key)
    if cached is not None:
        request_cache[request_key] = cached
        return cached

    result = await _user_has_permission_for_domain(user_id, permission_code, domain_id, {domain_id})
    request_cache[request_key] = result
    await django_cache.aset(cross_key, result, _PERM_CACHE_TTL)
    return result


async def _user_has_permission_for_resource(user_id, permission_code, resource_id, resource_ids):

    # Check for user roles declared on the resource
    user_resource_roles = [
        o.role
        async for o in models.UserResourceRole.objects.filter(
            user__id=user_id, resource__id__in=resource_ids
        ).select_related("role")
    ]
    if user_resource_roles:
        for_resource = models.ResourceRolePermission.objects.filter(
            resource__id__in=resource_ids, role__in=user_resource_roles, permission__code=permission_code
        )
        if await for_resource.aexists():
            return True

    # Check acquisition. Only if an item exists and specifically opts out of inherit
    # do we return false.
    cannot_inherit = await models.ResourcePermission.objects.filter(
        resource__id=resource_id, permission__code=permission_code, inherit=False
    ).aexists()
    if cannot_inherit:
        return False

    # We can inherit. If resource has a parent then the resource ancestry determines whether
    # we have permission or not. If resource has no parent then the domain ancestry
    # determines whether we have permission or not.
    resource = await models.Resource.objects.select_related("domain").aget(id=resource_id)
    if resource.parent_id is not None:
        return await _user_has_permission_for_resource(user_id, permission_code, resource.parent_id, resource_ids | {resource.parent_id})
    else:
        # This is the most difficult part because we transition from traversing upward over resources
        # to traversing upward over domains.

        # This set of roles satisfies the required permission. The user already has a role declared
        # on the resource or its traversable parents, so we don't need to consider the user when
        # checking the domains.
        for role in user_resource_roles:
            if await domain_has_permission_for_role(resource.domain_id, permission_code, role.code):
                return True

        # Roles and permissions set on the resource or its traversable parents. Here we do consider
        # the user when checking the domain.
        async for obj in models.ResourceRolePermission.objects.filter(
            resource__id__in=resource_ids, permission__code=permission_code
        ).select_related("role"):
            if await user_has_role_for_domain(user_id, obj.role.code, resource.domain_id):
                return True

        # Simple recursion
        return await user_has_permission_for_domain(user_id, permission_code, resource.domain_id)

    return False


async def user_has_permission_for_resource(user_id, permission_code, resource_id):
    request_cache = _cache()
    request_key = ("uhp_resource", user_id, permission_code, resource_id)
    if request_key in request_cache:
        return request_cache[request_key]

    # Check cross-request (Django) cache before hitting the database.
    cross_key = await _cross_request_key("r", user_id, permission_code, resource_id)
    cached = await django_cache.aget(cross_key)
    if cached is not None:
        request_cache[request_key] = cached
        return cached

    result = await _user_has_permission_for_resource(user_id, permission_code, resource_id, {resource_id})
    request_cache[request_key] = result
    await django_cache.aset(cross_key, result, _PERM_CACHE_TTL)
    return result


async def get_user_domains(user):
    """Return all domains on which the user has any roles, both explicit and inherited.
    """
    domain_ids = list(set([
        o.hex async for o in models.UserDomainRole.objects.filter(user=user).values_list("domain_id", flat=True)
    ]))
    if domain_ids:
        recursive_ids = await sync_to_async(_get_user_domains_recursive_ids)(domain_ids)
        return models.Domain.objects.filter(
            id__in=domain_ids + recursive_ids
        ).select_related("parent").order_by("title")
    else:
        return models.Domain.objects.none()


async def get_domain_roles(domain):
    found = []
    parent = domain
    while parent is not None:
        async for obj in models.DomainRolePermission.objects.filter(domain=parent).select_related("role"):
            if obj.role not in found:
                found.append(obj.role)
        parent = parent.parent
    return sorted(found, key=lambda item: item.code)


async def get_domain_permissions(domain):
    found = []
    parent = domain
    while parent is not None:
        async for obj in models.DomainPermission.objects.filter(domain=parent).select_related("permission"):
            if obj.permission not in found:
                # We cheat a bit by gluing inherit on the permission
                obj.permission.inherit = obj.inherit
                found.append(obj.permission)
        async for obj in models.DomainRolePermission.objects.filter(domain=parent).select_related("permission"):
            if obj.permission not in found:
                found.append(obj.permission)
        parent = parent.parent

    _set_default_inherit(found)
    return sorted(found, key=lambda item: item.code)


async def domain_roles_permissions_mapping(domain):
    """Mapping structure used by views.
    """
    roles = await get_domain_roles(domain)
    permissions = await get_domain_permissions(domain)
    active_pairs = {
        (obj.role_id, obj.permission_id)
        async for obj in models.DomainRolePermission.objects.filter(domain=domain)
    }
    return _build_role_permission_mapping(roles, permissions, active_pairs)


async def get_resource_roles(resource):
    found = []
    parent = resource
    while parent is not None:
        async for obj in models.ResourceRolePermission.objects.filter(resource=parent).select_related("role"):
            if obj.role not in found:
                found.append(obj.role)
        parent = parent.parent

    domain = await models.Domain.objects.aget(id=resource.domain_id)
    for role in await get_domain_roles(domain):
        if role not in found:
            found.append(role)

    return sorted(found, key=lambda item: item.code)


async def get_resource_permissions(resource):
    found = []
    parent = resource
    while parent is not None:
        async for obj in models.ResourcePermission.objects.filter(resource=parent).select_related("permission"):
            if obj.permission not in found:
                # We cheat a bit by gluing inherit on the permission
                obj.permission.inherit = obj.inherit
                found.append(obj.permission)
        async for obj in models.ResourceRolePermission.objects.filter(resource=parent).select_related("permission"):
            if obj.permission not in found:
                found.append(obj.permission)
        parent = parent.parent

    domain = await models.Domain.objects.aget(id=resource.domain_id)
    for permission in await get_domain_permissions(domain):
        if permission not in found:
            found.append(permission)

    _set_default_inherit(found)
    return sorted(found, key=lambda item: item.code)


async def resource_roles_permissions_mapping(resource):
    """Mapping structure used by views.
    """
    roles = await get_resource_roles(resource)
    permissions = await get_resource_permissions(resource)
    active_pairs = {
        (obj.role_id, obj.permission_id)
        async for obj in models.ResourceRolePermission.objects.filter(resource=resource)
    }
    return _build_role_permission_mapping(roles, permissions, active_pairs)


# ---------------------------------------------------------------------------
# Sync utility variants (P3.5)
# ---------------------------------------------------------------------------
# Used by Django admin views and the OAuth validator which run in a sync WSGI
# context.  These avoid the event-loop overhead of async_to_sync() wrappers by
# using the synchronous Django ORM directly.

def get_user_domains_sync(user):
    """Synchronous variant of get_user_domains for use in sync (admin/OAuth) contexts."""
    domain_ids = list({
        value.hex
        for value in models.UserDomainRole.objects.filter(user=user).values_list("domain_id", flat=True)
    })
    if not domain_ids:
        return models.Domain.objects.none()
    recursive_ids = _get_user_domains_recursive_ids(domain_ids)
    return models.Domain.objects.filter(
        id__in=domain_ids + recursive_ids
    ).select_related("parent").order_by("title")


def _get_domain_roles_sync(domain):
    found = []
    parent = domain
    while parent is not None:
        for obj in models.DomainRolePermission.objects.filter(domain=parent).select_related("role"):
            if obj.role not in found:
                found.append(obj.role)
        parent = parent.parent
    return sorted(found, key=lambda item: item.code)


def _get_domain_permissions_sync(domain):
    found = []
    parent = domain
    while parent is not None:
        for obj in models.DomainPermission.objects.filter(domain=parent).select_related("permission"):
            if obj.permission not in found:
                obj.permission.inherit = obj.inherit
                found.append(obj.permission)
        for obj in models.DomainRolePermission.objects.filter(domain=parent).select_related("permission"):
            if obj.permission not in found:
                found.append(obj.permission)
        parent = parent.parent
    _set_default_inherit(found)
    return sorted(found, key=lambda item: item.code)


def domain_roles_permissions_mapping_sync(domain):
    """Synchronous variant of domain_roles_permissions_mapping for admin views."""
    roles = _get_domain_roles_sync(domain)
    permissions = _get_domain_permissions_sync(domain)
    active_pairs = {
        (obj.role_id, obj.permission_id)
        for obj in models.DomainRolePermission.objects.filter(domain=domain)
    }
    return _build_role_permission_mapping(roles, permissions, active_pairs)


def _get_resource_roles_sync(resource):
    found = []
    parent = resource
    while parent is not None:
        for obj in models.ResourceRolePermission.objects.filter(resource=parent).select_related("role"):
            if obj.role not in found:
                found.append(obj.role)
        parent = parent.parent
    domain = models.Domain.objects.get(id=resource.domain_id)
    for role in _get_domain_roles_sync(domain):
        if role not in found:
            found.append(role)
    return sorted(found, key=lambda item: item.code)


def _get_resource_permissions_sync(resource):
    found = []
    parent = resource
    while parent is not None:
        for obj in models.ResourcePermission.objects.filter(resource=parent).select_related("permission"):
            if obj.permission not in found:
                obj.permission.inherit = obj.inherit
                found.append(obj.permission)
        for obj in models.ResourceRolePermission.objects.filter(resource=parent).select_related("permission"):
            if obj.permission not in found:
                found.append(obj.permission)
        parent = parent.parent
    domain = models.Domain.objects.get(id=resource.domain_id)
    for permission in _get_domain_permissions_sync(domain):
        if permission not in found:
            found.append(permission)
    _set_default_inherit(found)
    return sorted(found, key=lambda item: item.code)


def resource_roles_permissions_mapping_sync(resource):
    """Synchronous variant of resource_roles_permissions_mapping for admin views."""
    roles = _get_resource_roles_sync(resource)
    permissions = _get_resource_permissions_sync(resource)
    active_pairs = {
        (obj.role_id, obj.permission_id)
        for obj in models.ResourceRolePermission.objects.filter(resource=resource)
    }
    return _build_role_permission_mapping(roles, permissions, active_pairs)

