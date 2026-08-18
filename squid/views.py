import os
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse, HttpResponse, Http404
from django.db import models
from django.utils.text import slugify

from .models import ProxyList, DomainItem, PortalLink
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
    Criação de uma nova porta de escuta / sala associada a um grupo e sincronização com o Squid.
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

        port = ProxyPort.objects.create(
            group=group,
            name=name,
            port_number=port_number,
            current_status=initial_status,
            is_active=True
        )

        # Sincroniza imediatamente o squid.conf
        from .squid_sync import apply_squid_changes
        sync_ok, sync_msg = apply_squid_changes()

        if sync_ok:
            messages.success(request, f"Sala '{name}' (Porta {port_number}) criada e aplicada no Squid com sucesso!")
        else:
            messages.warning(request, f"Sala '{name}' (Porta {port_number}) criada, mas houve um aviso no Squid: {sync_msg}")

        return redirect('groups')

    return redirect('groups')


@login_required
def port_edit_view(request, port_id):
    """
    Edição de dados de uma porta/sala (Nome, Número da Porta, Grupo e Status) com sincronização imediata no Squid.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    port = get_object_or_404(ProxyPort, id=port_id)
    old_port_number = port.port_number

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        port_str = request.POST.get('port_number', '').strip()
        group_id = request.POST.get('group_id')
        current_status = request.POST.get('current_status', port.current_status)

        if not name:
            messages.error(request, 'O nome da sala é obrigatório.')
            return redirect('groups')

        if port_str:
            try:
                new_port_number = int(port_str)
                if new_port_number < 1024 or new_port_number > 65535:
                    messages.error(request, 'O número da porta deve estar entre 1024 e 65535.')
                    return redirect('groups')
                if ProxyPort.objects.filter(port_number=new_port_number).exclude(id=port.id).exists():
                    messages.error(request, f"A porta {new_port_number} já está em uso por outra sala.")
                    return redirect('groups')
                port.port_number = new_port_number
            except ValueError:
                messages.error(request, 'Número de porta inválido.')
                return redirect('groups')

        if group_id and group_id.isdigit():
            new_group = get_object_or_404(ProxyGroup, id=int(group_id))
            port.group = new_group

        port.name = name
        port.current_status = current_status
        port.save()

        # Sincroniza imediatamente o arquivo de configuração do Squid (/etc/squid/squid.conf)
        from .squid_sync import apply_squid_changes
        sync_ok, sync_msg = apply_squid_changes()

        if sync_ok:
            if old_port_number != port.port_number:
                messages.success(request, f"Porta alterada de {old_port_number} para {port.port_number} e sincronizada no Squid com sucesso!")
            else:
                messages.success(request, f"Sala '{port.name}' (Porta {port.port_number}) atualizada com sucesso!")
        else:
            messages.warning(request, f"Porta atualizada no banco, mas houve aviso no Squid: {sync_msg}")

        return redirect('groups')

    return redirect('groups')


@login_required
def port_delete_view(request, port_id):
    """
    Exclusão de uma porta/sala do sistema com reconfiguração do Squid.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado: apenas Administradores de TI podem excluir portas.")

    port = get_object_or_404(ProxyPort, id=port_id)
    name = port.name
    port_num = port.port_number
    port.delete()

    # Sincroniza imediatamente o squid.conf removendo a porta
    from .squid_sync import apply_squid_changes
    sync_ok, sync_msg = apply_squid_changes()

    messages.success(request, f"Sala '{name}' (Porta {port_num}) excluída e removida do Squid com sucesso.")
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
    if new_status in ['ALLOWED', 'BLACKLIST', 'WHITELIST', 'BLOCKED']:
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


