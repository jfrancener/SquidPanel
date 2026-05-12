import os
import re
import paramiko
import subprocess
from collections import defaultdict
from django.shortcuts import render, redirect
from django.http import JsonResponse
from .models import DomainRule
from django.views.decorators.csrf import csrf_exempt

import tldextract

def get_squid_logs():
    hostname = "10.40.88.3"
    username = "root"
    password = "@info win 123"
    
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname, username=username, password=password, timeout=5)
        
        stdin, stdout, stderr = client.exec_command('cat /var/squid/logs/access.log')
        logs = stdout.read().decode('utf-8').splitlines()
        client.close()
        return logs
    except Exception as e:
        print(f"Erro ao conectar no pfSense: {e}")
        return []

def extract_domain(url_or_domain):
    clean = url_or_domain.split(':')[0]
    match = re.search(r'[a-z0-9\-\.]+\.[a-z]{2,}', clean.lower())
    if match:
        return match.group(0)
    return None

def dashboard(request):
    logs = get_squid_logs()
    
    # Busca todas as regras salvas no banco
    rules = DomainRule.objects.all()
    blacklist = {r.domain for r in rules if r.rule_type == 'block'}
    whitelist = {r.domain for r in rules if r.rule_type == 'allow'}
    hidden_domains = {r.domain for r in rules if r.rule_type == 'hide'}
    verified_domains = {r.domain for r in rules if r.is_verified}
    
    groups = defaultdict(lambda: {
        'count': 0, 
        'subdomains': defaultdict(lambda: {'count': 0, 'status': 'Desconhecido'}),
        'is_hidden': False,
        'in_blacklist': False,
        'in_whitelist': False,
        'is_verified': False
    })
    
    for line in logs:
        parts = line.split()
        if len(parts) >= 7:
            status = parts[3]
            url = parts[6]
            domain = extract_domain(url)
            
            if domain:
                ext = tldextract.extract(domain)
                root_domain = ext.registered_domain if ext.registered_domain else domain
                
                # Check root level rules
                root_hidden = root_domain in hidden_domains
                groups[root_domain]['is_hidden'] = root_hidden
                groups[root_domain]['in_blacklist'] = root_domain in blacklist
                groups[root_domain]['in_whitelist'] = root_domain in whitelist
                groups[root_domain]['is_verified'] = root_domain in verified_domains
                
                # Add to total hits of the group
                groups[root_domain]['count'] += 1
                
                # Register the specific subdomain
                groups[root_domain]['subdomains'][domain]['count'] += 1
                groups[root_domain]['subdomains'][domain]['is_verified'] = domain in verified_domains
                
                if 'DENIED' in status:
                    groups[root_domain]['subdomains'][domain]['status'] = 'Bloqueado'
                elif groups[root_domain]['subdomains'][domain]['status'] != 'Bloqueado':
                    groups[root_domain]['subdomains'][domain]['status'] = 'Liberado'
    
    context_domains = []
    for root_dom, data in groups.items():
        subs = []
        # Calculate group aggregated status
        all_blocked = True
        all_allowed = True
        
        for sub_dom, sub_data in data['subdomains'].items():
            sub_is_hidden = data['is_hidden'] or (sub_dom in hidden_domains)
            sub_is_verified = data['is_verified'] or sub_data.get('is_verified', False)
            
            if sub_data['status'] == 'Liberado':
                all_blocked = False
            if sub_data['status'] == 'Bloqueado':
                all_allowed = False
                
            subs.append({
                'domain': sub_dom,
                'count': sub_data['count'],
                'last_status': sub_data['status'],
                'in_blacklist': sub_dom in blacklist,
                'in_whitelist': sub_dom in whitelist,
                'is_hidden': sub_is_hidden,
                'is_verified': sub_is_verified,
                'is_root': sub_dom == root_dom
            })
            
        subs.sort(key=lambda x: x['count'], reverse=True)
        
        group_status = 'Misto'
        if all_blocked and not all_allowed: group_status = 'Bloqueado'
        elif all_allowed and not all_blocked: group_status = 'Liberado'
        
        # Se houver apenas 1 subdomínio E for exatamente o root, simplificamos no template
        is_single_root = len(subs) == 1 and subs[0]['domain'] == root_dom
        
        # Filtra para não mostrar lixo (menos de 10 requisições no total da família), 
        # a menos que a família ou algum subdomínio tenha uma regra aplicada.
        has_root_rule = data['in_blacklist'] or data['in_whitelist'] or data['is_hidden']
        has_sub_rule = any(sub['in_blacklist'] or sub['in_whitelist'] or sub['is_hidden'] for sub in subs)
        
        if data['count'] >= 10 or has_root_rule or has_sub_rule:
            context_domains.append({
                'domain': root_dom,
                'count': data['count'],
                'last_status': group_status,
                'in_blacklist': data['in_blacklist'],
                'in_whitelist': data['in_whitelist'],
                'is_hidden': data['is_hidden'],
                'is_verified': data['is_verified'],
                'subdomains': subs,
                'is_single': len(subs) == 1
            })
        
    context_domains.sort(key=lambda x: x['count'], reverse=True)
    
    return render(request, 'dashboard/index.html', {
        'domains': context_domains, 
        'total_logs': len(logs),
        'full_blacklist': sorted(list(blacklist)),
        'full_whitelist': sorted(list(whitelist))
    })

