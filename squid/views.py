from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.db import models
from django.utils.text import slugify

from .models import ProxyList, DomainItem
from .squid_sync import apply_squid_changes, restart_squid_service, mark_squid_sync_needed, is_squid_sync_needed
from dashboard.models import ProxyGroup, ProxyPort, UserProfile

# ==========================================
# 1. GESTÃO DE GRUPOS E PORTAS (SALAS)
# ==========================================

@login_required
def groups_view(request):
    """
    Listagem e gerenciamento de Grupos de Proxy e suas respectivas Portas/Salas.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado: apenas Administradores e Coordenadores podem gerenciar Grupos.")

    query = request.GET.get('q', '').strip()
    groups = ProxyGroup.objects.prefetch_related('ports', 'whitelists', 'blacklists').filter(is_active=True).order_by('name')

    if query:
        groups = groups.filter(
            models.Q(name__icontains=query) |
            models.Q(description__icontains=query) |
            models.Q(ports__name__icontains=query)
        ).distinct()

    all_whitelists = ProxyList.objects.filter(list_type='WHITELIST', is_active=True).order_by('-is_mandatory', 'name')
    all_blacklists = ProxyList.objects.filter(list_type='BLACKLIST', is_active=True).order_by('name')
    total_ports_count = ProxyPort.objects.filter(is_active=True).count()

    return render(request, 'squid/groups_index.html', {
        'profile': profile,
        'groups': groups,
        'query': query,
        'all_whitelists': all_whitelists,
        'all_blacklists': all_blacklists,
        'total_ports_count': total_ports_count,
        'active_menu': 'groups'
    })


@login_required
def group_create_view(request):
    """
    Criação de um novo Grupo de Proxy com política e listas associadas.
    Garante que Whitelists obrigatórias sejam sempre incluídas.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        default_policy = request.POST.get('default_policy', 'WHITELIST_STRICT')
        selected_whitelists = request.POST.getlist('whitelists')
        selected_blacklists = request.POST.getlist('blacklists')

        if not name:
            messages.error(request, 'O nome do grupo é obrigatório.')
            return redirect('groups')

        if ProxyGroup.objects.filter(name=name).exists():
            messages.error(request, f"Já existe um grupo cadastrado com o nome '{name}'.")
            return redirect('groups')

        group = ProxyGroup.objects.create(
            name=name,
            description=description,
            default_policy=default_policy,
            is_active=True
        )

        if selected_whitelists:
            group.whitelists.set(selected_whitelists)
        if selected_blacklists:
            group.blacklists.set(selected_blacklists)

        # Garante que Whitelists obrigatórias estejam sempre presentes
        mandatory_wls = ProxyList.objects.filter(list_type='WHITELIST', is_mandatory=True)
        group.whitelists.add(*mandatory_wls)

        messages.success(request, f"Grupo '{name}' criado com sucesso! Agora você pode adicionar portas/salas a ele.")
        return redirect('groups')

    return redirect('groups')


@login_required
def group_edit_view(request, group_id):
    """
    Edição de um Grupo existente, suas políticas de acesso e listas vinculadas.
    Garante que Whitelists obrigatórias permaneçam sempre ativas.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    group = get_object_or_404(ProxyGroup, id=group_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        default_policy = request.POST.get('default_policy', group.default_policy)
        selected_whitelists = request.POST.getlist('whitelists')
        selected_blacklists = request.POST.getlist('blacklists')

        if not name:
            messages.error(request, 'O nome do grupo é obrigatório.')
            return redirect('groups')

        group.name = name
        group.description = description
        group.default_policy = default_policy
        group.save()

        group.whitelists.set(selected_whitelists)
        group.blacklists.set(selected_blacklists)

        # Garante que Whitelists obrigatórias continuem sempre vinculadas
        mandatory_wls = ProxyList.objects.filter(list_type='WHITELIST', is_mandatory=True)
        group.whitelists.add(*mandatory_wls)

        messages.success(request, f"Grupo '{group.name}' atualizado com sucesso!")
        return redirect('groups')

    return redirect('groups')


@login_required
def group_delete_view(request, group_id):
    """
    Exclusão de um Grupo de Proxy e suas portas.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado: apenas Administradores de TI podem excluir grupos.")

    group = get_object_or_404(ProxyGroup, id=group_id)
    name = group.name
    group.delete()

    messages.success(request, f"Grupo '{name}' e suas portas associadas foram excluídos com sucesso.")
    return redirect('groups')


