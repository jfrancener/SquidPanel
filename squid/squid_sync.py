import os
import sys
import subprocess
from django.conf import settings
from django.utils import timezone
from dashboard.models import ProxyGroup, ProxyPort, SystemSetting
from squid.models import ProxyList, DomainItem


def get_squid_paths():
    """
    Retorna os caminhos dos arquivos do Squid conforme o sistema operacional.
    """
    if sys.platform == 'win32':
        base_dir = os.path.join(settings.BASE_DIR, 'scratch', 'squid_config')
        os.makedirs(os.path.join(base_dir, 'lists'), exist_ok=True)
        return {
            'conf_file': os.path.join(base_dir, 'squid.conf'),
            'lists_dir': os.path.join(base_dir, 'lists'),
            'is_linux': False
        }
    else:
        lists_dir = '/etc/squid/lists'
        os.makedirs(lists_dir, exist_ok=True)
        return {
            'conf_file': '/etc/squid/squid.conf',
            'lists_dir': lists_dir,
            'is_linux': True
        }


def mark_squid_sync_needed():
    """
    Marca que existem alterações pendentes de sincronização com o Squid.
    """
    SystemSetting.set_value('squid_pending_sync', 'true', 'Existem alterações pendentes de aplicação no Squid')


def mark_squid_sync_completed():
    """
    Marca que a sincronização foi aplicada com sucesso.
    """
    SystemSetting.set_value('squid_pending_sync', 'false', 'Squid sincronizado')
    SystemSetting.set_value('squid_last_sync', timezone.now().strftime('%d/%m/%Y %H:%M:%S'), 'Data da última sincronização')


def is_squid_sync_needed():
    """
    Verifica se há alterações pendentes.
    """
    return SystemSetting.get_value('squid_pending_sync', 'false') == 'true'


def generate_squid_config_and_lists():
    """
    Gera dinamicamente todos os arquivos de Whitelist/Blacklist e o /etc/squid/squid.conf
    com base nos Grupos, Portas e Listas cadastrados no SquidPanel.
    """
    paths = get_squid_paths()
    lists_dir = paths['lists_dir']
    conf_file = paths['conf_file']

    # 1. Gera o arquivo de Whitelist Obrigatória do Sistema
    mandatory_domains = set()
    mandatory_lists = ProxyList.objects.filter(list_type='WHITELIST', is_mandatory=True, is_active=True)
    for ml in mandatory_lists:
        domains = ml.domains.filter(is_active=True).values_list('domain', flat=True)
        mandatory_domains.update(domains)

    mandatory_file_path = os.path.join(lists_dir, 'mandatory_whitelist.txt')
    with open(mandatory_file_path, 'w', encoding='utf-8') as f:
        f.write("# Whitelists Obrigatorias do Sistema (SquidPanel)\n")
        for d in sorted(mandatory_domains):
            f.write(f"{d}\n")

    # 2. Gera arquivos de listas por Grupo
    groups = ProxyGroup.objects.prefetch_related('whitelists', 'blacklists', 'ports').filter(is_active=True)
    
    group_list_files = {}

    for g in groups:
        # Whitelists do grupo
        g_wl_domains = set()
        for wl in g.whitelists.filter(is_active=True):
            g_wl_domains.update(wl.domains.filter(is_active=True).values_list('domain', flat=True))

        wl_file_path = os.path.join(lists_dir, f"group_{g.id}_whitelist.txt")
        with open(wl_file_path, 'w', encoding='utf-8') as f:
            f.write(f"# Whitelist do Grupo: {g.name}\n")
            for d in sorted(g_wl_domains):
                f.write(f"{d}\n")

        # Blacklists do grupo
        g_bl_domains = set()
        for bl in g.blacklists.filter(is_active=True):
            g_bl_domains.update(bl.domains.filter(is_active=True).values_list('domain', flat=True))

        bl_file_path = os.path.join(lists_dir, f"group_{g.id}_blacklist.txt")
        with open(bl_file_path, 'w', encoding='utf-8') as f:
            f.write(f"# Blacklist do Grupo: {g.name}\n")
            for d in sorted(g_bl_domains):
                f.write(f"{d}\n")

        group_list_files[g.id] = {
            'wl_path': wl_file_path,
            'bl_path': bl_file_path,
            'has_wl': len(g_wl_domains) > 0,
            'has_bl': len(g_bl_domains) > 0,
        }

    # 3. Monta o conteúdo completo do squid.conf
    dns_servers = SystemSetting.get_value('server_dns', '1.1.1.1 8.8.8.8').replace(',', ' ')
    active_ports = list(ProxyPort.objects.select_related('group').filter(is_active=True).order_by('port_number'))

    conf_lines = []
    conf_lines.append("# ========================================================")
    conf_lines.append(f"# SQUID.CONF GERADO AUTOMATICAMENTE PELO SQUIDPANEL")
    conf_lines.append(f"# Gerado em: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}")
    conf_lines.append("# ========================================================\n")

    # Parâmetros de Servidor e DNS
    conf_lines.append("# --- Servidores DNS ---")
    conf_lines.append(f"dns_nameservers {dns_servers}\n")

    # Portas de Escuta Dinâmicas
    conf_lines.append("# --- Portas de Escuta das Salas e Grupos ---")
    for p in active_ports:
        conf_lines.append(f"http_port {p.port_number} name=port_{p.port_number}")
    conf_lines.append("")

    # ACLs Básicas de Rede e Segurança
    conf_lines.append("# --- ACLs Padroes de Seguranca ---")
    conf_lines.append("acl SSL_ports port 443")
    conf_lines.append("acl Safe_ports port 80          # http")
    conf_lines.append("acl Safe_ports port 21          # ftp")
    conf_lines.append("acl Safe_ports port 443         # https")
    conf_lines.append("acl Safe_ports port 1025-65535  # portas altas")
    conf_lines.append("acl CONNECT method CONNECT\n")

    # ACLs de Porta
    conf_lines.append("# --- ACLs Mapeadas por Porta ---")
    for p in active_ports:
        conf_lines.append(f"acl myport_{p.port_number} myportname port_{p.port_number}")
    conf_lines.append("")

    # ACLs de Domínios Obrigatórios
    conf_lines.append("# --- ACL de Whitelist Obrigatoria do Sistema ---")
    conf_lines.append(f'acl mandatory_whitelist dstdomain "{mandatory_file_path}"\n')

    # ACLs de Domínios por Grupo
    conf_lines.append("# --- ACLs de Whitelists e Blacklists por Grupo ---")
    for g in groups:
        files = group_list_files[g.id]
        conf_lines.append(f'acl group_{g.id}_wl dstdomain "{files["wl_path"]}"')
        conf_lines.append(f'acl group_{g.id}_bl dstdomain "{files["bl_path"]}"')
    conf_lines.append("")

    # Regras de Segurança Padrão
    conf_lines.append("# --- Regras de Seguranca Basicas ---")
    conf_lines.append("http_access deny !Safe_ports")
    conf_lines.append("http_access deny CONNECT !SSL_ports")
    conf_lines.append("http_access allow localhost manager")
    conf_lines.append("http_access deny manager\n")

    # Regras de Acesso por Porta e Status
    conf_lines.append("# ========================================================")
    conf_lines.append("# REGRAS DE ACESSO POR SALA / PORTA (SQUIDPANEL)")
    conf_lines.append("# ========================================================")

    for p in active_ports:
        g = p.group
        conf_lines.append(f"\n# Porta {p.port_number}: {p.name} (Grupo: {g.name}) - Modo: {p.current_status}")

        if p.current_status == 'ALLOWED':
            # Modo Liberado Total (100% Livre, sem Blacklist)
            conf_lines.append(f"http_access allow myport_{p.port_number}")

        elif p.current_status == 'BLACKLIST':
            # Modo Liberado com Blacklist
            conf_lines.append(f"http_access deny myport_{p.port_number} group_{g.id}_bl")
            conf_lines.append(f"http_access allow myport_{p.port_number}")

        else:
            # Modo Whitelist (Padrão Seguro)
            conf_lines.append(f"http_access allow myport_{p.port_number} mandatory_whitelist")
            conf_lines.append(f"http_access allow myport_{p.port_number} group_{g.id}_wl")
            conf_lines.append(f"http_access deny myport_{p.port_number}")

    # Bloqueio Geral no Final
    conf_lines.append("\n# --- Bloqueio Padrao no Final ---")
    conf_lines.append("http_access allow localhost")
    conf_lines.append("http_access deny all\n")

    # Logs e Otimizações
    conf_lines.append("# --- Configuracoes de Log e Cache ---")
    conf_lines.append("logformat squidpanel %ts.%03tu %6tr %>a %Ss/%03>Hs %<st %rm %ru %[un %Sh/%<a %mt %lp")
    conf_lines.append("access_log /var/log/squid/access.log squidpanel")
    conf_lines.append("buffered_logs off")
    conf_lines.append("logfile_rotate 10")
    conf_lines.append("coredump_dir /var/spool/squid")
    conf_lines.append("visible_hostname SquidPanel")
    conf_lines.append("forwarded_for on")
    conf_lines.append("via on\n")

    # Escreve o squid.conf
    with open(conf_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(conf_lines))

    # Ajusta permissões no Linux se necessário
    if paths['is_linux']:
        try:
            os.system(f"chown -R proxy:proxy {lists_dir} {conf_file} 2>/dev/null || true")
            os.system(f"chmod -R 755 {lists_dir} 2>/dev/null || true")
        except Exception:
            pass

    return conf_file, lists_dir


