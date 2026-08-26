import os
import ssl
import sys
import socket
import dns.resolver
import dns.reversename
from ldap3 import Server, Connection, ALL, SIMPLE, Tls
from django.utils import timezone
from dashboard.models import SystemSetting
from squid.models import DeviceHost, AccessLog


def get_ad_config():
    """
    Retorna as configurações do Active Directory salvas no banco.
    """
    return {
        'server_ip': SystemSetting.get_value('ad_server_ip', '10.40.88.1'),
        'server_ip_secondary': SystemSetting.get_value('ad_server_ip_secondary', '10.40.88.2'),
        'domain': SystemSetting.get_value('ad_domain', 'pij.local'),
        'user': SystemSetting.get_value('ad_user', 'informatica@pij.local'),
        'password': SystemSetting.get_value('ad_password', 'info@pij3948'),
        'base_dn': SystemSetting.get_value('ad_base_dn', 'DC=pij,DC=local'),
    }


def query_netbios_name(ip_address, timeout=0.5):
    """
    Consulta o nome NetBIOS da máquina através de pacote Node Status Request (UDP 137).
    Funciona em estações Windows e servidores mesmo sem registro no DNS do AD.
    """
    if not ip_address:
        return None

    # Pacote NetBIOS Node Status Request (RFC 1002)
    query = b'\x82\x28\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x20CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\x00\x00\x21\x00\x01'
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(query, (ip_address, 137))
        data, _ = sock.recvfrom(1024)
        sock.close()

        if len(data) > 57:
            num_names = data[56]
            for i in range(num_names):
                offset = 57 + (i * 18)
                if offset + 18 <= len(data):
                    name = data[offset:offset+15].decode('ascii', errors='ignore').strip()
                    name_type = data[offset+15]
                    flags = int.from_bytes(data[offset+16:offset+18], 'big')
                    is_group = bool(flags & 0x8000)
                    # Tipo 0x00 = Workstation / Nome da máquina individual
                    if not is_group and name_type == 0x00 and name:
                        return name.upper()
    except Exception:
        pass
    return None


def resolve_ip_hostname(ip_address, ad_resolver=None):
    """
    Tenta resolver o hostname de um IP usando múltiplas fontes:
    1. Consulta NetBIOS direta (UDP 137)
    2. Consulta PTR no DNS do AD
    3. Resolução padrão do sistema
    """
    # 1. NetBIOS (Mais preciso e rápido para rede Windows local)
    nb_name = query_netbios_name(ip_address)
    if nb_name:
        return nb_name, "Descoberta NetBIOS (UDP 137)"

    # 2. DNS Reverso (PTR) nos servidores do AD
    if ad_resolver:
        try:
            rev_name = dns.reversename.from_address(ip_address)
            answers = ad_resolver.resolve(rev_name, 'PTR')
            if answers:
                ptr_host = str(answers[0]).rstrip('.').split('.')[0].upper()
                if ptr_host and not ptr_host.startswith('10.'):
                    return ptr_host, "DNS Reverso AD (PTR)"
        except Exception:
            pass

    # 3. gethostbyaddr do SO
    try:
        host, _, _ = socket.gethostbyaddr(ip_address)
        clean = host.split('.')[0].upper()
        if clean and not clean.startswith('10.'):
            return clean, "DNS Reverso Sistema"
    except Exception:
        pass

    return None, None


