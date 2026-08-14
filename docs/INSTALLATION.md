# Guia de Instalação e Provisionamento - SquidPanel

Instruções para provisionar e validar a infraestrutura do **SquidPanel** no Proxmox VE rodando Debian 13 (Trixie).

---

## 1. Criação do Container LXC no Proxmox

1. **Template:** Baixe o template `debian-13-standard` (ou `debian-12-standard`).
2. **Configuração de Recursos:**
   - **Hostname:** `squidpanel`
   - **CPU:** 2 vCPUs
   - **Memória:** 1024 MB (Swap: 512 MB)
   - **Disco:** 16 GB a 32 GB
   - **Rede:** Interface em bridge (`vmbr0`), IPv4 estático (ex: `10.40.90.99/22`), Gateway da rede e DNS local.

---

## 2. Execução do Provisionamento Automatizado

No seu ambiente de desenvolvimento, execute o script:

```bash
python scripts/provision_server.py
```

O script automatizado executa as seguintes etapas no servidor:
1. Instalação do `squid`, `nginx`, `python3-venv`, `ufw`, `sudo`, etc.
2. Ajuste do fuso horário para `America/Sao_Paulo`.
3. Criação da pasta da aplicação `/var/www/SquidPanel` com permissões para `www-data`.
4. Montagem da arquitetura modular do Squid em `/etc/squid/conf.d/` e `/etc/squid/acls/`.
5. Liberação de permissões no `/etc/sudoers.d/squidpanel` para reload seguro do Squid.
6. Abertura das portas de escuta iniciais:
   - `9010` (Grupo Admin)
   - `9020`, `9021`, `9022`, `9023`, `9025` (Salas 1 a 5)
7. Configuração do firewall `ufw`.

---

## 3. Comandos de Diagnóstico e Validação

Para verificar o status do servidor e das portas ativas:

```bash
python scripts/server_status.py
```

Comandos manuais úteis no terminal do servidor:
```bash
# Testar integridade da sintaxe do Squid
squid -k parse

# Recarregar configurações do Squid sem derrubar conexões ativas
sudo squid -k reconfigure

# Verificar portas TCP em escuta
ss -tuln | grep -E ':(22|80|9010|9020|9021|9022|9023|9025)'

# Acompanhar logs de acesso em tempo real
tail -f /var/log/squid/access.log
```
