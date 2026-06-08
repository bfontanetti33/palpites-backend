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
│   │   └── mercadopago_webhook.py   # Webhook pagamentos MP + /criar-preferencia
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
| POST | /api/v1/pagamentos/criar-preferencia | JWT ou PREMIUM_TOKEN | Cria preference MP Checkout Pro |

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
| SUPABASE_JWT_SECRET | ⏳ pendente — CRÍTICO: sem ela todo JWT de usuário retorna None e paywall rejeita 403 |
| SENTRY_DSN | ⏳ opcional |

**CORS:** `ALLOWED_ORIGIN` inclui palpitesdaia.com.br, www.palpitesdaia.com.br, magic-guess-stream.lovable.app e lovableproject.com

---

## 12. Monitoramento (Telegram)

- Bot: `palpitesdaia_monitor_bot`
- Token: <TELEGRAM_BOT_TOKEN> (ver Railway env vars)
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
- **Pagamento:** Mercado Pago (Pix + cartão) — backend implementado (cb1c62b), aguarda variáveis Railway
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
- **Backend MP implementado e commitado (cb1c62b)** — webhook fail-closed, 3 planos, endpoint /criar-preferencia

### ❌ Problemas Conhecidos / Backlog imediato
- **6 jogos sem odds (Türkiye/Congo DR)** — provável problema de ENCODING do slug (türkiye/curaçao caractere especial). Investigar.
- **Escanteios N=None** internamente — lag de cache L2 (TTL team_stats 30 dias). A média aparece na tela; só o N interno falta. Some quando o cache expirar ou em full-fetch.
- **Fraseado "favorita com 39/48%"** na narrativa — num jogo de 3 vias, 39% é "ligeiramente à frente", não "favorita". Ajuste de narrativa.
- **Mercado Pago NÃO funcional** (botões "Assinar" sem ação) — RISCO Nº 1, ver seção 21. Backend pronto, faltam variáveis Railway + login Lovable.
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
- ✅ Backend Mercado Pago (webhook + /criar-preferencia) — commit cb1c62b
- ⏳ Login (Supabase Auth) — pré-requisito do pagamento
- ⏳ Variáveis Railway MP + JWT secret (destrava paywall)

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

# Testar /criar-preferencia em sandbox (com PREMIUM_TOKEN real do Railway)
curl -s -X POST "https://palpites-backend-production.up.railway.app/api/v1/pagamentos/criar-preferencia" \
  -H "Authorization: Bearer <PREMIUM_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"plano":"mensal","email":"teste@teste.com"}'
# Resposta esperada: {"preference_id":..., "init_point":..., "sandbox_init_point":...}
# 503 = MERCADOPAGO_ACCESS_TOKEN ausente | 403 = token errado | 400 = plano inválido
```

---

## 19. Próxima Ação Prioritária (pós 08/06)

```
LANÇAMENTO segunda 08/06 = GRÁTIS (paywall desligado). Modelo/cache prontos e validados.
Copa começa 11/06. Paywall previsto pra sábado (depende do Mercado Pago — ver seção 21).

1. Mercado Pago + Login (RISCO Nº 1) — ver seção 21 para o plano completo
   → backend PRONTO (cb1c62b) — falta: 3 variáveis Railway + frontend login
   → SUPABASE_JWT_SECRET é o desbloqueio mais crítico (sem ela todo usuário leva 403)
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

## 21. Plano Mercado Pago + Login (decisões + diagnóstico + implementação 08/06)

### Decisões
- **Preços:** R$2,90/jogo (24h) · R$6,90/semana · R$14,90/mês
  - ATENÇÃO: o site ainda mostra R$19,90/mês — propagar R$14,90 no Lovable
- **Modelo:** PAGAMENTO ÚNICO por período (preference / Checkout Pro), NÃO recorrente
  - paga 1x, vale 1/7/30 dias; renova manualmente. Recorrente (preapproval) fica pra depois.
- **Integração escolhida:** Checkout Pro (MP cuida da tela de pagamento; backend cria preference, webhook confirma). NÃO usar Checkout Transparente (lida com cartão, PCI) nem link/botão (manual).
- **Login:** Supabase Auth — backend JÁ valida JWT; falta o frontend (Lovable) gerar (cadastro/login)

