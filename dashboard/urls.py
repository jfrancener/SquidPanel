from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('action/', views.domain_action, name='domain_action'),
    path('sync/', views.save_and_sync, name='save_and_sync'),
    path('sync-github/', views.sync_from_github, name='sync_from_github'),
]