def discover_hostnames_from_active_logs():
    """
    Varre os IPs ativos mais recentes que estão sem hostname nos logs de acesso
    e tenta identificá-los ativamente na rede.
    """
    config = get_ad_config()
    ad_resolver = dns.resolver.Resolver()
    ad_resolver.nameservers = [config['server_ip'], config['server_ip_secondary']]
    ad_resolver.timeout = 0.6
    ad_resolver.lifetime = 0.8

    # Busca os IPs sem hostname que mais geram tráfego recente
    unresolved_ips = list(
        AccessLog.objects.filter(hostname__in=['', '-', 'None', None])
        .values_list('client_ip', flat=True)
        .distinct()[:50]
    )

    discovered = 0
    for ip in unresolved_ips:
        # Se já existe no DeviceHost, pula
        if DeviceHost.objects.filter(ip_address=ip).exists():
            continue

        name, source = resolve_ip_hostname(ip, ad_resolver)
        if name:
            DeviceHost.objects.update_or_create(
                ip_address=ip,
                defaults={
                    'hostname': name,
                    'description': source or 'Descoberta Automática de Rede'
                }
            )
            discovered += 1

    return discovered


def sync_devices_from_ad():
    """
    Consulta todos os computadores cadastrados no Active Directory via LDAPS (porta 636)
    e resolve seus respectivos endereços IP através do servidor DNS do AD e NetBIOS.
    Atualiza automaticamente a tabela DeviceHost no banco de dados.
    """
    config = get_ad_config()
    server_ip = config['server_ip']
    secondary_ip = config['server_ip_secondary']
    user = config['user']
    password = config['password']
    base_dn = config['base_dn']
    domain = config['domain']

    try:
        tls_config = Tls(validate=ssl.CERT_NONE)
        server_ssl = Server(server_ip, port=636, use_ssl=True, tls=tls_config, connect_timeout=4)
        conn = Connection(server_ssl, user=user, password=password, authentication=SIMPLE, auto_bind=True)
    except Exception as e:
        # Tenta no servidor secundário se o primário falhar
        try:
            server_ssl2 = Server(secondary_ip, port=636, use_ssl=True, tls=tls_config, connect_timeout=4)
            conn = Connection(server_ssl2, user=user, password=password, authentication=SIMPLE, auto_bind=True)
        except Exception as e2:
            return 0, f"Falha ao conectar no AD ({server_ip} / {secondary_ip}): {e2}"

    # Configura o resolvedor DNS apontando para os controladores de domínio
    ad_resolver = dns.resolver.Resolver()
    ad_resolver.nameservers = [server_ip, secondary_ip]
    ad_resolver.timeout = 0.8
    ad_resolver.lifetime = 1.0

    try:
        conn.search(
            search_base=base_dn,
            search_filter='(objectClass=computer)',
            attributes=['name', 'dNSHostName', 'operatingSystem', 'description']
        )
    except Exception as e:
        return 0, f"Erro na consulta LDAP de computadores: {e}"

    entries = conn.entries
    if not entries:
        return 0, "Nenhum computador retornado pelo AD."

    updated_count = 0
    created_count = 0

    for e in entries:
        name = str(e.name).strip() if e.name else None
        if not name:
            continue

        dns_name = str(e.dNSHostName).strip() if e.dNSHostName else f"{name}.{domain}"
        desc = str(e.description).strip() if e.description else str(e.operatingSystem or '').strip()

        try:
            answers = ad_resolver.resolve(dns_name, 'A')
            for rdata in answers:
                ip = str(rdata).strip()
                if ip:
                    dev, created = DeviceHost.objects.update_or_create(
                        ip_address=ip,
                        defaults={
                            'hostname': name.upper(),
                            'description': desc or f"Domínio {domain}"
                        }
                    )
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
        except Exception:
            # Computador offline ou sem registro DNS no momento
            pass

    # Varredura complementar em IPs que geram tráfego nos logs mas não estão no AD
    try:
        discovered = discover_hostnames_from_active_logs()
        created_count += discovered
    except Exception:
        pass

    SystemSetting.set_value('ad_last_sync', timezone.now().strftime('%d/%m/%Y %H:%M:%S'), 'Última sincronização com o Active Directory')
    SystemSetting.set_value('ad_total_synced_devices', str(created_count + updated_count), 'Total de computadores sincronizados do AD')

    msg = f"Sincronização AD concluída: {created_count} novos computadores identificados, {updated_count} IPs atualizados!"
    return (created_count + updated_count), msg
