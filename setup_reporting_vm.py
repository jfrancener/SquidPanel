import paramiko
import time

def setup_vm():
    hostname = "10.40.89.15"
    username = "admin"
    passwords = ["@Jufran0803", "@info win 123"]
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    def handler(title, instructions, prompt_list):
        if not prompt_list:
            return []
        return [password for _ in prompt_list]

    for password in passwords:
        for username in ["root", "admin"]:
            try:
                print(f"Tentando {username} com senha {password}...")
                client.connect(hostname, username=username, password=password, look_for_keys=False, allow_agent=False, timeout=30)
                print(f"Conectado com sucesso como {username}!")
                found = True
                break
            except paramiko.AuthenticationException:
                try:
                    # Tentar keyboard-interactive
                    transport = client.get_transport()
                    if transport is None:
                        transport = paramiko.Transport(hostname)
                        transport.start_client()
                    transport.auth_interactive(username, handler)
                    print(f"Conectado via interativo como {username}!")
                    found = True
                    break
                except:
                    print(f"Senha incorreta para {username}: {password}")
            except Exception as e:
                print(f"Erro com {username}: {e}")
        if found: break
    else:
        print("Falha total na autenticação.")
        return
    
    commands = [
        "apt-get update",
        "apt-get install -y goaccess nginx sshpass",
        # Criar diretório para o relatório se não existir
        "mkdir -p /var/www/html/report",
        # Gerar chave SSH se não existir (para o acesso ao Squid)
        "if [ ! -f /root/.ssh/id_rsa ]; then ssh-keygen -t rsa -N '' -f /root/.ssh/id_rsa; fi"
    ]
    
    for cmd in commands:
        print(f"Executando: {cmd}")
        stdin, stdout, stderr = client.exec_command(cmd)
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            print(f"Erro ao executar {cmd}: {stderr.read().decode()}")
        else:
            print(f"Sucesso: {cmd}")

    client.close()

if __name__ == "__main__":
    setup_vm()