@login_required
def port_lists_view(request, port_id):
    """
    Gerencia listas exclusivas (override) de uma porta específica.
    GET: retorna as listas atualmente vinculadas.
    POST: atualiza as listas vinculadas (whitelists e blacklists).
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return JsonResponse({'success': False, 'error': 'Acesso negado'}, status=403)

    port = get_object_or_404(ProxyPort, id=port_id)

    if request.method == 'GET':
        current_wl_ids = list(port.port_whitelists.values_list('id', flat=True))
        current_bl_ids = list(port.port_blacklists.values_list('id', flat=True))
        return JsonResponse({
            'success': True,
            'port_id': port.id,
            'port_name': port.name,
            'port_number': port.port_number,
            'whitelist_ids': current_wl_ids,
            'blacklist_ids': current_bl_ids,
        })

    if request.method == 'POST':
        wl_ids = request.POST.getlist('port_whitelists')
        bl_ids = request.POST.getlist('port_blacklists')

        # Atualiza M2M
        port.port_whitelists.set(
            ProxyList.objects.filter(id__in=wl_ids, list_type='WHITELIST', is_active=True)
        )
        port.port_blacklists.set(
            ProxyList.objects.filter(id__in=bl_ids, list_type='BLACKLIST', is_active=True)
        )

        # Sincroniza squid.conf
        from .squid_sync import apply_squid_changes
        sync_ok, sync_msg = apply_squid_changes()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            wl_count = port.port_whitelists.count()
            bl_count = port.port_blacklists.count()
            return JsonResponse({
                'success': True,
                'message': f'Listas da porta {port.name} atualizadas com sucesso!',
                'wl_count': wl_count,
                'bl_count': bl_count,
                'sync_ok': sync_ok,
            })

        messages.success(request, f"Listas exclusivas da porta '{port.name}' atualizadas!")
        return redirect('groups')

    return JsonResponse({'success': False, 'error': 'Método não suportado'}, status=405)


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
from .models import AccessLog, DeviceHost, HiddenDomain
from .log_service import cleanup_old_logs, sync_logs_from_squid_file
from dashboard.models import SystemSetting


@login_required
def logs_view(request):
    """
    Tela completa de Logs de Acesso com filtros por Data, Hora, Grupo, Porta, Status, Domínio, IP e Hostname.
    Lê os dados reais diretamente de /var/log/squid/access.log.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    sync_logs_from_squid_file()

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

    # Filtro por Ação (Permitido / Bloqueado no Proxy / Bloqueado no Destino)
    if action_filter == 'ALLOWED':
        logs_qs = logs_qs.filter(action='ALLOWED').exclude(http_status__contains='/403').exclude(http_status__contains='/401')
    elif action_filter == 'BLOCKED_PROXY':
        logs_qs = logs_qs.filter(models.Q(action='BLOCKED') | models.Q(http_status__icontains='DENIED'))
    elif action_filter == 'BLOCKED_DEST':
        logs_qs = logs_qs.filter(action='ALLOWED').filter(
            models.Q(http_status__contains='/403') |
            models.Q(http_status__contains='/401') |
            models.Q(http_status__contains='/429') |
            models.Q(http_status__contains='/407')
        )
    elif action_filter == 'BLOCKED':
        logs_qs = logs_qs.filter(
            models.Q(action='BLOCKED') |
            models.Q(http_status__icontains='DENIED') |
            models.Q(http_status__contains='/403') |
            models.Q(http_status__contains='/401')
        )

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
    Endpoint AJAX para o Monitor em Tempo Real (Live Stream) com suporte a filtros por Porta, Grupo,
    Hostname/IP, Status (Liberados, Bloqueados no Proxy, Bloqueados no Destino) e Silenciamento de Domínios.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    sync_logs_from_squid_file()
    last_id = request.GET.get('last_id')
    port_id = request.GET.get('port_id')
    group_id = request.GET.get('group_id')
    action_filter = request.GET.get('action', 'ALL').strip().upper()
    hostname_filter = request.GET.get('hostname', '').strip()
    hide_cdns = request.GET.get('hide_cdns', 'true').strip().lower() == 'true'

    logs_qs = AccessLog.objects.select_related('port', 'group').all()

    # 1. Filtro para Ocultar Domínios Silenciados (HiddenDomain do Banco de Dados)
    if hide_cdns:
        hidden_patterns = list(HiddenDomain.objects.values_list('domain', flat=True))
        if hidden_patterns:
            q_hidden = models.Q()
            for pat in hidden_patterns:
                q_hidden |= models.Q(domain__icontains=pat)
            logs_qs = logs_qs.exclude(q_hidden)

    # 2. Filtro por Porta e Grupo
    if port_id and port_id.isdigit():
        logs_qs = logs_qs.filter(port_id=int(port_id))
    elif group_id and group_id.isdigit():
        logs_qs = logs_qs.filter(group_id=int(group_id))

    # 3. Filtro por Ação / Status no Live
    if action_filter == 'ALLOWED':
        logs_qs = logs_qs.filter(action='ALLOWED').exclude(http_status__contains='/403').exclude(http_status__contains='/401')
    elif action_filter == 'BLOCKED_PROXY':
        logs_qs = logs_qs.filter(models.Q(action='BLOCKED') | models.Q(http_status__icontains='DENIED'))
    elif action_filter == 'BLOCKED_DEST':
        logs_qs = logs_qs.filter(action='ALLOWED').filter(
            models.Q(http_status__contains='/403') |
            models.Q(http_status__contains='/401') |
            models.Q(http_status__contains='/429') |
            models.Q(http_status__contains='/407')
        )
    elif action_filter == 'BLOCKED':
        logs_qs = logs_qs.filter(
            models.Q(action='BLOCKED') |
            models.Q(http_status__icontains='DENIED') |
            models.Q(http_status__contains='/403') |
            models.Q(http_status__contains='/401')
        )

    # 4. Filtro por Hostname / IP
    if hostname_filter:
        logs_qs = logs_qs.filter(
            models.Q(hostname__icontains=hostname_filter) |
            models.Q(client_ip__icontains=hostname_filter)
        )

    if last_id and last_id.isdigit() and int(last_id) > 0:
        # Busca registros com ID maior em ordem cronológica (id ASC)
        new_logs = list(logs_qs.filter(id__gt=int(last_id)).order_by('id')[:100])
    else:
        # Carga inicial: pega os 35 mais recentes e inverte para exibição correta
        recent_logs = list(logs_qs.order_by('-id')[:35])
        new_logs = list(reversed(recent_logs))

    device_map = {d.ip_address: d for d in DeviceHost.objects.all()}

    data = []
    for l in new_logs:
        dev = device_map.get(l.client_ip)
        local_ts = timezone.localtime(l.timestamp)
        effective_hostname = l.hostname or (dev.hostname if dev else None)
        data.append({
            'id': l.id,
            'timestamp': local_ts.strftime('%H:%M:%S'),
            'date': local_ts.strftime('%d/%m/%Y'),
            'client_ip': l.client_ip,
            'hostname': effective_hostname,
            'device_desc': dev.description if dev else None,
            'port_number': l.port_number,
            'port_name': l.port.name if l.port else f"Porta {l.port_number}",
            'group_name': l.group.name if l.group else '-',
            'domain': l.domain,
            'full_url': l.full_url,
            'method': l.method,
            'action': l.action,
            'http_status': l.http_status,
            'status_code': l.status_code,
            'status_category': l.status_category,
            'is_proxy_blocked': l.is_proxy_blocked,
            'is_dest_blocked': l.is_dest_blocked,
            'bytes': l.formatted_bytes,
            'latency': f"{l.response_time_ms}ms"
        })

    return JsonResponse({'success': True, 'logs': data})


