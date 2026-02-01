from django.urls import path

from triplea import views


urlpatterns = [
    path('', views.HomeView.as_view(), name="home"),
]
