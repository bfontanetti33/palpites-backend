# CONTEXT — Palpites da IA (Copa 2026)

> Documento único de contexto para retomar o desenvolvimento em qualquer sessão.
> Atualizado: 2026-06-07 | Branch: main

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
│   │   └── schemas.py          # Pydantic models: Partida, RecomendacaoIA, EntradaForma, etc.
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
│   └── cache_partidas.json     # Cache disco de partidas computadas
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

**Calibração:** `ALPHA_REG = 0.5` (provisório, conservador pré-Copa). Recalibrar após fase de grupos 2026 via `calibrar_alpha_backtest.py`.

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
    ├─ Cache hit (static_cache, todos componentes frescos)? → Retorna <100ms, zero API
    │
    └─ Cache miss parcial ou total → football_agent.buscar_detalhe_partida()
            │
            ├─ API-Football /teams/statistics      (stats históricas — NÃO é fonte de cartões)
            ├─ API-Football /fixtures?team&last=20  (forma recente — inclui amistosos ✅)
            │        ├─ /fixtures/statistics por fixture → cartões amarelos/vermelhos por jogo ✅
            │        └─ FALLBACK: forma_recente_seed.json se API retornar vazio ✅
            ├─ API-Football /fixtures/headtohead   (H2H; frequentemente vazio)
            ├─ API-Football /fixtures?id=           (árbitro — coletado mas NÃO passado ao Claude)
            ├─ API-Football /fixtures/statistics    (escanteios — últimos 5 jogos)
            └─ The Odds API (soccer_fifa_world_cup) (odds 1X2; over/under ainda sem cobertura)
                    │
                    └─ ia_agent.gerar_recomendacao()
                            │
                            ├─ C1 → C2 → C3 → C4 → C4B → C5 (Claude)
                            │
                            └─ Salva em static_cache (disco) + _partida_cache (RAM)