# ==========================================
# 2. GESTÃO DE PORTAS / SALAS DENTRO DOS GRUPOS
# ==========================================

@login_required
def port_create_view(request, group_id):
    """
    Criação de uma nova porta de escuta / sala associada a um grupo.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    group = get_object_or_404(ProxyGroup, id=group_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        port_str = request.POST.get('port_number', '').strip()
        initial_status = request.POST.get('current_status', 'WHITELIST')

        if not name or not port_str:
            messages.error(request, 'Nome da sala e número da porta são obrigatórios.')
            return redirect('groups')

        try:
            port_number = int(port_str)
            if port_number < 1024 or port_number > 65535:
                messages.error(request, 'O número da porta deve estar entre 1024 e 65535.')
                return redirect('groups')
        except ValueError:
            messages.error(request, 'Número de porta inválido.')
            return redirect('groups')

        if ProxyPort.objects.filter(port_number=port_number).exists():
            messages.error(request, f"A porta de proxy {port_number} já está em uso por outra sala.")
            return redirect('groups')

        ProxyPort.objects.create(
            group=group,
            name=name,
            port_number=port_number,
            current_status=initial_status,
            is_active=True
        )

        messages.success(request, f"Sala '{name}' (Porta {port_number}) criada com sucesso no grupo '{group.name}'!")
        return redirect('groups')

    return redirect('groups')


@login_required
def port_edit_view(request, port_id):
    """
    Edição de dados de uma porta/sala (Nome, Grupo ou Status).
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    port = get_object_or_404(ProxyPort, id=port_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        group_id = request.POST.get('group_id')
        current_status = request.POST.get('current_status', port.current_status)

        if not name:
            messages.error(request, 'O nome da sala é obrigatório.')
            return redirect('groups')

        if group_id:
            new_group = get_object_or_404(ProxyGroup, id=group_id)
            port.group = new_group

        port.name = name
        port.current_status = current_status
        port.save()

        messages.success(request, f"Porta '{port.name}' ({port.port_number}) atualizada com sucesso!")
        return redirect('groups')

    return redirect('groups')


@login_required
def port_delete_view(request, port_id):
    """
    Exclusão de uma porta/sala do sistema.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado: apenas Administradores de TI podem excluir portas.")

    port = get_object_or_404(ProxyPort, id=port_id)
    name = port.name
    port_num = port.port_number
    port.delete()

    messages.success(request, f"Sala '{name}' (Porta {port_num}) excluída com sucesso.")
    return redirect('groups')


@login_required
def check_port_availability_view(request):
    """
    Verificação em tempo real via AJAX se um número de porta já está em uso no Squid.
    """
    port_str = request.GET.get('port', '').strip()
    exclude_id = request.GET.get('exclude_id')

    if not port_str:
        return JsonResponse({'valid': False, 'message': 'Digite um número de porta.'})

    try:
        port_number = int(port_str)
        if port_number < 1024 or port_number > 65535:
            return JsonResponse({'valid': False, 'available': False, 'message': 'A porta deve estar entre 1024 e 65535.'})
    except ValueError:
        return JsonResponse({'valid': False, 'available': False, 'message': 'Número de porta inválido.'})

    query = ProxyPort.objects.filter(port_number=port_number)
    if exclude_id:
        query = query.exclude(id=exclude_id)

    existing_port = query.select_related('group').first()
    if existing_port:
        return JsonResponse({
            'valid': True,
            'available': False,
            'port_number': port_number,
            'room_name': existing_port.name,
            'group_name': existing_port.group.name,
            'message': f"A porta {port_number} já está em uso pela sala '{existing_port.name}' ({existing_port.group.name})."
        })

    return JsonResponse({
        'valid': True,
        'available': True,
        'port_number': port_number,
        'message': f"Porta {port_number} disponível!"
    })


@login_required
def port_toggle_status_view(request, port_id):
    """
    Altera o modo de liberação de uma porta específica:
    - ALLOWED: Liberado Total (100% Livre, sem Blacklist)
    - BLACKLIST: Liberado com Blacklist
    - WHITELIST: Apenas Whitelist (Modo Seguro)
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    port = get_object_or_404(ProxyPort, id=port_id)

    # Verifica permissão do usuário para esta porta
    if not profile.is_admin and port not in profile.allowed_ports.all() and port.group not in profile.allowed_groups.all():
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Acesso negado'}, status=403)
        return HttpResponseForbidden("Você não tem permissão para controlar esta porta.")

    new_status = request.POST.get('status') or request.GET.get('status')
    if new_status in ['ALLOWED', 'BLACKLIST', 'WHITELIST']:
        port.current_status = new_status
        port.save()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'port_id': port.id,
                'port_number': port.port_number,
                'port_name': port.name,
                'new_status': port.current_status,
                'status_display': port.get_current_status_display()
            })

        messages.success(request, f"Status da sala '{port.name}' (Porta {port.port_number}) alterado para {port.get_current_status_display()}.")

    return redirect(request.META.get('HTTP_REFERER', 'groups'))


