from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from dashboard import views as dashboard_views
from squid import views as squid_views

urlpatterns = [
    # Favicon para eliminar 404
    path('favicon.ico', RedirectView.as_view(url='/static/favicon.svg', permanent=True)),

    # App Users (Autenticação e Gestão de Usuários)
    path('', include('users.urls')),

    # App Squid (Proxy, Whitelists e Regras)
    path('proxy/', include('squid.urls')),

    # Download Direto do Certificado SSL Raiz
    path('certificate/download/', squid_views.download_certificate_view, name='root_download_certificate'),

    # Portal Educacional / Página de Bloqueio Personalizada
    path('portal/<int:port_number>/', squid_views.portal_view, name='root_portal'),

    # Scripts PAC / WPAD Globais e por Porta (Padrão de Mercado)
    path('proxy.pac', squid_views.pac_global_view, name='root_proxy_pac'),
    path('wpad.dat', squid_views.pac_global_view, name='root_wpad_dat'),
    path('<int:port_number>.pac', squid_views.pac_by_port_view, name='root_port_pac'),
    path('<int:port_number>.dat', squid_views.pac_by_port_view, name='root_port_dat'),
    path('pac/<int:port_number>.pac', squid_views.pac_by_port_view, name='root_pac_by_port'),
    path('pac/<slug:port_slug>.pac', squid_views.pac_by_slug_view, name='root_pac_by_slug'),

    # App Dashboard (Painel Principal e Configurações)
    path('', dashboard_views.dashboard_view, name='dashboard'),
    path('api/system-metrics/', dashboard_views.system_metrics_api_view, name='api_system_metrics'),
    path('settings/general/', dashboard_views.settings_general_view, name='settings_general'),
    path('settings/session/', dashboard_views.settings_session_view, name='settings_session'),
    path('settings/logs/', dashboard_views.settings_logs_view, name='settings_logs'),
    path('settings/export/', dashboard_views.settings_export_view, name='settings_export'),
    path('settings/export/config/xml/', dashboard_views.export_config_xml_view, name='export_config_xml'),
    path('settings/export/logs/txt/', dashboard_views.export_logs_txt_view, name='export_logs_txt'),
]
