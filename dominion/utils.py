import contextvars
import secrets

from asgiref.sync import sync_to_async
from django.core.cache import cache as django_cache

from dominion import models

# Cross-request permission cache TTL (seconds).
_PERM_CACHE_TTL = 300

# Cache key for the global "rules version" — bumped on any DomainRolePermission /
# ResourceRolePermission mutation so all cached permission results are immediately stale.
_RULES_VER_KEY = "dominion:rv"


def _user_ver_key(user_id: str) -> str:
    return f"dominion:uv:{user_id}"


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
    return f"dominion:p:{rules_ver}:{user_ver}:{kind}:{user_id}:{perm_code}:{object_id}"


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


def invalidate_user_permissions_sync(user_id) -> None:
    """Synchronous counterpart of :func:`invalidate_user_permissions`.

    Safe to call from signal receivers, the Django admin, management commands,
    and any host project embedding Dominion that mutates role assignments via
    the ORM.
    """
    django_cache.delete(_user_ver_key(str(user_id)))


def invalidate_rules_permissions_sync() -> None:
    """Synchronous counterpart of :func:`invalidate_rules_permissions`."""
    django_cache.delete(_RULES_VER_KEY)


# ---------------------------------------------------------------------------
# Shared helper functions
# ---------------------------------------------------------------------------

