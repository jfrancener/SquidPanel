import paramiko

def fix_with_manual_format():
    hostname = "10.40.89.15"
    username = "root"
    password = "@Jufran0803"
    
    squid_ip = "10.40.88.3"
    squid_user = "admin"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname, username=username, password=password)

    # 1. Script de conversão gerando algo bem simples
    convert_script = """
import sys, datetime
for line in sys.stdin:
    try:
        parts = line.split()
        if len(parts) < 7: continue
        ts = datetime.datetime.fromtimestamp(float(parts[0]))
        dt = ts.strftime('%d/%b/%Y:%H:%M:%S')
        status = parts[3].split('/')[-1]
        method = parts[5]
        url = parts[6]
        size = parts[4]
        ip = parts[2]
        # Formato customizado simples: IP DATE TIME METHOD URL STATUS SIZE
        print(f'{ip} {dt} {method} {url} {status} {size}')
    except:
        continue
"""
    sftp = client.open_sftp()
    with sftp.open("/root/convert_squid.py", "w") as f:
        f.write(convert_script)
    sftp.close()

    # 2. Script Bash com formato manual
    report_bash = f"""#!/bin/bash
scp {squid_user}@{squid_ip}:/var/squid/logs/access.log /tmp/squid_access.log

python3 /root/convert_squid.py < /tmp/squid_access.log > /tmp/squid_access_clean.log

# Formato manual: %h %d:%t %m %U %s %b
goaccess /tmp/squid_access_clean.log --log-format='%h %d:%t %m %U %s %b' --date-format=%d/%b/%Y --time-format=%H:%M:%S -o /var/www/html/index.html --no-global-config
"""
    with client.open_sftp().open("/root/generate_report.sh", "w") as f:
        f.write(report_bash)
    client.exec_command("chmod +x /root/generate_report.sh")
    
    print("Executando geração de relatório com formato manual...")
    stdin, stdout, stderr = client.exec_command("/root/generate_report.sh")
    print(stdout.read().decode())
    print(stderr.read().decode())
    
    # Amostra para debug
    stdin, stdout, stderr = client.exec_command("head -n 1 /tmp/squid_access_clean.log")
    print("Amostra da linha:", stdout.read().decode())
    
    client.close()

if __name__ == "__main__":
    fix_with_manual_format()
