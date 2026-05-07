import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, TestCase

from triplea.middleware import oauth_complete_process


class OAuthCompleteProcessTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        User = get_user_model()
        self.user = User.objects.create(username="mw_test_user", email="mw@test.com")

    def _make_response(self):
        return HttpResponse("OK")

    def _get_response(self, request):
        return self._make_response()

    def test_no_cookie_passes_through(self):
        request = self.factory.get("/some/path/")
        request.user = self.user
        middleware = oauth_complete_process(self._get_response)

        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"OK")

    def test_cookie_and_authenticated_user_redirects(self):
        request = self.factory.get("/some/path/")
        request.user = self.user
        request.COOKIES["oauth_redirect_next"] = "http://example.com/dashboard/"
        middleware = oauth_complete_process(self._get_response)

        response = middleware(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "http://example.com/dashboard/")

    def test_cookie_and_authenticated_user_clears_cookie(self):
        request = self.factory.get("/some/path/")
        request.user = self.user
        request.COOKIES["oauth_redirect_next"] = "http://example.com/dashboard/"
        middleware = oauth_complete_process(self._get_response)

        response = middleware(request)

        # Cookie must be deleted (max-age=0).
        self.assertIn("oauth_redirect_next", response.cookies)
        self.assertEqual(response.cookies["oauth_redirect_next"]["max-age"], 0)

    def test_cookie_and_anonymous_user_passes_through(self):
        request = self.factory.get("/some/path/")
        request.user = AnonymousUser()
        request.COOKIES["oauth_redirect_next"] = "http://example.com/dashboard/"
        middleware = oauth_complete_process(self._get_response)

        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"OK")

    def test_get_response_is_called_when_passing_through(self):
        called = []

        def get_response(req):
            called.append(True)
            return HttpResponse("through")

        request = self.factory.get("/")
        request.user = AnonymousUser()
        request.COOKIES["oauth_redirect_next"] = "http://example.com/"
        middleware = oauth_complete_process(get_response)

        middleware(request)

        self.assertTrue(called)