### DIAGNÓSTICO (o que já existe — descoberto 08/06)
Quase tudo da fundação JÁ EXISTE. Falta menos do que parecia:
- ✅ **app/auth/supabase_client.py** — verify_jwt_token, get_user_premium_status, set_premium, deduct_avulso_credit, register_usage, get_user_id_by_email (novo). COMPLETO.
- ✅ **Paywall** — _verificar_acesso_recomendacao (partidas.py linha 57-99): admin token / JWT premium ou crédito / 403. Fail-closed, completo.
- ✅ **Tabela users** (Supabase) — is_premium, premium_until, avulso_credits — lida e escrita.
- ✅ **Webhook** /api/v1/webhooks/mercadopago — recebe, busca pagamento, notifica Telegram. Os 3 bugs foram corrigidos (ver abaixo).

### BACKEND IMPLEMENTADO E COMMITADO (commit cb1c62b — em produção)
- **Bug 1 (segurança CRÍTICA) — webhook fail-closed:** _verificar_assinatura agora retorna False (não True) se secret ausente/exceção; webhook faz `if not MP_WEBHOOK_SECRET: return 403`; enforça `if not _verificar_assinatura(): return 403`. Manifest HMAC corrigido (data_id do body, request_id do header). ANTES era fail-open — qualquer POST forjado virava premium de graça.
- **Bug 2:** get_user_id_by_email(email) antes de set_premium (filtrava por user_id, recebia email). Se não acha: loga + Telegram [ERRO: conta não encontrada].
- **Bug 3:** _PLANOS dict centralizado — jogo (24h/R$2,90), semanal (7d/R$6,90), mensal (30d/R$14,90) + aliases. credito=True (avulso→add_avulso_credit) / False (temporal→set_premium).
- **NOVO endpoint:** `POST /api/v1/pagamentos/criar-preferencia`
  - Header: `Authorization: Bearer <JWT-Supabase>` (extrai email) OU `Bearer <PREMIUM_TOKEN>` + email no body (atalho de teste sandbox sem login)
  - Body: `{ "plano": "jogo"|"semanal"|"mensal", "slug": "<slug>" (só plano jogo) }`
  - Resposta: `{ "preference_id", "init_point", "sandbox_init_point", "plano", "preco", "label" }`
  - 503 se MP_ACCESS_TOKEN ausente. Usa httpx direto (sem SDK MP).

### VARIÁVEIS Railway pendentes (Brunno adiciona — DESTRAVA tudo)
- **SUPABASE_JWT_SECRET** — Supabase → Settings → API → JWT Settings. SEM ela todo usuário leva 403 (paywall morto pra usuários reais). É o desbloqueio mais crítico.
- **MERCADOPAGO_ACCESS_TOKEN** — chave de TESTE (sandbox) já criada por Brunno.
- **MERCADOPAGO_WEBHOOK_SECRET** — painel MP (config webhooks). SEM ela o webhook é fail-closed (rejeita 403).

### ORDEM DE EXECUÇÃO (retomar daqui)
1. ~~Commitar o backend (webhook fixes + endpoint criar-preferencia) → push → deploy~~ ✅ FEITO (cb1c62b)
2. Brunno adiciona as 3 variáveis no Railway
3. TESTAR backend isolado em sandbox (sem depender do Lovable), via atalho PREMIUM_TOKEN+email:
   ```
   curl -s -X POST "https://palpites-backend-production.up.railway.app/api/v1/pagamentos/criar-preferencia" \
     -H "Authorization: Bearer <SEU_PREMIUM_TOKEN_DO_RAILWAY>" \
     -H "Content-Type: application/json" \
     -d '{"plano":"mensal","email":"teste@teste.com"}'
   ```
   → deve retornar sandbox_init_point. Usar o PREMIUM_TOKEN real (não texto literal).
4. Lovable implementa login + botões + paywall (prompt na seção 21b abaixo)
5. Teste ponta a ponta sandbox: login → botão → checkout MP (cartão teste) → webhook → premium → acesso libera
6. Só depois: trocar MP_ACCESS_TOKEN pra PRODUÇÃO e ligar o paywall (sábado)

### CRÍTICO — segurança de pagamento
- Testar TUDO em SANDBOX antes de produção. NUNCA testar cobrança em produção.
- O acesso premium é liberado pelo BACKEND via webhook — o frontend só mostra confirmação.

---

## 21b. Prompt pronto pro Lovable (login + pagamento)

