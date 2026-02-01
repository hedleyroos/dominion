import os
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from triplea.mail.models import EmailMessage


class ViewsTestCase(TestCase):
    def setUp(self):
        super().setUp()

    @override_settings(EMAIL_BACKEND="triplea.mail.backends.CeleryFileBackend", EMAIL_FILE_PATH="/tmp/triplea-test-messages/")
    def test_register_golden_path(self):
        # First page
        url = reverse("django_registration_register")
        response = self.client.get(url)
        self.assertContains(response, "Username:")

        # Success page
        response = self.client.post(
            url, {"username": "koos", "email": "koos@aaa.com", "password1": "local123", "password2": "local123"},
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request['PATH_INFO'], "/accounts/register/complete/")

        # Check mail, extract link and follow
        obj = EmailMessage.objects.all().last()
        body = obj.unpickled.body
        link = "/" + re.search(r"testserver/([^'\"\n >]+)", body).group(1)
        response = self.client.get(link, follow=True)
        self.assertEqual(response.status_code, 200)

        # Confirm account is active and activation_date is set
        user = get_user_model().objects.get(email="koos@aaa.com")
        self.failUnless(user.is_active)
        self.failUnless(user.activation_date)

        # Sign in
        url = reverse("login")
        response = self.client.post(url, {"username": "koos", "password": "local123"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.failUnless(response.context['user'].is_authenticated)

