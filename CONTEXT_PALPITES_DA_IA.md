# Palpites da IA — Contexto Completo do Projeto

> Documento de contexto para retomar o desenvolvimento em qualquer sessão.
> Última atualização: 08/06/2026 (véspera do lançamento)

---

## 1. O Produto

**Palpites da IA** é um site de análise estatística de apostas esportivas para a Copa do Mundo 2026, com modelo de IA que gera palpites embasados em dados reais.

- **Frontend:** https://palpitesdaia.com.br (também magic-guess-stream.lovable.app)
- **Backend:** https://palpites-backend-production.up.railway.app
- **GitHub Frontend:** github.com/bfontanetti33/palpitesdaia
- **GitHub Backend:** github.com/bfontanetti33/palpites-backend
- **Dono:** Brunno Fontanetti (bfontanetti33)
- **Sócio (publicidade/marketing):** Chi

---

## 2. Stack Técnica

| Camada | Tecnologia |
|--------|-----------|
| Frontend | React, TanStack, Tailwind, Lovable Cloud |
| Backend | Python 3.11, FastAPI, Uvicorn |
| Deploy Backend | Railway (região southamerica-east1 — São Paulo) |
| Deploy Frontend | Lovable Cloud (CI/CD automático via GitHub) |
| Banco de dados | Supabase (jwzvuixvuptazfyasmlm.supabase.co) |
| Domínio | palpitesdaia.com.br (Registro.br) |
| Email | Resend (contato@palpitesdaia.com.br — DNS pendente) |

---

## 3. Arquitetura do Backend

```
palpites-backend/
├── main.py                          # FastAPI app, CORS, rate limiting, startup
├── app/
│   ├── agents/
│   │   ├── football_agent.py        # Busca dados API-Football
│   │   ├── ia_agent.py              # Modelo 5 camadas + Claude narrativa
│   │   └── odds_engine.py           # Shin Method + z-score + consensus
│   ├── cache/
│   │   ├── static_cache.py          # Cache em disco (imutável entre deploys)
│   │   └── odds_cache.py            # Cache odds em memória (TTL dinâmico)
│   ├── auth/
│   │   └── supabase_client.py       # JWT auth, premium status, usage log
│   ├── payments/
│   │   └── mercadopago_webhook.py   # Webhook pagamentos MP
│   ├── monitoring/
│   │   ├── telegram_bot.py          # Alertas + resumo diário 8h BRT
│   │   └── cron_jobs.py             # Jobs automáticos em background
│   └── routes/
│       └── admin.py                 # /health-check, /stats, /telegram-test
└── seeds/
    ├── copa_2026.json               # 72 jogos fase de grupos (IDs oficiais)
    ├── squads_copa_2026.json        # 47/48 seleções (Curaçao sem dados)
    ├── arbitros_copa_2026.json      # 52 árbitros (20 com dados reais Copa 22/18)
    ├── forma_recente_seed.json      # Forma recente dos times (seed local)
    └── cache_partidas.json          # Cache estático em disco
```

---

## 4. Modelo Estatístico — 5 Camadas

| Camada | Nome | Descrição |
|--------|------|-----------|
| 1 | Rating Dinâmico | Elo FIFA 50% + Pi-rating 30% + FIFA Ranking 20%. Normalização Z-score regional por confederação. Decaimento temporal: peso = 0.98^dias |
| 2 | Dixon-Coles + Skellam | Poisson aprimorado com correção para placares baixos. Calibração isotônica. Gera matriz de placares, prob 1X2, BTTS, Over/Under |
| 3 | Value Bet Detector | Shin Method (remoção de margem), consensus ponderado por qualidade de casa, z-score (teste de hipótese), sharp money detection. SOMENTE com odds reais |
| 4 | Context Engine | Home advantage MEX×1.25+altitude, EUA×1.10, CAN×1.10. Fadiga. Rodada 1. Zebra detector fator 2x Copa |
| 4B | Tail Risk (Taleb) | Fat tail: 85% Dixon-Coles + 15% Student-t (4 graus). Fragility score. Uncertainty index. Barbell signal |
| 5 | Claude Narrativa | claude-sonnet-4-6, AsyncAnthropic timeout 45s. Gera narrativa PT-BR, resumo_rapido, top3, alertas, analise_completa |

