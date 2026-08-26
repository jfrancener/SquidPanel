import ssl
import json
import urllib.request
from django.utils import timezone
from dashboard.models import SystemSetting
from squid.models import DeviceHost, AccessLog


def get_tactical_config():
    """
    Retorna as configurações do Tactical RMM.
    """
    return {
        'api_url': SystemSetting.get_value('tactical_api_url', 'https://api.ftech.srv.br/agents/').strip(),
        'api_key': SystemSetting.get_value('tactical_api_key', 'FOT9QIGW4SMODWSZQIOBFDNNUZ2YQS03').strip(),
        'webhook_token': SystemSetting.get_value('tactical_webhook_token', 'sp-tactical-secure-token-2026').strip(),
    }


def sync_devices_from_tactical():
    """
    Consulta a API do Tactical RMM e sincroniza automaticamente a tabela DeviceHost.
    Também atualiza logs de acesso pendentes com os novos hostnames identificados.
    """
    config = get_tactical_config()
    api_url = config['api_url']
    api_key = config['api_key']

    if not api_url or not api_key:
        return 0, "URL da API ou Chave de API do Tactical RMM não configuradas."

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        api_url,
        headers={
            'X-API-KEY': api_key,
            'Content-Type': 'application/json',
            'User-Agent': 'SquidPanel/1.0'
        }
    )

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
            if resp.status != 200:
                return 0, f"Erro HTTP {resp.status} retornado pelo Tactical RMM."
            agents = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return 0, f"Falha na comunicação com Tactical RMM: {e}"

    if not isinstance(agents, list):
        return 0, "Resposta inesperada da API do Tactical RMM."

    updated_count = 0
    created_count = 0
    ip_to_host_map = {}

    for a in agents:
        hostname = str(a.get('hostname', '')).strip().upper()
        if not hostname:
            continue

        site_name = str(a.get('site_name', '')).strip()
        client_name = str(a.get('client_name', '')).strip()
        desc_parts = [p for p in [site_name, client_name] if p]
        desc = f"Tactical RMM ({' - '.join(desc_parts)})" if desc_parts else "Tactical RMM"

        local_ips_raw = str(a.get('local_ips', ''))
        ips = [ip.strip() for ip in local_ips_raw.replace(';', ',').split(',') if ip.strip()]

        for ip in ips:
            # Filtra apenas IPs de rede local interna válida
            if ip.startswith('10.40.') or ip.startswith('192.168.') or ip.startswith('172.'):
                ip_to_host_map[ip] = hostname
                dev, created = DeviceHost.objects.update_or_create(
                    ip_address=ip,
                    defaults={
                        'hostname': hostname,
                        'description': desc
                    }
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

    # Atualiza apenas os IPs que de fato possuem logs sem hostname no banco
    logs_updated = 0
    unresolved_ips = set(
        AccessLog.objects.filter(hostname__in=['', '-', 'None', None])
        .values_list('client_ip', flat=True)
        .distinct()
    )
    if unresolved_ips:
        for ip in unresolved_ips:
            if ip in ip_to_host_map:
                affected = AccessLog.objects.filter(
                    client_ip=ip,
                    hostname__in=['', '-', 'None', None]
                ).update(hostname=ip_to_host_map[ip])
                logs_updated += affected

    now_str = timezone.now().strftime('%d/%m/%Y %H:%M:%S')
    SystemSetting.set_value('tactical_last_sync', now_str, 'Última sincronização com Tactical RMM')
    SystemSetting.set_value('tactical_total_synced_devices', str(len(ip_to_host_map)), 'Total de IPs mapeados pelo Tactical RMM')

    msg = f"Sincronização Tactical RMM: {len(agents)} agentes consultados, {len(ip_to_host_map)} IPs vinculados ({created_count} novos, {updated_count} atualizados) e {logs_updated} logs históricos corrigidos."
    return len(ip_to_host_map), msg


def process_webhook_agent_update(data):
    """
    Processa webhook/payload enviado pelo Tactical RMM ou script local quando um agente muda de IP ou liga.
    Exemplo de payload suportado:
    {
       "hostname": "PIJ-CEJA-03",
       "ip": "10.40.91.142",
       "local_ips": "10.40.91.142, 54.232.189.113",
       "site": "CEJA"
    }
    """
    hostname = str(data.get('hostname') or data.get('name') or '').strip().upper()
    if not hostname:
        return False, "Hostname ausente no payload."

    raw_ips = []
    if 'ip' in data and data['ip']:
        raw_ips.append(str(data['ip']).strip())
    if 'local_ips' in data and data['local_ips']:
        for item in str(data['local_ips']).replace(';', ',').split(','):
            if item.strip():
                raw_ips.append(item.strip())

    if not raw_ips:
        return False, "Nenhum endereço IP informado."

    site = data.get('site') or data.get('site_name') or ''
    desc = f"Tactical RMM Webhook ({site})" if site else "Tactical RMM Webhook"

    registered = []
    for ip in raw_ips:
        if ip.startswith('10.40.') or ip.startswith('192.168.') or ip.startswith('172.'):
            DeviceHost.objects.update_or_create(
                ip_address=ip,
                defaults={
                    'hostname': hostname,
                    'description': desc
                }
            )
            # Atualiza logs sem hostname desse IP
            AccessLog.objects.filter(
                client_ip=ip,
                hostname__in=['', '-', 'None', None]
            ).update(hostname=hostname)
            registered.append(ip)

    return True, f"Hostname '{hostname}' associado aos IPs: {', '.join(registered)}"
