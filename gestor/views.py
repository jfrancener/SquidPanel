import os
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.db import models
from django.utils import timezone

from dashboard.models import ProxyPort, ProxyGroup, UserProfile, RoomSchedule
from squid.models import AccessLog, DeviceHost, HiddenDomain
from squid.squid_sync import apply_squid_changes
from .scheduler_service import process_room_schedules


def _get_user_authorized_ports(profile):
    """
    Retorna o QuerySet com as portas autorizadas para o usuário logado.
    - Se for Administrador: todas as portas ativas.
    - Se for Coordenador/Professor: portas diretamente vinculadas ou vinculadas aos grupos autorizados.
    """
    if profile.is_admin:
        return ProxyPort.objects.select_related('group').filter(is_active=True).order_by('port_number')

    allowed_groups = profile.allowed_groups.filter(is_active=True)
    return ProxyPort.objects.select_related('group').filter(is_active=True).filter(
        models.Q(authorized_users=profile) |
        models.Q(group__in=allowed_groups)
    ).distinct().order_by('port_number')


# ==========================================
# 1. DASHBOARD PRINCIPAL DO GESTOR
# ==========================================

@login_required
def gestor_dashboard_view(request):
    """
    Painel de controle simplificado e focado para Coordenadores / Gestores e Professores.
    Permite gerenciar o modo das salas atribuídas e monitorar acessos em tempo real.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    ports = _get_user_authorized_ports(profile)

    total_ports = ports.count()
    allowed_count = ports.filter(current_status='ALLOWED').count()
    blocked_count = ports.filter(current_status='BLOCKED').count()
    whitelist_count = ports.filter(current_status='WHITELIST').count()
    blacklist_count = ports.filter(current_status='BLACKLIST').count()

    # Agendamentos em vigor agora
    now = timezone.localtime(timezone.now())
    active_schedules_count = RoomSchedule.objects.filter(port__in=ports, is_enabled=True, current_state='ACTIVE').count()

    return render(request, 'gestor/dashboard.html', {
        'profile': profile,
        'ports': ports,
        'total_ports': total_ports,
        'allowed_count': allowed_count,
        'blocked_count': blocked_count,
        'whitelist_count': whitelist_count,
        'blacklist_count': blacklist_count,
        'active_schedules_count': active_schedules_count,
        'active_menu': 'dashboard',
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

    logs_qs = AccessLog.objects.select_related('port', 'group').filter(port_id__in=authorized_port_ids)

    if port_id and port_id.isdigit():
        p_id = int(port_id)
        if p_id in authorized_port_ids or profile.is_admin:
            logs_qs = logs_qs.filter(port_id=p_id)

    if hide_cdns:
        hidden_patterns = list(HiddenDomain.objects.values_list('domain', flat=True))
        if hidden_patterns:
            q_hidden = models.Q()
            for pat in hidden_patterns:
                q_hidden |= models.Q(domain__icontains=pat)
            logs_qs = logs_qs.exclude(q_hidden)

    if action_filter == 'ALLOWED':
        logs_qs = logs_qs.filter(action='ALLOWED').exclude(http_status__contains='/403').exclude(http_status__contains='/401')
    elif action_filter == 'BLOCKED':
        logs_qs = logs_qs.filter(
            models.Q(action='BLOCKED') |
            models.Q(http_status__icontains='DENIED') |
            models.Q(http_status__contains='/403') |
            models.Q(http_status__contains='/401')
        )

    if last_id and last_id.isdigit() and int(last_id) > 0:
        new_logs = list(logs_qs.filter(id__gt=int(last_id)).order_by('id')[:60])
    else:
        recent = list(logs_qs.order_by('-id')[:30])
        new_logs = list(reversed(recent))

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


# ==========================================
# 2. MÓDULO DE AGENDAMENTOS (SCHEDULER)
# ==========================================

@login_required
def gestor_schedules_view(request):
    """
    Listagem e gerenciamento de Agendamentos de Horários para as salas autorizadas.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    authorized_ports = _get_user_authorized_ports(profile)

    query = request.GET.get('q', '').strip()
    port_filter = request.GET.get('port_id', '').strip()

    schedules_qs = RoomSchedule.objects.filter(port__in=authorized_ports).select_related('port', 'created_by')

    if query:
        schedules_qs = schedules_qs.filter(
            models.Q(name__icontains=query) |
            models.Q(port__name__icontains=query)
        )

    if port_filter and port_filter.isdigit():
        schedules_qs = schedules_qs.filter(port_id=int(port_filter))

    schedules = list(schedules_qs.order_by('-is_enabled', 'start_time'))

    # Verifica status atual de cada agendamento
    now = timezone.localtime(timezone.now())
    for s in schedules:
        s.is_active_now = s.is_in_effect_now(now)

    total_schedules = len(schedules)
    active_now_count = sum(1 for s in schedules if s.is_active_now)

    return render(request, 'gestor/schedules.html', {
        'profile': profile,
        'schedules': schedules,
        'ports': authorized_ports,
        'query': query,
        'port_filter': port_filter,
        'total_schedules': total_schedules,
        'active_now_count': active_now_count,
        'active_menu': 'schedules',
    })


