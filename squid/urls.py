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
    path('ports/<int:port_id>/lists/', views.port_lists_view, name='port_lists'),

    # Logs de Acesso & Monitor em Tempo Real
    path('logs/', views.logs_view, name='logs'),
    path('logs/live-stream/', views.logs_live_stream_view, name='logs_live_stream'),
    path('logs/add-to-list/', views.log_add_to_list_view, name='log_add_to_list'),
    path('logs/cleanup/', views.logs_cleanup_view, name='logs_cleanup'),
    path('devices/save/', views.device_save_view, name='device_save'),
    path('devices/sync-ad/', views.sync_ad_devices_view, name='sync_ad_devices'),

    # Domínios Ocultos no Live Stream
    path('logs/hidden-domains/add/', views.hidden_domain_add_view, name='hidden_domain_add'),
    path('logs/hidden-domains/<int:hidden_id>/delete/', views.hidden_domain_delete_view, name='hidden_domain_delete'),
    path('logs/hidden-domains/list-json/', views.hidden_domain_list_json_view, name='hidden_domain_list_json'),

    # Testador de Políticas e Navegação
    path('tester/', views.proxy_tester_view, name='proxy_tester'),

    # Controle & Sincronização do Serviço Squid
    path('service/apply/', views.squid_apply_view, name='squid_apply'),
    path('service/restart/', views.squid_restart_view, name='squid_restart'),

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

    # Download do Certificado Raiz SSL (Público)
    path('certificate/download/', views.download_certificate_view, name='download_certificate'),

    # Portal Educacional / Página de Bloqueio Personalizada
    path('portal/<int:port_number>/', views.portal_view, name='portal'),
    path('portal-links/', views.portal_links_admin_view, name='portal_links_admin'),
    path('portal-links/create/', views.portal_link_create_view, name='portal_link_create'),
    path('portal-links/<int:link_id>/edit/', views.portal_link_edit_view, name='portal_link_edit'),
    path('portal-links/<int:link_id>/delete/', views.portal_link_delete_view, name='portal_link_delete'),
    path('portal-links/ports/<int:port_id>/toggle-portal/', views.portal_toggle_port_view, name='portal_toggle_port'),

    # Scripts PAC / WPAD (Proxy Auto-Configuration)
    path('pac/<int:port_number>.pac', views.pac_by_port_view, name='pac_by_port'),
    path('pac/<int:port_number>.dat', views.pac_by_port_view, name='pac_by_port_dat'),
    path('pac/<slug:port_slug>.pac', views.pac_by_slug_view, name='pac_by_slug'),
    path('proxy.pac', views.pac_global_view, name='pac_global'),
    path('wpad.dat', views.pac_global_view, name='wpad_global'),
]


