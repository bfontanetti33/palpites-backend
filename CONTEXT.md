# CONTEXT — Palpites da IA (Copa 2026)

> Documento único de contexto para retomar o desenvolvimento em qualquer sessão.
> Atualizado: 2026-06-05 | Branch: claude/recomendacao-500-errors-9eNqU

---

## 1. O Produto

**Palpites da IA** é um site de análise estatística de apostas esportivas para a Copa do Mundo 2026, com modelo de IA que gera palpites embasados em dados reais, em português acessível.

| | |
|--|--|
| **Frontend** | https://palpitesdaia.com.br (também magic-guess-stream.lovable.app) |
| **Backend** | https://palpites-backend-production.up.railway.app |
| **GitHub Frontend** | github.com/bfontanetti33/palpitesdaia |
| **GitHub Backend** | github.com/bfontanetti33/palpites-backend |
| **Dono** | Brunno Fontanetti (bfontanetti33) |
| **Sócio** | Chi (publicidade/marketing + TikTok @palpitesdaia, 20k seguidores) |
| **Diferencial** | Modelo estatístico robusto + linguagem acessível + honestidade intelectual |

---

## 2. Stack Técnica

| Camada | Tecnologia | Detalhe |
|--------|-----------|---------|
| Frontend | React, TanStack, Tailwind | Lovable Cloud (CI/CD automático via GitHub) |
| Backend | Python 3.11, FastAPI 0.111 | Uvicorn 2 workers |
| Deploy Backend | Railway | Região southamerica-east1 (São Paulo) |
| Banco de dados | Supabase | jwzvuixvuptazfyasmlm.supabase.co |
| Domínio | palpitesdaia.com.br | Registro.br |
| Email | Resend | contato@palpitesdaia.com.br (DNS pendente) |
| AI narrativa | Anthropic Claude SDK 0.105.2 | claude-sonnet-4-6, timeout 45s |
| Auth JWT | python-jose 3.5.0 | |
| Cache | cachetools TTLCache 5.3.3 | |
| Rate limit | slowapi 0.1.9 | |
| Erros | Sentry SDK 2.61.1 | Opcional |
| HTTP client | httpx 0.27.0 | |

---

## 3. Estrutura de Arquivos

```
palpites-backend/
├── app/
│   ├── agents/
│   │   ├── football_agent.py   # Busca dados API-Football; seed fallback para forma
│   │   ├── ia_agent.py         # Pipeline 5 camadas + narrativa Claude
│   │   ├── odds_agent.py       # The Odds API (soccer_fifa_world_cup)
│   │   ├── odds_engine.py      # Shin Method + z-score + value bet detection
│   │   └── players_agent.py    # Jogadores de destaque dos elencos
│   ├── auth/
│   │   └── supabase_client.py  # JWT verification + status premium + usage log
│   ├── cache/
│   │   ├── static_cache.py     # Cache disco (cache_partidas.json) + TTL tiered
│   │   └── odds_cache.py       # Cache memória odds (TTLCache 25h, 80 slots)
│   ├── models/
│   │   └── schemas.py          # Pydantic models: Partida, RecomendacaoIA, etc.
│   ├── monitoring/
│   │   ├── cron_jobs.py        # 4 background tasks asyncio
│   │   └── telegram_bot.py     # Alertas Telegram + estado global
│   ├── payments/
│   │   └── mercadopago_webhook.py  # Webhook MercadoPago (configurado, pendente teste)
│   ├── routes/
│   │   ├── partidas.py         # Endpoints públicos, premium, zebras, bingo
│   │   └── admin.py            # Endpoints administrativos
│   ├── limiter.py              # Configuração slowapi
│   └── main.py                 # App FastAPI + startup + CORS + middlewares
├── seeds/
│   ├── copa_2026.json          # 72 jogos, 48 times, grupos (fonte da verdade)
│   ├── forma_recente_seed.json # Forma real de 48 seleções (até mai/2026) ← FALLBACK ATIVO
│   ├── squads_copa_2026.json   # Elencos 47/48 times (Curaçao sem dados)
│   ├── arbitros_copa_2026.json # 52 árbitros com stats Copa 2022/2018
│   └── cache_partidas.json     # Cache disco de partidas computadas (vazio no git — ver §11)
├── scripts/
│   ├── backtest_copa.py        # Backtest do modelo vs Copa 2022/2018
│   ├── registrar_resultado.py  # Registra resultado real após cada jogo
│   └── prewarm_primeira_semana.py
├── docs/
│   ├── lovable_supabase_integration.md
│   └── mercadopago_setup.md
├── CONTEXT.md                  # Este arquivo
├── TASKS.md                    # Lista de tarefas e status
├── railway.toml                # Região: southamerica-east1
└── requirements.txt
```

