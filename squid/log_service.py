import os
import sys
from datetime import datetime, timedelta
from urllib.parse import urlparse
from django.utils import timezone
from django.conf import settings

from .models import AccessLog, ProxyList, DomainItem
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


def parse_squid_log_line(line, port_map):
    """
    Faz o parsing de uma linha do /var/log/squid/access.log no formato nativo do Squid / SquidPanel.
    Exemplos:
    1786730000.123 45 10.40.90.101 TCP_TUNNEL/200 4520 CONNECT scielo.br:443 - HIER_DIRECT/142.250.191.14 - 9020
    ou formato nativo sem porta no final:
    1786730000.123 45 10.40.90.101 TCP_TUNNEL/200 4520 CONNECT scielo.br:443 - HIER_DIRECT/142.250.191.14 -
    """
    parts = line.strip().split()
    if len(parts) < 7:
        return None

    try:
        # 1. Timestamp UNIX
        ts_float = float(parts[0])
        log_time = datetime.fromtimestamp(ts_float, tz=timezone.utc)

        # 2. Latência
        response_time_ms = int(parts[1]) if parts[1].isdigit() else 0

        # 3. IP do Cliente
        client_ip = parts[2]

        # 4. Status HTTP / Squid
        http_status = parts[3]

        # 5. Bytes Trafegados
        bytes_sent = int(parts[4]) if parts[4].isdigit() else 0

        # 6. Método HTTP
        method = parts[5].upper()

        # 7. URL ou Host requisitado
        raw_url = parts[6]
        full_url = raw_url

        # Extrai o domínio limpo
        if '://' in raw_url:
            parsed = urlparse(raw_url)
            domain = parsed.hostname or raw_url
        else:
            domain = raw_url.split(':')[0]

        domain = domain.lstrip('.').lower()

        # 8. Mime Type
        mime_type = parts[9] if len(parts) > 9 else '-'

        # 9. Porta local de escuta (se presente na última posição)
        port_number = None
        if len(parts) >= 11 and parts[-1].isdigit():
            port_number = int(parts[-1])
        elif len(parts) >= 10 and parts[-1].isdigit():
            port_number = int(parts[-1])

        # Se não vier a porta na linha, tenta associar pela primeira porta cadastrada ou 9020
        if not port_number:
            first_port = next(iter(port_map.values()), None)
            port_number = first_port.port_number if first_port else 9020

        # Ação (ALLOWED / BLOCKED)
        is_blocked = 'DENIED' in http_status or '403' in http_status or 'ERR' in http_status
        action = 'BLOCKED' if is_blocked else 'ALLOWED'

        proxy_port = port_map.get(port_number)
        proxy_group = proxy_port.group if proxy_port else None

        return AccessLog(
            timestamp=log_time,
            client_ip=client_ip,
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
    except Exception:
        return None


def sync_logs_from_squid_file():
    """
    Lê incrementalmente as novas linhas do arquivo /var/log/squid/access.log
    e insere os registros reais no banco de dados.
    """
    log_file_path = get_squid_log_path()
    if not os.path.exists(log_file_path):
        return 0

    # Carrega mapa de portas em memória
    port_map = {p.port_number: p for p in ProxyPort.objects.select_related('group').filter(is_active=True)}

    # Pega offset anterior
    offset_str = SystemSetting.get_value('squid_log_file_offset', '0')
    try:
        last_offset = int(offset_str)
    except Exception:
        last_offset = 0

    current_size = os.path.getsize(log_file_path)

    # Se o arquivo foi rotacionado (tamanho menor que o offset), recomeça do início
    if current_size < last_offset:
        last_offset = 0

    new_logs = []

    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(last_offset)
            for line in f:
                parsed_log = parse_squid_log_line(line, port_map)
                if parsed_log:
                    new_logs.append(parsed_log)
            new_offset = f.tell()

        if new_logs:
            AccessLog.objects.bulk_create(new_logs)

        SystemSetting.set_value('squid_log_file_offset', str(new_offset), 'Offset do arquivo access.log')
        return len(new_logs)
    except Exception as e:
        print(f"Erro ao sincronizar logs do Squid: {e}")
        return 0