# ==========================================
# 3. LISTAGEM DE WHITELISTS E BLACKLISTS
# ==========================================

@login_required
def whitelists_view(request):
    """
    Listagem de todas as Whitelists criadas no sistema.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    query = request.GET.get('q', '').strip()
    lists = ProxyList.objects.filter(list_type='WHITELIST').prefetch_related('domains', 'applied_groups_whitelist').order_by('-is_mandatory', 'name')

    if query:
        lists = lists.filter(
            models.Q(name__icontains=query) |
            models.Q(description__icontains=query)
        )

    total_lists = lists.count()
    total_domains = DomainItem.objects.filter(proxy_list__list_type='WHITELIST', is_active=True).count()
    all_groups = ProxyGroup.objects.filter(is_active=True)

    return render(request, 'squid/lists_index.html', {
        'profile': profile,
        'lists': lists,
        'list_type': 'WHITELIST',
        'title': 'Whitelists (Sites Permitidos)',
        'type_label': 'Whitelist',
        'badge_color': 'emerald',
        'query': query,
        'total_lists': total_lists,
        'total_domains': total_domains,
        'all_groups': all_groups,
        'active_menu': 'whitelists'
    })


@login_required
def blacklists_view(request):
    """
    Listagem de todas as Blacklists criadas no sistema.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    query = request.GET.get('q', '').strip()
    lists = ProxyList.objects.filter(list_type='BLACKLIST').prefetch_related('domains', 'applied_groups_blacklist').order_by('name')

    if query:
        lists = lists.filter(
            models.Q(name__icontains=query) |
            models.Q(description__icontains=query)
        )

    total_lists = lists.count()
    total_domains = DomainItem.objects.filter(proxy_list__list_type='BLACKLIST', is_active=True).count()
    all_groups = ProxyGroup.objects.filter(is_active=True)

    return render(request, 'squid/lists_index.html', {
        'profile': profile,
        'lists': lists,
        'list_type': 'BLACKLIST',
        'title': 'Blacklists (Sites Bloqueados)',
        'type_label': 'Blacklist',
        'badge_color': 'rose',
        'query': query,
        'total_lists': total_lists,
        'total_domains': total_domains,
        'all_groups': all_groups,
        'active_menu': 'blacklists'
    })


