import paramiko

def fix_report_script():
    hostname = "10.40.89.15"
    username = "root"
    password = "@Jufran0803"
    
    squid_ip = "10.40.88.3"
    squid_user = "admin"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname, username=username, password=password)

    report_script = f"""#!/bin/bash
# Baixar o log do squid
scp {squid_user}@{squid_ip}:/var/squid/logs/access.log /tmp/squid_access.log

# Limpar espaços extras
awk '$1=$1' /tmp/squid_access.log > /tmp/squid_access_clean.log

# Gerar o relatório HTML
goaccess /tmp/squid_access_clean.log --log-format=SQUID -o /var/www/html/index.html --no-global-config

# Limpar logs temporários
rm /tmp/squid_access.log /tmp/squid_access_clean.log
"""
    client.exec_command(f"echo '{report_script}' > /root/generate_report.sh")
    client.exec_command("chmod +x /root/generate_report.sh")
    
    print("Gerando relatório...")
    stdin, stdout, stderr = client.exec_command("/root/generate_report.sh")
    print(stdout.read().decode())
    print(stderr.read().decode())
    
    client.close()

if __name__ == "__main__":
    fix_report_script()