---

## 4. Modelo Estatístico — 5 Camadas

| # | Nome | Descrição |
|---|------|-----------|
| 1 | **Rating Dinâmico** | Elo 50% + Pi-rating 30% + FIFA Ranking 20%. Z-score regional por confederação. Decaimento temporal: peso = 0.98^dias |
| 2 | **Dixon-Coles + Skellam** | Poisson aprimorado com correção para placares baixos. Gera matriz de placares, prob 1X2, BTTS, Over/Under |
| 3 | **Value Bet Detector** | Shin Method (remoção de margem), consensus ponderado, z-score, sharp money detection. Só com odds reais |
| 4 | **Context Engine** | Home advantage (MEX×1.25+altitude, EUA×1.10, CAN×1.10), fadiga, rodada 1, zebra detector fator 2× Copa |
| 4B | **Tail Risk (Taleb)** | Fat tail: 85% Dixon-Coles + 15% Student-t (4 graus). Fragility score. Uncertainty index. Barbell signal |
| 5 | **Claude Narrativa** | claude-sonnet-4-6, AsyncAnthropic timeout 45s. Gera texto PT-BR user-friendly |

**Regra de ouro:** nunca retorna 500 — cada camada tem fallback independente.

---

## 5. Fontes de Dados

| Fonte | Dados | Custo |
|-------|-------|-------|
| API-Football v3 (Pro) | Fixtures, H2H, forma recente, stats, jogadores | $19/mês |
| The Odds API | Odds reais (Pinnacle, 40+ casas) | $30/mês |
| Wikipedia | Squads, Elo ratings, FIFA Ranking | Grátis |
| seeds/copa_2026.json | 72 jogos fase de grupos (IDs oficiais) | Grátis |
| seeds/forma_recente_seed.json | Últimos 10 jogos de cada seleção | Grátis |
| Anthropic Claude | Narrativa PT-BR | ~$2/mês |

---

## 6. Pipeline de Dados

```
Usuário abre /copa/jogos/{slug}/recomendacao
    │
    ├─ Cache hit (static_cache)? → Retorna em <100ms, zero API
    │
    └─ Cache miss → football_agent.buscar_detalhe_partida()
            │
            ├─ API-Football /teams/statistics      (stats históricas; falha para nacionais)
            ├─ API-Football /fixtures?team&last=20  (forma recente)
            │        └─ FALLBACK: forma_recente_seed.json se API retornar vazio ✅
            ├─ API-Football /fixtures/headtohead   (H2H; frequentemente vazio)
            ├─ API-Football /fixtures?id=           (árbitro)
            └─ The Odds API                        (odds 1X2, over/under)
                    │
                    └─ ia_agent.gerar_recomendacao()
                            │
                            ├─ C1 → C2 → C3 → C4 → C4B → C5 (Claude)
                            │
                            └─ Salva em static_cache (disco) + _partida_cache (RAM)
```

---

## 7. Sistema de Cache

### Camadas

| Camada | Onde | TTL | Slots | Uso |
|--------|------|-----|-------|-----|
| `_cache` | RAM (TTLCache) | 8h | 400 | Respostas brutas API-Football |
| `_partida_cache` | RAM (TTLCache) | 8h | 72 | Objetos Partida completos |
| `odds_cache` | RAM (TTLCache) | 25h | 80 | Odds por slug |
| `football_api_cache.json` | Disco | 8h | ~5MB | Backup do `_cache` — sobrevive restart/redeploy |
| `cache_partidas.json` | Disco + git | tiered | ilimitado | Partidas + stats + narrativa |

### TTL do cache_partidas (tiered por proximidade do jogo)
| Distância | TTL stats | TTL narrativa | TTL partida |
|-----------|-----------|---------------|-------------|
| > 12h | 24h | 8h | 8h |
| 2–12h | 1h | 8h | 8h |
| < 2h | 30min | 8h | 8h |
| dados_insuficientes | — | — | 4h |

