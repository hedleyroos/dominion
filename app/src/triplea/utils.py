from asgiref.sync import sync_to_async

from triplea import models


# The queries are complex because the role and permission mappings on domain and resources are sparse to avoid
# database bloat. Resources live within resources, and the top level resource lives in a domain, and
# domains live within domains. This module therefore has a lot of recursive functions.


async def user_has_role_for_domain(user_id, role_code, domain_id):
    if await models.UserDomainRole.objects.filter(user__id=user_id, role__code=role_code, domain__id=domain_id).aexists():
        return True

    domain = await models.Domain.objects.aget(id=domain_id)
    if domain.parent_id:
        return await user_has_role_for_domain(user_id, role_code, domain.parent_id)

    return False


async def domain_has_permission_for_role(domain_id, permission_code, role_code):

    if await models.DomainRolePermission.objects.filter(domain__id=domain_id, role__code=role_code, permission__code=permission_code).aexists():
        return True

    # Check acquisition. Only if an item exists and specifically opts out of inherit
    # do we return false.
    cannot_inherit = await models.DomainPermission.objects.filter(
        domain__id=domain_id, permission__code=permission_code, inherit=False
    ).aexists()
    if cannot_inherit:
        return False

    # We can inherit. Traverse upwards.
    domain = await models.Domain.objects.aget(id=domain_id)
    if domain.parent_id:
        return await domain_has_permission_for_role(domain.parent_id, permission_code, role_code)


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
    domain = await models.Domain.objects.select_related("parent").aget(id=domain_id)
    if domain.parent_id is not None:
        return await _user_has_permission_for_domain(user_id, permission_code, domain.parent_id, domain_ids+[domain.parent_id])

    return False


async def user_has_permission_for_domain(user_id, permission_code, domain_id):
    domain_ids = [domain_id]
    return await _user_has_permission_for_domain(user_id, permission_code, domain_id, domain_ids)


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
        return await _user_has_permission_for_resource(user_id, permission_code, resource.parent_id, resource_ids+[resource.parent_id])
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
    resource_ids = [resource_id]
    return await _user_has_permission_for_resource(user_id, permission_code, resource_id, resource_ids)


async def get_user_domains(user):
    """Return all domains on which the user has any roles, both explicit and inherited.
    """
    domain_ids = list(set([
        o.hex async for o in models.UserDomainRole.objects.filter(user=user).values_list("domain_id", flat=True)
    ]))
    if domain_ids:
        domain_ids_str = "'" + "','".join(domain_ids) + "'"
        table_name = "triplea_domain"
        query = f"""
        WITH RECURSIVE children (id) AS (
        SELECT {table_name}.id FROM {table_name} WHERE id in ({domain_ids_str})
          UNION ALL
        SELECT {table_name}.id FROM children, {table_name}
          WHERE {table_name}.parent_id = children.id
        )
        SELECT {table_name}.id
        FROM {table_name}, children WHERE children.id = {table_name}.id
        """
        recursive_ids = await sync_to_async(lambda: [o.id for o in models.Domain.objects.raw(query)])()
        return models.Domain.objects.filter(
            id__in=domain_ids + recursive_ids
        ).order_by("title")
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

    # Inherit defaults to true
    for item in found:
        if not hasattr(item, "inherit"):
            item.inherit = True

    return sorted(found, key=lambda item: item.code)


async def domain_roles_permissions_mapping(domain):
    """Mapping structure used by views.
    """
    rows = []
    roles = await get_domain_roles(domain)
    for permission in await get_domain_permissions(domain):
        row = [permission]
        for role in roles:
            active = await models.DomainRolePermission.objects.filter(domain=domain, role=role, permission=permission).aexists()
            row.append({"permission": permission, "active": active, "role": role})
        rows.append(row)
    return rows


async def get_resource_roles(resource):
    found = []
    parent = resource
    while parent is not None:
        async for obj in models.ResourceRolePermission.objects.filter(resource=resource).select_related("role"):
            if obj.role not in found:
                found.append(obj.role)
        parent = resource.parent

    domain = await models.Domain.objects.aget(id=resource.domain_id)
    for role in await get_domain_roles(domain):
        if role not in found:
            found.append(role)

    return sorted(found, key=lambda item: item.code)


async def get_resource_permissions(resource):
    found = []
    parent = resource
    while parent is not None:
        async for obj in models.ResourcePermission.objects.filter(resource=resource).select_related("permission"):
            if obj.permission not in found:
                # We cheat a bit by gluing inherit on the permission
                obj.permission.inherit = obj.inherit
                found.append(obj.permission)
        async for obj in models.ResourceRolePermission.objects.filter(resource=resource).select_related("permission"):
            if obj.permission not in found:
                found.append(obj.permission)
        parent = resource.parent

    domain = await models.Domain.objects.aget(id=resource.domain_id)
    for permission in await get_domain_permissions(domain):
        if permission not in found:
            found.append(permission)

    # Inherit defaults to true
    for item in found:
        if not hasattr(item, "inherit"):
            item.inherit = True

    return sorted(found, key=lambda item: item.code)


async def resource_roles_permissions_mapping(resource):
    """Mapping structure used by views.
    """
    rows = []
    roles = await get_resource_roles(resource)
    for permission in await get_resource_permissions(resource):
        row = [permission]
        for role in roles:
            active = await models.ResourceRolePermission.objects.filter(resource=resource, role=role, permission=permission).aexists()
            row.append({"permission": permission, "active": active, "role": role})
        rows.append(row)
    return rows