@login_required
def hidden_domain_add_view(request):
    """
    Endpoint AJAX para adicionar um domínio ao banco de domínios ocultos do Live Stream.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return JsonResponse({'success': False, 'error': 'Acesso negado'}, status=403)

    if request.method == 'POST':
        domain_str = request.POST.get('domain', '').strip()
        description = request.POST.get('description', '').strip()

        if not domain_str:
            return JsonResponse({'success': False, 'error': 'Domínio é obrigatório.'})

        item = HiddenDomain(domain=domain_str, description=description or f"Silenciado do Live Stream ({timezone.now().strftime('%d/%m/%Y %H:%M')})")
        cleaned = item.clean_domain()

        if HiddenDomain.objects.filter(domain=cleaned).exists():
            return JsonResponse({'success': False, 'error': f"O domínio '{cleaned}' já está cadastrado no banco de domínios ocultos."})

        item.domain = cleaned
        item.save()

        return JsonResponse({
            'success': True,
            'domain': cleaned,
            'id': item.id,
            'message': f"Domínio '{cleaned}' silenciado com sucesso do Live Stream!"
        })

    return JsonResponse({'success': False, 'error': 'Método inválido.'}, status=405)


@login_required
def hidden_domain_delete_view(request, hidden_id):
    """
    Endpoint AJAX para remover um domínio da base de domínios ocultos.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return JsonResponse({'success': False, 'error': 'Acesso negado'}, status=403)

    item = get_object_or_404(HiddenDomain, id=hidden_id)
    dom_name = item.domain
    item.delete()

    return JsonResponse({
        'success': True,
        'message': f"Domínio '{dom_name}' removido da base de domínios ocultos."
    })


