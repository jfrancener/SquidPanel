from django.urls import path
from . import views

urlpatterns = [
    # Whitelists
    path('whitelists/', views.whitelists_view, name='whitelists'),
    path('whitelists/create/', views.whitelist_create_view, name='whitelist_create'),
    path('whitelists/<int:list_id>/', views.whitelist_detail_view, name='whitelist_detail'),
    path('whitelists/<int:list_id>/edit/', views.whitelist_edit_view, name='whitelist_edit'),
    path('whitelists/<int:list_id>/delete/', views.whitelist_delete_view, name='whitelist_delete'),
    
    # Domínios
    path('whitelists/<int:list_id>/domains/<int:domain_id>/delete/', views.domain_delete_view, name='domain_delete'),
    path('whitelists/<int:list_id>/bulk-add/', views.domain_bulk_add_view, name='domain_bulk_add'),
]
