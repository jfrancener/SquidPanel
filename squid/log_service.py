import os
import sys
from datetime import datetime, timezone as dt_timezone, timedelta
from urllib.parse import urlparse
from django.utils import timezone
from django.conf import settings

from .models import AccessLog, ProxyList, DomainItem, DeviceHost
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

        # Extrai o domínio limpo
        if '://' in raw_url:
            parsed = urlparse(raw_url)
            domain = parsed.hostname or raw_url
        else:
            domain = raw_url.split(':')[0]

        domain = domain.lstrip('.').lower()

        # 9. Mime Type
        mime_type = parts[9] if len(parts) > 9 else '-'

        # 10. Porta local de escuta (se presente na última posição)
        port_number = None
        if len(parts) >= 11 and parts[-1].isdigit():
            port_number = int(parts[-1])
        elif len(parts) >= 10 and parts[-1].isdigit():
            port_number = int(parts[-1])

        # Se não vier a porta na linha, tenta associar pela primeira porta cadastrada ou 9020
        if not port_number:
            first_port = next(iter(port_map.values()), None)
            port_number = first_port.port_number if first_port else 9020

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


def sync_logs_from_squid_file():
    """
    Lê incrementalmente as novas linhas completas do arquivo /var/log/squid/access.log
    e insere os registros reais no banco de dados com seus respectivos hostnames.
    """
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

    new_logs = []
    valid_offset = last_offset

    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(last_offset)
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
                    new_logs.append(parsed_log)

        if new_logs:
            AccessLog.objects.bulk_create(new_logs)

        SystemSetting.set_value('squid_log_file_offset', str(valid_offset), 'Offset do arquivo access.log')
        return len(new_logs)
    except Exception as e:
        print(f"Erro ao ler access.log do Squid: {e}")
        return 0