@login_required
def hidden_domain_list_json_view(request):
    """
    Retorna a lista de domínios ocultos para o modal de gerenciamento.
    """
    items = list(HiddenDomain.objects.all().values('id', 'domain', 'description', 'created_at'))
    for i in items:
        i['created_at'] = timezone.localtime(i['created_at']).strftime('%d/%m/%Y %H:%M')
    return JsonResponse({'success': True, 'domains': items, 'total': len(items)})


@login_required
def proxy_tester_view(request):
    """
    Simulador e Testador de Políticas de Navegação.
    Permite digitar qualquer domínio ou URL, selecionar uma porta (ou todas) e descobrir
    em tempo real se o Squid vai permitir ou bloquear o acesso, explicando a regra exata e permitindo ações.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    input_domain = request.GET.get('domain', '').strip()
    selected_port_id = request.GET.get('port_id', '').strip()

    all_ports = list(ProxyPort.objects.select_related('group').filter(is_active=True).order_by('port_number'))
    all_groups = list(ProxyGroup.objects.filter(is_active=True).order_by('name'))
    all_whitelists = list(ProxyList.objects.filter(list_type='WHITELIST', is_active=True).order_by('name'))
    all_blacklists = list(ProxyList.objects.filter(list_type='BLACKLIST', is_active=True).order_by('name'))

    result = None

    if input_domain:
        cleaned_domain = input_domain.lower()
        if '://' in cleaned_domain:
            from urllib.parse import urlparse
            cleaned_domain = urlparse(cleaned_domain).hostname or cleaned_domain
        else:
            cleaned_domain = cleaned_domain.split(':')[0].split('/')[0]
        cleaned_domain = cleaned_domain.lstrip('.')

        target_port = None
        if selected_port_id and selected_port_id.isdigit():
            target_port = ProxyPort.objects.select_related('group').filter(id=int(selected_port_id), is_active=True).first()

        def domain_matches(test_d, list_pattern):
            lp = list_pattern.lower().strip()
            td = test_d.lower().strip()
            if lp.startswith('.'):
                root = lp.lstrip('.')
                return td == root or td.endswith('.' + root)
            elif lp.startswith('*.'):
                root = lp[2:]
                return td == root or td.endswith('.' + root)
            else:
                return td == lp or td.endswith('.' + lp)

        # 1. Busca em TODAS as Whitelists ativas do sistema
        matched_whitelists = []
        all_wl = ProxyList.objects.filter(list_type='WHITELIST', is_active=True).prefetch_related('domains')
        for wl in all_wl:
            for item in wl.domains.filter(is_active=True):
                if domain_matches(cleaned_domain, item.domain):
                    matched_whitelists.append({
                        'list': wl,
                        'matched_pattern': item.domain,
                        'is_mandatory': wl.is_mandatory,
                        'groups': list(wl.groups.filter(is_active=True)) if hasattr(wl, 'groups') else []
                    })
                    break

        # 2. Busca em TODAS as Blacklists ativas do sistema
        matched_blacklists = []
        all_bl = ProxyList.objects.filter(list_type='BLACKLIST', is_active=True).prefetch_related('domains')
        for bl in all_bl:
            for item in bl.domains.filter(is_active=True):
                if domain_matches(cleaned_domain, item.domain):
                    matched_blacklists.append({
                        'list': bl,
                        'matched_pattern': item.domain,
                        'groups': list(bl.groups.filter(is_active=True)) if hasattr(bl, 'groups') else []
                    })
                    break

        # 3. Avaliação por Porta
        port_evaluations = []
        ports_to_test = [target_port] if target_port else all_ports

        for p in ports_to_test:
            g = p.group
            mode = p.current_status

            in_mandatory_wl = any(m['is_mandatory'] for m in matched_whitelists)
            mandatory_item = next((m for m in matched_whitelists if m['is_mandatory']), None)

            in_group_wl = any(g in m['groups'] for m in matched_whitelists)
            group_wl_item = next((m for m in matched_whitelists if g in m['groups']), None)

            in_group_bl = any(g in m['groups'] for m in matched_blacklists)
            group_bl_item = next((m for m in matched_blacklists if g in m['groups']), None)

            status = 'BLOCKED'
            reason = ''
            badge_class = 'bg-rose-500/15 text-rose-400 border-rose-500/30'

            if mode == 'ALLOWED':
                status = 'ALLOWED'
                reason = 'Porta 100% Livre (Modo Aberto)'
                badge_class = 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
            elif mode == 'BLACKLIST':
                if in_mandatory_wl:
                    status = 'ALLOWED'
                    reason = f"Liberado pela Whitelist Obrigatória: '{mandatory_item['list'].name}' (Precedência máxima)"
                    badge_class = 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                elif in_group_wl:
                    status = 'ALLOWED'
                    reason = f"Liberado pela Whitelist do Grupo: '{group_wl_item['list'].name}' (Precedência sobre Blacklist)"
                    badge_class = 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                elif in_group_bl:
                    status = 'BLOCKED'
                    reason = f"Bloqueado pela Blacklist do Grupo: '{group_bl_item['list'].name}'"
                    badge_class = 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                else:
                    status = 'ALLOWED'
                    reason = "Liberado (Não está em nenhuma Blacklist ativa deste Grupo)"
                    badge_class = 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
            else:  # Modo WHITELIST
                if in_mandatory_wl:
                    status = 'ALLOWED'
                    reason = f"Liberado pela Whitelist Obrigatória: '{mandatory_item['list'].name}'"
                    badge_class = 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                elif in_group_wl:
                    status = 'ALLOWED'
                    reason = f"Liberado pela Whitelist do Grupo: '{group_wl_item['list'].name}'"
                    badge_class = 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                else:
                    status = 'BLOCKED'
                    reason = "Bloqueado (Modo Whitelist Restritivo: domínio não cadastrado em nenhuma Whitelist do Grupo)"
                    badge_class = 'bg-rose-500/15 text-rose-400 border-rose-500/30'

            port_evaluations.append({
                'port': p,
                'group': g,
                'mode': mode,
                'status': status,
                'is_allowed': status == 'ALLOWED',
                'reason': reason,
                'badge_class': badge_class,
                'in_mandatory_wl': in_mandatory_wl,
                'in_group_wl': in_group_wl,
                'in_group_bl': in_group_bl
            })

        result = {
            'cleaned_domain': cleaned_domain,
            'input_domain': input_domain,
            'target_port': target_port,
            'matched_whitelists': matched_whitelists,
            'matched_blacklists': matched_blacklists,
            'port_evaluations': port_evaluations,
            'has_mandatory': any(m['is_mandatory'] for m in matched_whitelists),
        }

    return render(request, 'squid/tester.html', {
        'profile': profile,
        'all_ports': all_ports,
        'all_groups': all_groups,
        'all_whitelists': all_whitelists,
        'all_blacklists': all_blacklists,
        'input_domain': input_domain,
        'selected_port_id': selected_port_id,
        'result': result,
        'active_menu': 'tester'
    })


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


def download_certificate_view(request):
    """
    Endpoint público para download do Certificado Raiz SSL (CA) do SquidPanel
    para instalação nos computadores clientes (Windows, Linux, macOS).
    """
    cert_paths = [
        '/etc/squid/certs/squidpanel_ca.crt',
        '/etc/squid/certs/squidpanel_ca.pem',
        os.path.join(settings.BASE_DIR, 'scratch', 'squid_config', 'certs', 'squidpanel_ca.crt'),
        os.path.join(settings.BASE_DIR, 'scratch', 'squid_config', 'certs', 'squidpanel_ca.pem'),
    ]

    cert_file = None
    for p in cert_paths:
        if os.path.exists(p):
            cert_file = p
            break

    if not cert_file:
        from .squid_sync import ensure_ssl_ca_certificate
        cert_file = ensure_ssl_ca_certificate()

    if not cert_file or not os.path.exists(cert_file):
        from django.http import Http404
        raise Http404("Certificado SSL ainda não gerado no servidor.")

    from django.http import HttpResponse
    with open(cert_file, 'rb') as f:
        response = HttpResponse(f.read(), content_type='application/x-x509-ca-cert')
        response['Content-Disposition'] = 'attachment; filename="SquidPanel_CA.crt"'
        return response


@login_required
def sync_ad_devices_view(request):
    """
    Aciona a sincronização automática de Hostnames e IPs a partir do Active Directory e DNS.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Apenas Administradores podem sincronizar o Active Directory.")

    from .ad_sync import sync_devices_from_ad
    count, msg = sync_devices_from_ad()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': count > 0 or 'concluída' in msg.lower(), 'message': msg, 'count': count})

    if count > 0 or 'concluída' in msg.lower():
        messages.success(request, f"🖥️ {msg}")
    else:
        messages.error(request, f"Erro na sincronização AD: {msg}")

    return redirect(request.META.get('HTTP_REFERER', 'logs'))


