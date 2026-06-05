# CONTEXT — Estado Técnico do Projeto

> Atualizado: 2026-06-05
> Deploy: https://palpites-backend-production.up.railway.app
> Branch principal: `main` (auto-deploy no Railway)

---

## Visão Geral

Backend FastAPI para análise e predição de jogos da Copa do Mundo FIFA 2026. Combina dados históricos reais (API-Football), odds de apostas (The Odds API) e modelo matemático em 5 camadas para gerar probabilidades e narrativas em português.

---

## Stack

| Componente | Tecnologia | Versão |
|------------|-----------|--------|
| Framework  | FastAPI   | 0.111.0 |
| Runtime    | Uvicorn (2 workers) | 0.29.0 |
| HTTP client | httpx   | 0.27.0 |
| AI narrativa | Anthropic Claude | SDK 0.105.2 |
| Validação  | Pydantic  | 2.11.5 |
| Cache      | cachetools TTLCache | 5.3.3 |
| Rate limit | slowapi   | 0.1.9 |
| Auth JWT   | python-jose | 3.5.0 |
| Erros      | Sentry SDK | 2.61.1 |
| Deploy     | Railway   | southamerica-east1 |

---

## Estrutura de Arquivos

```
palpites-backend/
├── app/
│   ├── agents/
│   │   ├── football_agent.py   # Busca dados da API-Football + 5 camadas de stats
│   │   ├── ia_agent.py         # Orquestra pipeline + gera narrativa Claude
│   │   ├── odds_agent.py       # Busca odds da The Odds API
│   │   ├── odds_engine.py      # Shin method + value bet analysis
│   │   └── players_agent.py    # Jogadores de destaque dos elencos
│   ├── auth/
│   │   └── supabase_client.py  # JWT verification + status de assinatura
│   ├── cache/
│   │   ├── static_cache.py     # Cache disco (cache_partidas.json) + TTL tiered
│   │   └── odds_cache.py       # Cache memória para odds (TTLCache 25h, 80 slots)
│   ├── models/
│   │   └── schemas.py          # Pydantic models: Partida, RecomendacaoIA, etc.
│   ├── monitoring/
│   │   ├── cron_jobs.py        # 4 background tasks asyncio
│   │   └── telegram_bot.py     # Alertas Telegram + estado global
│   ├── payments/
│   │   └── mercadopago_webhook.py  # Webhook MercadoPago (configurado)
│   ├── routes/
│   │   ├── partidas.py         # Endpoints públicos e premium
│   │   └── admin.py            # Endpoints administrativos
│   ├── limiter.py              # Configuração slowapi
│   └── main.py                 # App FastAPI + startup + CORS + middlewares
├── seeds/
│   ├── copa_2026.json          # 72 jogos, 48 times, grupos (fonte da verdade)
│   ├── forma_recente_seed.json # Forma real de 48 seleções (até mai/2026)
│   ├── squads_copa_2026.json   # Elencos de 47/48 times
│   ├── arbitros_copa_2026.json # 52 árbitros com stats reais
│   └── cache_partidas.json     # Cache disco de partidas computadas
├── scripts/                    # Scripts auxiliares (rodar manualmente)
│   ├── backtest_copa.py        # Backtest do modelo vs Copa 2022/2018
│   ├── registrar_resultado.py  # Registra resultado real após cada jogo
│   └── prewarm_primeira_semana.py  # Prewarm manual dos 24 jogos
├── docs/
│   ├── lovable_supabase_integration.md
│   └── mercadopago_setup.md
├── railway.toml                # Região: southamerica-east1
└── requirements.txt
```

---

## Endpoints Completos

### Públicos (sem auth)
| Método | Path | Descrição |
|--------|------|-----------|
| GET | `/health` | Status básico do servidor |
| GET | `/api/v1/copa/jogos` | Lista 72 jogos com probabilidades |
| GET | `/api/v1/copa/jogos/{slug}` | Detalhe: forma, H2H, odds, árbitro |
| GET | `/api/v1/copa/zebras` | Jogos onde azarão tem >35% chance |
| GET | `/api/v1/copa/bingo` | Under 2.5 + BTTS alinhados |
| GET | `/api/v1/copa/odds-baixa` | Value bets com odd > 2.0 |

