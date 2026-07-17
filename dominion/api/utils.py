import math

from connexion import request
from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import HttpRequest
from django_ratelimit.core import is_ratelimited


async def check_rate_limit(group: str, rate: str) -> bool:
    """Return True if the current request is rate-limited.

    Builds a minimal Django HttpRequest from the Connexion/Starlette request
    so django-ratelimit can extract the client IP via the 'ip' key.
    """
    starlette_request = request._starlette_request
    fake_request = HttpRequest()
    client = starlette_request.client
    fake_request.META["REMOTE_ADDR"] = client.host if client else "127.0.0.1"
    fake_request.method = starlette_request.method
    return await sync_to_async(is_ratelimited)(
        fake_request,
        group=group,
        key="ip",
        rate=rate,
        method=fake_request.method,
        increment=True,
    )


async def paginate_result(queryset, serializer_class):
    """Simple Rest style paginator.
    """
    items_per_page = settings.DOMINION_API_RESULTS_PER_PAGE
    count = await queryset.acount()
    max_pages = max(1, math.ceil(count / items_per_page))

    starlette_request = request._starlette_request
    # No validation on invalid page. Just fix it.
    try:
        page = int(starlette_request.query_params.get("page", 1))
    except ValueError:
        page = 1
    if page < 1:
        page = 1
    if page > max_pages:
        page = max_pages

    base_url = str(starlette_request.url)
    if "?" in base_url:
        base_url = base_url.split("?")[0]

    i = 0
    for k, v in starlette_request.query_params.items():
        if k != "page":
            if i == 0:
                base_url += "?"
            else:
                base_url += "&"
            base_url = base_url + k + "=" + str(v)
            i += 1

    if "?" not in base_url:
        base_url += "?page="
    else:
        base_url += "&page="

    previous_url = base_url + str(page - 1)
    next_url = base_url + str(page + 1)

    result = {
        "count": count,
    }
    if page > 1:
        result["previous"] = previous_url
    if page < max_pages:
        result["next"] = next_url

    serializer = serializer_class(queryset[(page-1)*items_per_page:page*items_per_page], many=True)
    result["results"] = await serializer.adata

    return result


