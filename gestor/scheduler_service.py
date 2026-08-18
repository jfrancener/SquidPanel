import os
from django.utils import timezone
from dashboard.models import RoomSchedule, ProxyPort
from squid.squid_sync import apply_squid_changes


def process_room_schedules():
    """
    Motor de Execução dos Agendamentos de Salas.
    Avalia as regras ativas minuto a minuto e altera o status das portas no Squid.
    """
    now = timezone.localtime(timezone.now())
    schedules = RoomSchedule.objects.filter(is_enabled=True).select_related('port')
    
    changed_ports = []
    log_messages = []

    # Agrupa agendamentos por sala/porta
    ports_map = {}
    for s in schedules:
        if s.port_id not in ports_map:
            ports_map[s.port_id] = []
        ports_map[s.port_id].append(s)

    for port_id, port_schedules in ports_map.items():
        port = ProxyPort.objects.filter(id=port_id, is_active=True).first()
        if not port:
            continue

        # Verifica se algum agendamento para esta sala está em vigor agora
        active_schedule = None
        for s in port_schedules:
            if s.is_in_effect_now(now):
                active_schedule = s
                break

        if active_schedule:
            # A sala deve estar no modo 'action' do agendamento
            if port.current_status != active_schedule.action or active_schedule.current_state != 'ACTIVE':
                old_status = port.current_status
                port.current_status = active_schedule.action
                port.last_status_source = 'SCHEDULE'
                port.active_schedule = active_schedule
                port.last_modified_by = None
                port.save(update_fields=['current_status', 'last_status_source', 'active_schedule', 'last_modified_by', 'updated_at'])
                
                active_schedule.current_state = 'ACTIVE'
                active_schedule.last_run_at = now
                active_schedule.save(update_fields=['current_state', 'last_run_at', 'updated_at'])
                
                changed_ports.append(port)
                log_messages.append(
                    f"Agendamento '{active_schedule.name}': Sala '{port.name}' alterada de {old_status} para {port.get_current_status_display()}."
                )
        else:
            # Nenhum agendamento está em vigor agora para esta sala.
            # Se havia algum agendamento 'ACTIVE', reverte para a ação de saída (revert_action).
            for s in port_schedules:
                if s.current_state == 'ACTIVE':
                    old_status = port.current_status
                    port.current_status = s.revert_action
                    port.last_status_source = 'SCHEDULE'
                    port.active_schedule = None
                    port.last_modified_by = None
                    port.save(update_fields=['current_status', 'last_status_source', 'active_schedule', 'last_modified_by', 'updated_at'])

                    s.current_state = 'INACTIVE'
                    s.last_run_at = now
                    # Se for agendamento pontual e a data/hora já passaram, desativa para não rodar novamente
                    if s.schedule_type == 'ONETIME':
                        s.is_enabled = False

                    s.save(update_fields=['current_state', 'last_run_at', 'is_enabled', 'updated_at'])
                    changed_ports.append(port)
                    log_messages.append(
                        f"Término do agendamento '{s.name}': Sala '{port.name}' revertida de {old_status} para {port.get_current_status_display()}."
                    )

    # Se houve alteração em alguma sala, aplica imediatamente no Squid
    squid_synced = False
    squid_msg = ""
    if changed_ports:
        squid_synced, squid_msg = apply_squid_changes()

    return {
        'success': True,
        'timestamp': now.strftime('%d/%m/%Y %H:%M:%S'),
        'changed_count': len(changed_ports),
        'squid_synced': squid_synced,
        'squid_msg': squid_msg,
        'log': log_messages
    }
