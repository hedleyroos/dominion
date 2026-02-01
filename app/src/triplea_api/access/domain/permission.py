from uuid import UUID

from triplea.models import Domain
from triplea.utils import user_has_permission_for_domain


DOMAIN_NOT_FOUND = "Domain not found for id: {}."


def get(user_id, domain_id, permission, user, token_info, **kwargs):
    user = token_info["user"]

    # Connexion doesn't validate UUID's yet
    try:
        UUID(user_id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % user_id}, 400
    try:
        UUID(domain_id)
    except ValueError:
        return {"message": "%s is not a valid UUID." % domain_id}, 400

    try:
        domain = Domain.objects.get(id=domain_id)
    except Domain.DoesNotExist:
        domain = None
    if domain is None:
        # 400 because this is technically a bad request
        return {"message": DOMAIN_NOT_FOUND.format(domain_id)}, 400

    # Only users with domain check_access permission may perform this query
    if not user_has_permission_for_domain(user.id, "check_access", domain.id):
        return {"message": "You require the `Check access` permission on the domain to perform this check."}, 403

    if user_has_permission_for_domain(user_id, permission, domain_id):
        return {"result": True}, 200

    return {"result": False}, 200
