import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.db import models
from django.utils import timezone

from dashboard.models import ProxyPort, ProxyGroup, UserProfile
from squid.models import AccessLog, DeviceHost, HiddenDomain
from squid.squid_sync import apply_squid_changes


def _get_user_authorized_ports(profile):
    """
    Retorna o QuerySet com as portas autorizadas para o usuário logado.
    - Se for Administrador: todas as portas ativas.
    - Se for Coordenador/Professor: portas diretamente vinculadas ou vinculadas aos grupos autorizados.
    """
    if profile.is_admin:
        return ProxyPort.objects.select_related('group').filter(is_active=True).order_by('port_number')

    # Portas associadas diretamente ao perfil ou aos grupos autorizados
    allowed_groups = profile.allowed_groups.filter(is_active=True)
    return ProxyPort.objects.select_related('group').filter(is_active=True).filter(
        models.Q(authorized_users=profile) |
        models.Q(group__in=allowed_groups)
    ).distinct().order_by('port_number')


@login_required
def gestor_dashboard_view(request):
    """
    Painel de controle simplificado e focado para Coordenadores / Gestores e Professores.
    Permite gerenciar o modo das salas atribuídas e monitorar acessos em tempo real.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    ports = _get_user_authorized_ports(profile)

    # Estatísticas básicas para o cabeçalho
    total_ports = ports.count()
    allowed_count = ports.filter(current_status='ALLOWED').count()
    blocked_count = ports.filter(current_status='BLOCKED').count()
    whitelist_count = ports.filter(current_status='WHITELIST').count()
    blacklist_count = ports.filter(current_status='BLACKLIST').count()

    return render(request, 'gestor/dashboard.html', {
        'profile': profile,
        'ports': ports,
        'total_ports': total_ports,
        'allowed_count': allowed_count,
        'blocked_count': blocked_count,
        'whitelist_count': whitelist_count,
        'blacklist_count': blacklist_count,
    })


@login_required
def gestor_set_port_mode_api(request, port_id):
    """
    Endpoint AJAX para alterar o modo de acesso de uma sala/porta (ALLOWED, BLOCKED, WHITELIST, BLACKLIST).
    Aplica imediatamente as novas regras no Squid.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método inválido.'}, status=405)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    authorized_ports = _get_user_authorized_ports(profile)

    port = get_object_or_404(ProxyPort, id=port_id)
    if not profile.is_admin and port not in authorized_ports:
        return JsonResponse({'success': False, 'error': 'Você não tem permissão para gerenciar esta sala.'}, status=403)

    new_mode = request.POST.get('mode', '').strip().upper()
    valid_modes = ['ALLOWED', 'BLOCKED', 'WHITELIST', 'BLACKLIST']
    if new_mode not in valid_modes:
        return JsonResponse({'success': False, 'error': f'Modo inválido. Opções válidas: {", ".join(valid_modes)}'}, status=400)

    port.current_status = new_mode
    port.save()

    # Aplica imediatamente no Squid
    ok, msg = apply_squid_changes()

    mode_labels = {
        'ALLOWED': 'Livre (Acesso Total)',
        'BLOCKED': 'Bloqueado',
        'WHITELIST': 'Whitelist (Apenas Permitidos)',
        'BLACKLIST': 'Blacklist (Livre com Restrições)',
    }

    return JsonResponse({
        'success': True,
        'port_id': port.id,
        'port_name': port.name,
        'new_mode': new_mode,
        'mode_label': mode_labels.get(new_mode, new_mode),
        'squid_synced': ok,
        'message': f"Modo da sala '{port.name}' alterado para {mode_labels.get(new_mode, new_mode)} e aplicado no Squid com sucesso!"
    })


@login_required
def gestor_live_stream_api(request):
    """
    Endpoint AJAX para streaming de logs em tempo real filtrado estritamente pelas salas
    que o gestor tem autorização para monitorar.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    authorized_ports = _get_user_authorized_ports(profile)
    authorized_port_ids = list(authorized_ports.values_list('id', flat=True))

    port_id = request.GET.get('port_id', '').strip()
    last_id = request.GET.get('last_id', '0').strip()
    action_filter = request.GET.get('action', '').strip()
    hide_cdns = request.GET.get('hide_cdns', 'true') == 'true'

    # Filtra logs estritamente dentro das portas autorizadas do usuário
    logs_qs = AccessLog.objects.select_related('port', 'group').filter(port_id__in=authorized_port_ids)

    # 1. Filtro opcional por sala específica
    if port_id and port_id.isdigit():
        p_id = int(port_id)
        if p_id in authorized_port_ids or profile.is_admin:
            logs_qs = logs_qs.filter(port_id=p_id)

    # 2. Filtro de Domínios Ocultos/Silenciados
    if hide_cdns:
        hidden_patterns = list(HiddenDomain.objects.values_list('domain', flat=True))
        if hidden_patterns:
            q_hidden = models.Q()
            for pat in hidden_patterns:
                q_hidden |= models.Q(domain__icontains=pat)
            logs_qs = logs_qs.exclude(q_hidden)

    # 3. Filtro por Ação (Permitido / Bloqueado)
    if action_filter == 'ALLOWED':
        logs_qs = logs_qs.filter(action='ALLOWED').exclude(http_status__contains='/403').exclude(http_status__contains='/401')
    elif action_filter == 'BLOCKED':
        logs_qs = logs_qs.filter(
            models.Q(action='BLOCKED') |
            models.Q(http_status__icontains='DENIED') |
            models.Q(http_status__contains='/403') |
            models.Q(http_status__contains='/401')
        )

    # 4. Paginação incremental pelo ID
    if last_id and last_id.isdigit() and int(last_id) > 0:
        new_logs = list(logs_qs.filter(id__gt=int(last_id)).order_by('id')[:60])
    else:
        # Carga inicial: últimos 30 registros
        recent = list(logs_qs.order_by('-id')[:30])
        new_logs = list(reversed(recent))

    # Mapeamento de Hostnames / Descrições dos Computadores
    device_map = {d.ip_address: d for d in DeviceHost.objects.all()}

    data = []
    for l in new_logs:
        dev = device_map.get(l.client_ip)
        local_ts = timezone.localtime(l.timestamp)
        effective_hostname = l.hostname or (dev.hostname if dev else None)
        
        data.append({
            'id': l.id,
            'timestamp': local_ts.strftime('%H:%M:%S'),
            'date': local_ts.strftime('%d/%m/%Y'),
            'client_ip': l.client_ip,
            'hostname': effective_hostname,
            'device_desc': dev.description if dev else None,
            'port_number': l.port_number,
            'port_name': l.port.name if l.port else f"Porta {l.port_number}",
            'group_name': l.group.name if l.group else '-',
            'domain': l.domain,
            'full_url': l.full_url,
            'method': l.method,
            'action': l.action,
            'http_status': l.http_status,
            'status_code': l.status_code,
            'status_category': l.status_category,
            'is_proxy_blocked': l.is_proxy_blocked,
            'is_dest_blocked': l.is_dest_blocked,
            'bytes': l.formatted_bytes,
            'latency': f"{l.response_time_ms}ms"
        })

    return JsonResponse({'success': True, 'logs': data})
