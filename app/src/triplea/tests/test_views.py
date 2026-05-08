from django.test import TestCase
from django.urls import reverse


class HealthViewTest(TestCase):
    def test_healthz_returns_200(self):
        response = self.client.get(reverse("health"))
        assert response.status_code == 200
        assert response.content == b"ok"


class HomeViewTest(TestCase):
    def test_home_view_returns_200(self):
        response = self.client.get(reverse("home"))
        assert response.status_code == 200
