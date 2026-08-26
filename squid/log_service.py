import os
import sys
from datetime import datetime, timezone as dt_timezone, timedelta
from urllib.parse import urlparse
from django.utils import timezone
from django.conf import settings

from .models import AccessLog, ProxyList, DomainItem, DeviceHost, DiscoveredSublink, AllowedRefererHub
from dashboard.models import ProxyGroup, ProxyPort, SystemSetting


def get_squid_log_path():
    """
    Retorna o caminho do arquivo de access.log do Squid.
    """
    if sys.platform == 'win32':
        mock_path = os.path.join(settings.BASE_DIR, 'scratch', 'squid_config', 'access.log')
        return mock_path
    return '/var/log/squid/access.log'


def cleanup_old_logs():
    """
    Remove registros de log mais antigos que o período de retenção configurado.
    """
    retention_days_str = SystemSetting.get_value('log_retention_days', '30')
    try:
        retention_days = int(retention_days_str)
    except (ValueError, TypeError):
        retention_days = 30

    cutoff_date = timezone.now() - timedelta(days=retention_days)
    deleted_count, _ = AccessLog.objects.filter(timestamp__lt=cutoff_date).delete()
    return deleted_count, retention_days


def parse_squid_log_line(line, port_map, device_map=None):
    """
    Faz o parsing de uma linha do /var/log/squid/access.log no formato nativo do Squid / SquidPanel.
    Grava o Hostname correspondente ao IP naquele exato momento.
    """
    parts = line.strip().split()
    if len(parts) < 7:
        return None

    try:
        # 1. Timestamp UNIX
        ts_float = float(parts[0])
        log_time = datetime.fromtimestamp(ts_float, tz=dt_timezone.utc)

        # 2. Latência
        response_time_ms = int(parts[1]) if parts[1].isdigit() else 0

        # 3. IP do Cliente
        client_ip = parts[2]

        # 4. Hostname do Equipamento no momento da requisição
        hostname = ''
        if device_map and client_ip in device_map:
            hostname = device_map[client_ip]

        # 5. Status HTTP / Squid
        http_status = parts[3]

        # 6. Bytes Trafegados
        bytes_sent = int(parts[4]) if parts[4].isdigit() else 0

        # 7. Método HTTP
        method = parts[5].upper()

        # 8. URL ou Host requisitado
        raw_url = parts[6]
        full_url = raw_url

        # Descarta linhas de erros internos sintéticos do próprio Squid (ex: error:invalid-request, error:transaction-end)
        if raw_url.startswith('error:') or raw_url.startswith('-') or raw_url.lower() == 'error':
            return None

        # Extrai o domínio limpo
        if '://' in raw_url:
            parsed = urlparse(raw_url)
            domain = parsed.hostname or raw_url
        else:
            domain = raw_url.split(':')[0]

        domain = domain.lstrip('.').lower()
        if not domain or domain == 'error':
            return None

        # 9. Mime Type
        mime_type = parts[9] if len(parts) > 9 else '-'

        # 10. Porta local de escuta (se presente na última posição)
        port_number = None
        if len(parts) >= 11 and parts[-1].isdigit():
            port_number = int(parts[-1])
        elif len(parts) >= 10 and parts[-1].isdigit():
            port_number = int(parts[-1])

        # Se a requisição não tiver porta de escuta válida (ex: erro abortado antes do handshake), ignora para não poluir salas aleatórias
        if not port_number or port_number not in port_map:
            return None

        # Ação (ALLOWED / BLOCKED pelo Proxy Squid)
        # O Squid marca bloqueios por ACL com TCP_DENIED, UDP_DENIED, NONE/403 ou ERR_ACCESS_DENIED
        status_upper = http_status.upper()
        is_proxy_blocked = 'DENIED' in status_upper or 'ERR_ACCESS_DENIED' in status_upper or status_upper.startswith('NONE/403')
        action = 'BLOCKED' if is_proxy_blocked else 'ALLOWED'

        proxy_port = port_map.get(port_number)
        proxy_group = proxy_port.group if proxy_port else None

        return AccessLog(
            timestamp=log_time,
            client_ip=client_ip,
            hostname=hostname,
            port_number=port_number,
            port=proxy_port,
            group=proxy_group,
            method=method,
            domain=domain,
            full_url=full_url,
            http_status=http_status,
            action=action,
            bytes_sent=bytes_sent,
            response_time_ms=response_time_ms,
            mime_type=mime_type
        )
    except Exception as e:
        return None


