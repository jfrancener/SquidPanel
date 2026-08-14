from django.urls import path
from . import views

urlpatterns = [
    # Listagens
    path('whitelists/', views.whitelists_view, name='whitelists'),
    path('blacklists/', views.blacklists_view, name='blacklists'),

    # Gestão de Listas (White e Black)
    path('lists/create/', views.list_create_view, name='list_create'),
    path('lists/<int:list_id>/', views.list_detail_view, name='list_detail'),
    path('lists/<int:list_id>/edit/', views.list_edit_view, name='list_edit'),
    path('lists/<int:list_id>/delete/', views.list_delete_view, name='list_delete'),

    # Domínios dentro de uma lista
    path('lists/<int:list_id>/domains/<int:domain_id>/delete/', views.domain_delete_view, name='domain_delete'),
    path('lists/<int:list_id>/bulk-add/', views.domain_bulk_add_view, name='domain_bulk_add'),
]
