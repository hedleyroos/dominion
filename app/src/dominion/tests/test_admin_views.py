from django.contrib.auth import get_user_model
from django.test import TestCase

from tests.base import BaseTestCase
from dominion import models


class AdminViewsTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.staff_user = User.objects.create(
            username="staffadmin", email="staffadmin@test.com", is_staff=True, is_superuser=True
        )
        self.client.force_login(self.staff_user)

    # --- Domain manage-roles-permissions view ---

    def test_domain_view_get_returns_200(self):
        url = f"/admin/dominion/domain/{self.domaina.id}/manage-roles-permissions/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_domain_view_get_contains_mapping_in_context(self):
        url = f"/admin/dominion/domain/{self.domaina.id}/manage-roles-permissions/"
        response = self.client.get(url)
        self.assertIn("mapping", response.context)
        self.assertIsInstance(response.context["mapping"], list)

    def test_domain_view_post_redirects_on_success(self):
        permission_read = models.Permission.objects.get(code="read")
        url = f"/admin/dominion/domain/{self.domaina.id}/manage-roles-permissions/"
        data = {f"permission_{permission_read.id}_on": "on"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

    def test_domain_view_requires_staff_login(self):
        self.client.logout()
        url = f"/admin/dominion/domain/{self.domaina.id}/manage-roles-permissions/"
        response = self.client.get(url)
        # Django admin redirects unauthenticated requests to the login page.
        self.assertEqual(response.status_code, 302)

    # --- Resource manage-roles-permissions view ---

    def test_resource_view_get_returns_200(self):
        url = f"/admin/dominion/resource/{self.domaina_resourcea.id}/manage-roles-permissions/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_resource_view_get_contains_mapping_in_context(self):
        url = f"/admin/dominion/resource/{self.domaina_resourcea.id}/manage-roles-permissions/"
        response = self.client.get(url)
        self.assertIn("mapping", response.context)
        self.assertIsInstance(response.context["mapping"], list)

    def test_resource_view_post_redirects_on_success(self):
        url = f"/admin/dominion/resource/{self.domaina_resourcea.id}/manage-roles-permissions/"
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 302)
