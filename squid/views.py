from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.db import models
from django.utils.text import slugify

from .models import ProxyList, DomainItem
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

    all_whitelists = ProxyList.objects.filter(list_type='WHITELIST', is_active=True).order_by('name')
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

        messages.success(request, f"Grupo '{name}' criado com sucesso! Agora você pode adicionar portas/salas a ele.")
        return redirect('groups')

    return redirect('groups')


@login_required
def group_edit_view(request, group_id):
    """
    Edição de um Grupo existente, suas políticas de acesso e listas vinculadas.
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
def port_toggle_status_view(request, port_id):
    """
    Altera o modo de liberação de uma porta específica (Liberada Total, Whitelist ou Bloqueada).
    Suporta atualização instantânea via AJAX sem recarregar a página.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    port = get_object_or_404(ProxyPort, id=port_id)

    # Verifica permissão do usuário para esta porta
    if not profile.is_admin and port not in profile.allowed_ports.all() and port.group not in profile.allowed_groups.all():
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Acesso negado'}, status=403)
        return HttpResponseForbidden("Você não tem permissão para controlar esta porta.")

    new_status = request.POST.get('status') or request.GET.get('status')
    if new_status in ['ALLOWED', 'WHITELIST', 'BLOCKED']:
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
    lists = ProxyList.objects.filter(list_type='WHITELIST').prefetch_related('domains', 'applied_groups_whitelist').order_by('name')

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
            is_active=True
        )

        if selected_groups:
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
    Edição de metadados da Lista (Nome, Descrição, Grupos associados).
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    proxy_list = get_object_or_404(ProxyList, id=list_id)
    all_groups = ProxyGroup.objects.filter(is_active=True)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        selected_groups = request.POST.getlist('groups')

        if not name:
            messages.error(request, 'O nome não pode ficar em branco.')
            return redirect('list_detail', list_id=proxy_list.id)

        proxy_list.name = name
        proxy_list.description = description
        proxy_list.save()

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
    Exclusão de uma Lista inteira.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado: apenas Administradores de TI podem excluir listas.")

    proxy_list = get_object_or_404(ProxyList, id=list_id)
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
