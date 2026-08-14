import os
import time
import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.utils.text import slugify

from .models import (
    SystemSetting,
    ProxyGroup,
    ProxyPort,
    RoomSchedule,
    DomainRule,
    UserProfile
)

# ==========================================
# 1. AUTENTICAÇÃO E SESSÃO
# ==========================================

def login_view(request):
    """
    Tela de login personalizada com controle de sessão persistente ('remember_me')
    e detecção de encerramento por inatividade.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    timeout_alert = request.GET.get('timeout') == '1'
    next_url = request.GET.get('next', 'dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        remember_me = request.POST.get('remember_me') == 'on'

        user = authenticate(request, username=username, password=password)
        if user is not None:
            if not user.is_active:
                messages.error(request, 'Esta conta está desativada. Contate o Administrador de TI.')
                return render(request, 'auth/login.html', {'next': next_url, 'timeout_alert': False})

            login(request, user)

            # Garante que o usuário possua UserProfile
            profile, _ = UserProfile.objects.get_or_create(user=user)

            # Configura a expiração da sessão com base na preferência do usuário e nas configurações do sistema
            if remember_me:
                request.session['remember_me'] = True
                try:
                    remember_days = int(SystemSetting.get_value('session_remember_days', 7))
                except (ValueError, TypeError):
                    remember_days = 7
                # Define expiração em segundos (ex: 7 dias)
                request.session.set_expiry(remember_days * 86400)
            else:
                request.session['remember_me'] = False
                # 0 = Expira quando o navegador é fechado
                request.session.set_expiry(0)
                request.session['last_activity'] = time.time()

            return redirect(next_url if next_url and next_url != '/' else 'dashboard')
        else:
            messages.error(request, 'Usuário ou senha incorretos. Verifique suas credenciais.')

    remember_days = SystemSetting.get_value('session_remember_days', 7)
    return render(request, 'auth/login.html', {
        'next': next_url,
        'timeout_alert': timeout_alert,
        'remember_days': remember_days
    })


def logout_view(request):
    """
    Encerra a sessão do usuário de forma segura.
    """
    logout(request)
    messages.success(request, 'Você saiu do sistema com segurança.')
    return redirect('login')


# ==========================================
# 2. DASHBOARD PRINCIPAL
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
        
        # Portas permitidas diretamente ou pertencentes aos grupos autorizados
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
# 3. MÓDULO DE CONFIGURAÇÕES (GERAL & SESSÃO)
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

            # Validações básicas de limites razoáveis
            timeout_minutes = max(1, min(240, timeout_minutes)) # 1 min a 4 horas
            remember_days = max(1, min(30, remember_days))       # 1 a 30 dias

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


# ==========================================
# 4. GESTÃO DE USUÁRIOS E PERMISSÕES (RBAC)
# ==========================================

@login_required
def user_list_view(request):
    """
    Listagem de todos os usuários do sistema com seus respectivos perfis e salas autorizadas.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado: você não tem permissão para gerenciar usuários.")

    query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '').strip()

    users = User.objects.select_related('profile').prefetch_related('profile__allowed_groups', 'profile__allowed_ports').all().order_by('-date_joined')

    if query:
        users = users.filter(
            models.Q(username__icontains=query) |
            models.Q(first_name__icontains=query) |
            models.Q(last_name__icontains=query) |
            models.Q(email__icontains=query)
        )

    if role_filter:
        users = users.filter(profile__role=role_filter)

    return render(request, 'users/index.html', {
        'profile': profile,
        'users_list': users,
        'query': query,
        'role_filter': role_filter,
        'active_menu': 'users'
    })