@csrf_exempt
def domain_action(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        domain = request.POST.get('domain')
        
        if not domain or not action:
            return JsonResponse({'success': False, 'error': 'Dados invalidos'})
        
        clean_domain = domain.lstrip('.')
        
        if action == 'unhide':
            DomainRule.objects.filter(domain=clean_domain, rule_type='hide').delete()
            return JsonResponse({'success': True})
            
        if action == 'remove_rule':
            rule = DomainRule.objects.filter(domain=clean_domain).first()
            if rule:
                if rule.is_verified:
                    rule.rule_type = 'none'
                    rule.save()
                else:
                    rule.delete()
            return JsonResponse({'success': True})
            
        if action == 'edit_rule':
            old_domain = request.POST.get('old_domain')
            if old_domain:
                old_domain = old_domain.lstrip('.')
                rule = DomainRule.objects.filter(domain=old_domain).first()
                if rule:
                    rule.domain = clean_domain
                    rule.save()
            return JsonResponse({'success': True})
            
        if action in ['block', 'allow', 'hide', 'verify', 'unverify']:
            if action == 'verify':
                rule, created = DomainRule.objects.get_or_create(domain=clean_domain)
                rule.is_verified = True
                rule.save()
                return JsonResponse({'success': True})
            elif action == 'unverify':
                rule, created = DomainRule.objects.get_or_create(domain=clean_domain)
                rule.is_verified = False
                rule.save()
                return JsonResponse({'success': True})
            
            # Para as outras ações (block, allow, hide)
            rule, created = DomainRule.objects.get_or_create(domain=clean_domain)
            rule.rule_type = action
            rule.save()
            return JsonResponse({'success': True})
        
    return JsonResponse({'success': False})

@csrf_exempt
def mass_domain_action(request):
    if request.method == 'POST':
        import json
        try:
            data = json.loads(request.body)
            action = data.get('action')
            domains = data.get('domains', [])
            
            if not domains or not action:
                return JsonResponse({'success': False, 'error': 'Dados invalidos'})
                
            for domain in domains:
                clean_domain = domain.lstrip('.')
                
                if action == 'verify':
                    rule, _ = DomainRule.objects.get_or_create(domain=clean_domain)
                    rule.is_verified = True
                    rule.save()
                elif action == 'allow':
                    rule, _ = DomainRule.objects.get_or_create(domain=clean_domain)
                    rule.rule_type = 'allow'
                    rule.save()
                elif action == 'block':
                    rule, _ = DomainRule.objects.get_or_create(domain=clean_domain)
                    rule.rule_type = 'block'
                    rule.save()
                    
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
            
    return JsonResponse({'success': False})

@csrf_exempt
def save_and_sync(request):
    """
    Gera blacklist e whitelist baseado no DB, commita e faz push.
    Depois, aciona o update via SSH.
    """
    if request.method == 'POST':
        from django.conf import settings
        base_dir = str(settings.BASE_DIR)
        black_path = os.path.join(base_dir, 'blacklist.txt')
        white_path = os.path.join(base_dir, 'whitelist.txt')
        
        rules = DomainRule.objects.all()
        
        try:
            # Puxa as atualizações do GitHub primeiro para não dar conflito (rejeição de push)
            subprocess.run(["git", "fetch", "origin", "main"], cwd=base_dir)
            subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=base_dir)
            
            def filter_redundant(domain_list):
                # Sort by length so parents come first
                sorted_domains = sorted(domain_list, key=len)
                filtered = []
                for d in sorted_domains:
                    is_redundant = False
                    for parent in filtered:
                        if d == parent or d.endswith('.' + parent):
                            is_redundant = True
                            break
                    if not is_redundant:
                        filtered.append(d)
                return sorted(filtered)
            
            blocks = [r.domain for r in rules.filter(rule_type='block')]
            allows = [r.domain for r in rules.filter(rule_type='allow')]
            
            with open(black_path, 'w', encoding='utf-8') as f:
                for d in filter_redundant(blocks):
                    f.write(f".{d}\n")
                    
            with open(white_path, 'w', encoding='utf-8') as f:
                for d in filter_redundant(allows):
                    f.write(f".{d}\n")
                    
            # Sincroniza com GitHub
            subprocess.run(["git", "add", "blacklist.txt", "whitelist.txt"], cwd=base_dir, check=True)
            subprocess.run(["git", "commit", "-m", "Sync DB via Dashboard"], cwd=base_dir) 
            subprocess.run(["git", "push", "origin", "main"], cwd=base_dir, check=True)
            
            # Executa no firewall
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect("10.40.88.3", username="root", password="@info win 123", timeout=10)
            client.exec_command("/root/update_lists.sh")
            client.close()
            
            return JsonResponse({'success': True, 'message': 'Listas salvas, enviadas ao GitHub e atualizadas no Firewall!'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
            
    return JsonResponse({'success': False})

@csrf_exempt
def sync_from_github(request):
    """
    Puxa a versão mais recente do GitHub e atualiza o banco de dados (whitelist e blacklist).
    Isso garante que edições feitas direto no site do GitHub entrem no sistema.
    """
    if request.method == 'POST':
        base_dir = "d:\\Projetos Code\\serv"
        black_path = os.path.join(base_dir, 'blacklist.txt')
        white_path = os.path.join(base_dir, 'whitelist.txt')
        
        try:
            # Puxa a força o que está no GitHub
            subprocess.run(["git", "fetch", "origin", "main"], cwd=base_dir, check=True)
            subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=base_dir, check=True)
            
            # Lê os arquivos e atualiza o banco
            if os.path.exists(black_path):
                with open(black_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        domain = line.strip().lstrip('.')
                        if domain:
                            # Se não existir regra, ou se existir e não for 'hide', atualiza para 'block'
                            rule, created = DomainRule.objects.get_or_create(domain=domain, defaults={'rule_type': 'block'})
                            if not created and rule.rule_type != 'hide':
                                rule.rule_type = 'block'
                                rule.save()
                                
            if os.path.exists(white_path):
                with open(white_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        domain = line.strip().lstrip('.')
                        if domain:
                            rule, created = DomainRule.objects.get_or_create(domain=domain, defaults={'rule_type': 'allow'})
                            if not created and rule.rule_type != 'hide':
                                rule.rule_type = 'allow'
                                rule.save()
                                
            return JsonResponse({'success': True, 'message': 'Banco de dados atualizado com a versão do GitHub.'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
            
    return JsonResponse({'success': False})
