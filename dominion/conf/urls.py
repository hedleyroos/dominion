"""dominion URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, re_path, include

from dominion.views import AuthorizationView, HealthView


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", HealthView.as_view(), name="health"),

    # Declare our own authorization view
    # TODO: should be in tripla.urls because leaky abstraction. Order of url patterns
    # matters though, so needs planning.
    path("o/authorize/", AuthorizationView.as_view(), name="authorize"),

    path('o/', include('oauth2_provider.urls', namespace='oauth2_provider')),

    path("oidc/", include("mozilla_django_oidc.urls")),
    path('', include('dominion.urls')),
    path('', include('dominion.registration.urls')),
]
