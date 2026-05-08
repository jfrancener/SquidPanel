import paramiko

def final_fix_v2():
    hostname = "10.40.89.15"
    username = "root"
    password = "@Jufran0803"
    
    squid_ip = "10.40.88.3"
    squid_user = "admin"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname, username=username, password=password)

    setup_script = f"""
cat << 'EOF' > /root/generate_report.sh
#!/bin/bash
# Baixar o log do squid
scp {squid_user}@{squid_ip}:/var/squid/logs/access.log /tmp/squid_access.log

# Remover decimal do timestamp e normalizar espaços
python3 -c "import sys; [print(line.split()[0].split('.')[0] + ' ' + ' '.join(line.split()[1:])) for line in sys.stdin if line.strip()]" < /tmp/squid_access.log > /tmp/squid_access_clean.log

# Gerar o relatório HTML
# Formato: timestamp duration client status/code size method URL - hierarchy/address type
goaccess /tmp/squid_access_clean.log --log-format='%x %~ %h %^/%s %b %m %U %^ %^/%v %^' --date-format=%s --time-format=%s -o /var/www/html/index.html --no-global-config

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
        print("Saída/Erros:", err)
    
    client.close()

if __name__ == "__main__":
    final_fix_v2()
