from django.urls import path
from . import views

urlpatterns = [
    # Grupos e Portas
    path('groups/', views.groups_view, name='groups'),
    path('groups/create/', views.group_create_view, name='group_create'),
    path('groups/<int:group_id>/edit/', views.group_edit_view, name='group_edit'),
    path('groups/<int:group_id>/delete/', views.group_delete_view, name='group_delete'),
    
    # Portas / Salas
    path('ports/check/', views.check_port_availability_view, name='check_port_availability'),
    path('groups/<int:group_id>/ports/create/', views.port_create_view, name='port_create'),
    path('ports/<int:port_id>/edit/', views.port_edit_view, name='port_edit'),
    path('ports/<int:port_id>/delete/', views.port_delete_view, name='port_delete'),
    path('ports/<int:port_id>/toggle-status/', views.port_toggle_status_view, name='port_toggle_status'),

    # Logs de Acesso & Monitor em Tempo Real
    path('logs/', views.logs_view, name='logs'),
    path('logs/live-stream/', views.logs_live_stream_view, name='logs_live_stream'),
    path('logs/add-to-list/', views.log_add_to_list_view, name='log_add_to_list'),
    path('logs/cleanup/', views.logs_cleanup_view, name='logs_cleanup'),
    path('devices/save/', views.device_save_view, name='device_save'),

    # Listagens White e Black
    path('whitelists/', views.whitelists_view, name='whitelists'),
    path('blacklists/', views.blacklists_view, name='blacklists'),

    # Gestão de Listas
    path('lists/create/', views.list_create_view, name='list_create'),
    path('lists/<int:list_id>/', views.list_detail_view, name='list_detail'),
    path('lists/<int:list_id>/edit/', views.list_edit_view, name='list_edit'),
    path('lists/<int:list_id>/delete/', views.list_delete_view, name='list_delete'),

    # Domínios dentro de uma lista
    path('lists/<int:list_id>/domains/<int:domain_id>/delete/', views.domain_delete_view, name='domain_delete'),
    path('lists/<int:list_id>/bulk-add/', views.domain_bulk_add_view, name='domain_bulk_add'),
]
