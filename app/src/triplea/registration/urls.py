from django.urls import path, re_path, include
from django.views.generic.base import TemplateView

from triplea.registration import views


urlpatterns = [
    path('accounts/register/',
        views.RegistrationView.as_view(),
        name='django_registration_register',
    ),
    path('accounts/', include('django_registration.backends.activation.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
]
