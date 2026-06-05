# TASKS — Palpites da IA (Copa 2026)

> Atualizado: 2026-06-05
> Estado geral: **Backend estável em produção. Dados de forma corrigidos. Dados insuficientes sistêmicos em investigação.**

---

## ✅ CONCLUÍDO

### Infraestrutura
- [x] FastAPI deployado no Railway (região southamerica-east1)
- [x] Deploy automático via push para `main`
- [x] CORS configurado (lovable.app, lovableproject.com, palpitesdaia.com.br)
- [x] Rate limiting por IP (slowapi)
- [x] Sentry configurado (inicializa se `SENTRY_DSN` estiver presente)
- [x] Middleware de rastreamento de erros 500 com alerta Telegram
- [x] 2 workers uvicorn + keep-alive 30s

### Dados e Seeds
- [x] `seeds/copa_2026.json` — 72 jogos, 48 times, grupos completos
- [x] `seeds/squads_copa_2026.json` — elencos de 47/48 times
- [x] `seeds/forma_recente_seed.json` — forma real de 48 seleções (amistosos + eliminatórias até mai/2026)
- [x] `seeds/arbitros_copa_2026.json` — 52 árbitros com stats Copa 2022/2018
- [x] `seeds/cache_partidas.json` — cache persistente em disco (sobrevive deploy)

### Modelo de Predição (5 camadas)
- [x] **Camada 1** — Elo Rating + Pi Rating + FIFA Ranking (normalização regional)
- [x] **Camada 2** — Dixon-Coles modificado (modelo Poisson para lambdas de gols)
- [x] **Camada 3** — Shin odds (conversão implied prob com margem)
- [x] **Camada 4** — Contexto (home advantage, campo neutro, fadiga, rodada 1)
- [x] **Camada 4B** — Tail Risk Engine (fat tails, uncertainty index, barbell strategy)
- [x] **Camada 5** — Narrativa Claude (texto user-friendly em português brasileiro)
- [x] Fallback global por camada — nunca retorna 500

### Cache
- [x] Cache 2 camadas: `static_cache` (disco, 8h TTL) + `odds_cache` (memória, 25h TTL)
- [x] `_cache` TTLCache para respostas individuais da API-Football (8h, 400 entradas)
- [x] `_partida_cache` TTLCache para objetos Partida completos (8h, 72 entradas)
- [x] Cache persistente de API (`football_api_cache.json`) — restaura no startup sem gastar quota
- [x] Separação stats/narrativa com TTL independentes
- [x] Invalida stats+narrativa automaticamente quando novas odds chegam

### Cron Jobs (4 background tasks)
- [x] **Job 1** — Resumo diário Telegram (06h BRT)
- [x] **Job 2** — Odds tiered por proximidade: >12h=1×/dia, 2-12h=1×/hora, <2h=30min
- [x] **Job 3** — Healthcheck 15min (alerta Telegram se quota < 500)
- [x] **Job 4** — Prewarm stats 30min (pré-aquece todos os jogos dos próximos 14 dias)

### Endpoints Públicos
- [x] `GET /health` — status básico
- [x] `GET /api/v1/copa/jogos` — lista 72 jogos com probabilidades Elo nos cards
- [x] `GET /api/v1/copa/jogos/{slug}` — detalhe completo (forma, H2H, odds, árbitro)
- [x] `GET /api/v1/copa/zebras` — jogos onde azarão tem >35% chance (sem API)
- [x] `GET /api/v1/copa/bingo` — jogos com under 2.5 e BTTS alinhados
- [x] `GET /api/v1/copa/odds-baixa` — value bets com odd > 2.0 e prob modelo > 40%

### Endpoint Premium
- [x] `GET /api/v1/copa/jogos/{slug}/recomendacao` — análise completa 5 camadas + narrativa Claude
- [x] Auth dual: PREMIUM_TOKEN fixo (admin) + JWT Supabase (usuário premium/avulso)
- [x] Nunca retorna 500 — fallback por camada

### Admin Endpoints
- [x] `GET /api/v1/admin/health-check` — status completo (quota APIs, Supabase, Telegram, erros 24h)
- [x] `GET /api/v1/admin/prewarm?dias=N` — dispara prewarm em background, retorna imediatamente
- [x] `GET /api/v1/admin/validar-semana` — valida 24 jogos semana 1 (sem chamadas API, instantâneo)
- [x] `GET /api/v1/admin/cache-snapshot` — exporta cache_partidas.json para versionamento
- [x] `GET /api/v1/admin/odds-debug` — testa conexão Odds API
- [x] `GET /api/v1/admin/acuracia` — lê historico_predicoes.json para backtesting
- [x] `GET /api/v1/admin/stats` — métricas gerais de uso
- [x] Telegram test, status, resumo

