import xml.etree.ElementTree as ET
import xml.dom.minidom
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import models
from dashboard.models import SystemSetting, ProxyGroup, ProxyPort, UserProfile
from squid.models import ProxyList, DomainItem, DeviceHost, AccessLog


def generate_configuration_xml():
    """
    Gera um documento XML completo e estruturado com todas as configurações do servidor:
    Parâmetros gerais, Grupos, Portas/Salas, Whitelists, Blacklists, Domínios e Equipamentos.
    """
    root = ET.Element("squidpanel", {
        "version": "2.0",
        "exported_at": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "America/Sao_Paulo",
        "server": SystemSetting.get_value("server_name", "SquidPanel - Proxy Server")
    })

    # 1. Parâmetros Gerais do Sistema
    settings_elem = ET.SubElement(root, "system_settings")
    for s in SystemSetting.objects.all().order_by("key"):
        s_elem = ET.SubElement(settings_elem, "setting", {
            "key": s.key,
            "description": s.description or ""
        })
        s_elem.text = s.value

    # 2. Listas (Whitelists e Blacklists) e seus respectivos Domínios
    lists_elem = ET.SubElement(root, "lists")
    for pl in ProxyList.objects.prefetch_related("domains").all().order_by("list_type", "name"):
        pl_elem = ET.SubElement(lists_elem, "list", {
            "id": str(pl.id),
            "name": pl.name,
            "type": pl.list_type,
            "is_mandatory": "true" if pl.is_mandatory else "false",
            "is_active": "true" if pl.is_active else "false"
        })
        if pl.description:
            desc_elem = ET.SubElement(pl_elem, "description")
            desc_elem.text = pl.description

        domains_elem = ET.SubElement(pl_elem, "domains", {
            "count": str(pl.domains.count())
        })
        for d in pl.domains.filter(is_active=True).order_by("domain"):
            d_elem = ET.SubElement(domains_elem, "domain", {
                "id": str(d.id),
                "is_active": "true" if d.is_active else "false",
                "description": d.description or ""
            })
            d_elem.text = d.domain

    # 3. Grupos e Portas / Salas
    groups_elem = ET.SubElement(root, "groups")
    for g in ProxyGroup.objects.prefetch_related("ports", "whitelists", "blacklists").filter(is_active=True).order_by("name"):
        g_elem = ET.SubElement(groups_elem, "group", {
            "id": str(g.id),
            "name": g.name,
            "default_policy": g.default_policy,
            "is_active": "true" if g.is_active else "false"
        })
        if g.description:
            g_desc = ET.SubElement(g_elem, "description")
            g_desc.text = g.description

        # Portas vinculadas ao grupo
        ports_elem = ET.SubElement(g_elem, "ports", {"count": str(g.ports.count())})
        for p in g.ports.filter(is_active=True).order_by("port_number"):
            ET.SubElement(ports_elem, "port", {
                "id": str(p.id),
                "port_number": str(p.port_number),
                "name": p.name,
                "current_status": p.current_status,
                "is_active": "true" if p.is_active else "false"
            })

        # Whitelists do grupo
        gw_elem = ET.SubElement(g_elem, "assigned_whitelists")
        for wl in g.whitelists.filter(is_active=True):
            ET.SubElement(gw_elem, "whitelist_ref", {"id": str(wl.id), "name": wl.name})

        # Blacklists do grupo
        gb_elem = ET.SubElement(g_elem, "assigned_blacklists")
        for bl in g.blacklists.filter(is_active=True):
            ET.SubElement(gb_elem, "blacklist_ref", {"id": str(bl.id), "name": bl.name})

    # 4. Equipamentos / Hostnames Mapeados
    devices_elem = ET.SubElement(root, "devices", {"count": str(DeviceHost.objects.count())})
    for dev in DeviceHost.objects.all().order_by("hostname", "ip_address"):
        ET.SubElement(devices_elem, "device", {
            "ip_address": dev.ip_address,
            "hostname": dev.hostname,
            "description": dev.description or ""
        })

    # Formatação com identação limpa
    rough_string = ET.tostring(root, "utf-8")
    reparsed = xml.dom.minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding="utf-8")


