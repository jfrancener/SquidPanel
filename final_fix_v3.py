import paramiko

def final_fix_v3():
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

# Converter Squid para formato que GoAccess entenda melhor (CLF aproximado)
python3 -c "
import sys, datetime
for line in sys.stdin:
    parts = line.split()
    if len(parts) < 7: continue
    ts = datetime.datetime.fromtimestamp(float(parts[0]))
    dt = ts.strftime('%d/%b/%Y:%H:%M:%S +0000')
    # ip - - [date] \"method url\" status size
    print(f'{{parts[2]}} - - [{{dt}}] \"{{parts[5]}} {{parts[6]}} HTTP/1.1\" {{parts[3].split(\"/\")[-1]}} {{parts[4]}}')
" < /tmp/squid_access.log > /tmp/squid_access_clean.log

# Gerar o relatório HTML usando o formato COMBINED
goaccess /tmp/squid_access_clean.log --log-format=COMBINED -o /var/www/html/index.html --no-global-config

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
    final_fix_v3()
