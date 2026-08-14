from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from dashboard import views as dashboard_views

urlpatterns = [
    # Favicon para eliminar 404
    path('favicon.ico', RedirectView.as_view(url='/static/favicon.svg', permanent=True)),

    # App Users (Autenticação e Gestão de Usuários)
    path('', include('users.urls')),

    # App Dashboard (Painel Principal e Configurações)
    path('', dashboard_views.dashboard_view, name='dashboard'),
    path('settings/general/', dashboard_views.settings_general_view, name='settings_general'),
    path('settings/session/', dashboard_views.settings_session_view, name='settings_session'),
]
