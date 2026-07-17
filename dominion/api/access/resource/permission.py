from uuid import UUID

from dominion.models import Resource
from dominion.utils import user_has_permission_for_domain, user_has_permission_for_resource


RESOURCE_NOT_FOUND = "Resource not found for id: {}."


async def get(user_id, resource_id, permission, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(user_id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % user_id}, 400
    try:
        UUID(resource_id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % resource_id}, 400

    resource = await Resource.objects.select_related("domain").filter(id=resource_id).afirst()
    if resource is None:
        return {"message": RESOURCE_NOT_FOUND.format(resource_id)}, 404

    # Only users with domain check_access permission may perform this query
    if not await user_has_permission_for_domain(user.id, "check_access", resource.domain.id):
        return {"message": "You require the `Check access` permission on the resource's domain to perform this check."}, 403

    if await user_has_permission_for_resource(user_id, permission, resource_id):
        return {"result": True}, 200

    return {"result": False}, 200

