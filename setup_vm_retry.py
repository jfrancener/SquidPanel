import paramiko
import time

def setup_vm():
    hostname = "10.40.89.15"
    username = "root"
    password = "@Jufran0803"
    
    print(f"Conectando a {hostname} como {username}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(hostname, username=username, password=password, look_for_keys=False, allow_agent=False)
        print("Conectado com sucesso!")
    except Exception as e:
        print(f"Erro ao conectar: {e}")
        return

    commands = [
        "apt-get update",
        "apt-get install -y goaccess nginx sshpass",
        "mkdir -p /var/www/html/squid-report",
        "if [ ! -f /root/.ssh/id_rsa ]; then ssh-keygen -t rsa -N '' -f /root/.ssh/id_rsa; fi"
    ]
    
    for cmd in commands:
        print(f"Executando: {cmd}")
        stdin, stdout, stderr = client.exec_command(cmd)
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            print(f"Erro: {stderr.read().decode()}")
        else:
            print(f"OK: {cmd}")

    client.close()

if __name__ == "__main__":
    setup_vm()
