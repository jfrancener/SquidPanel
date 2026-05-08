import paramiko

def fix_with_separate_script():
    hostname = "10.40.89.15"
    username = "root"
    password = "@Jufran0803"
    
    squid_ip = "10.40.88.3"
    squid_user = "admin"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname, username=username, password=password)

    # 1. Criar o script de conversão Python de forma limpa
    convert_script = """
import sys, datetime
for line in sys.stdin:
    try:
        parts = line.split()
        if len(parts) < 7: continue
        ts = datetime.datetime.fromtimestamp(float(parts[0]))
        dt = ts.strftime('%d/%b/%Y:%H:%M:%S +0000')
        status = parts[3].split('/')[-1]
        method = parts[5]
        url = parts[6]
        size = parts[4]
        ip = parts[2]
        print(f'{ip} - - [{dt}] "{method} {url} HTTP/1.1" {status} {size}')
    except:
        continue
"""
    # Usando sftp para enviar o arquivo sem problemas de escape
    sftp = client.open_sftp()
    with sftp.open("/root/convert_squid.py", "w") as f:
        f.write(convert_script)
    sftp.close()

    # 2. Criar o script Bash que chama o Python
    report_bash = f"""#!/bin/bash
# Baixar o log
scp {squid_user}@{squid_ip}:/var/squid/logs/access.log /tmp/squid_access.log

# Converter usando o script separado
python3 /root/convert_squid.py < /tmp/squid_access.log > /tmp/squid_access_clean.log

# Gerar o relatório
goaccess /tmp/squid_access_clean.log --log-format=COMBINED -o /var/www/html/index.html --no-global-config

# Limpar
rm /tmp/squid_access.log /tmp/squid_access_clean.log
"""
    with client.open_sftp().open("/root/generate_report.sh", "w") as f:
        f.write(report_bash)
    client.exec_command("chmod +x /root/generate_report.sh")
    
    print("Executando geração de relatório corrigida...")
    stdin, stdout, stderr = client.exec_command("/root/generate_report.sh")
    print(stdout.read().decode())
    print(stderr.read().decode())
    
    client.close()

if __name__ == "__main__":
    fix_with_separate_script()