```

---

## 7. Sistema de Cache — TTL Tiered por Componente (Fase 3)

### Camadas

| Camada | Onde | TTL | Slots | Uso |
|--------|------|-----|-------|-----|
| `_cache` | RAM (TTLCache) | 8h | 400 | Respostas brutas API-Football |
| `_partida_cache` | RAM (TTLCache) | 8h | 72 | Objetos Partida completos |
| `odds_cache` | RAM (TTLCache) | 25h | 80 | Odds por slug |
| `football_api_cache.json` | Disco | 8h | ~5MB | Backup do `_cache` — sobrevive restart/redeploy |
| `cache_partidas.json` | Disco + git | tiered | ilimitado | Partidas + stats + narrativa |

### TTL por componente (static_cache.py — Fase 3)

| Componente | TTL | Gatilho de invalidade |
|-----------|-----|----------------------|
| team_stats | 168h (7 dias) | Competição terminada |
| forma | 72h | Time jogar novo jogo |
| h2h | 720h (30 dias) | Raramente muda |
| player_stats | 72h | Atualização de squad |
| narrativa | 8h | Stats mudarem |

**Resultado Fase 3:** 8.247 → 0 chamadas de API em cache hit (economia 100%). Cada componente rebusca somente quando stale — não no restart, não no deploy.

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

### Admin
| Endpoint | Descrição |
|----------|-----------|
| `GET /api/v1/admin/health-check` | Status completo (quota APIs, Supabase, erros 24h, vars_configuradas) |
| `GET /api/v1/admin/prewarm?dias=N` | Dispara prewarm em background |
| `GET /api/v1/admin/validar-semana` | Valida 24 jogos semana 1 |
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

## 11. Comportamento de Dados — Decisões e Armadilhas Conhecidas

### `_stats_time` — cascata de Copa do Mundo (bug parcialmente corrigido)
`_stats_time` tenta competições em cascata: Copa 2022 → Copa 2018 → Copa 2014 → Copa 2010 → AFCON → Euro → etc. Para na **primeira com `jogos > 0`**. Times que participaram de Copas antigas (ex: África do Sul 2010 como anfitriã, Argélia 2014) caem nessas fontes com `media_amarelos=0.0` porque a API-Football não tem dados de cartões para 2010/2014.

**6 times afetados (18 entradas = 14% do cache):**
- Copa 2010: Africa do Sul, Nova Zelândia, Paraguai
- Copa 2014: Argélia, Bósnia & Herzegovina, Costa do Marfim

**Fix (Fase 4):** cartões agora derivados da forma recente via `/fixtures/statistics`. `_stats_time` não é mais fonte de cartões.

### `_forma_recente` — inclui amistosos ✅
`_EXCLUIR_LIGA` exclui apenas feminino, sub-17/20/21/23, olímpico. **"Friendlies" NÃO é excluído.** A forma pega amistosos corretamente — era hipótese falsa que haveria filtro de clube vazando.

### Árbitro — coletado mas nunca passado ao Claude
`_arbitro()` coleta dados e os guarda em `Partida.arbitro`, mas `_montar_prompt()` **nunca inclui o árbitro no prompt**. Se Claude mencionar "considerando o árbitro" na narrativa = **alucinação pura**. Fix A aplicado: `_SYSTEM` proíbe explicitamente.

### `media_amarelos = 0.0` vs `null`
Quando `_stats_time` encontra fonte antiga (2010/2014), o campo é `0.0` (float real), **não null**. Claude recebia `"South Africa: 0.0 cartões amarelos por jogo"` e usava o dado falso. Após Fase 4, o campo vem de `/fixtures/statistics` dos jogos recentes.

### Odds API — dois níveis de value_bets
O response de `/recomendacao` tem dois campos com value bets:
1. `value_bets[]` (via `_calcular_value_bets` — ia_agent.py): `prob_dc`, `prob_impl`, `edge`, `odd_ref`, `value_score`, `tem_value`
2. `odds_analise.value_bets[]` (via `odds_engine.py`): `prob_modelo`, `prob_consenso`, `z_score`, `confianca`, `sharp_confirma`

O frontend pode exibir "modelo X% vs mercado Y%" usando campos já existentes.

### Odds API — cobertura Copa 2026
- Esporte: `soccer_fifa_world_cup` (72 eventos disponíveis) ✅
- Mercados: `h2h` (1X2) disponível ✅
- Mercados `totals` (Over/Under) e `btts`: **sem cobertura** — `odd_ref` null no top3
- A chave local `.env` é a velha (free 500 req, esgotada). **Testes de odds = sempre via Railway** (chave nova 20k)

---

## 12. Variáveis de Ambiente

| Variável | Local .env | Railway | Descrição |
|----------|-----------|---------|-----------|
| `ANTHROPIC_API_KEY` | ✅ | ✅ | Narrativas Claude |
| `API_FOOTBALL_KEY` | ✅ | ✅ | Pro — 20k req/mês |
| `ODDS_API_KEY` | ✅ (velha/esgotada) | ✅ (nova, 20k) | The Odds API — usar Railway para testes |
| `PREMIUM_TOKEN` | ✅ | ✅ | Token fixo admin/bypass |
| `SUPABASE_URL` | ❌ ausente | ✅ | https://jwzvuixvuptazfyasmlm.supabase.co |
| `SUPABASE_KEY` | ❌ ausente | ✅ | Chave secret |
| `SUPABASE_JWT_SECRET` | ❌ ausente | ✅ | Verificação JWT usuários |
| `TELEGRAM_BOT_TOKEN` | ❌ ausente | ✅ | Bot palpitesdaia_monitor_bot |
| `TELEGRAM_CHAT_ID` | ❌ ausente | ✅ | 8802057413 |
| `ADMIN_TOKEN` | — | ⚠️ opcional | Protege endpoints admin |
| `SENTRY_DSN` | — | ⚠️ false | Rastreamento de erros |
| `MERCADOPAGO_ACCESS_TOKEN` | — | ⏳ pendente | Pagamentos |
| `MERCADOPAGO_WEBHOOK_SECRET` | — | ⏳ pendente | HMAC dos webhooks |

**Decisão de segurança:** Supabase/Telegram são serviços de produção — não copiar para `.env` local. Testes que precisam dessas vars rodam via Railway.

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

## 17. Estado Atual em Produção (2026-06-07)

### Métricas (health-check)
```
quota_api_football : 67.507 req restantes (plano Pro 20k/mês — boa margem)
quota_odds_api     : 18.824 créditos restantes (chave nova 20k)
jogos_em_cache     : 35
erros_24h          : 0
supabase           : conectado
telegram           : configurado
uptime_segundos    : 6.790 (no momento da verificação)
```

### Value bets testados em produção — Mexico × África do Sul
```
odds_disponiveis : True (25 casas no consensus Shin)
value_bets       : 3 itens
  Vitória Fora   → modelo 27.5% vs mercado 11.8% | edge +15.7pp | odd 8.49 | retorno +133.5%
  Empate         → modelo 27.2% vs mercado 22.0% | edge +5.2pp  | odd 4.55 | retorno +23.8%
  Vitória Casa   → modelo 45.3% vs mercado 69.9% | edge -24.6pp | odd 1.43 | retorno -35.2%
