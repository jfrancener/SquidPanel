from django.contrib import admin
from django.urls import path
from dashboard import views

urlpatterns = [
    # Autenticação
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Painel Principal
    path('', views.dashboard_view, name='dashboard'),

    # Configurações com Sublinks
    path('settings/general/', views.settings_general_view, name='settings_general'),
    path('settings/session/', views.settings_session_view, name='settings_session'),

    # Gestão de Usuários e Permissões (RBAC)
    path('users/', views.user_list_view, name='user_list'),
    path('users/create/', views.user_create_view, name='user_create'),
    path('users/<int:user_id>/edit/', views.user_edit_view, name='user_edit'),
    path('users/<int:user_id>/toggle-status/', views.user_toggle_status_view, name='user_toggle_status'),
    path('users/<int:user_id>/delete/', views.user_delete_view, name='user_delete'),
]
