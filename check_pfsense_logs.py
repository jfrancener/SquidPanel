import paramiko

def check_pf_squid():
    hostname = "10.40.88.3"
    username = "root"
    password = "@info win 123"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(hostname, username=username, password=password, timeout=10)
        print(f"Conectado ao {hostname}")
        
        commands = [
            "ls -R /var/squid/",
            "ls -R /var/log/squid/",
            "find / -name access.log 2>/dev/null",
            "clog /var/log/squid/access.log | head -n 20", # pfSense use clog for some logs
            "tail -n 20 /var/log/squid/access.log"
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
    check_pf_squid()