### Premium (JWT Supabase ou PREMIUM_TOKEN)
| Método | Path | Descrição |
|--------|------|-----------|
| GET | `/api/v1/copa/jogos/{slug}/recomendacao` | Análise completa 5 camadas + narrativa Claude |

### Admin (ADMIN_TOKEN opcional)
| Método | Path | Descrição |
|--------|------|-----------|
| GET | `/api/v1/admin/health-check` | Status completo (quota APIs, erros, uptime) |
| GET | `/api/v1/admin/prewarm?dias=N` | Dispara prewarm em background |
| GET | `/api/v1/admin/validar-semana` | Valida 24 jogos semana 1 (instantâneo, sem API) |
| GET | `/api/v1/admin/cache-snapshot` | Exporta cache_partidas.json completo |
| GET | `/api/v1/admin/odds-debug` | Testa Odds API |
| GET | `/api/v1/admin/acuracia` | Métricas de acerto do modelo |
| GET | `/api/v1/admin/stats` | Métricas gerais |
| GET | `/api/v1/admin/telegram-test` | Envia mensagem teste Telegram |
| GET | `/api/v1/admin/supabase-test` | CRUD test no Supabase |

### Pagamentos
| Método | Path | Descrição |
|--------|------|-----------|
| POST | `/api/v1/pagamentos/mercadopago/webhook` | Recebe eventos MercadoPago |

---

## Pipeline de Dados

```
Usuário abre /copa/jogos/{slug}/recomendacao
    │
    ├─ Cache hit? → Retorna em <100ms (sem API)
    │
    └─ Cache miss → football_agent.buscar_detalhe_partida()
            │
            ├─ API-Football /teams/statistics (stats históricas)
            ├─ API-Football /fixtures?team&last=20 (forma recente)
            │        └─ Fallback: forma_recente_seed.json se API vazia
            ├─ API-Football /fixtures/headtohead (H2H)
            ├─ API-Football /fixtures?id= (árbitro)
            └─ The Odds API (odds 1X2, over/under)
                    │
                    └─ ia_agent.gerar_recomendacao()
                            │
                            ├─ C1: Elo + Pi Rating + FIFA (rating combinado)
                            ├─ C2: Dixon-Coles (lambda casa/fora)
                            ├─ C3: Shin odds (implied prob corrigida)
                            ├─ C4: Contexto (home advantage, fadiga)
                            ├─ C4B: Tail Risk (fat tails, barbell)
                            └─ C5: Claude narrativa (texto PT-BR)
                                    │
                                    └─ Salva em cache disco + memória
```

---

## Sistema de Cache

### Camadas (da mais rápida para a mais lenta)

| Camada | Onde | TTL | Tamanho | Uso |
|--------|------|-----|---------|-----|
| `_cache` | RAM (TTLCache) | 8h | 400 slots | Respostas brutas API-Football |
| `_partida_cache` | RAM (TTLCache) | 8h | 72 slots | Objetos Partida completos |
| `odds_cache` | RAM (TTLCache) | 25h | 80 slots | Odds por slug |
| `football_api_cache.json` | Disco | 8h | ~5MB | Backup do `_cache` — sobrevive restart |
| `cache_partidas.json` | Disco + git | TTL tiered | ilimitado | Partidas + stats + narrativa |

### TTL do cache_partidas (tiered por proximidade)
- > 12h até o jogo → stats válidas por **24h**
- 2–12h até o jogo → stats válidas por **1h**
- < 2h até o jogo → stats válidas por **30min**
- Narrativa: sempre **8h** (muda pouco)
- Partida completa: **8h** (dados_insuficientes=True → **4h**)

---

## Cron Jobs (iniciam no startup)

| Job | Frequência | Início | Função |
|-----|-----------|--------|--------|
| cache_diario | 1×/dia (06h BRT) | imediato | Resumo Telegram com estado do cache |
| odds_tiered | 30min | +1min startup | Atualiza odds com freq por proximidade |
| prewarm_stats | 30min | +2min startup | Pré-aquece stats dos próximos 14 dias |
| healthcheck | 15min | +5min startup | Alerta Telegram se quota < 500 |

---