@login_required
def gestor_schedule_create_view(request):
    """
    Criação de um novo agendamento de sala (pontual ou recorrente).
    """
    if request.method != 'POST':
        return redirect('gestor_schedules')

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    authorized_ports = _get_user_authorized_ports(profile)

    port_id = request.POST.get('port_id', '').strip()
    name = request.POST.get('name', '').strip()
    schedule_type = request.POST.get('schedule_type', 'RECURRENT').strip()
    specific_date_str = request.POST.get('specific_date', '').strip()
    days_list = request.POST.getlist('days_of_week')
    start_time_str = request.POST.get('start_time', '').strip()
    end_time_str = request.POST.get('end_time', '').strip()
    action = request.POST.get('action', 'ALLOWED').strip().upper()
    revert_action = request.POST.get('revert_action', 'BLOCKED').strip().upper()
    is_enabled = request.POST.get('is_enabled') == 'on'

    if not name or not port_id or not start_time_str or not end_time_str:
        messages.error(request, 'Preencha todos os campos obrigatórios para o agendamento.')
        return redirect('gestor_schedules')

    port = get_object_or_404(ProxyPort, id=int(port_id))
    if not profile.is_admin and port not in authorized_ports:
        return HttpResponseForbidden("Acesso negado para esta sala.")

    try:
        start_time = datetime.strptime(start_time_str, '%H:%M').time()
        end_time = datetime.strptime(end_time_str, '%H:%M').time()
    except ValueError:
        messages.error(request, 'Formato de horário inválido (utilize HH:MM).')
        return redirect('gestor_schedules')

    specific_date = None
    if schedule_type == 'ONETIME':
        if not specific_date_str:
            messages.error(request, 'Informe a data específica para o agendamento pontual.')
            return redirect('gestor_schedules')
        try:
            specific_date = datetime.strptime(specific_date_str, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, 'Formato de data inválido.')
            return redirect('gestor_schedules')
        days_str = ''
    else:
        if not days_list:
            messages.error(request, 'Selecione ao menos um dia da semana para o agendamento recorrente.')
            return redirect('gestor_schedules')
        days_str = ",".join(sorted(days_list))

    schedule = RoomSchedule.objects.create(
        port=port,
        name=name,
        schedule_type=schedule_type,
        specific_date=specific_date,
        days_of_week=days_str,
        start_time=start_time,
        end_time=end_time,
        action=action,
        revert_action=revert_action,
        is_enabled=is_enabled,
        created_by=request.user
    )

    # Executa o motor do agendador para verificar se a regra entra em vigor imediatamente
    process_room_schedules()

    messages.success(request, f"Agendamento '{name}' para a sala '{port.name}' criado com sucesso!")
    return redirect('gestor_schedules')


