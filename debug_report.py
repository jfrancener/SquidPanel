import paramiko

def debug_conversion():
    hostname = "10.40.89.15"
    username = "root"
    password = "@Jufran0803"
    
    squid_ip = "10.40.88.3"
    squid_user = "admin"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname, username=username, password=password)

    # Script sem o 'rm' final para podermos inspecionar
    setup_script = f"""
cat << 'EOF' > /root/generate_report.sh
#!/bin/bash
scp {squid_user}@{squid_ip}:/var/squid/logs/access.log /tmp/squid_access.log 2>/tmp/scp_error.log

python3 -c "
import sys, datetime
count = 0
for line in sys.stdin:
    try:
        parts = line.split()
        if len(parts) < 7: continue
        ts = datetime.datetime.fromtimestamp(float(parts[0]))
        dt = ts.strftime('%d/%b/%Y:%H:%M:%S +0000')
        status = parts[3].split('/')[-1]
        print(f'{{parts[2]}} - - [{{dt}}] \"{{parts[5]}} {{parts[6]}} HTTP/1.1\" {{status}} {{parts[4]}}')
        count += 1
    except Exception as e:
        sys.stderr.write(f'Erro na linha: {{e}}\\n')
sys.stderr.write(f'Convertidas {{count}} linhas\\n')
" < /tmp/squid_access.log > /tmp/squid_access_clean.log 2>/tmp/conv_error.log

goaccess /tmp/squid_access_clean.log --log-format=COMBINED -o /var/www/html/index.html --no-global-config 2>/tmp/goaccess_error.log
EOF
chmod +x /root/generate_report.sh
"""
    client.exec_command(setup_script)
    
    print("Executando script de debug...")
    stdin, stdout, stderr = client.exec_command("/root/generate_report.sh")
    stdout.channel.recv_exit_status()
    
    # Verificar erros
    print("--- Erro SCP ---")
    stdin, stdout, stderr = client.exec_command("cat /tmp/scp_error.log")
    print(stdout.read().decode())
    
    print("--- Erro Conversão ---")
    stdin, stdout, stderr = client.exec_command("cat /tmp/conv_error.log")
    print(stdout.read().decode())
    
    print("--- Erro GoAccess ---")
    stdin, stdout, stderr = client.exec_command("cat /tmp/goaccess_error.log")
    print(stdout.read().decode())

    print("--- Amostra do log limpo ---")
    stdin, stdout, stderr = client.exec_command("head -n 5 /tmp/squid_access_clean.log")
    print(stdout.read().decode())

    client.close()

if __name__ == "__main__":
    debug_conversion()