def _get_cmd_prefix():
    if sys.platform != 'win32' and hasattr(os, 'geteuid') and os.geteuid() != 0:
        return ['sudo']
    return []


def apply_squid_changes():
    """
    Gera a configuração atualizada e aplica imediatamente no Squid (squid -k reconfigure).
    """
    conf_file, lists_dir = generate_squid_config_and_lists()
    paths = get_squid_paths()

    if paths['is_linux']:
        prefix = _get_cmd_prefix()
        # Testa sintaxe primeiro
        res_test = subprocess.run(prefix + ['squid', '-k', 'parse'], capture_output=True, text=True)
        if res_test.returncode != 0:
            return False, f"Erro de sintaxe no Squid: {res_test.stderr}"

        # Recarrega configurações
        res_reconfig = subprocess.run(prefix + ['squid', '-k', 'reconfigure'], capture_output=True, text=True)
        if res_reconfig.returncode != 0:
            # Se não estiver rodando, tenta iniciar
            subprocess.run(prefix + ['systemctl', 'restart', 'squid'], capture_output=True, text=True)

    mark_squid_sync_completed()
    return True, "Configurações aplicadas e recarregadas no Squid com sucesso!"


def restart_squid_service():
    """
    Reinicia completamente o serviço do Squid (systemctl restart squid).
    """
    conf_file, lists_dir = generate_squid_config_and_lists()
    paths = get_squid_paths()

    if paths['is_linux']:
        prefix = _get_cmd_prefix()
        res = subprocess.run(prefix + ['systemctl', 'restart', 'squid'], capture_output=True, text=True)
        if res.returncode != 0:
            return False, f"Erro ao reiniciar o Squid: {res.stderr}"

    mark_squid_sync_completed()
    return True, "Serviço do Squid reiniciado com sucesso!"

