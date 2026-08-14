from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.db import models
from django.utils.text import slugify

from .models import ProxyList, DomainItem
from dashboard.models import ProxyGroup, UserProfile

# ==========================================
# 1. LISTAGEM DE WHITELISTS E BLACKLISTS
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
# 2. CRIAÇÃO, EDIÇÃO E EXCLUSÃO DE LISTAS
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

        # Associa aos grupos selecionados
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

    # Processa adição individual de domínio
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

        # Atualiza a associação dos grupos
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
# 3. GESTÃO DE DOMÍNIOS (INDIVIDUAL & EM LOTE)
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