---

## 5. Fontes de Dados

| Fonte | Dados | Plano | Custo |
|-------|-------|-------|-------|
| API-Football v3 | Fixtures, H2H, forma recente, stats, jogadores | Pro | $19/mês |
| The Odds API | Odds reais (Pinnacle, Bet365, 40+ casas) | Pago | $30/mês |
| Wikipedia | Squads oficiais, Elo ratings, FIFA Ranking | Scraping | Grátis |
| Seed copa_2026.json | 72 jogos fase de grupos | Local | Grátis |
| Anthropic Claude | Narrativa IA em PT-BR | Pay-as-you-go | ~$2/mês |

---

## 6. Estratégia de Cache (2 Camadas)

### Camada 1 — Cache Estático (disco, imutável)
- Arquivo: `seeds/cache_partidas.json`
- Persiste entre deploys (zero requests no restart)
- Invalida SOMENTE quando time jogar novo jogo
- Campos: forma, stats, H2H, jogadores, ratings, probabilidades, narrativa, top3

### Camada 2 — Odds Dinâmicas (memória, TTL variável)
- Atualiza por proximidade do jogo:
  - >12h antes: 1x/dia
  - 2-12h antes: 1x/hora
  - <2h antes: a cada 30min
- Só para jogos de hoje e amanhã (máximo 16 simultâneos)

### Consumo estimado mensal
- API-Football: ~1.120 req/mês (limite: 225.000/mês)
- The Odds API: ~200 req/mês
- Anthropic Claude: ~$2/mês
- Redeploys: 0 requests extras

---

## 7. Endpoints da API

| Método | Endpoint | Auth | Descrição |
|--------|----------|------|-----------|
| GET | /health | — | Status do servidor |
| GET | /api/v1/copa/jogos | — | Lista 72 jogos com favorito e probs |
| GET | /api/v1/copa/jogos/{slug} | — | Detalhe completo: stats, H2H, odds, jogadores |
| GET | /api/v1/copa/jogos/{slug}/recomendacao | Bearer Token | Análise completa IA (5 camadas + Claude) |
| GET | /api/v1/admin/health-check | — | Status detalhado + vars configuradas |
| GET | /api/v1/admin/stats | — | Métricas do servidor |
| GET | /api/v1/admin/telegram-test | — | Envia mensagem teste no Telegram |
| POST | /api/v1/webhooks/mercadopago | HMAC | Webhook pagamentos |

---

## 8. Rate Limiting

| Endpoint | Limite |
|----------|--------|
| /copa/jogos | 60 req/min |
| /copa/jogos/{slug} | 20 req/min |
| /recomendacao | 5 req/min |
| Global por IP | 200 req/min |

Mensagem 429 em PT-BR com Retry-After header.

---

## 9. Critérios de Zebra e Bingo

### Zebra (azarão com embasamento)
- value_score > 0.15 E z_score > 1.96 E odds_disponiveis=True
- prob_modelo azarão > 25%
- Pelo menos 1 evidência concreta (forma, Elo diff, fadiga, uncertainty)
- Azarão com >= 5 jogos nos últimos 10
- Fator 2x para Copa do Mundo
- Sharp money contra → rejeita zebra

### Bingo (acumulada da IA)
- prob_modelo > 60% E fair_odd > 1.30 E value_score >= 0
- Mercados permitidos: Over 1.5/2.5, BTTS Sim, Vitória favorito, Chance Dupla
- Mercados proibidos: Under, Vitória Fora, placar exato
- Jogos diferentes, 3-5 seleções, odd total 2.0-8.0
- Rejeita: uncertainty_index > 70, odds_disponiveis=False