top3 (over/btts) : odd_ref null — mercados totals/btts sem cobertura na Odds API
```

**Nota sobre divergência México:** modelo diz 45%, mercado diz 70% de vitória para o México. Sinal de que o modelo subestima o favorito — confirma necessidade de recalibração pós-Copa (ALPHA_REG).

---

## 18. Fixes Implementados nesta Sessão (aguardando commit)

### Fix A — Anti-alucinação árbitro (`ia_agent.py`)
Adicionado bloco `ÁRBITRO — REGRA ANTI-INVENÇÃO` no `_SYSTEM`:
- Proíbe Claude de mencionar árbitro, juiz ou disciplina arbitral
- Árbitro é coletado mas **nunca incluído no prompt** — qualquer menção seria alucinação

### Fix C — Retry 429 em `players_agent.py`
`_api_get` agora tenta 3× com backoff exponencial (1s → 2s → 4s) antes de propagar o 429. Recupera jogadores como Kimmich/Goretzka quando a API está temporariamente sobrecarregada.

### Fase 4 — Cartões da mesma fonte da forma (`football_agent.py`, `schemas.py`)
- `EntradaForma` ganha `fixture_id`, `cartoes_amarelos`, `cartoes_vermelhos`
- Nova `_enriquecer_forma_com_cartoes()`: busca `/fixtures/statistics` por fixture, extrai cartões por time
- `_enriquecer_btts_over`: deriva `media_amarelos/vermelhos` dos jogos com dado (ignora jogos sem dado na média)
- `_stats_time`: zerada de responsabilidade sobre cartões (`media_amarelos=None`)
- Orquestração: `_get_forma_enriched` encadeia `_forma_recente` + `_enriquecer_forma_com_cartoes`
- **Quota:** `/fixtures/statistics` já era chamada por `_media_escanteios` (5 fixtures). Fase 4 aproveita cache — zero quota extra nos 5 mais recentes; até 5 fixtures adicionais para jogos 6-10 na forma.

---

## 19. Slugs — Semana 1 (Jun 11-17)

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

## 20. Roadmap

### Fase 1 — Dados reais ✅ COMPLETA
### Fase 2 — Agente IA + Monetização (88%)
- ✅ Modelo 5 camadas
- ✅ Cache inteligente 2 camadas
- ✅ Forma recente com fallback seed
- ✅ Fase 3: cache tiered por componente (economia 100% em hits)
- ✅ Fix A: anti-alucinação árbitro no _SYSTEM
- ✅ Fix C: retry 429 em players_agent
- ✅ Fase 4: cartões da mesma fonte da forma (aguardando commit)
- ⏳ Mercados totals/btts na Odds API (Over/Under, BTTS com odd real)
- ⏳ Recalibrar ALPHA_REG após fase de grupos (está 0.5 provisório)
- ⏳ Cache persistente entre deploys (cache-snapshot → commit)
- ⏳ Supabase no Lovable (login/cadastro real)
- ⏳ Mercado Pago funcional

### Fase 3 — Monitoramento (após lançamento)
- Sentry + UptimeRobot + backtest contínuo pós-Copa

### Fase 4 (produto) — Escala (futuro)
- Dataset próprio Copa 2026, modelo XGBoost, histórico de acertos rastreado

---

## 21. Comandos Úteis

```bash
# Pasta local do projeto (Windows)
cd "C:\Users\brunn\OneDrive\Documentos\CLAUDIO\Palpites_da_IA\palpites-backend"

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

