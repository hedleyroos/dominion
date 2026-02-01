from django.conf import settings


def paginate_result(queryset, serializer_class, request):
    """Simple Rest style paginator.
    """
    items_per_page = settings.TRIPLEA_API_RESULTS_PER_PAGE
    count = queryset.count()
    max_pages = int(count / items_per_page) + 1

    # No validation on invalid page. Just fix it.
    try:
        page = int(request.values.get("page", 1))
    except ValueError:
        page = 1
    if page < 1:
        page = 1
    if page > max_pages:
        page = max_pages

    previous = max(page - 1, 1)
    next = min(page + 1, max_pages)

    # There are certainly better ways to do this. See what urllib offers.
    if "?" in request.url:
        base_url, querystring = request.url.split("?")
    else:
        base_url = request.url

    i = 0
    for k, v in request.values.items():
        if k != "page":
            if i == 0:
                base_url += "?"
            else:
                base_url += "&"
            base_url = base_url + k + "=" + str(v)
    if "?" not in base_url:
        base_url += "?page="
    else:
        base_url + "&page="
    previous_url = base_url + str(previous)
    next_url = base_url + str(next)

    result = {
        "count": count,
    }
    if previous != page:
        result["previous"] = previous_url
    if next != max_pages:
        result["next"] = next_url

    result["results"] = serializer_class(queryset[(page-1)*items_per_page:page*items_per_page], many=True).data

    return result

