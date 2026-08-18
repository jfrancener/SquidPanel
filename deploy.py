#!/usr/bin/env python
"""
SquidPanel - Script de Deploy Automatizado
Executa o fluxo completo de deploy:
1. Commit e Push no repositório Git local
2. Acionamento do webhook seguro de produção (10.40.88.5)
3. Execução automática de 'git pull', migrações, recarga do Squid e reinício do WSGI no servidor.
"""

import sys
import os
import subprocess
import urllib.request
import urllib.error
import json
import time

# Configura encoding para UTF-8 no Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

SERVER_URL = os.environ.get('SQUIDPANEL_SERVER_URL', 'http://10.40.88.5/adminsp/api/deploy/')
DEPLOY_TOKEN = os.environ.get('SQUIDPANEL_DEPLOY_TOKEN', 'squidpanel-deploy-secret-2026')


def print_banner():
    print("=" * 65)
    print(">>> SQUIDPANEL - DEPLOY AUTOMATIZADO PARA PRODUCAO")
    print("=" * 65)


def run_git_steps(commit_message=None):
    print("\n[1/3] Verificando alteracoes locais no Git...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. git add
    subprocess.run(['git', 'add', '-A'], cwd=base_dir, check=True)
    
    # 2. Verifica se há algo para commitar
    status_res = subprocess.run(
        ['git', 'status', '--porcelain'],
        cwd=base_dir,
        capture_output=True,
        text=True
    )
    
    if status_res.stdout.strip():
        msg = commit_message or f"Deploy automatico: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        print(f"[*] Criando commit: '{msg}'")
        subprocess.run(['git', 'commit', '-m', msg], cwd=base_dir, check=True)
    else:
        print("[i] Nenhuma alteracao pendente de commit local.")

    # 3. git push
    print("[*] Enviando alteracoes para o repositorio remoto (origin main)...")
    push_res = subprocess.run(
        ['git', 'push', 'origin', 'main'],
        cwd=base_dir,
        capture_output=True,
        text=True
    )
    if push_res.returncode != 0:
        print(f"[!] Aviso no Git Push: {push_res.stderr.strip() or push_res.stdout.strip()}")
    else:
        print("[+] Git Push concluido com sucesso!")


def trigger_server_deploy():
    print(f"\n[2/3] Acionando deploy no servidor remoto ({SERVER_URL})...")
    
    headers = {
        'User-Agent': 'SquidPanel-DeployCLI/1.0',
        'X-Deploy-Token': DEPLOY_TOKEN,
        'Content-Type': 'application/json'
    }
    
    req_data = json.dumps({'token': DEPLOY_TOKEN}).encode('utf-8')
    req = urllib.request.Request(SERVER_URL, data=req_data, headers=headers, method='POST')
    
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw_res = resp.read().decode('utf-8')
            data = json.loads(raw_res)
            
            print("\n[3/3] Resumo da Execucao no Servidor:")
            print("-" * 55)
            if data.get('logs'):
                for log in data['logs']:
                    print(f"  - {log}")
            print("-" * 55)
            
            if data.get('success'):
                print(f"[OK] {data.get('message', 'Deploy concluido com sucesso!')}\n")
                return True
            else:
                print(f"[ERRO] Erro reportado pelo servidor: {data.get('error')}\n")
                return False
                
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8', errors='ignore')
        print(f"\n[!] Erro HTTP {e.code} ao conectar no servidor: {err_msg}")
        return False
    except Exception as e:
        print(f"\n[!] Falha na conexao com o servidor de producao: {e}")
        print("[i] Dica: Verifique se o servidor 10.40.88.5 esta acessivel na rede.")
        return False


def main():
    print_banner()
    commit_msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    
    try:
        run_git_steps(commit_msg)
        success = trigger_server_deploy()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n💥 Erro inesperado durante o deploy: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