# ==========================================
# 4. CRIAÇÃO, EDIÇÃO E EXCLUSÃO DE LISTAS
# ==========================================

@login_required
def list_create_view(request):
    """
    Criação de uma nova lista temática (Whitelist ou Blacklist).
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        list_type = request.POST.get('list_type', 'WHITELIST').strip()
        description = request.POST.get('description', '').strip()
        is_mandatory = request.POST.get('is_mandatory') == 'on' and list_type == 'WHITELIST'
        selected_groups = request.POST.getlist('groups')

        if not name:
            messages.error(request, 'O nome da lista é obrigatório.')
            return redirect('whitelists' if list_type == 'WHITELIST' else 'blacklists')

        slug = slugify(name)
        if ProxyList.objects.filter(name=name, list_type=list_type).exists():
            messages.error(request, f"Já existe uma {list_type.title()} com o nome '{name}'.")
            return redirect('whitelists' if list_type == 'WHITELIST' else 'blacklists')

        proxy_list = ProxyList.objects.create(
            name=name,
            slug=slug,
            list_type=list_type,
            color='emerald' if list_type == 'WHITELIST' else 'rose',
            description=description,
            is_mandatory=is_mandatory,
            is_active=True
        )

        # Se for obrigatória, aplica em todos os grupos
        if is_mandatory:
            for g in ProxyGroup.objects.all():
                g.whitelists.add(proxy_list)
        elif selected_groups:
            groups = ProxyGroup.objects.filter(id__in=selected_groups)
            for g in groups:
                if list_type == 'WHITELIST':
                    g.whitelists.add(proxy_list)
                else:
                    g.blacklists.add(proxy_list)

        messages.success(request, f"{list_type.title()} '{name}' criada com sucesso! Adicione domínios abaixo.")
        return redirect('list_detail', list_id=proxy_list.id)

    return redirect('whitelists')


@login_required
def list_detail_view(request, list_id):
    """
    Visualização detalhada e gerenciamento de domínios dentro de uma lista.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    proxy_list = get_object_or_404(ProxyList, id=list_id)
    query = request.GET.get('q', '').strip()

    domains = proxy_list.domains.all().order_by('domain')
    if query:
        domains = domains.filter(
            models.Q(domain__icontains=query) |
            models.Q(description__icontains=query)
        )

    all_groups = ProxyGroup.objects.filter(is_active=True)
    if proxy_list.list_type == 'WHITELIST':
        applied_groups = proxy_list.applied_groups_whitelist.filter(is_active=True)
    else:
        applied_groups = proxy_list.applied_groups_blacklist.filter(is_active=True)

    if request.method == 'POST' and 'add_domain' in request.POST:
        domain_str = request.POST.get('domain', '').strip()
        desc = request.POST.get('domain_description', '').strip()

        if domain_str:
            item = DomainItem(proxy_list=proxy_list, domain=domain_str, description=desc)
            cleaned = item.clean_domain()

            if proxy_list.domains.filter(domain=cleaned).exists():
                messages.warning(request, f"O domínio '{cleaned}' já está nesta lista.")
            else:
                item.save()
                messages.success(request, f"Domínio '{cleaned}' adicionado com sucesso!")
        else:
            messages.error(request, 'Digite um domínio válido.')

        return redirect('list_detail', list_id=proxy_list.id)

    return render(request, 'squid/list_detail.html', {
        'profile': profile,
        'proxy_list': proxy_list,
        'domains': domains,
        'query': query,
        'all_groups': all_groups,
        'applied_groups': applied_groups,
        'active_menu': 'whitelists' if proxy_list.list_type == 'WHITELIST' else 'blacklists'
    })


