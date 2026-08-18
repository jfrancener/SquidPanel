from django.urls import path
from . import views

urlpatterns = [
    # Dashboard Principal do Gestor
    path('', views.gestor_dashboard_view, name='gestor_dashboard'),

    # Endpoints AJAX de Controle e Sincronização em Tempo Real
    path('api/ports/<int:port_id>/set-mode/', views.gestor_set_port_mode_api, name='gestor_set_port_mode'),
    path('api/logs/live-stream/', views.gestor_live_stream_api, name='gestor_live_stream'),

    # Módulo de Agendamentos de Salas
    path('schedules/', views.gestor_schedules_view, name='gestor_schedules'),
    path('schedules/create/', views.gestor_schedule_create_view, name='gestor_schedule_create'),
    path('schedules/<int:schedule_id>/edit/', views.gestor_schedule_edit_view, name='gestor_schedule_edit'),
    path('schedules/<int:schedule_id>/toggle/', views.gestor_schedule_toggle_view, name='gestor_schedule_toggle'),
    path('schedules/<int:schedule_id>/delete/', views.gestor_schedule_delete_view, name='gestor_schedule_delete'),
    path('schedules/api/run-check/', views.gestor_schedule_run_check_api, name='gestor_schedule_run_check'),
]
