from connexion import request
from django.conf import settings


async def paginate_result(queryset, serializer_class):
    """Simple Rest style paginator.
    """
    items_per_page = settings.TRIPLEA_API_RESULTS_PER_PAGE
    count = await queryset.acount()
    max_pages = int(count / items_per_page) + 1

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

    previous = max(page - 1, 1)
    next_page = min(page + 1, max_pages)

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

    previous_url = base_url + str(previous)
    next_url = base_url + str(next_page)

    result = {
        "count": count,
    }
    if previous != page:
        result["previous"] = previous_url
    if next_page != max_pages:
        result["next"] = next_url

    serializer = serializer_class(queryset[(page-1)*items_per_page:page*items_per_page], many=True)
    result["results"] = await serializer.adata

    return result