### Consumo estimado mensal
- API-Football: ~200–300 req/mês (rate limit 2s entre chamadas reais)
- The Odds API: ~200 req/mês (tiered por proximidade)
- Redeploys: 0 req extras (football_api_cache.json restaura do disco)

---

## 8. Endpoints

### Públicos
| Endpoint | Rate limit | Descrição |
|----------|-----------|-----------|
| `GET /health` | — | Status básico |
| `GET /api/v1/copa/jogos` | 60/min | Lista 72 jogos com probabilidades |
| `GET /api/v1/copa/jogos/{slug}` | 20/min | Detalhe: forma, H2H, odds, árbitro |
| `GET /api/v1/copa/zebras` | — | Azarões com embasamento estatístico |
| `GET /api/v1/copa/bingo` | — | Acumulada: under 2.5 + BTTS alinhados |
| `GET /api/v1/copa/odds-baixa` | — | Value bets: odd > 2.0 + prob modelo > 40% |

### Premium (JWT Supabase ou PREMIUM_TOKEN)
| Endpoint | Rate limit | Descrição |
|----------|-----------|-----------|
| `GET /api/v1/copa/jogos/{slug}/recomendacao` | 5/min | Análise completa 5 camadas + narrativa Claude |

### Admin (ADMIN_TOKEN opcional)
| Endpoint | Descrição |
|----------|-----------|
| `GET /api/v1/admin/health-check` | Status completo (quota APIs, Supabase, erros 24h) |
| `GET /api/v1/admin/prewarm?dias=N` | Dispara prewarm em background (retorna imediatamente) |
| `GET /api/v1/admin/validar-semana` | Valida 24 jogos semana 1 (instantâneo, sem API) |
| `GET /api/v1/admin/cache-snapshot` | Exporta cache_partidas.json completo |
| `GET /api/v1/admin/odds-debug` | Testa Odds API |
| `GET /api/v1/admin/acuracia` | Métricas de acerto do modelo |
| `GET /api/v1/admin/stats` | Métricas gerais de uso |
| `GET /api/v1/admin/telegram-test` | Envia mensagem de teste Telegram |
| `GET /api/v1/admin/supabase-test` | CRUD test no Supabase |

### Pagamentos
| Endpoint | Descrição |
|----------|-----------|
| `POST /api/v1/pagamentos/mercadopago/webhook` | Recebe eventos MercadoPago |

---

## 9. Cron Jobs (iniciam no startup)

| Job | Frequência | Início | Função |
|-----|-----------|--------|--------|
| cache_diario | 1×/dia (06h BRT / 09h UTC) | imediato | Resumo Telegram com estado do cache |
| odds_tiered | tick 30min | +1min | Atualiza odds com freq por proximidade do jogo |
| prewarm_stats | tick 30min | +2min | Pré-aquece stats dos próximos 14 dias |
| healthcheck | 15min | +5min | Alerta Telegram se quota API-Football < 500 |

---

## 10. Critérios Zebra e Bingo

### Zebra (azarão com embasamento)
- value_score > 0.15 **E** z_score > 1.96 **E** odds_disponiveis=True
- prob_modelo do azarão > 25%
- Pelo menos 1 evidência concreta (forma, Elo diff, fadiga, uncertainty)
- Azarão com >= 5 jogos nos últimos 10
- Fator 2× para Copa do Mundo
- Sharp money contra → rejeita zebra

### Bingo (acumulada da IA)
- prob_modelo > 60% **E** fair_odd > 1.30 **E** value_score >= 0
- Mercados permitidos: Over 1.5/2.5, BTTS Sim, Vitória favorito, Chance Dupla
- Mercados proibidos: Under, Vitória Fora, placar exato
- 3–5 seleções, jogos diferentes, odd total 2.0–8.0
- Rejeita: uncertainty_index > 70, odds_disponiveis=False

---

## 11. Problema Crítico: Cache Reseta em Cada Deploy

**O que acontece:** Cada push para `main` cria um container novo no Railway com memória zerada. O `cache_partidas.json` commitado no git é `{}` (vazio), então o deploy começa sem dados. O cron de prewarm repopula tudo em ~8–10min.

**Solução pendente:**
```bash
# 1. Aguardar prewarm terminar (~10min após deploy)
# 2. Chamar:
curl https://palpites-backend-production.up.railway.app/api/v1/admin/cache-snapshot > cache_snapshot.json

# 3. Salvar o conteúdo de "dados" em seeds/cache_partidas.json
# 4. Commitar:
git add seeds/cache_partidas.json
git commit -m "chore: snapshot cache 24 jogos semana 1"
git push
```
Após isso, cada deploy começa com os 24 jogos prontos — cron só atualiza o stale.

