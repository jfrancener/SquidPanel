import paramiko

def finalize_config():
    hostname = "10.40.89.15"
    username = "root"
    password = "@Jufran0803"
    
    squid_ip = "10.40.88.3"
    squid_user = "admin"
    squid_pass = "@info win 123"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname, username=username, password=password)

    # 1. Copiar chave para o Squid (usando sshpass para automatizar a primeira vez)
    print("Configurando SSH sem senha para o Squid...")
    copy_key_cmd = f"sshpass -p '{squid_pass}' ssh-copy-id -o StrictHostKeyChecking=no {squid_user}@{squid_ip}"
    stdin, stdout, stderr = client.exec_command(copy_key_cmd)
    stdout.channel.recv_exit_status()

    # 2. Criar o script de geração de relatório
    print("Criando script de relatório...")
    report_script = f"""#!/bin/bash
# Baixar o log do squid
scp {squid_user}@{squid_ip}:/var/log/squid/access.log /tmp/squid_access.log

# Gerar o relatório HTML
# --log-format=SQUID é o padrão para o Squid
goaccess /tmp/squid_access.log --log-format=SQUID -o /var/www/html/index.html --real-time-html --no-global-config

# Limpar log temporário
rm /tmp/squid_access.log
"""
    client.exec_command(f"echo '{report_script}' > /root/generate_report.sh")
    client.exec_command("chmod +x /root/generate_report.sh")

    # 3. Configurar Nginx (servir /var/www/html na porta 80)
    print("Configurando Nginx...")
    nginx_conf = """
server {
    listen 80;
    server_name _;
    root /var/www/html;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
"""
    client.exec_command(f"echo '{nginx_conf}' > /etc/nginx/sites-available/default")
    client.exec_command("systemctl restart nginx")

    # 4. Agendar no Cron (a cada 10 minutos)
    print("Agendando no cron...")
    cron_job = "*/10 * * * * /root/generate_report.sh > /dev/null 2>&1"
    client.exec_command(f"(crontab -l 2>/dev/null; echo '{cron_job}') | crontab -")

    # 5. Executar a primeira vez
    print("Gerando primeiro relatório...")
    client.exec_command("/root/generate_report.sh")

    print("Configuração finalizada!")
    client.close()

if __name__ == "__main__":
    finalize_config()
