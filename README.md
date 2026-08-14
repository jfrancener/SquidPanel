# SquidPanel - Gerenciador Inteligente de Proxy Squid

O **SquidPanel** é uma plataforma moderna e enxuta para gerenciamento multi-grupos de Proxy Squid, desenvolvida para ambientes escolares, corporativos e laboratoriais.

---

## 🎯 Principais Recursos

- **Controle Multi-Grupos por Portas:**
  - **Grupo 1 (Administrativo):** Whitelist estrita para tráfego seguro 24/7 (Porta `9010`).
  - **Grupo 2 (Salas de Aula / Laboratórios):** Portas dedicadas por sala (`9020` a `9025`) com controle individual de liberação.
- **Temporizador e Agendamento de Aulas:**
  - Botão de liberação rápida com contagem regressiva (ex: *Liberar Sala por 50 minutos*).
  - Agendamento recorrente de horários por dia da semana.
- **Controle de Acesso Baseado em Funções (RBAC):**
  - **Administrador TI:** Controle total sobre infraestrutura, portas, whitelists globais e logs.
  - **Professor / Coordenação:** Acesso restrito apenas ao gerenciamento e liberação das salas de aula.
- **Arquitetura Nativa de Alto Desempenho:**
  - Roda nativo em Container LXC (Debian 13 no Proxmox).
  - Recarregamento instantâneo do Squid via `sudoers` (< 0.2 segundos).

---

## 📁 Estrutura do Repositório

```
SquidPanel/
├── docs/                     # Documentação de Arquitetura, Banco de Dados e Instalação
│   ├── ARCHITECTURE.md       # Desenho da arquitetura do sistema e fluxo de dados
│   ├── DATABASE_PLAN.md      # Estudo e planejamento do banco de dados
│   └── INSTALLATION.md       # Guia de provisionamento do servidor
├── scripts/                  # Scripts operacionais e de deploy
│   ├── provision_server.py   # Script de setup do Debian 13 no Proxmox
│   └── server_status.py      # Diagnóstico rápido de portas e serviços
└── README.md
```

---

## 🚀 Guia Rápido de Instalação

Consulte a documentação completa em [docs/INSTALLATION.md](docs/INSTALLATION.md).
