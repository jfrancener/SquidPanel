import paramiko

def list_log_dirs():
    hostname = "10.40.88.3"
    username = "root"
    password = "@info win 123"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(hostname, username=username, password=password, timeout=10)
        print(f"Conectado ao {hostname}")
        
        commands = [
            "ls -F /var/log/squid/",
            "ls -F /var/log/",
            "find /var/log -name '*access.log*'",
            "squid -v | grep -i 'log'"
        ]
        
        for cmd in commands:
            print(f"Executando: {cmd}")
            stdin, stdout, stderr = client.exec_command(cmd)
            print(stdout.read().decode())
            print(stderr.read().decode())
        
        client.close()
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    list_log_dirs()
