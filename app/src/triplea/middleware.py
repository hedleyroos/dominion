from django.http import HttpResponseRedirect


def oauth_complete_process(get_response):
    """If a user was directed to us as part of an OAuth process then the user may have
    forgotten eg. his password. That may kick off entire workflows, and we can't
    easily use the "next" parameter to remember where to eventually redirect to. Use
    a cookie.
    """

    def middleware(request):
        cookies = request.COOKIES
        redirect_next = cookies.get("oauth_redirect_next", None)
        if not redirect_next:
            return get_response(request)

        if request.user.is_authenticated:
            response = HttpResponseRedirect(redirect_next)
            response.delete_cookie("oauth_redirect_next")
            return response

        return get_response(request)

    return middleware