```
Implementar login de usuário e fluxo de pagamento (Mercado Pago Checkout Pro) no site.
CONTEXTO: o backend (FastAPI no Railway) já valida JWT do Supabase Auth e tem o paywall pronto.
Backend: https://palpites-backend-production.up.railway.app

1. AUTENTICAÇÃO (Supabase Auth)
- Login e cadastro (email+senha) via Supabase Auth — projeto já usa Supabase (jwzvuixvuptazfyasmlm.supabase.co)
- Telas "Entrar"/"Criar conta" no header; guardar o access_token JWT; header reflete logado/deslogado

2. PÁGINA DE PLANOS — preços: jogo R$2,90 (24h) · semanal R$6,90 (7d, NOVO) · mensal R$14,90 (corrigir, hoje R$19,90)
Ao clicar Assinar: se não logado→login; se logado→
POST https://palpites-backend-production.up.railway.app/api/v1/pagamentos/criar-preferencia
  Header: Authorization: Bearer {access_token Supabase} + Content-Type: application/json
  Body: { "plano": "jogo"|"semanal"|"mensal", "slug": "<slug>" (só plano jogo) }
  Resposta: { "init_point", "sandbox_init_point" } → redireciona pro init_point (sandbox_init_point em teste)

3. RETORNO: criar /pagamento/sucesso, /pagamento/erro, /pagamento/pendente. Sucesso: "Pagamento confirmado!".
   Acesso liberado pelo BACKEND via webhook (não pelo frontend).

4. PAYWALL: análise completa é paga. Enviar JWT pro backend. 403→mostra paywall (Desbloquear+planos); 200→mostra análise.

IMPORTANTE: NÃO lidar com cartão no frontend (Checkout Pro do MP cuida). Manter visual (tema escuro, verde).
Em teste usar sandbox_init_point; em produção init_point.
```

### Backlog MP pós-lançamento
- Assinatura RECORRENTE (preapproval) — substituir pagamento único quando houver tempo de testar
- Recalcular break-even com preços novos (R$14,90, não R$19,90)

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
- **cb1c62b:** Mercado Pago backend — webhook fail-closed + Bug 2 (email→user_id) + Bug 3 (3 planos) + endpoint /criar-preferencia
- (de sessões/etapas anteriores no mesmo arco: c3678df palpite 1X2 puro, 6899429 roteamento valor/zebra)

### Trabalho principal do dia
1. **Palpite/Valor/Zebra separados** — palpite = 1X2 mais provável puro (sem value_score); valor = melhor preço; zebra = azarão com edge → aba /zebras
2. **Elo TSV** — trocado o hardcoded de origem incerta pelo eloratings.net (validado na fonte: Ecuador é 9º real). 48 times mapeados, códigos ambíguos checados (ZA≠SA, KR≠KO, CD≠CG, BA≠BH, NS=Northern Ireland≠NI=Nicarágua)
3. **Auditoria do rating** — 3 teorias erradas desmentidas por dados; modelo já calibrado (58/32/10 efetivo). NÃO normalizar. Decisão: manter ×3.0 no FIFA, recalibração pós-Copa.
4. **Odds** — causa do value_bets vazio era partida.odds=None congelado (busca falhou no prewarm). Endpoint /admin/refresh-odds busca odds reais (Pinnacle). Resultado: 66/72 com odds.
5. **Recálculo único** — refresh-odds + prewarm, zero 429 (warm-up + pacing + Fix B domaram o burst de cold-start)
6. **Check de tela** (Claude in Chrome) — validado: palpite 1X2, Elo propagado, sem false value, zebras, value honesto, árbitro honesto
7. **Mercado Pago backend** — diagnóstico completo, 3 bugs corrigidos, novo endpoint /criar-preferencia

### Lições/achados
- Fix B "existia mas não" — estava no players_agent (ffe8d0a), não no football_agent. Corrigido hoje.
- Endpoints admin eram fail-open (sem ADMIN_TOKEN = aberto). Token criado. Backlog: revisar pra fail-closed.
- Path dos endpoints admin: /api/v1/admin/... (não /admin/...). Header: Authorization (com ou sem Bearer).
- haiti-scotland mostrava Over como palpite (linha 601 sem filtro _MERCADOS_1X2) — corrigido, afetava jogos equilibrados.
- Webhook MP tinha manifest HMAC errado (usava request_id para data_id). Corrigido: data_id vem do body `data.data.id`.