@login_required
def list_edit_view(request, list_id):
    """
    Edição de metadados da Lista (Nome, Descrição, Obrigatoriedade, Grupos associados).
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    proxy_list = get_object_or_404(ProxyList, id=list_id)
    all_groups = ProxyGroup.objects.filter(is_active=True)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        is_mandatory = request.POST.get('is_mandatory') == 'on' and proxy_list.list_type == 'WHITELIST'
        selected_groups = request.POST.getlist('groups')

        if not name:
            messages.error(request, 'O nome não pode ficar em branco.')
            return redirect('list_detail', list_id=proxy_list.id)

        proxy_list.name = name
        proxy_list.description = description
        proxy_list.is_mandatory = is_mandatory
        proxy_list.save()

        # Atualiza a associação dos grupos
        if is_mandatory:
            for g in all_groups:
                g.whitelists.add(proxy_list)
        else:
            for g in all_groups:
                if proxy_list.list_type == 'WHITELIST':
                    if str(g.id) in selected_groups:
                        g.whitelists.add(proxy_list)
                    else:
                        g.whitelists.remove(proxy_list)
                else:
                    if str(g.id) in selected_groups:
                        g.blacklists.add(proxy_list)
                    else:
                        g.blacklists.remove(proxy_list)

        messages.success(request, f"Lista '{proxy_list.name}' atualizada com sucesso!")
        return redirect('list_detail', list_id=proxy_list.id)

    return redirect('list_detail', list_id=proxy_list.id)


@login_required
def list_delete_view(request, list_id):
    """
    Exclusão de uma Lista inteira (protegendo listas obrigatórias).
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado: apenas Administradores de TI podem excluir listas.")

    proxy_list = get_object_or_404(ProxyList, id=list_id)

    if proxy_list.is_mandatory:
        messages.error(request, f"A lista '{proxy_list.name}' é uma Whitelist Obrigatória do Sistema e não pode ser excluída.")
        return redirect('whitelists')

    list_type = proxy_list.list_type
    name = proxy_list.name
    proxy_list.delete()

    messages.success(request, f"A {list_type.title()} '{name}' e seus domínios foram excluídos.")
    return redirect('whitelists' if list_type == 'WHITELIST' else 'blacklists')


# ==========================================
# 5. GESTÃO DE DOMÍNIOS (INDIVIDUAL & EM LOTE)
# ==========================================

@login_required
def domain_delete_view(request, list_id, domain_id):
    """
    Exclusão de um domínio de uma lista.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    proxy_list = get_object_or_404(ProxyList, id=list_id)
    domain_item = get_object_or_404(DomainItem, id=domain_id, proxy_list=proxy_list)

    dom_name = domain_item.domain
    domain_item.delete()

    messages.success(request, f"Domínio '{dom_name}' removido da lista.")
    return redirect('list_detail', list_id=proxy_list.id)


@login_required
def domain_bulk_add_view(request, list_id):
    """
    Importação em lote de domínios (um por linha).
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    proxy_list = get_object_or_404(ProxyList, id=list_id)

    if request.method == 'POST':
        bulk_text = request.POST.get('bulk_domains', '').strip()
        lines = [line.strip() for line in bulk_text.splitlines() if line.strip()]

        added_count = 0
        duplicate_count = 0

        for line in lines:
            if line.startswith('#') or line.startswith('//'):
                continue
            
            temp_item = DomainItem(proxy_list=proxy_list, domain=line)
            cleaned = temp_item.clean_domain()

            if cleaned and not proxy_list.domains.filter(domain=cleaned).exists():
                DomainItem.objects.create(
                    proxy_list=proxy_list,
                    domain=cleaned,
                    description='Importado em lote'
                )
                added_count += 1
            else:
                duplicate_count += 1

        messages.success(request, f"Importação concluída: {added_count} domínios adicionados! ({duplicate_count} já existiam ou eram inválidos).")

    return redirect('list_detail', list_id=proxy_list.id)


# ==========================================
# 6. LOGS DE ACESSO, AUDITORIA & MONITOR AO VIVO
# ==========================================