def pac_by_port_view(request, port_number):
    """
    Endpoint público para servir script PAC de uma porta específica (ex: /9010.pac ou /pac/9010.pac).
    Suporta parâmetro ?strict=1 para desativar fallback DIRECT se desejado.
    """
    fallback_direct = request.GET.get('strict') != '1'
    from .pac_service import pac_response
    return pac_response(port_number=port_number, fallback_direct=fallback_direct, filename=f"{port_number}.pac")


def pac_by_slug_view(request, port_slug):
    """
    Endpoint público para servir script PAC pelo nome/slug da sala (ex: /pac/galeria.pac).
    """
    port = ProxyPort.objects.filter(slug=port_slug, is_active=True).first()
    if not port:
        raise Http404("Porta não encontrada.")
    
    fallback_direct = request.GET.get('strict') != '1'
    from .pac_service import pac_response
    return pac_response(port_number=port.port_number, fallback_direct=fallback_direct, filename=f"{port_slug}.pac")


def pac_global_view(request):
    """
    Endpoint público para servir o script PAC global (/proxy.pac ou /wpad.dat).
    """
    port_param = request.GET.get('port')
    port_number = int(port_param) if port_param and port_param.isdigit() else None
    fallback_direct = request.GET.get('strict') != '1'
    from .pac_service import pac_response
    return pac_response(port_number=port_number, fallback_direct=fallback_direct, filename="proxy.pac")