### Frentes abertas no fim da sessão
- **Playground (2º terminal): FECHADO.** A The Odds API NÃO cobre amistosos internacionais (sport_key soccer_international_friendlies dá 404; nenhuma das 65 chaves soccer cobre amistosos). Conclusão: value bet só valida com odds reais nos JOGOS DA COPA (soccer_fifa_world_cup, Pinnacle) — já validado no check de tela (Ghana×Panama). Amistosos servem pra testar o MODELO/rating, não value bet. Playground ficou com value bet section + degradação honesta, bug :.1f de escanteios corrigido, early-exit após 404. Nada de produção tocado.
- **Mercado Pago: BACKEND PRONTO (cb1c62b).** Diagnóstico feito, backend commitado e deployado, prompt do Lovable pronto. Ver seções 21 e 21b. Próximo: variáveis Railway → teste sandbox → Lovable. Prazo: paywall sábado. NÃO bloqueia o lançamento de segunda (que é grátis).

### Lembretes pra retomada
- O LANÇAMENTO de segunda 08/06 é GRÁTIS (paywall desligado) — o produto pra isso está PRONTO e validado.
- O Mercado Pago é pro paywall de SÁBADO — atacar com calma, em sandbox, cabeça fresca.
- Tráfego vem do TikTok = MOBILE. Vale um check de tela responsivo (não feito ainda) antes de divulgar pesado.
- Backlog rápido: encoding dos 6 slugs Türkiye/Congo · trocar ADMIN_TOKEN · fraseado "favorita 39%".

---

## 24. Notas Técnicas Claude (pós cb1c62b)

### Detalhes de implementação que vale registrar

**webhook HMAC — manifest exato:**
```
manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
```
- `data_id` vem de `body["data"]["id"]` (campo no body do POST)
- `x_request_id` vem do header `x-request-id` (não confundir com data_id)
- `ts` vem do próprio header `x-signature` (formato `ts=...,v1=...`)
- Erro clássico: usar request_id no lugar de data_id para o campo `id:` — manifesto errado = todas as assinaturas falham

**supabase_client.py — qual função usa o quê:**
- `add_avulso_credit(email)` — aceita email, faz lookup internamente (ok usar direto)
- `set_premium(user_id, iso_date)` — exige UUID, NÃO aceita email. Sempre usar `get_user_id_by_email(email)` antes
- `deduct_avulso_credit(user_id)` — exige UUID, leitura+escrita (não atômica, risco de race se usuário fizer duas requisições simultâneas — ok pra escala atual)
- `verify_jwt_token(token)` — depende de `SUPABASE_JWT_SECRET`; retorna None imediatamente se env ausente (linha 75)

**por que SUPABASE_JWT_SECRET é o bloqueador mais crítico:**
Sem ela, `verify_jwt_token()` retorna `None` para qualquer JWT válido do Supabase Auth. O paywall (`_verificar_acesso_recomendacao`) interpreta `None` como não-autenticado e retorna 403. Resultado: usuários que pagaram e têm conta não conseguem acessar. Adicioná-la ao Railway destrava o paywall para TODOS os usuários com JWT real, sem nenhuma mudança de código.

**fire test (scripts/_fire_test.py) — resultados pós-dbd0afe:**
- 24/24 jogos Rodada 1 com palpite 1X2 correto (zero "Over" como palpite)
- haiti-scotland: `palpite_principal.mercado = "Resultado 1X2"` confirmado
- 3 falhas transientes no primeiro batch (timeout) — individuais reruns OK; Railway sem cold start após prewarm

**_MERCADOS_1X2 — onde está definido:**
```python
# ia_agent.py linha 518
_MERCADOS_1X2 = {"vitoria_casa", "empate", "vitoria_fora"}

# ia_agent.py linha 601 (fix dbd0afe)
((m, p) for m, p in probs_dc.items() if m in _MERCADOS_1X2 and m in odds and odds.get(m, 0) > 0)
```
Sem o `m in _MERCADOS_1X2`, jogos com probs DC equilibradas podiam ter "Over 2.5" ou "BTTS" como palpite principal por terem prob_dc mais alta que qualquer mercado 1X2.

**cache_partidas.json — estrutura correta:**
- Correto: `_store[slug]["stats"]["dados"].rating_casa.elo_score`
- Errado (camada velha): `_store[slug]["partida"].rating_casa.elo_score`
- O campo `partida` é da L1 (pode ter Elo antigo). Os dados de Elo TSV ficam em `stats.dados`.

**endpoint /criar-preferencia — path completo:**
`POST /api/v1/pagamentos/criar-preferencia`
- Definido em `app/payments/mercadopago_webhook.py` com decorator `@router.post("/pagamentos/criar-preferencia")`
- Montado em `main.py` linha 88: `app.include_router(mp_router, prefix="/api/v1", tags=["Pagamentos"])`
- Retorna: `preference_id`, `init_point` (produção), `sandbox_init_point` (teste), `plano`, `preco`, `label`
