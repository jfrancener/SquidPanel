import paramiko

def setup_server_sync():
    hostname = "10.40.88.3"
    username = "root"
    password = "@info win 123"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(hostname, username=username, password=password, timeout=10)
        print(f"Conectado ao {hostname}")
        
        # Criar diretório para ACLs se não existir
        client.exec_command("mkdir -p /var/squid/acl")
        
        # Script de atualização
        # Nota: Usamos a URL 'raw' do GitHub
        update_script = """#!/bin/sh
# URLs dos arquivos RAW no GitHub
BLACKLIST_URL="https://raw.githubusercontent.com/jfrancener/blacklist/main/blacklist.txt"
WHITELIST_URL="https://raw.githubusercontent.com/jfrancener/blacklist/main/whitelist.txt"

# Caminhos locais
BLACKLIST_PATH="/var/squid/acl/git_blacklist.acl"
WHITELIST_PATH="/var/squid/acl/git_whitelist.acl"

echo "Atualizando listas do GitHub..."
curl -s -L $BLACKLIST_URL -o $BLACKLIST_PATH
curl -s -L $WHITELIST_URL -o $WHITELIST_PATH

echo "Recarregando Squid..."
/usr/local/sbin/squid -k reconfigure
echo "Concluído!"
"""
        
        # Salvar o script no servidor
        stdin, stdout, stderr = client.exec_command("cat > /root/update_lists.sh")
        stdin.write(update_script)
        stdin.close()
        
        # Dar permissão de execução
        client.exec_command("chmod +x /root/update_lists.sh")
        
        # Executar pela primeira vez
        print("Executando atualização inicial...")
        stdin, stdout, stderr = client.exec_command("/root/update_lists.sh")
        print(stdout.read().decode())
        print(stderr.read().decode())
        
        # Adicionar ao crontab (a cada 30 minutos)
        # No pfSense, é melhor usar o pacote 'Cron' se disponível, mas vamos tentar via crontab manual
        client.exec_command('(crontab -l 2>/dev/null; echo "*/30 * * * * /root/update_lists.sh") | crontab -')
        
        print("Sincronização configurada com sucesso!")
        
        client.close()
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    setup_server_sync()
