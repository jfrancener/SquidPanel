from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import RedirectView
from django.conf import settings
from django.views.static import serve
from dashboard import views as dashboard_views
from squid import views as squid_views

urlpatterns = [
    # Favicon para eliminar 404
    path('favicon.ico', RedirectView.as_view(url='/static/favicon.svg', permanent=True)),

    # Página Inicial Genérica Minimalista (Root URL http://10.40.88.5/)
    path('', dashboard_views.generic_home_view, name='home'),

    # Admin Django Padrão (Mudado de /admin/ para /django_admin/)
    path('django_admin/', admin.site.urls),

    # Painel Administrativo do SquidPanel & Autenticação (Apenas em /adminsp/)
    path('adminsp/', dashboard_views.dashboard_view, name='dashboard'),
    path('adminsp/', include('users.urls')),

    # Configurações do Sistema no /adminsp/
    path('adminsp/settings/general/', dashboard_views.settings_general_view, name='settings_general'),
    path('adminsp/settings/session/', dashboard_views.settings_session_view, name='settings_session'),
    path('adminsp/settings/logs/', dashboard_views.settings_logs_view, name='settings_logs'),
    path('adminsp/settings/export/', dashboard_views.settings_export_view, name='settings_export'),
    path('adminsp/settings/export/config/xml/', dashboard_views.export_config_xml_view, name='export_config_xml'),
    path('adminsp/settings/export/logs/txt/', dashboard_views.export_logs_txt_view, name='export_logs_txt'),
    path('adminsp/api/system-metrics/', dashboard_views.system_metrics_api_view, name='api_system_metrics'),

    # App Squid (Proxy, Whitelists e Regras)
    path('proxy/', include('squid.urls')),

    # Download Direto do Certificado SSL Raiz
    path('certificate/download/', squid_views.download_certificate_view, name='root_download_certificate'),

    # Portal Educacional / Página de Bloqueio Personalizada por Slug ou Número de Porta
    path('portal/', squid_views.portal_view, {'port_identifier': 'ead'}, name='root_portal_default'),
    path('portal/<str:port_identifier>/', squid_views.portal_view, name='root_portal'),

    # Scripts PAC / WPAD Globais e por Porta (Padrão de Mercado)
    path('proxy.pac', squid_views.pac_global_view, name='root_proxy_pac'),
    path('wpad.dat', squid_views.pac_global_view, name='root_wpad_dat'),
    path('<int:port_number>.pac', squid_views.pac_by_port_view, name='root_port_pac'),
    path('<int:port_number>.dat', squid_views.pac_by_port_view, name='root_port_dat'),
    path('pac/<int:port_number>.pac', squid_views.pac_by_port_view, name='root_pac_by_port'),
    path('pac/<slug:port_slug>.pac', squid_views.pac_by_slug_view, name='root_pac_by_slug'),
]

# Servir arquivos estáticos mesmo com DEBUG = False
urlpatterns += [
    re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATICFILES_DIRS[0] if (hasattr(settings, 'STATICFILES_DIRS') and settings.STATICFILES_DIRS) else settings.STATIC_ROOT}),
]