---

## 12. Variáveis de Ambiente

| Variável | Status | Descrição |
|----------|--------|-----------|
| `ANTHROPIC_API_KEY` | ✅ | Narrativas Claude |
| `API_FOOTBALL_KEY` | ✅ | Pro — 20k req/mês |
| `ODDS_API_KEY` | ✅ | The Odds API |
| `PREMIUM_TOKEN` | ✅ | Token fixo admin/bypass |
| `SUPABASE_URL` | ✅ | https://jwzvuixvuptazfyasmlm.supabase.co |
| `SUPABASE_KEY` | ✅ | Chave secret |
| `SUPABASE_JWT_SECRET` | ✅ | Verificação JWT usuários |
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot palpitesdaia_monitor_bot |
| `TELEGRAM_CHAT_ID` | ✅ | 8802057413 |
| `ADMIN_TOKEN` | ⚠️ opcional | Protege endpoints admin |
| `SENTRY_DSN` | ⚠️ opcional | Rastreamento de erros |
| `MERCADOPAGO_ACCESS_TOKEN` | ⏳ pendente | Pagamentos |
| `MERCADOPAGO_WEBHOOK_SECRET` | ⏳ pendente | HMAC dos webhooks |

**CORS configurado para:** palpitesdaia.com.br, www.palpitesdaia.com.br, *.lovable.app, *.lovableproject.com, localhost:3000/5173

---

## 13. Supabase

- **URL:** https://jwzvuixvuptazfyasmlm.supabase.co
- **Tabelas criadas:**
  - `users`: id, email, is_premium, premium_until, avulso_credits, created_at
  - `usage_log`: id, user_id, slug, created_at
- **Status:** conectado no backend, **pendente no Lovable** (login/cadastro real não ativo)

---

## 14. Monitoramento Telegram

- **Bot:** palpitesdaia_monitor_bot
- **Alertas imediatos:** erro 500, quota < 500, Anthropic < $2, sharp money
- **Resumo diário:** 06h BRT com estado do cache

---

## 15. Monetização

| | |
|--|--|
| **Modelo** | R$19,90/mês (ilimitado) ou R$2,90/jogo (avulso) |
| **Paywall** | Homepage gratuita, análise completa paga |
| **Estratégia lançamento** | Gratuito dia 1 → ativa paywall sábado |
| **Pagamento** | Mercado Pago (Pix + cartão) — integração pendente |
| **Break-even** | 23 assinantes a R$19,90/mês |

---

## 16. Custos Mensais

| Serviço | Custo |
|---------|-------|
| Lovable Pro | $25/mês |
| Railway Hobby | $5/mês |
| API-Football Pro | $19/mês |
| The Odds API | $30/mês |
| Anthropic API | ~$2/mês |
| **Total** | **~$81/mês (~R$450)** |
| Domínio | R$40/ano |

---

## 17. Estado Atual em Produção (2026-06-05)

### Métricas
```
quota_api_football : 7.499 req restantes (plano Pro 20k/mês)
quota_odds_api     : 19.672 créditos restantes
erros_24h          : 0
supabase           : conectado
telegram           : configurado
uptime             : reseta a cada push para main
```

### Validação semana 1 — após prewarm completo (~10min)
```
Com stats   : 24/24  ✅ modelo Elo + Poisson funciona para todos
Com odds    : 22/24  ⚠️ Australia e Portugal/Congo sem cobertura Odds API
Com forma   : 24/24  ✅ fix deployado: seed local como fallback
dados_insuf :  0/24  ✅ fix deployado: flag só True quando forma ausente
Status OK   : ?/24   ⏳ verificar após merge para main + prewarm
```

---

## 18. Slugs — Semana 1 (Jun 11-17)

```
Jun 11: mexico-south-africa, south-korea-czech-republic
Jun 12: canada-bosnia-and-herzegovina, usa-paraguay
Jun 13: qatar-switzerland, brazil-morocco, haiti-scotland
Jun 14: australia-türkiye, germany-curaçao, netherlands-japan,
        ivory-coast-ecuador, sweden-tunisia
Jun 15: spain-cape-verde-islands, belgium-egypt,
        saudi-arabia-uruguay, iran-new-zealand
Jun 16: france-senegal, iraq-norway, argentina-algeria
Jun 17: austria-jordan, portugal-congo-dr, england-croatia,
        ghana-panama, uzbekistan-colombia
```