from datetime import datetime, timedelta
from django.utils import timezone
from django.core.paginator import Paginator
from .models import AccessLog, DeviceHost
from .log_service import cleanup_old_logs, generate_mock_initial_logs_if_empty
from dashboard.models import SystemSetting


@login_required
def logs_view(request):
    """
    Tela completa de Logs de Acesso com filtros por Data, Hora, Grupo, Porta, Status, Domínio, IP e Hostname.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    generate_mock_initial_logs_if_empty()

    query_term = request.GET.get('q', '').strip()
    group_id = request.GET.get('group')
    port_id = request.GET.get('port')
    action_filter = request.GET.get('action', 'ALL')
    quick_time = request.GET.get('quick_time', '')
    
    date_from = request.GET.get('date_from', '')
    time_from = request.GET.get('time_from', '')
    date_to = request.GET.get('date_to', '')
    time_to = request.GET.get('time_to', '')

    logs_qs = AccessLog.objects.select_related('port', 'group').all()

    # RBAC: Se não for Admin, restringe aos grupos/portas autorizados
    if not profile.is_admin:
        allowed_ports = profile.allowed_ports.all()
        allowed_groups = profile.allowed_groups.all()
        logs_qs = logs_qs.filter(
            models.Q(port__in=allowed_ports) |
            models.Q(group__in=allowed_groups)
        )

    # Filtro por Termo (Domínio, IP ou Hostname)
    if query_term:
        matching_ips = list(DeviceHost.objects.filter(
            models.Q(hostname__icontains=query_term) |
            models.Q(description__icontains=query_term)
        ).values_list('ip_address', flat=True))

        logs_qs = logs_qs.filter(
            models.Q(domain__icontains=query_term) |
            models.Q(client_ip__icontains=query_term) |
            models.Q(client_ip__in=matching_ips) |
            models.Q(full_url__icontains=query_term)
        )

    # Filtro por Grupo
    if group_id:
        logs_qs = logs_qs.filter(group_id=group_id)

    # Filtro por Porta
    if port_id:
        logs_qs = logs_qs.filter(port_id=port_id)

    # Filtro por Ação (Permitido / Bloqueado)
    if action_filter == 'ALLOWED':
        logs_qs = logs_qs.filter(action='ALLOWED')
    elif action_filter == 'BLOCKED':
        logs_qs = logs_qs.filter(action='BLOCKED')

    # Filtro por Tempo Rápido
    now = timezone.now()
    if quick_time == '15m':
        logs_qs = logs_qs.filter(timestamp__gte=now - timedelta(minutes=15))
    elif quick_time == '30m':
        logs_qs = logs_qs.filter(timestamp__gte=now - timedelta(minutes=30))
    elif quick_time == '1h':
        logs_qs = logs_qs.filter(timestamp__gte=now - timedelta(hours=1))
    elif quick_time == '4h':
        logs_qs = logs_qs.filter(timestamp__gte=now - timedelta(hours=4))
    elif quick_time == 'today':
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        logs_qs = logs_qs.filter(timestamp__gte=start_of_day)
    elif quick_time == 'yesterday':
        start_of_yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_yesterday = start_of_yesterday + timedelta(days=1)
        logs_qs = logs_qs.filter(timestamp__gte=start_of_yesterday, timestamp__lt=end_of_yesterday)
    elif quick_time == '7d':
        logs_qs = logs_qs.filter(timestamp__gte=now - timedelta(days=7))

    # Filtro Personalizado de Data e Hora
    if date_from:
        try:
            t_from = time_from if time_from else '00:00'
            dt_from_str = f"{date_from} {t_from}"
            dt_from = timezone.make_aware(datetime.strptime(dt_from_str, '%Y-%m-%d %H:%M'))
            logs_qs = logs_qs.filter(timestamp__gte=dt_from)
        except Exception:
            pass

    if date_to:
        try:
            t_to = time_to if time_to else '23:59'
            dt_to_str = f"{date_to} {t_to}"
            dt_to = timezone.make_aware(datetime.strptime(dt_to_str, '%Y-%m-%d %H:%M'))
            logs_qs = logs_qs.filter(timestamp__lte=dt_to)
        except Exception:
            pass

    # Estatísticas dos logs filtrados
    total_filtered_count = logs_qs.count()
    allowed_count = logs_qs.filter(action='ALLOWED').count()
    blocked_count = logs_qs.filter(action='BLOCKED').count()

    # Paginação
    paginator = Paginator(logs_qs, 50)
    page_number = request.GET.get('page', 1)
    logs_page = paginator.get_page(page_number)

    # Anexa DeviceHost aos logs da página atual
    device_map = {d.ip_address: d for d in DeviceHost.objects.all()}
    for log in logs_page:
        log.device = device_map.get(log.client_ip)

    # Dados para os dropdowns de filtro
    all_groups = ProxyGroup.objects.filter(is_active=True).order_by('name')
    all_ports = ProxyPort.objects.select_related('group').filter(is_active=True).order_by('port_number')
    
    # Listas ativas para o modal rápido de adicionar domínio
    whitelists = ProxyList.objects.filter(list_type='WHITELIST', is_active=True).order_by('name')
    blacklists = ProxyList.objects.filter(list_type='BLACKLIST', is_active=True).order_by('name')

    retention_days = SystemSetting.get_value('log_retention_days', '30')

    return render(request, 'squid/logs_index.html', {
        'profile': profile,
        'logs': logs_page,
        'total_filtered_count': total_filtered_count,
        'allowed_count': allowed_count,
        'blocked_count': blocked_count,
        'query_term': query_term,
        'selected_group': group_id,
        'selected_port': port_id,
        'action_filter': action_filter,
        'quick_time': quick_time,
        'date_from': date_from,
        'time_from': time_from,
        'date_to': date_to,
        'time_to': time_to,
        'all_groups': all_groups,
        'all_ports': all_ports,
        'whitelists': whitelists,
        'blacklists': blacklists,
        'retention_days': retention_days,
        'active_menu': 'logs'
    })


@login_required
def logs_live_stream_view(request):
    """
    Endpoint AJAX para o Monitor em Tempo Real (Live Stream) de uma porta ou grupo específico.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    last_id = request.GET.get('last_id')
    port_id = request.GET.get('port_id')
    group_id = request.GET.get('group_id')

    logs_qs = AccessLog.objects.select_related('port', 'group').order_by('-id')

    if port_id:
        logs_qs = logs_qs.filter(port_id=port_id)
    elif group_id:
        logs_qs = logs_qs.filter(group_id=group_id)

    if last_id and last_id.isdigit():
        new_logs = list(logs_qs.filter(id__gt=int(last_id))[:30])
    else:
        new_logs = list(logs_qs[:20])

    device_map = {d.ip_address: d for d in DeviceHost.objects.all()}

    data = []
    for l in reversed(new_logs):
        dev = device_map.get(l.client_ip)
        data.append({
            'id': l.id,
            'timestamp': l.timestamp.strftime('%H:%M:%S'),
            'date': l.timestamp.strftime('%d/%m/%Y'),
            'client_ip': l.client_ip,
            'hostname': dev.hostname if dev else None,
            'device_desc': dev.description if dev else None,
            'port_number': l.port_number,
            'port_name': l.port.name if l.port else f"Porta {l.port_number}",
            'group_name': l.group.name if l.group else '-',
            'domain': l.domain,
            'full_url': l.full_url,
            'method': l.method,
            'action': l.action,
            'http_status': l.http_status,
            'bytes': l.formatted_bytes,
            'latency': f"{l.response_time_ms}ms"
        })

    return JsonResponse({'success': True, 'logs': data})


