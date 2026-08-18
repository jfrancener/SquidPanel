#!/usr/bin/env python
"""
SquidPanel - Deploy Automatizado via SSH Direto
Executa o deploy completo através de conexão SSH com o servidor Linux:
1. Commit e Push no repositório Git local (Windows)
2. Conexão SSH segura com o servidor de produção (10.40.88.5)
3. Execução remota: git pull, migrate, squid sync e restart do gunicorn.
"""

import os
import sys
import time
import json
import argparse
import subprocess

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

try:
    import paramiko
except ImportError:
    print("[!] O pacote 'paramiko' nao esta instalado.")
    print("    Execute: pip install paramiko")
    sys.exit(1)


# Arquivo opcional de credenciais locais (ignorado no git)
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.deploy_config.json')


def load_config():
    defaults = {
        'host': '10.40.88.5',
        'port': 22,
        'username': 'root',
        'password': '',
        'key_filename': None,
        'remote_dir': '/var/www/SquidPanel'
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                defaults.update(saved)
        except Exception:
            pass
            
    # Variáveis de ambiente têm precedência se definidas
    if os.environ.get('DEPLOY_SSH_HOST'):
        defaults['host'] = os.environ.get('DEPLOY_SSH_HOST')
    if os.environ.get('DEPLOY_SSH_USER'):
        defaults['username'] = os.environ.get('DEPLOY_SSH_USER')
    if os.environ.get('DEPLOY_SSH_PASSWORD'):
        defaults['password'] = os.environ.get('DEPLOY_SSH_PASSWORD')
    if os.environ.get('DEPLOY_SSH_KEY'):
        defaults['key_filename'] = os.environ.get('DEPLOY_SSH_KEY')
    if os.environ.get('DEPLOY_REMOTE_DIR'):
        defaults['remote_dir'] = os.environ.get('DEPLOY_REMOTE_DIR')
        
    return defaults


def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        print(f"[i] Configuracoes salvas em {CONFIG_FILE}")
    except Exception as e:
        print(f"[!] Erro ao salvar {CONFIG_FILE}: {e}")


def run_local_git(commit_message=None):
    print("\n[1/3] Preparando alteracoes locais no Git...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. git add
    subprocess.run(['git', 'add', '-A'], cwd=base_dir, check=True)
    
    # 2. git status
    status_res = subprocess.run(
        ['git', 'status', '--porcelain'],
        cwd=base_dir,
        capture_output=True,
        text=True
    )
    
    if status_res.stdout.strip():
        msg = commit_message or f"Deploy automatico SSH: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        print(f"[*] Criando commit: '{msg}'")
        subprocess.run(['git', 'commit', '-m', msg], cwd=base_dir, check=True)
    else:
        print("[i] Nenhuma alteracao pendente de commit local.")

    # 3. git push
    print("[*] Enviando alteracoes para origin/main...")
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


def execute_remote_ssh(cfg):
    print(f"\n[2/3] Conectando via SSH em {cfg['username']}@{cfg['host']}:{cfg['port']}...")
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    connect_kwargs = {
        'hostname': cfg['host'],
        'port': cfg['port'],
        'username': cfg['username'],
        'timeout': 15,
        'banner_timeout': 15
    }
    
    if cfg.get('key_filename') and os.path.exists(cfg['key_filename']):
        connect_kwargs['key_filename'] = cfg['key_filename']
    elif cfg.get('password'):
        connect_kwargs['password'] = cfg['password']
    else:
        # Tenta chaves SSH padrao do sistema
        connect_kwargs['look_for_keys'] = True
        connect_kwargs['allow_agent'] = True

    try:
        ssh.connect(**connect_kwargs)
        print("[+] Conexao SSH estabelecida com sucesso!")
    except paramiko.AuthenticationException:
        print("\n[!] Falha de autenticacao SSH.")
        if not cfg.get('password'):
            import getpass
            pwd = getpass.getpass(f"Digite a senha SSH para {cfg['username']}@{cfg['host']}: ")
            if pwd:
                cfg['password'] = pwd
                save_config(cfg)
                connect_kwargs['password'] = pwd
                ssh.connect(**connect_kwargs)
                print("[+] Conectado com a senha fornecida!")
            else:
                return False
        else:
            return False
    except Exception as e:
        print(f"[!] Erro ao conectar via SSH: {e}")
        return False

    print("\n[3/3] Executando comandos de deploy no servidor remoto...")
    print("-" * 65)

    commands = [
        f"cd {cfg['remote_dir']} && git fetch origin main && git reset --hard origin/main",
        f"cd {cfg['remote_dir']} && ./venv/bin/python manage.py migrate --noinput",
        f"cd {cfg['remote_dir']} && ./venv/bin/python manage.py shell -c \""
        "from dashboard.models import ProxyGroup, ProxyPort; "
        "from squid.models import ProxyList, DomainItem; "
        "from squid.squid_sync import apply_squid_changes; "
        "educ = ProxyList.objects.filter(name__icontains='educa').first(); "
        "print('Educacional:', educ); "
        "for dom in ['.michaelis.uol.com.br', '.uerj.br']: "
        "    DomainItem.objects.get_or_create(proxy_list=educ, domain=dom); "
        "for g in ProxyGroup.objects.filter(is_active=True): "
        "    if any(k in g.name.lower() for k in ['ead', 'pedagogia', 'sala']): "
        "        g.whitelists.add(educ); print('Vinculado ao Grupo:', g.name); "
        "ok, msg = apply_squid_changes(); print('Squid Sync:', ok, msg)\"",
        "systemctl restart squidpanel",
        "systemctl reload squid || sudo squid -k reconfigure || true",
        "systemctl is-active squidpanel squid"
    ]

    full_cmd = " && ".join(commands[:4]) + " ; " + " ; ".join(commands[4:])
    
    stdin, stdout, stderr = ssh.exec_command(full_cmd, get_pty=True)
    
    for line in iter(stdout.readline, ""):
        if line:
            print(f"  {line.rstrip()}")
            
    exit_status = stdout.channel.recv_exit_status()
    print("-" * 65)
    
    ssh.close()
    
    if exit_status == 0:
        print("\n[OK] Deploy via SSH concluido com sucesso no servidor de producao!")
        return True
    else:
        print(f"\n[!] Comandos finalizados com codigo de retorno: {exit_status}")
        return False


def main():
    print("=" * 65)
    print(">>> SQUIDPANEL - DEPLOY VIA SSH DIRETO")
    print("=" * 65)

    cfg = load_config()

    parser = argparse.ArgumentParser(description="Deploy Automatizado via SSH para SquidPanel")
    parser.add_argument('--host', default=cfg['host'], help="IP ou Host do servidor (padrao: 10.40.88.5)")
    parser.add_argument('--port', type=int, default=cfg['port'], help="Porta SSH (padrao: 22)")
    parser.add_argument('--user', default=cfg['username'], help="Usuario SSH (padrao: root)")
    parser.add_argument('--password', default=cfg['password'], help="Senha SSH")
    parser.add_argument('--key', default=cfg.get('key_filename'), help="Caminho da chave privada SSH")
    parser.add_argument('--dir', default=cfg['remote_dir'], help="Diretorio remoto da aplicacao")
    parser.add_argument('--save', action='store_true', help="Salva as credenciais no .deploy_config.json")
    parser.add_argument('--skip-git', action='store_true', help="Pula etapa de git local")
    parser.add_argument('message', nargs='*', help="Mensagem do commit")

    args = parser.parse_args()

    cfg['host'] = args.host
    cfg['port'] = args.port
    cfg['username'] = args.user
    if args.password:
        cfg['password'] = args.password
    if args.key:
        cfg['key_filename'] = args.key
    cfg['remote_dir'] = args.dir

    if args.save:
        save_config(cfg)

    commit_msg = " ".join(args.message) if args.message else None

    try:
        if not args.skip_git:
            run_local_git(commit_msg)
        ok = execute_remote_ssh(cfg)
        sys.exit(0 if ok else 1)
    except KeyboardInterrupt:
        print("\n[!] Operacao cancelada pelo usuario.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[!] Erro fatal: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
