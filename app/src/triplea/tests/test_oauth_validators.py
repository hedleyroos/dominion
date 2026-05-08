from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from tests.base import BaseTestCase
from triplea.oauth_validators import CustomOAuth2Validator


def _make_oauth_request(user, client_id=1):
    request = MagicMock()
    request.user = user
    request.client.id = client_id
    return request


class GetAdditionalClaimsTestCase(BaseTestCase):
    def test_returns_required_claim_keys(self):
        validator = CustomOAuth2Validator()
        request = _make_oauth_request(self.owner, client_id=99)

        claims = validator.get_additional_claims(request)

        for key in ("given_name", "family_name", "name", "preferred_username", "email", "uuid", "domains", "api_key"):
            self.assertIn(key, claims)

    def test_first_call_creates_shadow_user(self):
        validator = CustomOAuth2Validator()
        request = _make_oauth_request(self.owner, client_id=100)

        validator.get_additional_claims(request)

        User = get_user_model()
        expected_username = f"{self.owner.username}%100"
        self.assertTrue(User.objects.filter(username=expected_username).exists())

    def test_shadow_user_has_correct_application_id(self):
        validator = CustomOAuth2Validator()
        request = _make_oauth_request(self.owner, client_id=101)

        validator.get_additional_claims(request)

        User = get_user_model()
        shadow = User.objects.get(username=f"{self.owner.username}%101")
        self.assertEqual(shadow.application_id, 101)

    def test_second_call_reuses_shadow_user(self):
        validator = CustomOAuth2Validator()
        request = _make_oauth_request(self.owner, client_id=102)

        claims_first = validator.get_additional_claims(request)
        claims_second = validator.get_additional_claims(request)

        self.assertEqual(claims_first["uuid"], claims_second["uuid"])

        User = get_user_model()
        expected_username = f"{self.owner.username}%102"
        self.assertEqual(User.objects.filter(username=expected_username).count(), 1)

    def test_claims_contain_user_name_fields(self):
        validator = CustomOAuth2Validator()
        request = _make_oauth_request(self.owner, client_id=103)

        claims = validator.get_additional_claims(request)

        self.assertEqual(claims["preferred_username"], self.owner.username)
        self.assertEqual(claims["email"], self.owner.email)

    def test_shadow_user_with_no_domain_roles_has_empty_domains(self):
        validator = CustomOAuth2Validator()
        # piet has no domain roles; shadow user starts fresh too.
        request = _make_oauth_request(self.piet, client_id=104)

        claims = validator.get_additional_claims(request)

        self.assertEqual(claims["domains"], [])


class ValidateSilentLoginTestCase(BaseTestCase):
    def test_authenticated_user_returns_true(self):
        validator = CustomOAuth2Validator()
        request = MagicMock()
        request.user = self.owner

        self.assertTrue(validator.validate_silent_login(request))

    def test_anonymous_user_returns_false(self):
        validator = CustomOAuth2Validator()
        request = MagicMock()
        request.user = AnonymousUser()

        self.assertFalse(validator.validate_silent_login(request))

    def test_missing_user_attribute_returns_false(self):
        validator = CustomOAuth2Validator()
        request = object()

        self.assertFalse(validator.validate_silent_login(request))