### Integrações Externas
- [x] API-Football v3 (Pro plan, 20k req/mês) — com rate limit 2s + retry 429
- [x] The Odds API — odds Copa 2026, 72 eventos, ~200 req/mês
- [x] Anthropic Claude API — narrativas (SDK 0.105.2)
- [x] Supabase — auth JWT + status ping
- [x] Telegram Bot — alertas de erro e resumos diários
- [x] MercadoPago — webhook configurado

### Qualidade e Operação
- [x] Forma recente: API-Football com fallback automático para seed local
- [x] Logging estruturado em todos os agentes (warnings de API vazia, 429, etc.)
- [x] Rate limiting API-Football: 2s mínimo entre chamadas reais + retry automático em 429
- [x] Quota preservada em redeploys via `football_api_cache.json` (disco)
- [x] Prewarm não-bloqueante (asyncio.create_task) — endpoint retorna em <1s
- [x] Scripts: backtest, registrar_resultado, prewarm_primeira_semana

---

## ❌ PROBLEMA ATIVO — Alta Prioridade

### `dados_insuficientes=True` sistêmico
- **Causa:** A flag é True quando `stats_casa.dados_insuficientes OR stats_fora.dados_insuficientes` — e as stats de `/teams/statistics` da API-Football falham para **todas** as seleções nacionais (times nacionais não têm stats de temporada no formato de clubes).
- **Impacto:** Todos os 24 jogos da semana 1 aparecem como "incompleto" no validador, mesmo com forma e odds corretos. O modelo ainda gera probabilidades via Elo, mas a flag polui os logs e a UX.
- **Fix sugerido:** Separar `dados_insuficientes` em dois flags: `sem_forma` (bloqueia modelo) e `sem_stats_api` (não bloqueia — usa Elo fallback). OU: mudar a condição para só ser True quando forma também estiver vazia.

### H2H vazio para todos os jogos
- **Causa:** A chamada `/fixtures/headtohead` retorna vazio para muitos confrontos entre seleções nacionais que raramente se enfrentam.
- **Impacto:** `h2h_count=0` em todos os 24 jogos. O modelo usa `confianca_h2h=0.85` de fallback mas perde contexto real.
- **Fix sugerido:** Criar `seeds/h2h_seed.json` com confrontos históricos Copa do Mundo (dados públicos do Wikipedia/FIFA). Formato igual ao `forma_recente_seed.json`.

---

## ⚠️ PENDENTE — Média Prioridade

### Dados
- [ ] Odds ausentes para **Australia × Türkiye** e **Portugal × Congo DR** — investigar se a Odds API não cobre esses confrontos ou se é timing
- [ ] Commit de `cache_partidas.json` populado no git após prewarm completo — hoje o arquivo no git é `{}`, então cada novo deploy começa do zero e gasta quota da API
- [ ] Seed H2H para os 24 jogos da semana 1 (eliminaria H2H vazio sistêmico)

### Modelo
- [ ] Modelo discorda das odds para Canada × Bosnia, Brazil × Morocco, Spain × Cape Verde — investigar se é bug de calibração ou discrepância real aceitável
- [ ] Validar dados de times pequenos: Curaçao, Jordan, Congo DR, Cape Verde, Uzbekistan — podem ter IDs errados no seed ou dados inexistentes na API

### Frontend / Produto
- [ ] Supabase configurado no Lovable (frontend ainda não usa auth real)
- [ ] MercadoPago — testar fluxo completo de pagamento em produção
- [ ] Lovable: conectar endpoint `/recomendacao` atrás de paywall real

---

## ⏳ BACKLOG — Baixa Prioridade

### Backtesting e Acurácia
- [ ] Registrar resultados reais após cada jogo (script `scripts/registrar_resultado.py` pronto)
- [ ] Popular `seeds/historico_predicoes.json` — hoje retorna `total_jogos: 0`
- [ ] Calibração do modelo via backtesting Copa 2022/2018 (`scripts/backtest_copa.py` pronto)

### Infraestrutura
- [ ] Railway volume mount para cache persistente entre deploys (alternativa a commitar JSON)
- [ ] CI/CD: testes automatizados antes do deploy
- [ ] Endpoint `/api/v1/copa/jogos/{slug}/recomendacao` — testar fluxo completo com usuário premium real

### Produto
- [ ] Segunda semana Copa 2026 (jogos 18-48) — validar cobertura após semana 1 rodar
- [ ] Arbitragem de odds (comparar múltiplos bookmakers para value bets mais precisos)
- [ ] Página de performance pública — mostra acertos históricos do modelo para vender o produto
