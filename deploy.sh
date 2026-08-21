#!/usr/bin/env bash
# =============================================================================
# SquidPanel — Deploy Local Completo
# Uso: ./deploy.sh ["mensagem de commit"]
# =============================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/venv/bin/python"
COMMIT_MSG="${1:-Deploy automatico: $(date '+%Y-%m-%d %H:%M:%S')}"

# Cores
GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

step() { echo -e "\n${CYAN}[$(date '+%H:%M:%S')]${NC} ${GREEN}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}  ✔ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail() { echo -e "${RED}  ✘ $1${NC}"; exit 1; }

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║      SQUIDPANEL — DEPLOY LOCAL COMPLETO      ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${NC}"

cd "$DIR"

# ─── 1. Git: stage, commit e push ─────────────────────────────────────────────
step "Git — verificando alterações"

git add -A

if git diff --cached --quiet; then
    warn "Nenhuma alteração pendente para commit."
else
    git commit -m "$COMMIT_MSG"
    ok "Commit criado: $COMMIT_MSG"
fi

step "Git — enviando para origin/main"
if git push origin main; then
    ok "Push concluído."
else
    warn "Push falhou ou sem alterações remotas — continuando."
fi

# ─── 2. Dependências Python ────────────────────────────────────────────────────
step "Instalando/atualizando dependências Python"
"$VENV" -m pip install -r "$DIR/requirements.txt" --quiet
ok "Dependências OK."

# ─── 3. Migrações do banco ────────────────────────────────────────────────────
step "Executando migrações do banco de dados"
"$VENV" "$DIR/manage.py" migrate --noinput
ok "Migrações aplicadas."

# ─── 4. Arquivos estáticos ────────────────────────────────────────────────────
step "Coletando arquivos estáticos"
"$VENV" "$DIR/manage.py" collectstatic --noinput --clear --verbosity 0
ok "Staticfiles coletados."

# ─── 5. Sincronizar Squid ────────────────────────────────────────────────────
step "Sincronizando regras do Squid"
"$VENV" "$DIR/manage.py" shell -c \
    "from squid.squid_sync import apply_squid_changes; r = apply_squid_changes(); print('  Resultado:', r)"
ok "Squid sincronizado."

# ─── 6. Recarregar Squid ────────────────────────────────────────────────────
step "Recarregando configuração do Squid"
if squid -k reconfigure 2>/dev/null; then
    ok "Squid recarregado (reconfigure)."
elif systemctl reload squid 2>/dev/null; then
    ok "Squid recarregado (systemctl reload)."
else
    warn "Não foi possível recarregar o Squid — verifique manualmente."
fi

# ─── 7. Reiniciar Gunicorn / SquidPanel ────────────────────────────────────────
step "Reiniciando serviço SquidPanel (gunicorn)"
if systemctl restart squidpanel; then
    ok "Serviço squidpanel reiniciado."
else
    fail "Falha ao reiniciar squidpanel. Verifique: journalctl -u squidpanel -n 30"
fi

# ─── 8. Verificação final ─────────────────────────────────────────────────────
step "Verificação final dos serviços"
sleep 2

SQUIDPANEL_STATUS=$(systemctl is-active squidpanel 2>/dev/null || echo "inativo")
SQUID_STATUS=$(systemctl is-active squid 2>/dev/null || echo "inativo")

echo ""
echo -e "  ${CYAN}squidpanel:${NC} $SQUIDPANEL_STATUS"
echo -e "  ${CYAN}squid:     ${NC} $SQUID_STATUS"
echo ""

if [ "$SQUIDPANEL_STATUS" = "active" ]; then
    echo -e "${GREEN}  ╔══════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}  ║      ✔  DEPLOY CONCLUÍDO COM SUCESSO!        ║${NC}"
    echo -e "${GREEN}  ╚══════════════════════════════════════════════╝${NC}"
else
    fail "SquidPanel não está ativo após o reinício. Logs: journalctl -u squidpanel -n 50"
fi