---

## 19. Roadmap

### Fase 1 — Dados reais ✅ COMPLETA
### Fase 2 — Agente IA + Monetização (85%)
- ✅ Modelo 5 camadas
- ✅ Cache inteligente 2 camadas
- ✅ Forma recente com fallback seed
- ⏳ Fix dados_insuficientes sistêmico
- ⏳ Cache persistente entre deploys (cache-snapshot → commit)
- ⏳ Supabase no Lovable (login/cadastro real)
- ⏳ Mercado Pago funcional

### Fase 3 — Monitoramento (após lançamento)
- Sentry + UptimeRobot + backtest contínuo pós-Copa

### Fase 4 — Escala (futuro)
- Dataset próprio Copa 2026, modelo XGBoost, histórico de acertos rastreado

---

## 20. Comandos Úteis

```bash
# Pasta local do projeto (Windows)
cd "C:\Users\brunn\OneDrive\Documentos\CLAUDIO\Palpites_da_IA\palpites-backend"

# Pasta remota (Claude Code / Railway)
/home/user/palpites-backend

# Deploy (Railway auto-deploya no push)
git add . && git commit -m "mensagem" && git push origin main

# Forçar redeploy sem mudança de código
git commit --allow-empty -m "chore: force redeploy" && git push origin main

# Prewarm manual (retorna imediatamente, roda em background)
curl https://palpites-backend-production.up.railway.app/api/v1/admin/prewarm?dias=14

# Snapshot do cache (chamar após prewarm terminar)
curl https://palpites-backend-production.up.railway.app/api/v1/admin/cache-snapshot

# Validação dos 24 jogos semana 1
curl https://palpites-backend-production.up.railway.app/api/v1/admin/validar-semana

# Health completo
curl https://palpites-backend-production.up.railway.app/api/v1/admin/health-check

# Seed árbitros (após quota reset às 21h BRT)
python scripts/gerar_seed_arbitros.py --min-jogos 15 --delay 2
```

---

## 21. Próximas Ações Prioritárias

```
1. [URGENTE] Commitar cache_partidas.json populado
   → chamar /admin/cache-snapshot após prewarm
   → salvar JSON em seeds/cache_partidas.json e commitar

2. [FEITO ✅] Fix dados_insuficientes sistêmico — branch claude/recomendacao-500-errors-9eNqU
   → dados_insuficientes=True apenas quando forma ausente (não por /teams/statistics)
   → validador: status "incompleto" não depende mais de tem_stats (StatsRecomendacao)
   → merge para main pendente

3. [ALTA] H2H: criar seeds/h2h_seed.json com confrontos históricos Copa
   → elimina h2h_count=0 para todos os jogos

4. [MÉDIA] Supabase no Lovable
   → Settings → Integrations → Supabase
   → login/cadastro real para usuários

5. [MÉDIA] Mercado Pago — testar fluxo completo
   → Webhook: /api/v1/pagamentos/mercadopago/webhook

6. Lançamento TikTok (Chi) — Copa começa 11/06/2026
```

---

## 22. Decisões Arquiteturais

**Por que seeds em vez de só API?**
API-Football tem limite diário e falha para seleções nacionais em alguns endpoints. Seeds garantem dados básicos sem custo. API enriquece quando disponível.

**Por que cache em disco (`cache_partidas.json`)?**
Railway usa containers efêmeros. Cache disco sobrevive a restarts dentro do mesmo deploy. Commitado no git, sobrevive a deploys também — desde que não seja `{}`.

**Por que forma_recente_seed.json como fallback?**
`/fixtures?team&last=20` para seleções nacionais retorna vazio frequentemente durante a Copa (fixtures em andamento, IDs específicos). O seed cobre os últimos 10 jogos de cada seleção até mai/2026 e ativa automaticamente.

**Por que dados_insuficientes=True mesmo com Elo e forma? (histórico)**
Flag original combinava duas condições: sem forma (bloqueia modelo) e sem stats API (não bloqueia — usa Elo fallback). Para seleções nacionais, a segunda sempre falha. Fix aplicado: `dados_insuficientes=True` somente quando `len(forma_casa)==0 OR len(forma_fora)==0`.