# ==========================================
# 10. PORTAL EDUCACIONAL & PÁGINA DE BLOQUEIO PERSONALIZADA
# ==========================================

def portal_view(request, port_number):
    """
    Página pública de Portal Educacional / Bloqueio Amigável com catálogo de links autorizados.
    Exibida quando um usuário tenta acessar uma URL não permitida na porta configurada (ex: 9030).
    """
    port = ProxyPort.objects.filter(port_number=port_number, is_active=True).first()
    blocked_url = request.GET.get('blocked', '').strip()
    
    # Se blocked_url veio como parâmetro do Squid (%u), limpa para exibição
    clean_blocked_host = ''
    if blocked_url:
        try:
            from urllib.parse import urlparse
            if '://' in blocked_url:
                clean_blocked_host = urlparse(blocked_url).netloc
            else:
                clean_blocked_host = blocked_url.split('/')[0].split(':')[0]
        except Exception:
            clean_blocked_host = blocked_url

    # Busca links aplicáveis a esta porta ou globais (port=None)
    links_qs = PortalLink.objects.filter(is_active=True).filter(
        models.Q(port=port) | models.Q(port__isnull=True)
    ).order_by('display_order', 'title')

    # Se a base estiver vazia, popula links iniciais padrão recomendados
    if not PortalLink.objects.exists():
        _seed_default_portal_links()
        links_qs = PortalLink.objects.filter(is_active=True).filter(
            models.Q(port=port) | models.Q(port__isnull=True)
        ).order_by('display_order', 'title')

    # Agrupa por categorias
    categories = [
        {
            'code': 'FACULDADES',
            'name': 'Faculdades & Portais Acadêmicos',
            'icon': 'fa-graduation-cap',
            'badge_color': 'from-indigo-500 to-cyan-500',
            'links': [l for l in links_qs if l.category == 'FACULDADES']
        },
        {
            'code': 'PESQUISA',
            'name': 'Pesquisa & Bibliotecas Virtuais',
            'icon': 'fa-book-bookmark',
            'badge_color': 'from-emerald-500 to-teal-500',
            'links': [l for l in links_qs if l.category == 'PESQUISA']
        },
        {
            'code': 'DICIONARIOS',
            'name': 'Dicionários & Enciclopédias',
            'icon': 'fa-spell-check',
            'badge_color': 'from-amber-500 to-orange-500',
            'links': [l for l in links_qs if l.category == 'DICIONARIOS']
        },
        {
            'code': 'FERRAMENTAS',
            'name': 'Ferramentas & Recursos Educacionais',
            'icon': 'fa-toolbox',
            'badge_color': 'from-purple-500 to-pink-500',
            'links': [l for l in links_qs if l.category == 'FERRAMENTAS']
        },
        {
            'code': 'OUTROS',
            'name': 'Outros Links Autorizados',
            'icon': 'fa-globe',
            'badge_color': 'from-slate-500 to-slate-400',
            'links': [l for l in links_qs if l.category == 'OUTROS']
        },
    ]
    # Remove categorias vazias
    active_categories = [c for c in categories if len(c['links']) > 0]

    return render(request, 'squid/portal.html', {
        'port': port,
        'port_number': port_number,
        'blocked_url': blocked_url,
        'clean_blocked_host': clean_blocked_host,
        'categories': active_categories,
        'total_links_count': links_qs.count()
    })


