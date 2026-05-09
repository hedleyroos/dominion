from django.urls import path

from dominion import views


urlpatterns = [
    path('', views.HomeView.as_view(), name="home"),
]
