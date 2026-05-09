from django.contrib.auth.views import LoginView
from django.urls import path, re_path, include
from django.views.generic.base import TemplateView
from django_ratelimit.decorators import ratelimit

from dominion.registration import views


urlpatterns = [
    path('accounts/register/',
        views.RegistrationView.as_view(),
        name='django_registration_register',
    ),
    path('accounts/login/',
        ratelimit(key='ip', rate='10/5m', block=True)(LoginView.as_view()),
        name='login',
    ),
    path('accounts/', include('django_registration.backends.activation.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
]