@login_required
def gestor_schedule_edit_view(request, schedule_id):
    """
    Edição de um agendamento existente.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    authorized_ports = _get_user_authorized_ports(profile)

    schedule = get_object_or_404(RoomSchedule, id=schedule_id)
    if not profile.is_admin and schedule.port not in authorized_ports:
        return HttpResponseForbidden("Acesso negado.")

    if request.method == 'POST':
        port_id = request.POST.get('port_id', '').strip()
        name = request.POST.get('name', '').strip()
        schedule_type = request.POST.get('schedule_type', 'RECURRENT').strip()
        specific_date_str = request.POST.get('specific_date', '').strip()
        days_list = request.POST.getlist('days_of_week')
        start_time_str = request.POST.get('start_time', '').strip()
        end_time_str = request.POST.get('end_time', '').strip()
        action = request.POST.get('action', 'ALLOWED').strip().upper()
        revert_action = request.POST.get('revert_action', 'BLOCKED').strip().upper()
        is_enabled = request.POST.get('is_enabled') == 'on'

        if not name or not port_id or not start_time_str or not end_time_str:
            messages.error(request, 'Preencha todos os campos obrigatórios.')
            return redirect('gestor_schedules')

        port = get_object_or_404(ProxyPort, id=int(port_id))
        if not profile.is_admin and port not in authorized_ports:
            return HttpResponseForbidden("Acesso negado para esta sala.")

        try:
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
            end_time = datetime.strptime(end_time_str, '%H:%M').time()
        except ValueError:
            messages.error(request, 'Formato de horário inválido.')
            return redirect('gestor_schedules')

        specific_date = None
        if schedule_type == 'ONETIME':
            if not specific_date_str:
                messages.error(request, 'Informe a data específica para o agendamento pontual.')
                return redirect('gestor_schedules')
            try:
                specific_date = datetime.strptime(specific_date_str, '%Y-%m-%d').date()
            except ValueError:
                messages.error(request, 'Formato de data inválido.')
                return redirect('gestor_schedules')
            days_str = ''
        else:
            if not days_list:
                messages.error(request, 'Selecione ao menos um dia da semana.')
                return redirect('gestor_schedules')
            days_str = ",".join(sorted(days_list))

        schedule.port = port
        schedule.name = name
        schedule.schedule_type = schedule_type
        schedule.specific_date = specific_date
        schedule.days_of_week = days_str
        schedule.start_time = start_time
        schedule.end_time = end_time
        schedule.action = action
        schedule.revert_action = revert_action
        schedule.is_enabled = is_enabled
        schedule.save()

        process_room_schedules()
        messages.success(request, f"Agendamento '{name}' atualizado com sucesso!")

    return redirect('gestor_schedules')


@login_required
def gestor_schedule_toggle_view(request, schedule_id):
    """
    Ativa ou pausa um agendamento.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    authorized_ports = _get_user_authorized_ports(profile)

    schedule = get_object_or_404(RoomSchedule, id=schedule_id)
    if not profile.is_admin and schedule.port not in authorized_ports:
        return HttpResponseForbidden("Acesso negado.")

    schedule.is_enabled = not schedule.is_enabled
    schedule.save()

    process_room_schedules()

    status_str = "habilitado" if schedule.is_enabled else "pausado"
    messages.success(request, f"Agendamento '{schedule.name}' {status_str} com sucesso!")
    return redirect('gestor_schedules')


@login_required
def gestor_schedule_delete_view(request, schedule_id):
    """
    Exclui um agendamento.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    authorized_ports = _get_user_authorized_ports(profile)

    schedule = get_object_or_404(RoomSchedule, id=schedule_id)
    if not profile.is_admin and schedule.port not in authorized_ports:
        return HttpResponseForbidden("Acesso negado.")

    name = schedule.name
    was_active = schedule.current_state == 'ACTIVE'
    port = schedule.port
    revert_action = schedule.revert_action

    schedule.delete()

    # Se estava ativo, reverte o status da sala
    if was_active:
        port.current_status = revert_action
        port.save()
        apply_squid_changes()

    process_room_schedules()

    messages.success(request, f"Agendamento '{name}' excluído com sucesso!")
    return redirect('gestor_schedules')


@login_required
def gestor_schedule_run_check_api(request):
    """
    Endpoint AJAX para disparar manualmente a checagem e aplicação dos agendamentos.
    """
    result = process_room_schedules()
    return JsonResponse(result)
