import os
import ssl
import sys
import dns.resolver
from ldap3 import Server, Connection, ALL, SIMPLE, Tls
from django.utils import timezone
from dashboard.models import SystemSetting
from squid.models import DeviceHost


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


def sync_devices_from_ad():
    """
    Consulta todos os computadores cadastrados no Active Directory via LDAPS (porta 636)
    e resolve seus respectivos endereços IP através do servidor DNS do AD.
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
                            'hostname': name,
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

    SystemSetting.set_value('ad_last_sync', timezone.now().strftime('%d/%m/%Y %H:%M:%S'), 'Última sincronização com o Active Directory')
    SystemSetting.set_value('ad_total_synced_devices', str(created_count + updated_count), 'Total de computadores sincronizados do AD')

    msg = f"Sincronização AD concluída: {created_count} novos computadores identificados, {updated_count} IPs atualizados!"
    return (created_count + updated_count), msg