## Variáveis de Ambiente Necessárias

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `API_FOOTBALL_KEY` | ✅ | Plano Pro — 20k req/mês |
| `ODDS_API_KEY` | ✅ | The Odds API — créditos pagos |
| `ANTHROPIC_API_KEY` | ✅ | Narrativas Claude |
| `SUPABASE_URL` | ✅ | URL do projeto Supabase |
| `SUPABASE_KEY` | ✅ | Chave anon ou service_role |
| `SUPABASE_JWT_SECRET` | ✅ | Verificação JWT dos usuários |
| `PREMIUM_TOKEN` | ✅ | Token fixo para acesso admin |
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot de alertas |
| `TELEGRAM_CHAT_ID` | ✅ | Chat/canal dos alertas |
| `ADMIN_TOKEN` | ⚠️ opcional | Protege endpoints admin (sem ele, aberto) |
| `SENTRY_DSN` | ⚠️ opcional | Rastreamento de erros |
| `MERCADOPAGO_TOKEN` | ⚠️ opcional | Pagamentos |

---

## Estado Atual em Produção (2026-06-05)

### Métricas do health-check
```
quota_api_football : 7.499 req restantes (plano Pro 20k/mês)
quota_odds_api     : 19.672 créditos restantes
erros_24h          : 0
supabase           : conectado
telegram           : configurado
uptime             : fresh (cada push a main causa novo deploy)
```

### Validação semana 1 (24 jogos, Jun 11-17)
Estado estável após prewarm completo (demora ~8-10 min após cada deploy):
```
Com stats   : 24/24 — modelo Elo + Poisson funciona para todos
Com odds    : 22/24 — Australia e Portugal/Congo sem cobertura na Odds API
Com forma   : 24/24 — fix deployado: seed local como fallback quando API vazia
Status OK   : 0/24  — bloqueado por dados_insuficientes sistêmico (ver abaixo)
```

### Problema sistêmico: dados_insuficientes=True
Todos os jogos têm `dados_insuficientes=True` porque a flag inclui `stats_casa.dados_insuficientes OR stats_fora.dados_insuficientes` — e a chamada `/teams/statistics` da API-Football falha para todas as seleções nacionais (não têm stats de temporada de clube). O modelo ainda funciona plenamente via Elo + forma (seed), mas a flag polui os logs e o validador. Precisa de fix na lógica da flag.

### Problema do ciclo deploy → reset de cache
Cada push para `main` dispara um novo deploy no Railway, criando um container novo com memória zerada. O `cache_partidas.json` commitado no git é `{}` (vazio), então o deploy começa sem dados. O cron de prewarm refaz tudo em ~8-10min a cada deploy. **Solução pendente:** após prewarm completo, chamar `/admin/cache-snapshot`, salvar o JSON retornado em `seeds/cache_partidas.json` e commitar — o próximo deploy já começa com os 24 jogos populados.

---

## Slugs dos 24 Jogos — Semana 1

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

## Como Rodar Localmente

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Configurar variáveis
cp .env.example .env   # editar com suas chaves

# 3. Rodar
uvicorn app.main:app --reload

# 4. Prewarm manual após startup
curl http://localhost:8000/api/v1/admin/prewarm?dias=7

# 5. Validar dados
curl http://localhost:8000/api/v1/admin/validar-semana
```

---

## Decisões Arquiteturais Relevantes

**Por que seeds em vez de só API?**
API-Football tem limite diário. Seeds garantem dados básicos sem custo de quota. API é usada para enriquecer (forma real, stats detalhadas).

**Por que cache em disco (`cache_partidas.json`)?**
Railway usa containers efêmeros. Sem cache disco, cada redeploy zeraria o cache em memória e gastaria ~200 chamadas de API para popular os 24 jogos. Com o arquivo commitado no git, o próximo deploy começa com dados.

**Por que `dados_insuficientes=True` mesmo com dados Elo?**
Flag original do projeto para indicar que API retornou vazio. O modelo tem fallback completo via Elo e forma seed, mas a flag não foi atualizada para refletir isso. Precisa de revisão.

**Por que forma_recente_seed.json?**
API-Football `/fixtures?team&last=20` para seleções nacionais às vezes retorna vazio (Copa em andamento, fixture ID específico). O seed cobre os últimos 10 jogos de cada seleção até mai/2026 e é usado como fallback automático.
