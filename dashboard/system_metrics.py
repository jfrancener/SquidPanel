import os
import shutil
import time
import socket
from datetime import timedelta

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def get_cpu_metrics():
    """
    Retorna percentual de uso de CPU e Carga Média (Load Average).
    """
    load_1, load_5, load_15 = (0.0, 0.0, 0.0)
    cpu_percent = 0.0

    if hasattr(os, 'getloadavg'):
        try:
            load_1, load_5, load_15 = os.getloadavg()
        except Exception:
            pass

    if HAS_PSUTIL:
        try:
            cpu_percent = psutil.cpu_percent(interval=None)
        except Exception:
            pass
    else:
        # Estima CPU com base no load 1m e número de núcleos
        cpu_count = os.cpu_count() or 1
        cpu_percent = min(100.0, round((load_1 / cpu_count) * 100, 1))

    return {
        'percent': round(cpu_percent, 1),
        'load_1': round(load_1, 2),
        'load_5': round(load_5, 2),
        'load_15': round(load_15, 2),
        'cores': os.cpu_count() or 1
    }


def get_memory_metrics():
    """
    Retorna métricas de Memória RAM (Total, Usada, Livre e Percentual).
    """
    if HAS_PSUTIL:
        try:
            mem = psutil.virtual_memory()
            return {
                'total_gb': round(mem.total / (1024 ** 3), 2),
                'used_gb': round(mem.used / (1024 ** 3), 2),
                'free_gb': round(mem.available / (1024 ** 3), 2),
                'percent': round(mem.percent, 1)
            }
        except Exception:
            pass

    # Fallback via /proc/meminfo no Linux
    total_kb, free_kb, avail_kb = 0, 0, 0
    if os.path.exists('/proc/meminfo'):
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    parts = line.split(':')
                    if len(parts) == 2:
                        k, v = parts[0].strip(), parts[1].strip().split()[0]
                        if k == 'MemTotal':
                            total_kb = int(v)
                        elif k == 'MemFree':
                            free_kb = int(v)
                        elif k == 'MemAvailable':
                            avail_kb = int(v)
            if avail_kb == 0:
                avail_kb = free_kb
            used_kb = total_kb - avail_kb
            percent = (used_kb / total_kb * 100) if total_kb > 0 else 0
            return {
                'total_gb': round(total_kb / (1024 ** 2), 2),
                'used_gb': round(used_kb / (1024 ** 2), 2),
                'free_gb': round(avail_kb / (1024 ** 2), 2),
                'percent': round(percent, 1)
            }
        except Exception:
            pass

    return {
        'total_gb': 4.0,
        'used_gb': 1.0,
        'free_gb': 3.0,
        'percent': 25.0
    }


def get_disk_metrics():
    """
    Retorna espaço em disco da partição raiz (/).
    """
    try:
        usage = shutil.disk_usage('/')
        total_gb = round(usage.total / (1024 ** 3), 1)
        used_gb = round(usage.used / (1024 ** 3), 1)
        free_gb = round(usage.free / (1024 ** 3), 1)
        percent = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0
        return {
            'total_gb': total_gb,
            'used_gb': used_gb,
            'free_gb': free_gb,
            'percent': percent
        }
    except Exception:
        return {
            'total_gb': 32.0,
            'used_gb': 8.0,
            'free_gb': 24.0,
            'percent': 25.0
        }


def get_internet_status():
    """
    Testa a conectividade de internet através de socket TCP rápido com DNS público (1.1.1.1:53 ou 8.8.8.8:53).
    Mede a latência real em milissegundos.
    """
    targets = [('1.1.1.1', 53), ('8.8.8.8', 53), ('10.40.88.1', 53)]
    for host, port in targets:
        try:
            start = time.perf_counter()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.2)
            sock.connect((host, port))
            sock.close()
            latency_ms = round((time.perf_counter() - start) * 1000, 1)
            return {
                'online': True,
                'status_text': 'Online',
                'latency_ms': latency_ms,
                'target': host
            }
        except Exception:
            continue

    return {
        'online': False,
        'status_text': 'Sem Internet / Gateway Indisponível',
        'latency_ms': 0,
        'target': '-'
    }


def get_server_uptime():
    """
    Retorna o tempo de atividade do servidor formatado.
    """
    if os.path.exists('/proc/uptime'):
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
                days = int(uptime_seconds // 86400)
                hours = int((uptime_seconds % 86400) // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                parts = []
                if days > 0:
                    parts.append(f"{days}d")
                if hours > 0:
                    parts.append(f"{hours}h")
                parts.append(f"{minutes}m")
                return " ".join(parts)
        except Exception:
            pass
    return "Ativo"


def get_network_info():
    """
    Retorna o Gateway, DNS Primário e IP de Escuta do servidor (com suporte a configuração manual no painel e detecção no SO).
    """
    from dashboard.models import SystemSetting

    # 1. IP de Escuta
    server_ip = SystemSetting.get_value('server_ip', '10.40.88.5')

    # 2. Gateway
    server_gateway = SystemSetting.get_value('server_gateway', '').strip()
    if not server_gateway:
        # Detecta a rota padrão real no Linux
        if os.path.exists('/proc/net/route'):
            try:
                with open('/proc/net/route', 'r') as f:
                    for line in f:
                        fields = line.strip().split()
                        if len(fields) >= 3 and fields[1] == '00000000':
                            gw_hex = fields[2]
                            server_gateway = socket.inet_ntoa(bytes.fromhex(gw_hex)[::-1])
                            break
            except Exception:
                pass
        if not server_gateway:
            server_gateway = '10.40.91.254'

    # 3. DNS Primário
    server_dns = SystemSetting.get_value('server_dns', '').strip()
    primary_dns = ''
    if server_dns:
        primary_dns = server_dns.split(',')[0].strip()
    elif os.path.exists('/etc/resolv.conf'):
        try:
            with open('/etc/resolv.conf', 'r') as f:
                for line in f:
                    if line.startswith('nameserver'):
                        primary_dns = line.split()[1].strip()
                        break
        except Exception:
            pass
    if not primary_dns:
        primary_dns = '10.40.88.1'

    return {
        'server_ip': server_ip,
        'gateway': server_gateway,
        'primary_dns': primary_dns
    }


def get_full_system_telemetry():
    """
    Consolida todas as métricas do servidor em um único dicionário para o Dashboard.
    """
    net_info = get_network_info()
    return {
        'cpu': get_cpu_metrics(),
        'memory': get_memory_metrics(),
        'disk': get_disk_metrics(),
        'internet': get_internet_status(),
        'uptime': get_server_uptime(),
        'server_ip': net_info['server_ip'],
        'gateway': net_info['gateway'],
        'primary_dns': net_info['primary_dns']
    }

