import random
from datetime import timedelta
from django.utils import timezone
from django.db import models

from .models import AccessLog, ProxyList, DomainItem
from dashboard.models import ProxyGroup, ProxyPort, SystemSetting


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


def generate_mock_initial_logs_if_empty():
    """
    Gera um lote inicial de logs realistas caso a tabela AccessLog esteja vazia.
    """
    if AccessLog.objects.exists():
        return

    ports = list(ProxyPort.objects.select_related('group').filter(is_active=True))
    if not ports:
        return

    sample_domains = [
        # Educacionais / Permitidos
        ('scielo.br', 'CONNECT', 'TCP_TUNNEL/200', 'ALLOWED', 45200, 'text/html'),
        ('academia.edu', 'CONNECT', 'TCP_TUNNEL/200', 'ALLOWED', 128400, 'application/json'),
        ('khanacademy.org', 'CONNECT', 'TCP_TUNNEL/200', 'ALLOWED', 350200, 'text/html'),
        ('translate.google.com', 'CONNECT', 'TCP_TUNNEL/200', 'ALLOWED', 15800, 'application/json'),
        ('scholar.google.com', 'CONNECT', 'TCP_TUNNEL/200', 'ALLOWED', 42100, 'text/html'),
        ('github.com', 'CONNECT', 'TCP_TUNNEL/200', 'ALLOWED', 98400, 'text/html'),
        ('cloudflare.com', 'CONNECT', 'TCP_TUNNEL/200', 'ALLOWED', 8400, 'text/plain'),
        ('dicio.com.br', 'GET', 'TCP_TUNNEL/200', 'ALLOWED', 31200, 'text/html'),
        ('minhabiblioteca.com.br', 'CONNECT', 'TCP_TUNNEL/200', 'ALLOWED', 189000, 'text/html'),
        
        # Bloqueados comuns
        ('facebook.com', 'CONNECT', 'TCP_DENIED/403', 'BLOCKED', 3840, 'text/html'),
        ('instagram.com', 'CONNECT', 'TCP_DENIED/403', 'BLOCKED', 4120, 'text/html'),
        ('tiktok.com', 'CONNECT', 'TCP_DENIED/403', 'BLOCKED', 3910, 'text/html'),
        ('bet365.com', 'CONNECT', 'TCP_DENIED/403', 'BLOCKED', 2900, 'text/html'),
        ('netflix.com', 'CONNECT', 'TCP_DENIED/403', 'BLOCKED', 5120, 'text/html'),
        ('shopee.com.br', 'CONNECT', 'TCP_DENIED/403', 'BLOCKED', 4300, 'text/html'),
        ('twitter.com', 'CONNECT', 'TCP_DENIED/403', 'BLOCKED', 3700, 'text/html'),
        ('globo.com', 'CONNECT', 'TCP_DENIED/403', 'BLOCKED', 4800, 'text/html'),
        ('chatgpt.com', 'CONNECT', 'TCP_DENIED/403', 'BLOCKED', 3600, 'text/html'),
    ]

    client_ips = [
        '10.40.90.101', '10.40.90.102', '10.40.90.105', '10.40.90.110',
        '10.40.90.115', '10.40.90.120', '10.40.90.133', '10.40.90.145'
    ]

    now = timezone.now()
    logs_to_create = []

    # Cria 120 logs distribuídos nas últimas 48 horas
    for i in range(120):
        port = random.choice(ports)
        domain_info = random.choice(sample_domains)
        client_ip = random.choice(client_ips)
        
        # Minutos atrás
        mins_ago = random.randint(1, 2880) # até 2 dias
        log_time = now - timedelta(minutes=mins_ago)

        logs_to_create.append(AccessLog(
            timestamp=log_time,
            client_ip=client_ip,
            port_number=port.port_number,
            port=port,
            group=port.group,
            method=domain_info[1],
            domain=domain_info[0],
            full_url=f"https://{domain_info[0]}/",
            http_status=domain_info[2],
            action=domain_info[3],
            bytes_sent=domain_info[4] + random.randint(100, 5000),
            response_time_ms=random.randint(15, 350),
            mime_type=domain_info[5]
        ))

    AccessLog.objects.bulk_create(logs_to_create)