def export_logs_to_txt(filters):
    """
    Exporta logs de acesso filtrados em formato .TXT limpo e legível para auditoria.
    """
    logs_qs = AccessLog.objects.select_related("port", "group").all()

    # 1. Filtro de Período
    period = filters.get("period", "today")
    now = timezone.now()

    if period == "today":
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        logs_qs = logs_qs.filter(timestamp__gte=start_of_day)
    elif period == "yesterday":
        start_yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_yesterday = start_yesterday + timedelta(days=1)
        logs_qs = logs_qs.filter(timestamp__gte=start_yesterday, timestamp__lt=end_yesterday)
    elif period == "7d":
        logs_qs = logs_qs.filter(timestamp__gte=now - timedelta(days=7))
    elif period == "30d":
        logs_qs = logs_qs.filter(timestamp__gte=now - timedelta(days=30))
    elif period == "custom":
        date_from = filters.get("date_from")
        date_to = filters.get("date_to")
        time_from = filters.get("time_from", "00:00")
        time_to = filters.get("time_to", "23:59")
        if date_from:
            try:
                dt_from = timezone.make_aware(datetime.strptime(f"{date_from} {time_from}", "%Y-%m-%d %H:%M"))
                logs_qs = logs_qs.filter(timestamp__gte=dt_from)
            except Exception:
                pass
        if date_to:
            try:
                dt_to = timezone.make_aware(datetime.strptime(f"{date_to} {time_to}", "%Y-%m-%d %H:%M"))
                logs_qs = logs_qs.filter(timestamp__lte=dt_to)
            except Exception:
                pass

    # 2. Filtro de Porta
    port_id = filters.get("port_id")
    if port_id and port_id.isdigit():
        logs_qs = logs_qs.filter(port_id=int(port_id))

    # 3. Filtro de Ação
    action = filters.get("action", "ALL")
    if action in ["ALLOWED", "BLOCKED"]:
        logs_qs = logs_qs.filter(action=action)

    # 4. Filtro por Hostname / IP
    hostname_ip = filters.get("hostname_ip", "").strip()
    if hostname_ip:
        logs_qs = logs_qs.filter(
            models.Q(hostname__icontains=hostname_ip) |
            models.Q(client_ip__icontains=hostname_ip)
        )

    # 5. Ordenação cronológica crescente para exportação de relatório
    logs_qs = logs_qs.order_by("timestamp")

    log_format = filters.get("format", "human")

    lines = []
    lines.append("=" * 110)
    lines.append(f" SQUIDPANEL - RELATÓRIO DE AUDITORIA DE LOGS DE ACESSO")
    lines.append(f" Gerado em: {timezone.now().strftime('%d/%m/%Y %H:%M:%S')} (Horário de Brasília - UTC-3)")
    lines.append(f" Total de Registros Exportados: {logs_qs.count()}")
    lines.append("=" * 110)
    lines.append("")

    if log_format == "squid":
        # Formato Nativo Squid: ts latency ip status bytes method url user peer mime port
        lines.append("# Formato: [TIMESTAMP_UNIX] [LATENCIA_MS] [IP_CLIENTE] [STATUS_SQUID] [BYTES] [METODO] [URL/DOMINIO] [PORTA] [HOSTNAME]")
        lines.append("-" * 110)
        for log in logs_qs.iterator(chunk_size=1000):
            ts = log.timestamp.timestamp()
            host = log.hostname or "-"
            lines.append(f"{ts:.3f} {log.response_time_ms} {log.client_ip} {log.http_status} {log.bytes_sent} {log.method} {log.domain} {log.port_number} {host}")
    else:
        # Formato Legível com Colunas Alinhadas
        header = f"{'DATA/HORA':<20} | {'PORTA':<6} | {'SALA / GRUPO':<22} | {'IP CLIENTE':<15} | {'HOSTNAME':<18} | {'STATUS':<10} | {'BYTES':<10} | {'DOMÍNIO / DESTINO'}"
        lines.append(header)
        lines.append("-" * 140)

        for log in logs_qs.iterator(chunk_size=1000):
            local_time = timezone.localtime(log.timestamp).strftime("%d/%m/%Y %H:%M:%S")
            room_name = (log.port.name if log.port else (log.group.name if log.group else "-"))[:20]
            host_display = (log.hostname or "-")[:17]
            bytes_str = log.formatted_bytes
            status_str = "BLOQUEADO" if log.action == "BLOCKED" else "PERMITIDO"
            
            line_str = f"{local_time:<20} | {log.port_number:<6} | {room_name:<22} | {log.client_ip:<15} | {host_display:<18} | {status_str:<10} | {bytes_str:<10} | {log.domain}"
            lines.append(line_str)

    lines.append("")
    lines.append("=" * 110)
    lines.append(" FIM DO RELATÓRIO DE AUDITORIA - SQUIDPANEL")
    lines.append("=" * 110)

    return "\n".join(lines)
