from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.db import models
from django.utils.text import slugify

from .models import ProxyList, DomainItem
from dashboard.models import ProxyGroup, UserProfile

# ==========================================
# GESTÃO DE WHITELISTS MODULARES
# ==========================================

@login_required
def whitelists_view(request):
    """
    Listagem de todas as Whitelists criadas no sistema em cards e tabela.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado: apenas Administradores e Coordenadores podem gerenciar Whitelists.")

    query = request.GET.get('q', '').strip()
    whitelists = ProxyList.objects.filter(list_type='WHITELIST').prefetch_related('domains', 'applied_groups_whitelist').order_by('name')

    if query:
        whitelists = whitelists.filter(
            models.Q(name__icontains=query) |
            models.Q(description__icontains=query)
        )

    # Estatísticas gerais
    total_lists = whitelists.count()
    total_domains = DomainItem.objects.filter(proxy_list__list_type='WHITELIST', is_active=True).count()
    all_groups = ProxyGroup.objects.filter(is_active=True)

    return render(request, 'squid/whitelists.html', {
        'profile': profile,
        'whitelists': whitelists,
        'query': query,
        'total_lists': total_lists,
        'total_domains': total_domains,
        'all_groups': all_groups,
        'active_menu': 'whitelists'
    })


@login_required
def whitelist_create_view(request):
    """
    Criação de uma nova Whitelist temática.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    all_groups = ProxyGroup.objects.filter(is_active=True)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', 'emerald').strip()
        description = request.POST.get('description', '').strip()
        selected_groups = request.POST.getlist('groups')

        if not name:
            messages.error(request, 'O nome da Whitelist é obrigatório.')
            return redirect('whitelists')

        slug = slugify(name)
        if ProxyList.objects.filter(name=name, list_type='WHITELIST').exists():
            messages.error(request, f"Já existe uma Whitelist com o nome '{name}'.")
            return redirect('whitelists')

        proxy_list = ProxyList.objects.create(
            name=name,
            slug=slug,
            list_type='WHITELIST',
            color=color,
            description=description,
            is_active=True
        )

        # Associa aos grupos selecionados
        if selected_groups:
            groups = ProxyGroup.objects.filter(id__in=selected_groups)
            for g in groups:
                g.whitelists.add(proxy_list)

        messages.success(request, f"Whitelist '{name}' criada com sucesso! Agora você pode adicionar domínios.")
        return redirect('whitelist_detail', list_id=proxy_list.id)

    return redirect('whitelists')


@login_required
def whitelist_detail_view(request, list_id):
    """
    Visualização detalhada e gerenciamento de domínios dentro de uma Whitelist.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    proxy_list = get_object_or_404(ProxyList, id=list_id, list_type='WHITELIST')
    query = request.GET.get('q', '').strip()

    domains = proxy_list.domains.all().order_by('domain')
    if query:
        domains = domains.filter(
            models.Q(domain__icontains=query) |
            models.Q(description__icontains=query)
        )

    all_groups = ProxyGroup.objects.filter(is_active=True)
    applied_groups = proxy_list.applied_groups_whitelist.filter(is_active=True)

    # Processa adição individual de domínio
    if request.method == 'POST' and 'add_domain' in request.POST:
        domain_str = request.POST.get('domain', '').strip()
        desc = request.POST.get('domain_description', '').strip()

        if domain_str:
            # Cria o item (o clean_domain é chamado automaticamente no model)
            item = DomainItem(proxy_list=proxy_list, domain=domain_str, description=desc)
            cleaned = item.clean_domain()

            if proxy_list.domains.filter(domain=cleaned).exists():
                messages.warning(request, f"O domínio '{cleaned}' já está nesta Whitelist.")
            else:
                item.save()
                messages.success(request, f"Domínio '{cleaned}' adicionado com sucesso!")
        else:
            messages.error(request, 'Digite um domínio válido.')

        return redirect('whitelist_detail', list_id=proxy_list.id)

    return render(request, 'squid/list_detail.html', {
        'profile': profile,
        'proxy_list': proxy_list,
        'domains': domains,
        'query': query,
        'all_groups': all_groups,
        'applied_groups': applied_groups,
        'active_menu': 'whitelists'
    })


@login_required
def whitelist_edit_view(request, list_id):
    """
    Edição de metadados da Whitelist (Nome, Cor, Descrição, Grupos associados).
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    proxy_list = get_object_or_404(ProxyList, id=list_id, list_type='WHITELIST')
    all_groups = ProxyGroup.objects.filter(is_active=True)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', proxy_list.color).strip()
        description = request.POST.get('description', '').strip()
        selected_groups = request.POST.getlist('groups')

        if not name:
            messages.error(request, 'O nome não pode ficar em branco.')
            return redirect('whitelist_detail', list_id=proxy_list.id)

        proxy_list.name = name
        proxy_list.color = color
        proxy_list.description = description
        proxy_list.save()

        # Atualiza a associação dos grupos
        for g in all_groups:
            if str(g.id) in selected_groups:
                g.whitelists.add(proxy_list)
            else:
                g.whitelists.remove(proxy_list)

        messages.success(request, f"Whitelist '{proxy_list.name}' atualizada com sucesso!")
        return redirect('whitelist_detail', list_id=proxy_list.id)

    return redirect('whitelist_detail', list_id=proxy_list.id)


@login_required
def whitelist_delete_view(request, list_id):
    """
    Exclusão de uma Whitelist inteira.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_admin:
        return HttpResponseForbidden("Acesso negado: apenas Administradores de TI podem excluir listas.")

    proxy_list = get_object_or_404(ProxyList, id=list_id, list_type='WHITELIST')
    name = proxy_list.name
    proxy_list.delete()

    messages.success(request, f"Whitelist '{name}' foi excluída com sucesso.")
    return redirect('whitelists')


@login_required
def domain_delete_view(request, list_id, domain_id):
    """
    Exclusão de um domínio individual de uma lista.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.is_manager:
        return HttpResponseForbidden("Acesso negado.")

    proxy_list = get_object_or_404(ProxyList, id=list_id)
    domain_item = get_object_or_404(DomainItem, id=domain_id, proxy_list=proxy_list)

    dom_name = domain_item.domain
    domain_item.delete()

    messages.success(request, f"Domínio '{dom_name}' removido da lista.")
    return redirect('whitelist_detail', list_id=proxy_list.id)


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
            # Ignora linhas de comentários
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

        messages.success(request, f"Importação concluída: {added_count} domínios adicionados com sucesso! ({duplicate_count} já existiam ou eram inválidos).")

    return redirect('whitelist_detail', list_id=proxy_list.id)
