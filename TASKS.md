# TASKS — Palpites da IA (Copa 2026)

> Atualizado: 2026-06-07 (sessão 3)
> Estado geral: **Backend estável. Cache 72/72 jogos commitado no git. Fix A+B (prewarm + retry) no código mas não commitados ainda.**

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
- [x] `seeds/cache_partidas.json` — 72/72 jogos com stats, commitado em git (commit 5191469)

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
- [x] Prewarm Fix A: warm-up `asyncio.sleep(10)` antes do jogo 1 (evita cold-start burst 429)
- [x] Prewarm Fix B: `_api_get` retry `range(5)` com backoff até 16s (players_agent.py)
- [x] Cirurgia 1: 9 jogadores recuperados (australia-türkiye, canada-bosnia, south-korea-czech)
- [x] Cirurgia 2: cartões recuperados — NZ media_amarelos=1.25, Ivory Coast=0.89
- [x] Cache 72/72 persistido no git — copa completa validada

---

## ⚠️ PROBLEMAS CONHECIDOS — Sem Fix Ativo

### `dados_insuficientes=True` sistêmico
- **Causa:** A flag é True quando `stats_casa.dados_insuficientes OR stats_fora.dados_insuficientes` — e as stats de `/teams/statistics` da API-Football falham para **todas** as seleções nacionais.
- **Impacto:** Jogos aparecem como "incompleto" no validador, mesmo com forma e odds corretos. Modelo usa Elo fallback.
- **Fix sugerido:** Separar flag em `sem_forma` (bloqueia modelo) e `sem_stats_api` (não bloqueia).

### H2H vazio para muitos jogos
- **Causa:** `/fixtures/headtohead` retorna vazio para confrontos raros entre seleções nacionais.
- **Impacto:** `h2h_count=0`. Modelo usa `confianca_h2h=0.85` de fallback.
- **Fix sugerido:** `seeds/h2h_seed.json` com confrontos históricos Copa do Mundo (Wikipedia/FIFA).

### `_forma_do_seed` não tem `fixture_id`
- **Causa:** Quando API retorna 0 fixtures para um time, `_forma_do_seed` cria `EntradaForma` sem `fixture_id`. `_enriquecer_forma_com_cartoes` pula todas as entradas → `media_amarelos=None`.
- **Impacto:** Times que caem no fallback seed têm cartões None mesmo que a API tenha dados. Resolvido temporariamente via cirurgias (re-fetch dos jogos afetados), mas pode reaparecer em novos jogos se a API falhar.
- **Fix definitivo:** `_forma_do_seed` buscar fixture IDs via `/fixtures?team={id}&date={data}` ou manter lista de fixture IDs no seed.

---

## ⚠️ PENDENTE — Alta Prioridade

### Código
- [ ] **Commitar Fix A+B** — `scripts/prewarm_copa2026.py` e `app/agents/players_agent.py` modificados mas não commitados
  ```
  git add app/agents/players_agent.py scripts/prewarm_copa2026.py
  git commit -m "fix: prewarm warm-up 10s + retry 5x backoff 16s (resolve cold-start burst)"
  git push origin main
  ```

### Dados
- [ ] Odds ausentes para **Australia × Türkiye** e **Portugal × Congo DR** — investigar cobertura na Odds API
- [ ] Mercados `totals` e `btts` na busca de odds (`odds_agent.py`: `markets=h2h,totals`) — Over/Under e BTTS com odd real para top3 completo
- [ ] Seed H2H — `seeds/h2h_seed.json` para jogos com H2H vazio

### Frontend / Produto
- [ ] Supabase configurado no Lovable (frontend ainda não usa auth real)
- [ ] MercadoPago — configurar vars Railway + testar fluxo completo (Pix + cartão)
- [ ] Lovable: conectar endpoint `/recomendacao` atrás de paywall real

---

## ⏳ BACKLOG — Baixa Prioridade

### Backtesting e Acurácia
- [ ] Registrar resultados reais após cada jogo (script `scripts/registrar_resultado.py` pronto)
- [ ] Popular `seeds/historico_predicoes.json` — hoje retorna `total_jogos: 0`
- [ ] Recalibrar `ALPHA_REG` após fase de grupos (está 0.5 provisório — modelo subestima favoritos)
- [ ] Calibração do modelo via backtesting Copa 2022/2018 (`scripts/backtest_copa.py` pronto)

### Infraestrutura
- [ ] CI/CD: testes automatizados antes do deploy
- [ ] Endpoint `/api/v1/copa/jogos/{slug}/recomendacao` — testar fluxo completo com usuário premium real
- [ ] Fix definitivo `_forma_do_seed` sem `fixture_id` (ver Problemas Conhecidos)

### Produto
- [ ] Validar cobertura fase de grupos completa após Copa começar (11/06)
- [ ] Arbitragem de odds (comparar múltiplos bookmakers para value bets mais precisos)
- [ ] Página de performance pública — mostra acertos históricos do modelo
- [ ] Limpar scripts temporários de diagnóstico: `scripts/_check_9players.py`, `scripts/_find_team_ids.py`, `scripts/_inspect_forma_cartoes.py`, `scripts/_test_cards_*.py`
- [ ] Limpar backups temporários: `seeds/cache_partidas.antes_cirurgia*.json`, `seeds/cache_partidas.backup*.json`