@login_required
def device_save_view(request):
    """
    Endpoint AJAX para cadastrar ou editar o Hostname/Identificação de um IP de equipamento.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return JsonResponse({'success': False, 'error': 'Acesso negado'}, status=403)

    if request.method == 'POST':
        ip_address = request.POST.get('ip_address', '').strip()
        hostname = request.POST.get('hostname', '').strip()
        description = request.POST.get('description', '').strip()

        if not ip_address or not hostname:
            return JsonResponse({'success': False, 'error': 'IP e Nome do Equipamento são obrigatórios.'})

        device, created = DeviceHost.objects.update_or_create(
            ip_address=ip_address,
            defaults={
                'hostname': hostname,
                'description': description
            }
        )

        return JsonResponse({
            'success': True,
            'ip_address': device.ip_address,
            'hostname': device.hostname,
            'description': device.description,
            'message': f"Equipamento '{device.hostname}' ({device.ip_address}) salvo com sucesso!"
        })

    return JsonResponse({'success': False, 'error': 'Método inválido.'}, status=405)


@login_required
def log_add_to_list_view(request):
    """
    Endpoint AJAX para adicionar diretamente um domínio requisitado a uma Whitelist ou Blacklist.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return JsonResponse({'success': False, 'error': 'Acesso negado'}, status=403)

    if request.method == 'POST':
        domain_str = request.POST.get('domain', '').strip()
        list_id = request.POST.get('list_id')
        description = request.POST.get('description', '').strip()

        if not domain_str or not list_id:
            return JsonResponse({'success': False, 'error': 'Domínio e Lista são obrigatórios.'})

        proxy_list = get_object_or_404(ProxyList, id=list_id)
        item = DomainItem(proxy_list=proxy_list, domain=domain_str, description=description or f"Adicionado a partir dos Logs ({timezone.now().strftime('%d/%m/%Y')})")
        cleaned = item.clean_domain()

        if proxy_list.domains.filter(domain=cleaned).exists():
            return JsonResponse({'success': False, 'error': f"O domínio '{cleaned}' já está cadastrado na lista '{proxy_list.name}'."})

        item.domain = cleaned
        item.save()

        return JsonResponse({
            'success': True,
            'domain': cleaned,
            'list_name': proxy_list.name,
            'list_type': proxy_list.get_list_type_display(),
            'message': f"Domínio '{cleaned}' adicionado com sucesso à {proxy_list.get_list_type_display()} '{proxy_list.name}'!"
        })

    return JsonResponse({'success': False, 'error': 'Método inválido.'}, status=405)