def _get_user_domains_recursive_ids(domain_ids: list[str]) -> list[str]:
    """Return IDs of descendant domains reachable from *domain_ids* via parent chain."""
    placeholders = ",".join(["%s"] * len(domain_ids))
    query = f"""
    WITH RECURSIVE children (id) AS (
    SELECT dominion_domain.id FROM dominion_domain WHERE id IN ({placeholders})
      UNION ALL
    SELECT dominion_domain.id FROM children, dominion_domain
      WHERE dominion_domain.parent_id = children.id
    )
    SELECT dominion_domain.id
    FROM dominion_domain, children WHERE children.id = dominion_domain.id
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


def reset_request_cache() -> None:
    """Clear the request-scoped permission cache.

    In ASGI each request runs in its own context, so the cache starts empty
    naturally. Call this at a request boundary as defence-in-depth (and to
    delineate logical requests in tests) so a reused context can never serve a
    stale version token or permission result from a previous request.
    """
    _request_cache.set(None)


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


async def _get_resource_ancestors(resource_id):
    """Return the full resource ancestor chain [resource, parent, …, root]."""
    cache = _cache()
    key = ("resource_ancestors", resource_id)
    if key in cache:
        return cache[key]

    ancestors = []
    current_id = resource_id
    while current_id:
        resource = await models.Resource.objects.select_related("domain").aget(id=current_id)
        ancestors.append(resource)
        current_id = resource.parent_id

    cache[key] = ancestors
    return ancestors


async def _batch_domain_has_permission_for_role(domain_id, permission_code, role_codes):
    """Walk the domain tree once, returning True if any role in *role_codes*
    has *permission_code* on *domain_id* or an ancestor."""
    if not role_codes:
        return False

    current_id = domain_id
    while current_id:
        if await models.DomainRolePermission.objects.filter(
            domain__id=current_id,
            role__code__in=role_codes,
            permission__code=permission_code,
        ).aexists():
            return True

        if await models.DomainPermission.objects.filter(
            domain__id=current_id,
            permission__code=permission_code,
            inherit=False,
        ).aexists():
            return False

        domain = await models.Domain.objects.aget(id=current_id)
        current_id = domain.parent_id

    return False


async def _batch_user_has_role_for_domain(user_id, domain_id, role_codes):
    """Walk the domain tree once, returning True if the user has any role in
    *role_codes* on *domain_id* or an ancestor."""
    if not role_codes:
        return False

    current_id = domain_id
    while current_id:
        if await models.UserDomainRole.objects.filter(
            user__id=user_id,
            domain__id=current_id,
            role__code__in=role_codes,
        ).aexists():
            return True

        domain = await models.Domain.objects.aget(id=current_id)
        current_id = domain.parent_id

    return False


async def _user_has_permission_for_resource(user_id, permission_code, resource_id, _resource_ids=None):
    """Check whether *user_id* holds *permission_code* on *resource_id*.

    The check walks the resource-ancestry chain in two phases:

    1. **Resource phase** — for every ancestor resource (including the target),
       check whether the user has an explicit UserResourceRole that is granted
       the permission via a ResourceRolePermission.  Also check for
       inheritance-blocking ResourcePermission records at each level.

    2. **Domain bridge** — at the root resource (no parent), transition to the
       domain tree and check domain-level roles and permissions for the user.

    The old per-level recursive query pattern has been replaced with a single
    ancestor pre-fetch and batched domain-tree walks to eliminate the N+1 loops
    that dominated this function at scale.
    """
    request_cache = _cache()
    cache_key = ("_uhp_resource", user_id, permission_code, resource_id)
    if cache_key in request_cache:
        return request_cache[cache_key]

    # Phase 1 — pre-load the resource ancestor chain (requests are cached).
    ancestors = await _get_resource_ancestors(resource_id)
    ancestor_ids = {str(r.id) for r in ancestors}

    # Check for explicit user roles on any ancestor resource.
    user_resource_roles = [
        urr.role
        async for urr in models.UserResourceRole.objects.filter(
            user__id=user_id, resource__id__in=ancestor_ids,
        ).select_related("role")
    ]
    if user_resource_roles:
        if await models.ResourceRolePermission.objects.filter(
            resource__id__in=ancestor_ids,
            role__in=user_resource_roles,
            permission__code=permission_code,
        ).aexists():
            request_cache[cache_key] = True
            return True

    # Inheritance blocks — stop at the first ancestor that blocks inheritance.
    for ancestor in ancestors:
        if await models.ResourcePermission.objects.filter(
            resource__id=ancestor.id,
            permission__code=permission_code,
            inherit=False,
        ).aexists():
            request_cache[cache_key] = False
            return False

    # Phase 2 — bridge to the domain tree.
    root_resource = ancestors[-1]
    domain_id = root_resource.domain_id

    # 2a — roles the user *already has* on the resource chain.  The domain only
    #      needs to grant those roles the required permission.
    if user_resource_roles:
        role_codes = list({r.code for r in user_resource_roles})
        if await _batch_domain_has_permission_for_role(domain_id, permission_code, role_codes):
            request_cache[cache_key] = True
            return True

    # 2b — roles that are granted the permission on the resource chain.  The
    #      user only needs to hold one of those roles on the domain.
    rrp_roles = [
        rrp.role
        async for rrp in models.ResourceRolePermission.objects.filter(
            resource__id__in=ancestor_ids,
            permission__code=permission_code,
        ).select_related("role")
    ]
    if rrp_roles:
        role_codes = list({r.code for r in rrp_roles})
        if await _batch_user_has_role_for_domain(user_id, domain_id, role_codes):
            request_cache[cache_key] = True
            return True

    # 2c — fall back to the standard domain permission check (cached).
    result = await user_has_permission_for_domain(user_id, permission_code, domain_id)
    request_cache[cache_key] = result
    return result


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

    result = await _user_has_permission_for_resource(user_id, permission_code, resource_id)
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


async def get_user_resources(user):
    """Return all resources on which the user has any explicit roles.
    """
    resource_ids = [
        o async for o in models.UserResourceRole.objects.filter(user=user).values_list("resource_id", flat=True)
    ]
    if resource_ids:
        return models.Resource.objects.filter(id__in=resource_ids).select_related("domain").order_by("urn")
    else:
        return models.Resource.objects.none()


async def get_domain_roles(domain):
    found = []
    parent = domain
    while parent is not None:
        async for obj in models.DomainRolePermission.objects.filter(domain=parent).select_related("role"):
            if obj.role not in found:
                found.append(obj.role)
        # Advance up the tree. Accessing parent.parent directly would trigger a
        # synchronous FK fetch (SynchronousOnlyOperation); fetch it asynchronously.
        if parent.parent_id is None:
            break
        parent = await models.Domain.objects.aget(id=parent.parent_id)
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
        if parent.parent_id is None:
            break
        parent = await models.Domain.objects.aget(id=parent.parent_id)

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
        # Advance up the resource tree asynchronously (see get_domain_roles).
        if parent.parent_id is None:
            break
        parent = await models.Resource.objects.aget(id=parent.parent_id)

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
        if parent.parent_id is None:
            break
        parent = await models.Resource.objects.aget(id=parent.parent_id)

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