@login_required
def user_create_view(request):
    """
    Criação de um novo usuário com perfil, cargo e atribuição de grupos/salas.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado: você não tem permissão para criar usuários.")

    groups = ProxyGroup.objects.filter(is_active=True).prefetch_related('ports')
    ports = ProxyPort.objects.filter(is_active=True).select_related('group').order_by('port_number')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        role = request.POST.get('role', 'OPERATOR')
        selected_groups = request.POST.getlist('allowed_groups')
        selected_ports = request.POST.getlist('allowed_ports')

        if not username or not password:
            messages.error(request, 'Usuário e senha são obrigatórios.')
            return render(request, 'users/form.html', {'groups': groups, 'ports': ports, 'profile': profile, 'is_edit': False})

        if User.objects.filter(username=username).exists():
            messages.error(request, f"O nome de usuário '{username}' já está em uso.")
            return render(request, 'users/form.html', {'groups': groups, 'ports': ports, 'profile': profile, 'is_edit': False})

        # Não permite que um Manager crie um ADMIN a menos que seja ele próprio um ADMIN
        if role == 'ADMIN' and not profile.is_admin:
            messages.error(request, 'Apenas Administradores Gerais podem conceder o perfil de Administrador.')
            role = 'MANAGER'

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )

        user_profile, _ = UserProfile.objects.get_or_create(user=user)
        user_profile.role = role
        user_profile.save()

        user_profile.allowed_groups.set(selected_groups)
        user_profile.allowed_ports.set(selected_ports)

        messages.success(request, f"Usuário '{username}' criado com sucesso!")
        return redirect('user_list')

    return render(request, 'users/form.html', {
        'profile': profile,
        'groups': groups,
        'ports': ports,
        'is_edit': False,
        'active_menu': 'users'
    })


@login_required
def user_edit_view(request, user_id):
    """
    Edição de dados, permissões, cargo e redefinição opcional de senha de um usuário.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado: você não tem permissão para editar usuários.")

    target_user = get_object_or_404(User.objects.select_related('profile'), id=user_id)
    target_profile, _ = UserProfile.objects.get_or_create(user=target_user)

    # Proteção: Manager não pode editar Admin
    if target_profile.is_admin and not profile.is_admin:
        messages.error(request, 'Você não tem permissão para alterar contas de Administrador Geral.')
        return redirect('user_list')

    groups = ProxyGroup.objects.filter(is_active=True).prefetch_related('ports')
    ports = ProxyPort.objects.filter(is_active=True).select_related('group').order_by('port_number')

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        role = request.POST.get('role', target_profile.role)
        selected_groups = request.POST.getlist('allowed_groups')
        selected_ports = request.POST.getlist('allowed_ports')

        target_user.first_name = first_name
        target_user.last_name = last_name
        target_user.email = email

        if password:
            target_user.set_password(password)

        target_user.save()

        if profile.is_admin:
            target_profile.role = role

        target_profile.save()
        target_profile.allowed_groups.set(selected_groups)
        target_profile.allowed_ports.set(selected_ports)

        messages.success(request, f"Usuário '{target_user.username}' atualizado com sucesso!")
        return redirect('user_list')

    selected_group_ids = list(target_profile.allowed_groups.values_list('id', flat=True))
    selected_port_ids = list(target_profile.allowed_ports.values_list('id', flat=True))

    return render(request, 'users/form.html', {
        'profile': profile,
        'target_user': target_user,
        'target_profile': target_profile,
        'groups': groups,
        'ports': ports,
        'selected_group_ids': selected_group_ids,
        'selected_port_ids': selected_port_ids,
        'is_edit': True,
        'active_menu': 'users'
    })


@login_required
def user_toggle_status_view(request, user_id):
    """
    Ativa ou desativa a conta de um usuário.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    target_user = get_object_or_404(User, id=user_id)
    if target_user == request.user:
        messages.error(request, 'Você não pode desativar sua própria conta.')
        return redirect('user_list')

    target_user.is_active = not target_user.is_active
    target_user.save()

    status_str = "ativado" if target_user.is_active else "desativado"
    messages.success(request, f"Usuário '{target_user.username}' foi {status_str} com sucesso.")
    return redirect('user_list')


@login_required
def user_delete_view(request, user_id):
    """
    Exclui um usuário do sistema.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado: apenas Administradores Gerais podem excluir contas.")

    target_user = get_object_or_404(User, id=user_id)
    if target_user == request.user:
        messages.error(request, 'Você não pode excluir sua própria conta.')
        return redirect('user_list')

    username = target_user.username
    target_user.delete()
    messages.success(request, f"Usuário '{username}' foi excluído permanentemente.")
    return redirect('user_list')