def sync_logs_from_squid_file(chunk_size=2000):
    """
    Lê incrementalmente as novas linhas completas do arquivo /var/log/squid/access.log
    e insere os registros no banco de dados em lotes (chunks) constantes para evitar
    picos de consumo de memória RAM e sobrecarga no PostgreSQL.
    """
    import gc
    log_file_path = get_squid_log_path()
    if not os.path.exists(log_file_path):
        return 0

    # Carrega mapa de portas e mapa de dispositivos (IP -> Hostname) em memória
    port_map = {p.port_number: p for p in ProxyPort.objects.select_related('group').filter(is_active=True)}
    device_map = dict(DeviceHost.objects.values_list('ip_address', 'hostname'))

    # Pega offset anterior
    offset_str = SystemSetting.get_value('squid_log_file_offset', '0')
    try:
        last_offset = int(offset_str)
    except Exception:
        last_offset = 0

    try:
        current_size = os.path.getsize(log_file_path)
    except Exception:
        return 0

    # Se o arquivo foi rotacionado (tamanho menor que o offset), recomeça do início
    if current_size < last_offset:
        last_offset = 0

    valid_offset = last_offset
    total_processed = 0

    # Pré-carrega metadados de sublinks apenas se houver portas em WHITELIST
    whitelist_ports = {p.port_number for p in port_map.values() if p.current_status == 'WHITELIST'}
    allowed_hubs = list(AllowedRefererHub.objects.filter(is_active=True)) if whitelist_ports else []

    active_wl_bases = set()
    if whitelist_ports and allowed_hubs:
        for d in DomainItem.objects.filter(
            proxy_list__list_type='WHITELIST',
            proxy_list__is_active=True,
            is_active=True
        ).values_list('domain', flat=True):
            active_wl_bases.add(d.strip().lower().lstrip('.'))

    discovered_sublinks_batch = {}

    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(last_offset)

            chunk_logs = []
            while True:
                line_start_pos = f.tell()
                line = f.readline()
                if not line:
                    break
                # Garante que só processa linhas terminadas em quebra de linha
                if not line.endswith('\n') and not line.endswith('\r'):
                    # Linha incompleta sendo escrita pelo Squid, recua para tentar no próximo polling
                    f.seek(line_start_pos)
                    break

                valid_offset = f.tell()
                parsed_log = parse_squid_log_line(line, port_map, device_map)
                if parsed_log:
                    chunk_logs.append(parsed_log)

                    # Coleta sublinks em memória para agregação
                    if whitelist_ports and allowed_hubs and parsed_log.action == 'ALLOWED' and parsed_log.port_number in whitelist_ports:
                        clean_d = parsed_log.domain.strip().lower().split(':')[0].lstrip('.')
                        if clean_d and not clean_d.startswith(('10.', '192.168.', '127.')):
                            is_in_wl = any(clean_d == base or clean_d.endswith('.' + base) for base in active_wl_bases)
                            if not is_in_wl:
                                for hub in allowed_hubs:
                                    hub_pat = hub.clean_pattern()
                                    if hub_pat and (clean_d == hub_pat or clean_d.endswith('.' + hub_pat)):
                                        if clean_d not in discovered_sublinks_batch:
                                            discovered_sublinks_batch[clean_d] = {
                                                'hub': hub,
                                                'url': parsed_log.full_url[:500] if parsed_log.full_url else f"https://{clean_d}",
                                                'hits': 0
                                            }
                                        discovered_sublinks_batch[clean_d]['hits'] += 1
                                        break

                # Quando atinge o tamanho do lote, grava no banco e libera a memória
                if len(chunk_logs) >= chunk_size:
                    AccessLog.objects.bulk_create(chunk_logs, batch_size=1000)
                    total_processed += len(chunk_logs)
                    chunk_logs.clear()
                    SystemSetting.set_value('squid_log_file_offset', str(valid_offset), 'Offset do arquivo access.log')

            # Grava os itens restantes do último lote
            if chunk_logs:
                AccessLog.objects.bulk_create(chunk_logs, batch_size=1000)
                total_processed += len(chunk_logs)
                chunk_logs.clear()

        # Salva o offset final
        SystemSetting.set_value('squid_log_file_offset', str(valid_offset), 'Offset do arquivo access.log')

        # Atualiza sublinks descobertos agregados
        if discovered_sublinks_batch:
            from django.db.models import F
            now = timezone.now()
            for d_name, d_data in discovered_sublinks_batch.items():
                sub, created = DiscoveredSublink.objects.get_or_create(
                    domain=d_name,
                    defaults={
                        'origin_hub': d_data['hub'],
                        'last_requested_url': d_data['url'],
                        'hit_count': d_data['hits']
                    }
                )
                if not created:
                    DiscoveredSublink.objects.filter(id=sub.id).update(
                        hit_count=F('hit_count') + d_data['hits'],
                        last_seen=now,
                        origin_hub=d_data['hub'] if not sub.origin_hub else sub.origin_hub,
                        last_requested_url=d_data['url'] or sub.last_requested_url
                    )

        del chunk_logs
        del discovered_sublinks_batch
        gc.collect()

        return total_processed
    except Exception as e:
        print(f"Erro ao ler access.log do Squid: {e}")
        return total_processed


