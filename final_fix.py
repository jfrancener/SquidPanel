import paramiko

def final_fix():
    hostname = "10.40.89.15"
    username = "root"
    password = "@Jufran0803"
    
    squid_ip = "10.40.88.3"
    squid_user = "admin"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname, username=username, password=password)

    # Criar o script usando cat << 'EOF' para evitar expansão de variáveis e problemas de aspas
    setup_script = f"""
cat << 'EOF' > /root/generate_report.sh
#!/bin/bash
# Baixar o log do squid
scp {squid_user}@{squid_ip}:/var/squid/logs/access.log /tmp/squid_access.log

# Normalizar espaços usando python (mais seguro contra problemas de aspas no shell)
python3 -c "import sys; [print(' '.join(line.split())) for line in sys.stdin]" < /tmp/squid_access.log > /tmp/squid_access_clean.log

# Gerar o relatório HTML usando o formato SQUID
goaccess /tmp/squid_access_clean.log --log-format=SQUID -o /var/www/html/index.html --no-global-config

# Limpar logs temporários
rm /tmp/squid_access.log /tmp/squid_access_clean.log
EOF
chmod +x /root/generate_report.sh
"""
    client.exec_command(setup_script)
    
    print("Gerando relatório...")
    stdin, stdout, stderr = client.exec_command("/root/generate_report.sh")
    print(stdout.read().decode())
    err = stderr.read().decode()
    if err:
        print("Erros:", err)
    
    client.close()

if __name__ == "__main__":
    final_fix()
