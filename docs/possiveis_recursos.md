# Possíveis Recursos Futuros — SquidPanel

> Gerado em: 2026-08-25
> Baseado na análise completa do projeto atual.

---

## 🔥 Impacto Alto / Esforço Razoável

1. **Dashboard de métricas históricas**
   - Hoje a telemetria é só "agora". Persistir métricas no banco e exibir gráficos de tendência (cache hit rate, banda consumida, top sites por sala) ao longo do tempo.

2. **Relatórios de uso por sala/grupo**
   - "Sala 3 acessou 450 domínios hoje, 12 foram bloqueados" — exportável em PDF/CSV.
   - Útil para coordenadores e equipe pedagógica.

3. **Notificações/Alertas**
   - Email ou webhook (Telegram/Discord/Slack) quando:
     - Uma sala excede um threshold de bloqueios
     - O Squid cai
     - Disco quase cheio

4. **Modo "Prova/Silêncio"**
   - Botão de emergência no painel do gestor que bloqueia TUDO instantaneamente (sem agendamento, sem whitelist).
   - Útil durante avaliações e provas.

5. **Histórico de mudanças (auditoria)**
   - "Quem liberou esse domínio? Quando?"
   - Log imutável de todas as ações dos usuários no painel.

---

## 🛡️ Segurança e Compliance

6. **2FA para o painel**
   - TOTP (Google Authenticator / Authy) para usuários ADMIN no mínimo.

7. **Filtro por categoria (blacklists públicas)**
   - Integrar listas públicas como MESD, URLblacklist.com ou similares.
   - Categorias: jogos, redes sociais, adulto, malware, etc.

8. **Bloqueio por horário global**
   - Política de "fora do horário escolar, ninguém acessa nada" que sobrepõe qualquer agendamento individual.

9. **Detecção de tentativas de bypass**
   - Alertar quando um IP tenta mudar o proxy manualmente ou acessa HTTPS direto sem passar pelo proxy.

---

## 📊 Análise e IA

10. **Análise de padrão de acesso**
    - "Esta sala tem comportamento anômalo comparado às outras."
    - Bom para detectar uso inadequado ou ataques internos.

11. **Sugestão automática de whitelist**
    - Com base nos sublinks descobertos + análise IA, sugerir proativamente domínios que deveriam ser liberados permanentemente.

12. **Relatório semanal automático**
    - Email automático para coordenadores com resumo da semana, sem precisar acessar o painel.

---

## 🔧 Operacional

13. **Suporte a múltiplos servidores Squid**
    - Gerenciar mais de um proxy na mesma instância do painel.
    - Útil para redes com vários prédios ou campi.

14. **Backup automático de configuração**
    - Snapshot diário do `squid.conf` gerado + banco.
    - Restore por interface web.

15. **Worker de background real (Celery ou django-q)**
    - O scheduler hoje precisa rodar como processo separado.
    - Integrar um worker nativo eliminaria essa dependência e permitiria tarefas assíncronas mais robustas.

16. **App mobile (PWA)**
    - O painel do gestor/coordenador como PWA instalável no celular.
    - Muito conveniente para uso direto em sala de aula.

---

## 🌐 Integrações

17. **Integração com Google Workspace**
    - Mapear grupos do Google para perfis do SquidPanel automaticamente.

18. **Integração com Moodle / Google Classroom**
    - Liberar automaticamente domínios de atividades ativas em plataformas de EAD.

19. **API REST pública documentada (Swagger/OpenAPI)**
    - Expor o controle das portas via API para integrações externas.
    - Útil para automações, scripts de TI e outros sistemas da escola.