def _seed_default_portal_links():
    """Popula links educativos padrão na primeira execução."""
    defaults = [
        ('Portal EAD UNIFACVEST', 'https://ead.unifacvest.edu.br', 'FACULDADES', 'Ambiente Virtual de Aprendizagem e Aulas Online', 'fa-graduation-cap', 1),
        ('Portal Institucional UNIFACVEST', 'https://www.unifacvest.edu.br', 'FACULDADES', 'Site oficial do Centro Universitário FACVEST', 'fa-university', 2),
        ('Google Acadêmico (Scholar)', 'https://scholar.google.com.br', 'PESQUISA', 'Pesquisa de artigos científicos, teses e livros acadêmicos', 'fa-magnifying-glass', 3),
        ('SciELO Brasil', 'https://www.scielo.br', 'PESQUISA', 'Biblioteca científica eletrônica online com artigos indexados', 'fa-book-open', 4),
        ('Periódicos CAPES', 'https://www.periodicos.capes.gov.br', 'PESQUISA', 'Acesso à produção científica nacional e internacional', 'fa-scroll', 5),
        ('Wikipédia em Português', 'https://pt.wikipedia.org', 'PESQUISA', 'Enciclopédia livre multilíngue e colaborativa', 'fa-earth-americas', 6),
        ('Dicio - Dicionário de Português', 'https://www.dicio.com.br', 'DICIONARIOS', 'Definições, sinônimos, antônimos e gramática da língua portuguesa', 'fa-spell-check', 7),
        ('Michaelis Online', 'https://michaelis.uol.com.br', 'DICIONARIOS', 'Dicionários de português, inglês e outros idiomas', 'fa-book', 8),
    ]
    for title, url, cat, desc, icon, order in defaults:
        PortalLink.objects.create(
            title=title,
            url=url,
            category=cat,
            description=desc,
            icon=icon,
            display_order=order,
            is_active=True
        )


