import paramiko

def verify_blacklist():
    hostname = "10.40.88.3"
    username = "root"
    password = "@info win 123"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(hostname, username=username, password=password, timeout=10)
        print(f"Conectado ao {hostname}")
        
        commands = [
            "grep 'cloudflare.com' /var/squid/acl/git_blacklist.acl",
            "ls -l /var/squid/acl/git_blacklist.acl",
            "tail -n 5 /var/squid/acl/git_blacklist.acl"
        ]
        
        for cmd in commands:
            print(f"Executando: {cmd}")
            stdin, stdout, stderr = client.exec_command(cmd)
            print(stdout.read().decode())
        
        client.close()
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    verify_blacklist()
