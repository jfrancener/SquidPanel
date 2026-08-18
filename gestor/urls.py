from django.urls import path
from . import views

urlpatterns = [
    # Dashboard Principal do Gestor
    path('', views.gestor_dashboard_view, name='gestor_dashboard'),

    # Endpoints AJAX de Controle e Sincronização em Tempo Real
    path('api/ports/<int:port_id>/set-mode/', views.gestor_set_port_mode_api, name='gestor_set_port_mode'),
    path('api/logs/live-stream/', views.gestor_live_stream_api, name='gestor_live_stream'),
]