@login_required
def logs_cleanup_view(request):
    """
    Executa a limpeza de logs antigos com base na regra de retenção.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Apenas Administradores podem executar a limpeza de logs.")

    deleted_count, retention_days = cleanup_old_logs()
    messages.success(request, f"Limpeza concluída com sucesso: {deleted_count} registros de logs com mais de {retention_days} dias foram removidos.")
    return redirect(request.META.get('HTTP_REFERER', 'logs'))


# ==========================================
# 7. CONTROLE & SINCRONIZAÇÃO DO SERVIÇO SQUID
# ==========================================

@login_required
def squid_apply_view(request):
    """
    Gera a configuração atualizada e aplica imediatamente no Squid (squid -k reconfigure).
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Apenas Administradores podem aplicar alterações no Squid.")

    success, msg = apply_squid_changes()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': success, 'message': msg})

    if success:
        messages.success(request, f"⚡ {msg}")
    else:
        messages.error(request, f"Erro ao aplicar no Squid: {msg}")

    return redirect(request.META.get('HTTP_REFERER', 'groups'))


@login_required
def squid_restart_view(request):
    """
    Reinicia completamente o serviço do Squid no sistema operacional.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Apenas Administradores podem reiniciar o serviço Squid.")

    success, msg = restart_squid_service()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': success, 'message': msg})

    if success:
        messages.success(request, f"🔄 {msg}")
    else:
        messages.error(request, f"Erro ao reiniciar o Squid: {msg}")

    return redirect(request.META.get('HTTP_REFERER', 'groups'))



