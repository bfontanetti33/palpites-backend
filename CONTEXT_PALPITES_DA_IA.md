# Palpites da IA — Contexto Completo do Projeto

> Documento de contexto para retomar o desenvolvimento em qualquer sessão.
> Última atualização: 05/06/2026

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

- **Modelo:** R$19,90/mês (ilimitado) ou R$2,90/jogo (avulso)
- **Paywall:** homepage gratuita, análise completa paga
- **Estratégia lançamento:** 100% gratuito no dia 1, ativa paywall sábado
- **Pagamento:** Mercado Pago (Pix + cartão) — integração pendente
- **Discussão pendente:** estratégia de precificação (early bird, anchoring, free trial)

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

## 16. Status Atual (05/06/2026)

### ✅ Funcionando
- Backend online (Railway São Paulo)
- 72 jogos listados com probabilidades
- Odds funcionando para 22/24 jogos semana 1
- Zero erros 500
- Cache em disco (persiste entre deploys)
- Supabase conectado
- Telegram bot ativo (resumo diário 8h)
- Domínio palpitesdaia.com.br ativo
- GA4 com eventos customizados
- Compliance + disclaimer + Lei 14.790/2023
- Paywall visual completo
- SEO + meta tags

### ❌ Problemas Conhecidos
- Forma recente: 0/24 jogos com dados (seed não usado como fallback)
- H2H: 0 jogos com histórico
- Odds na lista da homepage: mostra 0 (detalhe ok)
- Austrália e Portugal: sem odds da The Odds API

### ⏳ Pendente
- Conectar forma_recente_seed.json como fallback
- Supabase conectar no Lovable (login/cadastro real)
- Mercado Pago integração funcional
- Seed árbitros completo (rodar após quota reset: `python scripts/gerar_seed_arbitros.py --min-jogos 15 --delay 2`)
- CLAUDE.md no repositório backend

---

## 17. Roadmap

### Fase 1 — Dados reais ✅ COMPLETA

### Fase 2 — Agente IA + Monetização (80%)
- ✅ Modelo 5 camadas
- ✅ Odds Engine robusto
- ✅ Cache inteligente 2 camadas
- ⏳ Forma recente como fallback (bug crítico)
- ⏳ Supabase no Lovable
- ⏳ Mercado Pago funcional

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

## 19. Próxima Ação Prioritária

```
1. Corrigir forma recente como fallback (bug crítico)
   → conectar forma_recente_seed.json no _forma_recente()

2. Conectar Supabase no Lovable
   → Settings → Integrations → Supabase

3. Integrar Mercado Pago
   → Webhook: /api/v1/webhooks/mercadopago

4. Teste ponta a ponta: cadastro → pagamento → acesso

5. Lançamento TikTok (Chi) — Copa começa 11/06/2026
```

---

## 20. Contexto de Negócio

- **Copa do Mundo 2026:** 11/06 a 19/07/2026 (48 times, 104 jogos)
- **TikTok:** @palpitesdaia — 20k seguidores engajados (Chi)
- **Estratégia:** lançamento gratuito → coleta usuários → paywall sábado
- **Diferencial:** modelo estatístico robusto + linguagem acessível + honestidade intelectual (sem "78% de acerto" inventado)
- **Público-alvo:** apostador casual brasileiro que quer embasamento sem jargão técnico