@login_required
def portal_links_admin_view(request):
    """
    Interface administrativa para gerenciar os links do portal e quais portas têm portal personalizado ativo.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    links = PortalLink.objects.select_related('port').all().order_by('category', 'display_order', 'title')
    ports = ProxyPort.objects.select_related('group').filter(is_active=True).order_by('port_number')
    
    category_filter = request.GET.get('category', '').strip()
    port_filter = request.GET.get('port', '').strip()
    query = request.GET.get('q', '').strip()

    if category_filter:
        links = links.filter(category=category_filter)
    if port_filter and port_filter.isdigit():
        links = links.filter(port_id=int(port_filter))
    if query:
        links = links.filter(
            models.Q(title__icontains=query) |
            models.Q(url__icontains=query) |
            models.Q(description__icontains=query)
        )

    categories_choices = PortalLink.CATEGORY_CHOICES

    return render(request, 'squid/portal_links.html', {
        'profile': profile,
        'links': links,
        'ports': ports,
        'categories_choices': categories_choices,
        'category_filter': category_filter,
        'port_filter': port_filter,
        'query': query,
        'active_menu': 'portal_links'
    })


@login_required
def portal_link_create_view(request):
    """
    Criação de um novo link autorizado no Portal.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        url = request.POST.get('url', '').strip()
        category = request.POST.get('category', 'FACULDADES').strip()
        description = request.POST.get('description', '').strip()
        icon = request.POST.get('icon', 'fa-graduation-cap').strip()
        port_id = request.POST.get('port_id', '').strip()
        display_order = request.POST.get('display_order', '0').strip()

        if not title or not url:
            messages.error(request, 'Título e URL são obrigatórios.')
            return redirect('portal_links_admin')

        if not url.startswith('http://') and not url.startswith('https://'):
            url = f"https://{url}"

        port = ProxyPort.objects.filter(id=int(port_id)).first() if port_id and port_id.isdigit() else None
        order = int(display_order) if display_order.isdigit() else 0

        PortalLink.objects.create(
            title=title,
            url=url,
            category=category,
            description=description,
            icon=icon or 'fa-globe',
            port=port,
            display_order=order,
            is_active=True
        )

        messages.success(request, f"Link '{title}' adicionado ao Portal com sucesso!")
        return redirect('portal_links_admin')

    return redirect('portal_links_admin')


@login_required
def portal_link_edit_view(request, link_id):
    """
    Edição de um link do Portal.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    link = get_object_or_404(PortalLink, id=link_id)

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        url = request.POST.get('url', '').strip()
        category = request.POST.get('category', 'FACULDADES').strip()
        description = request.POST.get('description', '').strip()
        icon = request.POST.get('icon', 'fa-graduation-cap').strip()
        port_id = request.POST.get('port_id', '').strip()
        display_order = request.POST.get('display_order', '0').strip()
        is_active = request.POST.get('is_active') == 'on'

        if not title or not url:
            messages.error(request, 'Título e URL são obrigatórios.')
            return redirect('portal_links_admin')

        if not url.startswith('http://') and not url.startswith('https://'):
            url = f"https://{url}"

        port = ProxyPort.objects.filter(id=int(port_id)).first() if port_id and port_id.isdigit() else None
        order = int(display_order) if display_order.isdigit() else 0

        link.title = title
        link.url = url
        link.category = category
        link.description = description
        link.icon = icon or 'fa-globe'
        link.port = port
        link.display_order = order
        link.is_active = is_active
        link.save()

        messages.success(request, f"Link '{title}' atualizado com sucesso!")
        return redirect('portal_links_admin')

    return redirect('portal_links_admin')


@login_required
def portal_link_delete_view(request, link_id):
    """
    Exclusão de um link do Portal.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    link = get_object_or_404(PortalLink, id=link_id)
    title = link.title
    link.delete()

    messages.success(request, f"Link '{title}' removido do Portal.")
    return redirect('portal_links_admin')


@login_required
def portal_toggle_port_view(request, port_id):
    """
    Ativa/Desativa o uso de Portal Personalizado de Bloqueio em uma porta/sala.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    port = get_object_or_404(ProxyPort, id=port_id)
    port.use_custom_portal = not port.use_custom_portal
    port.save()

    mark_squid_sync_needed()

    status_txt = "ATIVADO (Redirecionará para Portal com Links)" if port.use_custom_portal else "DESATIVADO (Erro padrão do Squid)"
    messages.success(request, f"Portal personalizado da Porta {port.port_number} ({port.name}): {status_txt}. Clique em 'Aplicar no Squid' para sincronizar.")
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'use_custom_portal': port.use_custom_portal, 'port_number': port.port_number})

    return redirect('portal_links_admin')







