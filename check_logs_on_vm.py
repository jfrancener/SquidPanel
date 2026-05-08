import paramiko

def check_logs():
    hostname = "10.40.89.15"
    username = "root"
    passwords = ["@Jufran0803", "@info win 123"]
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    for password in passwords:
        try:
            client.connect(hostname, username=username, password=password, timeout=10)
            print(f"Conectado ao {hostname}")
            
            # Verificar se existem logs do squid no home ou em /tmp
            commands = [
                "ls -lh /root/access.log",
                "ls -lh /tmp/access.log",
                "ls -lh /var/www/html/report/",
                "crontab -l"
            ]
            
            for cmd in commands:
                print(f"Executando: {cmd}")
                stdin, stdout, stderr = client.exec_command(cmd)
                print(stdout.read().decode())
                print(stderr.read().decode())
            
            client.close()
            return
        except Exception as e:
            print(f"Erro com senha {password}: {e}")

if __name__ == "__main__":
    check_logs()
