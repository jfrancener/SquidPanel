import paramiko
import os

def download_log():
    hostname = "10.40.88.3"
    usernames = ["root", "admin"]
    passwords = ["@Jufran0803", "@info win 123"]
    remote_path = "/var/log/squid/access.log"
    local_path = "access.log"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    for password in passwords:
        for username in usernames:
            try:
                print(f"Tentando conectar ao {hostname} como {username}...")
                client.connect(hostname, username=username, password=password, timeout=10)
                print(f"Conectado com sucesso!")
                
                sftp = client.open_sftp()
                print(f"Baixando {remote_path} para {local_path}...")
                sftp.get(remote_path, local_path)
                sftp.close()
                client.close()
                print("Download concluído!")
                return True
            except Exception as e:
                print(f"Falha com {username}@{hostname}: {e}")
    
    print("Não foi possível baixar o log.")
    return False

if __name__ == "__main__":
    download_log()
