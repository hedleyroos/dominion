"""Introspection endpoint: "what can user X do on domain Y".

Returns the full set of permission codes the user effectively holds on the domain
(direct + inherited), rather than a single boolean check. Reuses the cached
``user_has_permission_for_domain`` resolver, so the per-permission checks share the
request-scoped and cross-request caches.
"""

from uuid import UUID

from django.db.models import Q

from dominion.models import Domain, Permission
from dominion.utils import user_has_permission_for_domain


DOMAIN_NOT_FOUND = "Domain not found for id: {}."


async def get(user_id, domain_id, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    for value in (user_id, domain_id):
        try:
            UUID(value)
        except ValueError:
            return {"message": "%s is not a valid UUID." % value}, 400

    domain = await Domain.objects.select_related("root").filter(id=domain_id).afirst()
    if domain is None:
        return {"message": DOMAIN_NOT_FOUND.format(domain_id)}, 404

    # Same gate as the single-permission check: the caller must be allowed to inspect
    # access on this domain.
    if not await user_has_permission_for_domain(user.id, "check_access", domain.id):
        return {
            "message": "You require the `Check access` permission on the domain to perform this check."
        }, 403

    # Candidate permissions: global (system) permissions plus any scoped to this
    # domain's root. Check each through the cached resolver and collect the granted ones.
    root_id = domain.root_id or domain.id
    candidate_codes = [
        code
        async for code in Permission.objects.filter(
            Q(domain__isnull=True) | Q(domain_id=root_id)
        ).values_list("code", flat=True)
    ]

    granted = [
        code
        for code in sorted(candidate_codes)
        if await user_has_permission_for_domain(user_id, code, domain_id)
    ]

    return {"user": user_id, "domain": domain_id, "permissions": granted}, 200
