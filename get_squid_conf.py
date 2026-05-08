import paramiko

def get_squid_conf():
    hostname = "10.40.88.3"
    username = "root"
    password = "@info win 123"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(hostname, username=username, password=password, timeout=10)
        print(f"Conectado ao {hostname}")
        
        # O arquivo no pfSense geralmente fica em /usr/local/etc/squid/squid.conf
        # Mas vamos procurar para ter certeza
        commands = [
            "ls /usr/local/etc/squid/squid.conf",
            "cat /usr/local/etc/squid/squid.conf"
        ]
        
        for cmd in commands:
            stdin, stdout, stderr = client.exec_command(cmd)
            print(stdout.read().decode())
        
        client.close()
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    get_squid_conf()
