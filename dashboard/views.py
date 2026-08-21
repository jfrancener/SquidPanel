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

from .system_metrics import get_full_system_telemetry
from django.http import JsonResponse

def generic_home_view(request):
    """
    Página inicial pública minimalista com identificador discreto do SquidPanel.
    """
    return render(request, 'generic_home.html')


@login_required
def dashboard_view(request):
    """
    Painel de controle principal exibindo telemetria do hardware, status do proxy e portas.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    # Se não for Administrador Geral de TI, redireciona para a Dashboard do Gestor
    if not profile.is_admin:
        return redirect('gestor_dashboard')

    groups = ProxyGroup.objects.prefetch_related('ports').filter(is_active=True)
    ports = ProxyPort.objects.select_related('group').filter(is_active=True).order_by('port_number')

    # Métricas para os cards estatísticos
    total_ports = ports.count()
    allowed_ports_count = ports.filter(current_status='ALLOWED').count()
    whitelist_ports_count = ports.filter(current_status='WHITELIST').count()
    blocked_ports_count = ports.filter(current_status='BLOCKED').count()
    total_rules = DomainRule.objects.count()

    # Telemetria do Servidor (CPU, RAM, Disco, Internet e Uptime)
    system_metrics = get_full_system_telemetry()

    return render(request, 'dashboard/index.html', {
        'profile': profile,
        'groups': groups,
        'ports': ports,
        'total_ports': total_ports,
        'allowed_ports_count': allowed_ports_count,
        'whitelist_ports_count': whitelist_ports_count,
        'blocked_ports_count': blocked_ports_count,
        'total_rules': total_rules,
        'system_metrics': system_metrics,
        'server_ip': system_metrics.get('server_ip', '10.40.88.5'),
        'active_menu': 'dashboard'
    })


def system_metrics_api_view(request):
    """
    Endpoint AJAX para atualização contínua em tempo real da telemetria de hardware no Dashboard.
    """
    return JsonResponse(get_full_system_telemetry())


# ==========================================
# 2. MÓDULO DE CONFIGURAÇÕES (GERAL & SESSÃO)
# ==========================================

@login_required
def settings_general_view(request):
    """
    Sublink: Parâmetros Gerais do Servidor (Apenas Admin).
    Permite configurar Nome, DNS, Gateway, IP de Escuta e E-mail do Administrador.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado: apenas Administradores de TI podem alterar as configurações.")

    from .system_metrics import get_network_info
    net_info = get_network_info()

    if request.method == 'POST':
        server_name = request.POST.get('server_name', 'SquidPanel - Proxy Server').strip()
        server_ip = request.POST.get('server_ip', '10.40.88.5').strip()
        server_gateway = request.POST.get('server_gateway', '').strip()
        server_dns = request.POST.get('server_dns', '1.1.1.1, 8.8.8.8').strip()
        admin_email = request.POST.get('admin_email', '').strip()

        SystemSetting.set_value('server_name', server_name, 'Nome de exibição do servidor')
        SystemSetting.set_value('server_ip', server_ip, 'Endereço IP de escuta do servidor')
        SystemSetting.set_value('server_gateway', server_gateway, 'Gateway padrão da rede')
        SystemSetting.set_value('server_dns', server_dns, 'Servidores DNS de consulta')
        SystemSetting.set_value('admin_email', admin_email, 'E-mail do Administrador de TI')

        # Configurações de Integração com IA
        ai_enabled = 'true' if request.POST.get('ai_integration_enabled') == 'on' else 'false'
        ai_api_url = request.POST.get('ai_api_url', '').strip()
        ai_api_key = request.POST.get('ai_api_key', '').strip()
        SystemSetting.set_value('ai_integration_enabled', ai_enabled, 'Análise de sublinks via IA ativada')
        SystemSetting.set_value('ai_api_url', ai_api_url, 'URL base da API de IA (9router)')
        # Só sobrescreve a chave se o usuário enviou algo (evita apagar chave ao salvar sem reeditar)
        if ai_api_key:
            SystemSetting.set_value('ai_api_key', ai_api_key, 'Chave de acesso da API de IA')

        # Sincroniza regras do Squid caso necessário
        from squid.squid_sync import apply_squid_changes
        apply_squid_changes()

        messages.success(request, 'Parâmetros gerais de rede e servidor atualizados com sucesso!')
        return redirect('settings_general')

    server_name = SystemSetting.get_value('server_name', 'SquidPanel - Proxy Server')
    server_ip = SystemSetting.get_value('server_ip', net_info['server_ip'])
    server_gateway = SystemSetting.get_value('server_gateway', net_info['gateway'])
    server_dns = SystemSetting.get_value('server_dns', '10.40.88.1, 10.40.88.2, 1.1.1.1')
    admin_email = SystemSetting.get_value('admin_email', 'informatica@pij.local')
    ai_integration_enabled = SystemSetting.get_value('ai_integration_enabled', 'false') == 'true'
    ai_api_url = SystemSetting.get_value('ai_api_url', '')
    ai_api_key_set = bool(SystemSetting.get_value('ai_api_key', ''))  # Apenas sinaliza se existe

    return render(request, 'settings/general.html', {
        'profile': profile,
        'server_name': server_name,
        'server_ip': server_ip,
        'server_gateway': server_gateway,
        'server_dns': server_dns,
        'admin_email': admin_email,
        'ai_integration_enabled': ai_integration_enabled,
        'ai_api_url': ai_api_url,
        'ai_api_key_set': ai_api_key_set,
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


@login_required
def settings_logs_view(request):
    """
    Sublink: Configuração de Retenção & Armazenamento de Logs (Apenas Admin).
    Permite definir quantos dias os logs do Squid ficam armazenados no sistema.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado: apenas Administradores de TI podem alterar as configurações.")

    from squid.models import AccessLog

    if request.method == 'POST':
        try:
            log_retention_days = int(request.POST.get('log_retention_days', 30))
            log_retention_days = max(1, min(365, log_retention_days))
            auto_cleanup = request.POST.get('auto_cleanup') == 'on'

            SystemSetting.set_value('log_retention_days', log_retention_days, 'Dias de retenção dos logs de acesso')
            SystemSetting.set_value('log_auto_cleanup', 'true' if auto_cleanup else 'false', 'Limpeza automática periódica')

            messages.success(request, f'Configurações de retenção de logs atualizadas para {log_retention_days} dias com sucesso!')
            return redirect('settings_logs')
        except ValueError:
            messages.error(request, 'Número de dias inválido.')

    log_retention_days = int(SystemSetting.get_value('log_retention_days', '30'))
    auto_cleanup = SystemSetting.get_value('log_auto_cleanup', 'true') == 'true'
    total_logs_count = AccessLog.objects.count()
    oldest_log = AccessLog.objects.order_by('timestamp').first()

    return render(request, 'settings/logs.html', {
        'profile': profile,
        'log_retention_days': log_retention_days,
        'auto_cleanup': auto_cleanup,
        'total_logs_count': total_logs_count,
        'oldest_log': oldest_log,
        'active_menu': 'settings_logs'
    })


# ==========================================
# 3. EXPORTAÇÃO & BACKUPS (XML & TXT)
# ==========================================

@login_required
def settings_export_view(request):
    """
    Tela de Gestão de Exportações e Backups (XML de Configurações e TXT de Logs).
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado: apenas Administradores de TI podem acessar a área de exportação.")

    from squid.models import ProxyList, DomainItem, DeviceHost, AccessLog

    total_groups = ProxyGroup.objects.filter(is_active=True).count()
    total_ports = ProxyPort.objects.filter(is_active=True).count()
    total_whitelists = ProxyList.objects.filter(list_type='WHITELIST', is_active=True).count()
    total_blacklists = ProxyList.objects.filter(list_type='BLACKLIST', is_active=True).count()
    total_domains = DomainItem.objects.filter(is_active=True).count()
    total_devices = DeviceHost.objects.count()
    total_logs = AccessLog.objects.count()

    all_ports = ProxyPort.objects.select_related('group').filter(is_active=True).order_by('port_number')
    all_groups = ProxyGroup.objects.filter(is_active=True).order_by('name')

    return render(request, 'settings/export.html', {
        'profile': profile,
        'total_groups': total_groups,
        'total_ports': total_ports,
        'total_whitelists': total_whitelists,
        'total_blacklists': total_blacklists,
        'total_domains': total_domains,
        'total_devices': total_devices,
        'total_logs': total_logs,
        'all_ports': all_ports,
        'all_groups': all_groups,
        'active_menu': 'settings_export'
    })


@login_required
def export_config_xml_view(request):
    """
    Gera e entrega o arquivo XML com todas as configurações do servidor para download.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado.")

    from django.http import HttpResponse
    from django.utils import timezone
    from .export_service import generate_configuration_xml

    xml_content = generate_configuration_xml()
    filename = f"SquidPanel_Config_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xml"

    response = HttpResponse(xml_content, content_type='application/xml; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_logs_txt_view(request):
    """
    Gera e entrega o arquivo TXT com os logs de acesso filtrados para download.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado.")

    from django.http import HttpResponse
    from django.utils import timezone
    from .export_service import export_logs_to_txt

    filters = {
        'period': request.GET.get('period', 'today'),
        'port_id': request.GET.get('port_id'),
        'action': request.GET.get('action', 'ALL'),
        'hostname_ip': request.GET.get('hostname_ip', '').strip(),
        'format': request.GET.get('format', 'human'),
        'date_from': request.GET.get('date_from'),
        'date_to': request.GET.get('date_to'),
        'time_from': request.GET.get('time_from', '00:00'),
        'time_to': request.GET.get('time_to', '23:59'),
    }

    txt_content = export_logs_to_txt(filters)
    filename = f"Squid_Logs_{filters['period']}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.txt"

    response = HttpResponse(txt_content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


from django.views.decorators.csrf import csrf_exempt
import json
import subprocess
import os
import sys

@csrf_exempt
def auto_deploy_api_view(request):
    """
    Endpoint seguro de Auto-Deploy e Sincronização em Produção.
    Permite atualizar o código no servidor, aplicar migrações,
    regerar e recarregar as regras do Squid e reiniciar o serviço WSGI.
    """
    if request.method not in ['POST', 'GET']:
        return JsonResponse({'success': False, 'error': 'Método inválido.'}, status=405)

    is_authenticated_admin = request.user.is_authenticated and hasattr(request.user, 'profile') and request.user.profile.is_admin
    expected_token = SystemSetting.get_value('deploy_token', 'squidpanel-deploy-secret-2026')

    # Obtém token dos headers, query params ou body
    token = (
        request.headers.get('X-Deploy-Token') or
        request.META.get('HTTP_X_DEPLOY_TOKEN') or
        request.GET.get('token') or
        request.POST.get('token')
    )

    if not token and request.body:
        try:
            body_data = json.loads(request.body.decode('utf-8'))
            token = body_data.get('token')
        except Exception:
            pass

    # Valida permissão: ou Admin logado no painel, ou Token válido
    if not is_authenticated_admin and (not token or token != expected_token):
        return JsonResponse({'success': False, 'error': 'Acesso negado: Token de deploy inválido ou permissão insuficiente.'}, status=403)

    log_results = []
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1. Git Pull
    try:
        git_res = subprocess.run(
            ['git', 'pull', 'origin', 'main'],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=30
        )
        git_out = (git_res.stdout + "\n" + git_res.stderr).strip()
        log_results.append(f"Git Pull: {git_out}")
    except Exception as e:
        log_results.append(f"Git Pull Erro: {str(e)}")

    # 2. Migrações Django
    try:
        from django.core.management import call_command
        call_command('migrate', interactive=False)
        log_results.append("Migrações: OK")
    except Exception as e:
        log_results.append(f"Migrações Erro: {str(e)}")

    # 3. Sincronização do Squid
    squid_msg = ""
    try:
        from squid.squid_sync import apply_squid_changes
        ok_squid, squid_msg = apply_squid_changes()
        log_results.append(f"Squid Sync: {'OK' if ok_squid else 'Falhou'} - {squid_msg}")
    except Exception as e:
        log_results.append(f"Squid Sync Erro: {str(e)}")

    # 4. Reload / Restart do Serviço WSGI
    try:
        wsgi_file = os.path.join(base_dir, 'core', 'wsgi.py')
        if os.path.exists(wsgi_file):
            os.utime(wsgi_file, None)
        
        if sys.platform != 'win32':
            prefix = ['sudo'] if hasattr(os, 'geteuid') and os.geteuid() != 0 else []
            subprocess.run(prefix + ['systemctl', 'restart', 'squidpanel'], capture_output=True, timeout=10)
            subprocess.run(prefix + ['systemctl', 'restart', 'gunicorn'], capture_output=True, timeout=10)
        log_results.append("Serviço WSGI: Recarregado com sucesso")
    except Exception as e:
        log_results.append(f"WSGI Reload Erro: {str(e)}")

    return JsonResponse({
        'success': True,
        'message': 'Deploy e sincronização executados com sucesso no servidor de produção!',
        'logs': log_results
    })


@csrf_exempt
def check_system_update_api_view(request):
    """
    Verifica de forma assíncrona se existem novos commits no repositório remoto (Git).
    Retorna se há atualização pendente e a quantidade de commits a aplicar.
    """
    expected_token = SystemSetting.get_value('deploy_token', 'squidpanel-deploy-secret-2026')
    token = (
        request.headers.get('X-Deploy-Token') or
        request.META.get('HTTP_X_DEPLOY_TOKEN') or
        request.GET.get('token') or
        request.POST.get('token')
    )

    is_authenticated_admin = request.user.is_authenticated and hasattr(request.user, 'profile') and request.user.profile.is_admin

    if not is_authenticated_admin and (not token or token != expected_token):
        return JsonResponse({'success': False, 'error': 'Acesso restrito.'}, status=403)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    try:
        # Busca referências remotas sem alterar arquivos locais
        subprocess.run(
            ['git', 'fetch', 'origin', 'main'],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=10
        )

        # Hash local e remoto
        local_hash = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            cwd=base_dir,
            text=True,
            timeout=5
        ).strip()

        remote_hash = subprocess.check_output(
            ['git', 'rev-parse', 'origin/main'],
            cwd=base_dir,
            text=True,
            timeout=5
        ).strip()

        # Contagem de commits atrás
        count_out = subprocess.check_output(
            ['git', 'rev-list', 'HEAD..origin/main', '--count'],
            cwd=base_dir,
            text=True,
            timeout=5
        ).strip()

        commits_behind = int(count_out) if count_out.isdigit() else 0
        has_update = commits_behind > 0 or (local_hash != remote_hash and local_hash and remote_hash)

        return JsonResponse({
            'success': True,
            'has_update': has_update,
            'commits_behind': commits_behind,
            'local_hash': local_hash[:7] if local_hash else '',
            'remote_hash': remote_hash[:7] if remote_hash else '',
            'message': f"{commits_behind} nova(s) atualização(ões) disponível(is)" if has_update else "Sistema atualizado."
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'has_update': False,
            'error': str(e),
            'message': 'Não foi possível verificar atualizações no momento.'
        })



