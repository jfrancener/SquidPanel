from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.db import models

from .models import (
    SystemSetting,
    ProxyGroup,
    ProxyPort,
    DomainRule,
    UserProfile
)

# ==========================================
# 1. DASHBOARD PRINCIPAL
# ==========================================

@login_required
def dashboard_view(request):
    """
    Painel de controle principal exibindo métricas, status das portas e resumo de grupos autorizados.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    # Filtra grupos e portas conforme o perfil do usuário (RBAC)
    if profile.is_admin:
        groups = ProxyGroup.objects.prefetch_related('ports').filter(is_active=True)
        ports = ProxyPort.objects.select_related('group').filter(is_active=True).order_by('port_number')
    else:
        # Usuário comum (Professor / Coordenador) visualiza apenas os grupos/portas atribuídos
        user_groups = profile.allowed_groups.filter(is_active=True)
        user_ports = profile.allowed_ports.filter(is_active=True)
        
        ports = ProxyPort.objects.filter(
            models.Q(id__in=user_ports.values_list('id', flat=True)) |
            models.Q(group__in=user_groups)
        ).distinct().select_related('group').order_by('port_number')
        
        groups = ProxyGroup.objects.filter(
            models.Q(id__in=user_groups.values_list('id', flat=True)) |
            models.Q(ports__in=ports)
        ).distinct().prefetch_related('ports')

    # Métricas para os cards estatísticos
    total_ports = ports.count()
    allowed_ports_count = ports.filter(current_status='ALLOWED').count()
    whitelist_ports_count = ports.filter(current_status='WHITELIST').count()
    blocked_ports_count = ports.filter(current_status='BLOCKED').count()
    total_rules = DomainRule.objects.count()

    return render(request, 'dashboard/index.html', {
        'profile': profile,
        'groups': groups,
        'ports': ports,
        'total_ports': total_ports,
        'allowed_ports_count': allowed_ports_count,
        'whitelist_ports_count': whitelist_ports_count,
        'blocked_ports_count': blocked_ports_count,
        'total_rules': total_rules,
        'active_menu': 'dashboard'
    })


# ==========================================
# 2. MÓDULO DE CONFIGURAÇÕES (GERAL & SESSÃO)
# ==========================================

@login_required
def settings_general_view(request):
    """
    Sublink: Parâmetros Gerais do Servidor (Apenas Admin).
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado: apenas Administradores de TI podem alterar as configurações.")

    if request.method == 'POST':
        server_name = request.POST.get('server_name', 'SquidPanel').strip()
        server_dns = request.POST.get('server_dns', '1.1.1.1, 8.8.8.8').strip()
        admin_email = request.POST.get('admin_email', '').strip()

        SystemSetting.set_value('server_name', server_name, 'Nome de exibição do servidor')
        SystemSetting.set_value('server_dns', server_dns, 'Servidores DNS de consulta')
        SystemSetting.set_value('admin_email', admin_email, 'E-mail do Administrador de TI')

        messages.success(request, 'Parâmetros gerais do servidor atualizados com sucesso!')
        return redirect('settings_general')

    server_name = SystemSetting.get_value('server_name', 'SquidPanel - Proxy Server')
    server_dns = SystemSetting.get_value('server_dns', '1.1.1.1, 8.8.8.8')
    admin_email = SystemSetting.get_value('admin_email', 'admin@local')

    return render(request, 'settings/general.html', {
        'profile': profile,
        'server_name': server_name,
        'server_dns': server_dns,
        'admin_email': admin_email,
        'active_menu': 'settings_general'
    })


@login_required
def settings_session_view(request):
    """
    Sublink: Configuração de Sessão & Segurança (Apenas Admin).
    Permite parametrizar dinamicamente os tempos de inatividade e validade de sessão.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado: apenas Administradores de TI podem alterar as configurações.")

    if request.method == 'POST':
        try:
            timeout_minutes = int(request.POST.get('session_timeout_minutes', 10))
            remember_days = int(request.POST.get('session_remember_days', 7))
            max_login_attempts = int(request.POST.get('max_login_attempts', 5))
            expire_browser_close = request.POST.get('expire_browser_close') == 'on'

            timeout_minutes = max(1, min(240, timeout_minutes))
            remember_days = max(1, min(30, remember_days))

            SystemSetting.set_value('session_timeout_minutes', timeout_minutes, 'Tempo de inatividade padrão (minutos)')
            SystemSetting.set_value('session_remember_days', remember_days, 'Validade da sessão Lembrar-me (dias)')
            SystemSetting.set_value('max_login_attempts', max_login_attempts, 'Máximo de tentativas de login')
            SystemSetting.set_value('expire_browser_close', 'true' if expire_browser_close else 'false', 'Encerrar sessão ao fechar navegador')

            messages.success(request, 'Configurações de Sessão e Segurança atualizadas com sucesso!')
            return redirect('settings_session')
        except ValueError:
            messages.error(request, 'Valores numéricos inválidos fornecidos.')

    timeout_minutes = SystemSetting.get_value('session_timeout_minutes', 10)
    remember_days = SystemSetting.get_value('session_remember_days', 7)
    max_login_attempts = SystemSetting.get_value('max_login_attempts', 5)
    expire_browser_close = SystemSetting.get_value('expire_browser_close', 'true') == 'true'

    return render(request, 'settings/session.html', {
        'profile': profile,
        'timeout_minutes': timeout_minutes,
        'remember_days': remember_days,
        'max_login_attempts': max_login_attempts,
        'expire_browser_close': expire_browser_close,
        'active_menu': 'settings_session'
    })
