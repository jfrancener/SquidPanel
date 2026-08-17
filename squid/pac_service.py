from django.http import HttpResponse, Http404
from django.conf import settings
from dashboard.models import SystemSetting, ProxyPort


def generate_pac_content(port_number=None, fallback_direct=True):
    """
    Gera o conteúdo JavaScript padronizado para Proxy Auto-Configuration (PAC / WPAD)
    com suporte nativo a bypass de rede local e failover transparente para DIRECT.
    """
    server_ip = SystemSetting.get_value('server_ip', '10.40.90.99')
    
    # Se nenhuma porta foi especificada, pega a primeira porta ativa ou 9010
    if not port_number:
        first_port = ProxyPort.objects.filter(is_active=True).order_by('port_number').first()
        port_number = first_port.port_number if first_port else 9010

    # Definição do retorno de proxy
    if fallback_direct:
        proxy_rule = f'PROXY {server_ip}:{port_number}; DIRECT'
    else:
        proxy_rule = f'PROXY {server_ip}:{port_number}'

    lines = [
        f"// ========================================================",
        f"// SQUIDPANEL - PROXY AUTO-CONFIGURATION (PAC)",
        f"// Porta de Destino: {port_number} | Servidor: {server_ip}",
        f"// Modo Fallback Alta Disponibilidade: {'ATIVO (DIRECT)' if fallback_direct else 'DESATIVADO (ESTRITO)'}",
        f"// ========================================================\n",
        f"function FindProxyForURL(url, host) {{",
        f"    // 1. Conexões para a rede local, localhost e intranet navegam direto (DIRECT)",
        f"    if (isPlainHostName(host) ||",
        f"        shExpMatch(host, '*.local') ||",
        f"        shExpMatch(host, '*.pij.local') ||",
        f"        shExpMatch(host, 'localhost') ||",
        f"        shExpMatch(host, '127.0.0.1') ||",
        f"        isInNet(host, '10.0.0.0', '255.0.0.0') ||",
        f"        isInNet(host, '172.16.0.0', '255.240.0.0') ||",
        f"        isInNet(host, '192.168.0.0', '255.255.0.0')) {{",
        f"        return 'DIRECT';",
        f"    }}",
        f"",
        f"    // 2. Direciona para o Proxy Squid. Se o servidor estiver offline, navega DIRECT!",
        f"    return '{proxy_rule}';",
        f"}}",
        f""
    ]

    return "\n".join(lines)


def pac_response(port_number=None, fallback_direct=True, filename=None):
    """
    Retorna uma HttpResponse com o cabeçalho correto para scripts PAC/WPAD.
    """
    content = generate_pac_content(port_number=port_number, fallback_direct=fallback_direct)
    
    response = HttpResponse(content, content_type='application/x-ns-proxy-autoconfig; charset=utf-8')
    if filename:
        response['Content-Disposition'] = f'inline; filename="{filename}"'
    else:
        response['Content-Disposition'] = f'inline; filename="proxy_{port_number or "auto"}.pac"'
    
    # Headers para evitar cache antigo no Windows
    response['Cache-Control'] = 'no-cache, must-revalidate'
    response['Pragma'] = 'no-cache'
    return response