# ATENÇÃO: testes que envolvem odds usam chave Railway (não a local, que está esgotada)
# Testar via: curl + PREMIUM_TOKEN, ou endpoint /api/v1/admin/odds-debug em produção
```

---

## 22. Próximas Ações Prioritárias

```
1. [AGORA] Revisar e commitar os 4 arquivos modificados:
   → Fix A (ia_agent.py), Fix C (players_agent.py), Fase 4 (football_agent.py, schemas.py)
   → Não rodar prewarm antes de aprovar o diff

2. [ALTA] Adicionar mercados totals/btts na busca de odds (odds_agent.py)
   → markets=h2h,totals — Over/Under e BTTS chegam com odd real
   → Permite top3 completo com value_score para Over/Under

3. [ALTA] Prewarm completo pós-commit
   → /admin/prewarm?dias=7 após merge
   → Verificar que 6 times afetados pelo bug de cartões estão corrigidos

4. [MÉDIA] Cache persistente entre deploys
   → /admin/cache-snapshot → seeds/cache_partidas.json → commit

5. [MÉDIA] Supabase no Lovable (login/cadastro real)

6. [MÉDIA] Mercado Pago — testar fluxo completo

7. Lançamento TikTok (Chi) — Copa começa 11/06/2026
```

---

## 23. Decisões Arquiteturais

**Por que seeds em vez de só API?**
API-Football tem limite diário e falha para seleções nacionais em alguns endpoints. Seeds garantem dados básicos sem custo. API enriquece quando disponível.

**Por que cache em disco (`cache_partidas.json`)?**
Railway usa containers efêmeros. Cache disco sobrevive a restarts dentro do mesmo deploy. Commitado no git, sobrevive a deploys também.

**Por que forma_recente_seed.json como fallback?**
`/fixtures?team&last=20` para seleções nacionais retorna vazio frequentemente. O seed cobre os últimos 10 jogos de cada seleção até mai/2026 e ativa automaticamente quando API retorna vazio.

**Por que cartões vêm da forma e não de `_stats_time`?**
`_stats_time` usa cascata Copa do Mundo — para na primeira edição com `jogos > 0`. Times que participaram de Copas antigas (2010/2014) recebiam `media_amarelos=0.0` porque a API não tem dados de cartões para jogos antigos. A forma recente (via `/fixtures/statistics`) usa os últimos 10 jogos de qualquer competição, garantindo dado atual e real.

**Por que árbitro não vai ao prompt do Claude?**
Decisão de design: árbitro é coletado e exposto via API (campo `Partida.arbitro`), mas `_montar_prompt` deliberadamente não o inclui — o dado pode ser "a confirmar" ou vir de média, o que causaria narrativas vagas. Claude gera texto melhor sem dado ruidoso.

**Por que ODDS_API_KEY local está diferente do Railway?**
A chave local é do plano free (500 req, esgotada). O Railway tem a chave do plano pago (20k). Decisão consciente: não copiar secrets de produção para ambiente local.
