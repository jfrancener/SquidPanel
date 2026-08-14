# Arquitetura do Sistema - SquidPanel

O **SquidPanel** foi projetado para desacoplar a complexidade do Proxy Squid em uma interface visual ágil e moderna.

---

## 1. Visão Geral da Arquitetura

```
               ┌────────────────────────────────────────────────────────┐
               │              PROXMOX VE - CT DEBIAN 13                 │
               │                                                        │
               │  ┌──────────────────────────────────────────────────┐  │
               │  │ Nginx (Reverse Proxy - Porta 80/443)              │  │
               │  └──────────────────────────┬───────────────────────┘  │
               │                             │ (WSGI / Unix Socket)     │
               │  ┌──────────────────────────▼───────────────────────┐  │
               │  │ SquidPanel Backend (Django / Python 3)           │  │
               │  │ Diretório: /var/www/SquidPanel                   │  │
               │  │ Banco de Dados: SQLite (WAL Mode)                │  │
               │  └──────────┬───────────────────────────┬───────────┘  │
               │             │ Gera regras dinâmicas     │ Recarrega    │
               │             ▼                           ▼              │
               │  ┌───────────────────────┐  ┌───────────────────────┐  │
               │  │ /etc/squid/conf.d/    │  │ sudo squid -k         │  │
               │  │ /etc/squid/acls/      │  │ reconfigure (<0.2s)   │  │
               │  └──────────┬────────────┘  └───────────────────────┘  │
               │             │                                          │
               │  ┌──────────▼───────────────────────────────────────┐  │
               │  │ Squid Proxy Server                               │  │
               │  │ • 9010 (Admin)                                   │  │
               │  │ • 9020 - 9025 (Salas de Aula 1 a 5)              │  │
               │  └──────────────────────────────────────────────────┘  │
               └────────────────────────────────────────────────────────┘
```

---

## 2. Componentes Principais

### A. Proxy Squid Modular
- As configurações não ficam em um único arquivo monolítico.
- `/etc/squid/conf.d/00-system.conf`: Proteções de portas, SSL, manager e localnet.
- `/etc/squid/conf.d/01-ports.conf`: Mapeamento dinâmico de portas (`http_port 9010 name=port_admin`).
- `/etc/squid/conf.d/02-schedules.conf`: ACLs de dias e horários (`MTWHF`).
- `/etc/squid/conf.d/03-rules.conf`: Regras de autorização por porta.
- `/etc/squid/acls/`: Listas de domínios em texto puro.

### B. Módulo de Gestão de Salas e Portas
- Cada porta representa uma sala ou setor.
- O navegador da estação da sala aponta para a porta correspondente via configuração local ou GPO do Windows.
- O IP da máquina cliente pode mudar livremente via DHCP sem afetar a identificação da sala.

### C. Módulo de Agendamentos e Temporizador (Timer de Aula)
- Liberação manual rápida com timer regressivo (ex: 50 minutos).
- Worker em background leve que avalia expirações de horários e retorna o status da porta para bloqueado/whitelist automaticamente.

### D. Controle de Acesso (RBAC)
- **SuperAdmin (TI):** Acesso completo a grupos, criação de portas, whitelists gerais e logs.
- **Operador / Professor:** Interface simplificada exibindo apenas os cards das salas autorizadas para liberação ou agendamento de aula.