---

## 10. Jogadores de Destaque

- Busca squads via Wikipedia (26 jogadores/seleção)
- Stats da temporada 25/26 via API-Football
- Normalização p90: stat_total / minutos × 90
- League Strength Score (LSS): Champions 1.10, Premier 1.00 ... PSL 0.42
- Filtro mínimo: >= 180 minutos jogados

---

## 11. Variáveis de Ambiente (Railway)

| Variável | Status |
|----------|--------|
| ANTHROPIC_API_KEY | ✅ |
| API_FOOTBALL_KEY | ✅ |
| ODDS_API_KEY | ✅ |
| PREMIUM_TOKEN | ✅ |
| ALLOWED_ORIGIN | ✅ |
| SUPABASE_URL | ✅ |
| SUPABASE_KEY | ✅ (secret key) |
| TELEGRAM_BOT_TOKEN | ✅ |
| TELEGRAM_CHAT_ID | ✅ |
| ADMIN_TOKEN | ✅ (criado 08/06 — protege /api/v1/admin/*; TROCAR pós-lançamento, apareceu no chat) |
| MERCADOPAGO_ACCESS_TOKEN | ⏳ pendente |
| MERCADOPAGO_WEBHOOK_SECRET | ⏳ pendente |
| SENTRY_DSN | ⏳ opcional |

**CORS:** `ALLOWED_ORIGIN` inclui palpitesdaia.com.br, www.palpitesdaia.com.br, magic-guess-stream.lovable.app e lovableproject.com

---

## 12. Monitoramento (Telegram)

- Bot: `palpitesdaia_monitor_bot`
- Token: 8890660681:AAEUnEfn4vzZUNp-Od5l8D_P4z6S7kvrjZ0
- Chat ID: 8802057413
- Resumo diário: 8h BRT
- Alertas imediatos: erro 500, quota < 500, Anthropic < $2, sharp money

---

## 13. Supabase

- URL: https://jwzvuixvuptazfyasmlm.supabase.co
- Tabelas criadas:
  - `users`: id, email, is_premium, premium_until, avulso_credits, created_at
  - `usage_log`: id, user_id, slug, created_at

---

## 14. Monetização

- **Preços (definidos 08/06):** R$2,90/jogo (24h) · R$6,90/semana · R$14,90/mês
  - NOTA: site ainda mostra R$19,90/mês — propagar R$14,90 no Lovable
- **Modelo de cobrança:** começar com PAGAMENTO ÚNICO por período (não recorrente). Detalhes na seção 21.
- **Paywall:** homepage gratuita, análise completa paga
- **Estratégia lançamento:** 100% gratuito no dia 1 (segunda 08/06), ativa paywall sábado
- **Pagamento:** Mercado Pago (Pix + cartão) — integração PENDENTE (risco nº 1, ver seção 21)
- **Break-even:** ~26 assinantes (a R$14,90 muda o cálculo — recalcular)

---

## 15. Custos Mensais

| Serviço | Custo/mês |
|---------|-----------|
| Lovable Pro | $25,00 |
| Railway Hobby | $5,00 |
| API-Football Pro | $19,00 |
| The Odds API | $30,00 |
| Anthropic API | ~$2,00 |
| **Total mensal** | **~$81,00 (~R$446)** |
| Domínio (anual) | R$40/ano |

**Investimento único realizado:** ~$30 (Claude Pro + créditos + Railway extra)

**Break-even:** 23 assinantes a R$19,90/mês

---

## 16. Status Atual (08/06/2026 — véspera do lançamento)

### ✅ Funcionando e VALIDADO NA TELA (check de tela feito via Claude in Chrome)
- Backend online (Railway São Paulo), zero erros 500, zero 429 no último prewarm
- 72 jogos listados com probabilidades; 66/72 com odds reais (Pinnacle)
- **Palpite = 1X2 mais provável puro** (México 62%, EUA 54%, etc.) — confirmado na tela, zero "Over" como palpite
- **Elo TSV** (eloratings.net, datado 07/06) — inversões propagadas (Panamá>Gana, Norway>Iraq) confirmadas na tela
- **Filtro A+B** — sem false value no favorito (México sem value bet de azarão) confirmado na tela
- **Value bets** com microcópia honesta (risco moderado, "não garantia", sharp money) — Ghana×Panama na tela
- **Aba Zebras** com conteúdo embasado (edge, z-score, baixa confiança) — Canada×Bosnia, Brasil×Marrocos
- Escanteios/cartões da forma recente (média aparece na tela)
- Narrativa sem invenção de árbitro ("árbitro a confirmar" honesto)
- Forma recente alimentando o lambda (confirmado: lambda usa media_gols_marcados_recente)
- Cache em disco validado e commitado (74c9fb5)
- Supabase conectado, Telegram bot ativo, domínio ativo, GA4, compliance Lei 14.790
- Página de planos com ancoragem de preço
- **Segurança: ADMIN_TOKEN criado no Railway** (endpoints /admin/* estavam fail-open, agora fechados)

### ❌ Problemas Conhecidos / Backlog imediato
- **6 jogos sem odds (Türkiye/Congo DR)** — provável problema de ENCODING do slug (türkiye/curaçao caractere especial). Investigar.
- **Escanteios N=None** internamente — lag de cache L2 (TTL team_stats 30 dias). A média aparece na tela; só o N interno falta. Some quando o cache expirar ou em full-fetch.
- **Fraseado "favorita com 39/48%"** na narrativa — num jogo de 3 vias, 39% é "ligeiramente à frente", não "favorita". Ajuste de narrativa.
- **Mercado Pago NÃO funcional** (botões "Assinar" sem ação) — RISCO Nº 1, ver seção 21.
- **Login real NÃO existe** (Supabase Auth) — pré-requisito do pagamento.
- **ADMIN_TOKEN apareceu no chat** — trocar por higiene pós-lançamento.

### ⏳ Pendente
- Mercado Pago + login (ver seção 21 — plano detalhado)
- Encoding dos 6 slugs Türkiye/Congo
- Seed árbitros completo (após quota reset)
- Recalibração pesos rating (58/32/10) e alpha/DC_RHO — pós-Copa com dados reais
- Prewarm periódico durante a Copa: `/api/v1/admin/prewarm?dias=14` (idempotente)

---

## 17. Roadmap

### Fase 1 — Dados reais ✅ COMPLETA

### Fase 2 — Agente IA + Monetização
- ✅ Modelo 5 camadas
- ✅ Odds Engine robusto (Pinnacle, 66/72 com odds)
- ✅ Cache inteligente 2 camadas
- ✅ Forma recente alimentando o lambda (confirmado)
- ✅ Palpite 1X2 / Valor / Zebra separados
- ✅ Elo TSV (eloratings.net, rastreável)
- ✅ Rating auditado e selado (58/32/10)
- ⏳ Login (Supabase Auth) — pré-requisito do pagamento
- ⏳ Mercado Pago funcional (pagamento único primeiro)

### Fase 3 — Monitoramento (após lançamento)
- Agente Claude monitora site, pagamentos, usuários e bugs
- Stack: Sentry + UptimeRobot + Supabase + Stripe/MP + Script Railway + Telegram

### Fase 4 — Escala (futuro)
- Dataset próprio Copa 2026
- Modelo XGBoost treinado
- Histórico de acertos rastreado
- Expansão para outras ligas

---

## 18. Comandos Úteis

```bash
# Abrir Claude Code na pasta do projeto
cd "C:\Users\brunn\OneDrive\Documentos\CLAUDIO\Palpites_da_IA\palpites-backend"
claude

# Validação completa
python scripts/validacao_completa.py

# Pré-cache manual
python scripts/precalcular_jogos.py

# Seed árbitros (após quota reset às 21h BRT)
python scripts/gerar_seed_arbitros.py --min-jogos 15 --delay 2

# Deploy (Railway auto-deploya no push)
git add . && git commit -m "mensagem" && git push origin main

# Forçar redeploy sem mudança de código
git commit --allow-empty -m "chore: force redeploy"
git push origin main
```

---

## 19. Próxima Ação Prioritária (pós 08/06)

```
LANÇAMENTO segunda 08/06 = GRÁTIS (paywall desligado). Modelo/cache prontos e validados.
Copa começa 11/06. Paywall previsto pra sábado (depende do Mercado Pago — ver seção 21).

1. Mercado Pago + Login (RISCO Nº 1) — ver seção 21 para o plano completo
   → decidido: começar com PAGAMENTO ÚNICO por período (não recorrente)
   → login (Supabase Auth) é pré-requisito — é majoritariamente frontend (Lovable)
   → testar TUDO em sandbox antes de produção

2. Encoding dos 6 slugs Türkiye/Congo (sem odds)

3. Trocar ADMIN_TOKEN (apareceu no chat)

4. Ajuste de narrativa "favorita com 39%" → "ligeiramente à frente"

5. Prewarm periódico durante a Copa (idempotente, dias=14)
```

---

## 20. Contexto de Negócio

- **Copa do Mundo 2026:** 11/06 a 19/07/2026 (48 times, 104 jogos)
- **TikTok:** @palpitesdaia — 20k seguidores engajados (Chi)
- **Estratégia:** lançamento gratuito (segunda 08/06) → coleta usuários → paywall sábado
- **Diferencial:** modelo estatístico robusto + linguagem acessível + honestidade intelectual (sem "78% de acerto" inventado)
- **Público-alvo:** apostador casual brasileiro que quer embasamento sem jargão técnico
- **Tráfego:** vem majoritariamente do TikTok = MOBILE (validar responsivo)

---

## 21. Plano Mercado Pago + Login (decisões tomadas 08/06)

### Decisões
- **Preços:** R$2,90/jogo (24h) · R$6,90/semana · R$14,90/mês
  - ATENÇÃO: o site ainda mostra R$19,90/mês — propagar R$14,90 no Lovable
- **Modelo:** começar com PAGAMENTO ÚNICO por período (preference), NÃO recorrente
  - paga 1x, vale 1/7/30 dias; renova manualmente. Recorrente (preapproval) fica pra depois.
  - razão: recorrente + login do zero é muito trabalho/risco até sábado
- **Login:** Supabase Auth — NÃO existe ainda, é PRÉ-REQUISITO de tudo, majoritariamente frontend (Lovable)

### Cadeia de dependências (ordem)
1. Login (Supabase Auth) — sem saber quem é o usuário, nada funciona
2. Criar preference no MP (backend) quando clica "Assinar"
3. Webhook (já existe parcial em mercadopago_webhook.py) marca is_premium + premium_until no Supabase
4. Paywall checa "é premium e dentro da validade?"

### Quem faz o quê
- **Backend (Claude Code):** criar preference, processar webhook, marcar premium no Supabase
- **Frontend (Lovable):** login (cadastro/senha), botão Assinar→backend, paywall
- **Brunno:** credenciais MP no Railway, configurar Supabase Auth, testar pagamento

### CRÍTICO — segurança de pagamento
- Testar TUDO em SANDBOX (credenciais de teste) antes de produção. Nunca testar direto em produção.
- Variáveis Railway pendentes: MERCADOPAGO_ACCESS_TOKEN, MERCADOPAGO_WEBHOOK_SECRET
- Próximo passo: rodar o DIAGNÓSTICO (o que já existe: login? webhook faz o quê? tabela users? variáveis?) antes de implementar

---

## 22. Processo de Validação (instituído 08/06 — SEMPRE seguir)

Sempre que mexer em algo crítico (modelo, cache, endpoints), rodar o ciclo até o FIM:

```
1. CÓDIGO  → o fix está implementado e o diff revisado
2. DADO    → testar no dado REAL (não suposição) — o número bate?
3. CACHE   → o cache/endpoint propaga o fix, ou serve o velho?
4. TELA ✅ → abrir o site renderizado e VER (pega "código certo / tela errada")
```

**Regra de ouro:** "passou no código" ≠ "pronto". Pronto = visto na tela.
A desconexão código↔tela foi o bug MAIS RECORRENTE do projeto (cache não propaga, endpoint lê camada velha).

**Checklist do check de tela:** home (prova social/headline/CTAs) · lista (palpites 1X2, idioma, sem números velhos) · página de jogo (palpite/value/zebra/jogadores/arbitragem honesta) · jogo de teste conhecido (México=Vitória ~62%) · estados de borda (sem odds, sem value, árbitro a confirmar) · planos (preços/âncoras).

**Lição de método (reforçada várias vezes):** MEDIR antes de aplicar. Teorias plausíveis erram — na auditoria do rating, 3 teorias seguidas ("Elo domina FIFA", "Pi esmagado", "FIFA precisa subir") foram desmentidas pelos dados reais. O modelo já estava calibrado (58/32/10). Só medir o impacto antes de mexer evitou estragar o que estava bom.

---

## 23. Sessão 08/06 — Fechamento (o que foi feito)

### Commits no main
- **45fb011:** Fix B (retry 5× no football_agent._get), Elo TSV, escanteios N, endpoint refresh-odds, prewarm HTTP
- **16252a4:** admin.py — narrativa no prewarm + warm-up 10s + pacing 1.5s
- **dbd0afe:** Fix palpite 1X2 (m in _MERCADOS_1X2 na linha 601 — estava esquecido, fazia Over virar palpite em jogos equilibrados)
- **74c9fb5:** Cache validado — 72 jogos, Elo TSV, palpite 1X2, odds Pinnacle
- (de sessões/etapas anteriores no mesmo arco: c3678df palpite 1X2 puro, 6899429 roteamento valor/zebra)

### Trabalho principal do dia
1. **Palpite/Valor/Zebra separados** — palpite = 1X2 mais provável puro (sem value_score); valor = melhor preço; zebra = azarão com edge → aba /zebras
2. **Elo TSV** — trocado o hardcoded de origem incerta pelo eloratings.net (validado na fonte: Ecuador é 9º real). 48 times mapeados, códigos ambíguos checados (ZA≠SA, KR≠KO, CD≠CG, BA≠BH, NS=Northern Ireland≠NI=Nicarágua)
3. **Auditoria do rating** — 3 teorias erradas desmentidas por dados; modelo já calibrado (58/32/10 efetivo). NÃO normalizar. Decisão: manter ×3.0 no FIFA, recalibração pós-Copa.
4. **Odds** — causa do value_bets vazio era partida.odds=None congelado (busca falhou no prewarm). Endpoint /admin/refresh-odds busca odds reais (Pinnacle). Resultado: 66/72 com odds.
5. **Recálculo único** — refresh-odds + prewarm, zero 429 (warm-up + pacing + Fix B domaram o burst de cold-start)
6. **Check de tela** (Claude in Chrome) — validado: palpite 1X2, Elo propagado, sem false value, zebras, value honesto, árbitro honesto

### Lições/achados
- Fix B "existia mas não" — estava no players_agent (ffe8d0a), não no football_agent. Corrigido hoje.
- Endpoints admin eram fail-open (sem ADMIN_TOKEN = aberto). Token criado. Backlog: revisar pra fail-closed.
- Path dos endpoints admin: /api/v1/admin/... (não /admin/...). Header: Authorization (com ou sem Bearer).
- haiti-scotland mostrava Over como palpite (linha 601 sem filtro _MERCADOS_1X2) — corrigido, afetava jogos equilibrados.

### Frentes abertas no fim da sessão
- Playground (2º terminal): descoberta se a The Odds API tem odds dos amistosos pro value bet real
- Mercado Pago: diagnóstico pendente (ver seção 21)
