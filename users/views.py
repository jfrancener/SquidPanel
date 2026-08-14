import time
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import HttpResponseForbidden

from dashboard.models import (
    SystemSetting,
    ProxyGroup,
    ProxyPort,
    UserProfile
)

# ==========================================
# 1. AUTENTICAÇÃO E SESSÃO
# ==========================================

def login_view(request):
    """
    Tela de login com controle de sessão persistente ('remember_me')
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
                return render(request, 'users/login.html', {'next': next_url, 'timeout_alert': False})

            login(request, user)

            # Garante que o usuário possua UserProfile
            profile, _ = UserProfile.objects.get_or_create(user=user)

            # Configura a expiração da sessão
            if remember_me:
                request.session['remember_me'] = True
                try:
                    remember_days = int(SystemSetting.get_value('session_remember_days', 7))
                except (ValueError, TypeError):
                    remember_days = 7
                request.session.set_expiry(remember_days * 86400)
            else:
                request.session['remember_me'] = False
                request.session.set_expiry(0)
                request.session['last_activity'] = time.time()

            return redirect(next_url if next_url and next_url != '/' else 'dashboard')
        else:
            messages.error(request, 'Usuário ou senha incorretos. Verifique suas credenciais.')

    remember_days = SystemSetting.get_value('session_remember_days', 7)
    return render(request, 'users/login.html', {
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
# 2. GESTÃO DE USUÁRIOS E PERMISSÕES (RBAC)
# ==========================================

@login_required
def user_list_view(request):
    """
    Listagem de todos os usuários com seus respectivos perfis e salas autorizadas.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado: você não tem permissão para gerenciar usuários.")

    query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '').strip()

    from django.db import models
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
