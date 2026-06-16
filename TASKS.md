# TASKS — Palpites da IA (Copa 2026)

> Atualizado: 2026-06-15 | HEAD: `badd350` | Copa em andamento (Rodada 2)

---

## ✅ CONCLUÍDO

### Infraestrutura
- [x] FastAPI deployado no Railway (southamerica-east1)
- [x] Deploy automático via push para `main`
- [x] CORS, Rate limiting, Sentry (opcional), 2 workers uvicorn
- [x] Middleware de rastreamento erros 500 + alerta Telegram
- [x] ADMIN_TOKEN protegendo /admin/*

### Dados e Seeds
- [x] `seeds/copa_2026.json` — 72 jogos, 48 times, grupos
- [x] `seeds/squads_copa_2026.json` — 47/48 times
- [x] `seeds/forma_recente_seed.json` — 48 seleções até mai/2026
- [x] `seeds/arbitros_copa_2026.json` — 52 árbitros
- [x] `seeds/cache_partidas.json` — 72/72 jogos com stats (commit 2b0e0b8)

### Modelo Estatístico (5 camadas)
- [x] Camadas 1–5 com fallback por camada
- [x] Elo TSV eloratings.net (auditado 07/06, 48 times)
- [x] Rating 58/32/10 (auditado, não normalizar)
- [x] Palpite 1X2 puro (fix linha 601 ia_agent.py)
- [x] Filtros A+B (sem false value no favorito)
- [x] Roteamento zebra/valor (is_value_pick, is_zebra)
- [x] Home advantage anfitrião-fora

### Odds Pipeline
- [x] h2h (1X2): bookmaker preferido
- [x] totals (Over/Under): consenso mediana, N_CASAS_MIN=3 (commit 120bcf1)
- [x] btts: consenso mediana, N_CASAS_MIN=3, nunca 1 casa (commit 120bcf1)

### Cache
- [x] Cache 2 camadas: static_cache + odds_cache
- [x] TTL tiered por componente
- [x] Cache persistente football_api_cache.json (sobrevive restart/deploy)
- [x] Invalida stats+narrativa quando novas odds chegam
- [x] **Vary: Authorization** em todas as respostas (commit badd350)
- [x] **Autenticado → private, no-store** (nunca cacheia — premium dinâmico) (commit badd350)
- [x] **Anônimo → public, max-age=300** (era 4h, reduzido para evitar stale) (commit badd350)

### Endpoints
- [x] /copa/jogos, /copa/jogos/{slug}, /recomendacao
- [x] /usuario/assinatura (status premium do usuário logado)
- [x] /copa/zebras, /bingo, /odds-baixa (temporariamente vazios)
- [x] /admin/* (health-check, prewarm, validar-semana, telegram-status, etc.)
- [x] 12 JOGOS_LIBERADOS sem auth em /recomendacao e detalhe
- [x] **/webhooks/kiwify** — Kiwify HMAC-SHA1, product_id → plano, acumulação premium (sessão 5)

### Auth e Pagamentos
- [x] `verify_jwt_token` — HS256 + ES256/RS256 via JWKS
- [x] `get_user_premium_status` — fail-closed, verificação temporal
- [x] `set_premium` / `add_avulso_credit` / `deduct_avulso_credit` / `get_user_id_by_email`
- [x] JOGOS_LIBERADOS bypass auth (commit f092558)
- [x] **Mercado Pago** — webhook fail-closed HMAC-SHA256, 3 planos, /criar-preferencia (commit cb1c62b)
- [x] **CPF obrigatório em /criar-preferencia** (400 se ausente — previne rejeições MP) (commit 7f60d79)
- [x] **Kiwify** — webhook completo (commits c99413d → 7623df1):
  - HMAC-SHA1 com `?signature=` query param
  - Eventos: order_approved, subscription_renewed
  - 3 product_ids mapeados (avulso/semanal/mensal) — confirmados em compras reais
  - TrackingParameters.src como email primário (evita mismatch)
  - Fallback avulso para product_id desconhecido sem Subscription
  - Alerta Telegram quando usuário não encontrado
- [x] **Janela de datas premium** — detalhe + recomendacao verificam horário do jogo vs. premium_until (commit 09d1c42)
- [x] **Lista personalizada /copa/jogos** — palpites zerados e bloqueado=True para jogos fora da janela (commit a695e8a)
- [x] Acumulação premium: `base = max(now_utc, current_until)` — nunca reseta plano ativo (ambos gateways)
- [x] SUPABASE_JWT_SECRET + MERCADOPAGO_ACCESS_TOKEN + MERCADOPAGO_WEBHOOK_SECRET no Railway
- [x] KIWIFY_WEBHOOK_TOKEN no Railway

### Qualidade
- [x] Prewarm Fix A: warm-up 10s antes do jogo 1
- [x] Prewarm Fix B: retry 5× backoff 16s em _api_get
- [x] Forma recente com fallback seed + fixture_id para cartões
- [x] Cirurgias 1 e 2: jogadores e cartões recuperados

---

## ⚠️ PENDENTE — Alta Prioridade

### Fix Lovable (Frontend) — JWT

> Root cause diagnosticado pelos DIAG logs. Fix necessário no Lovable (frontend).

- [ ] **JWT timing**: aguardar `supabase.auth.getSession()` ANTES do primeiro fetch de `/copa/jogos`
  - Sintoma: primeiro load chega como AUSENTE (anon) → jogos bloqueados até hard refresh
  - Fix: listener `onAuthStateChange` → re-fetch quando sessão aparecer
  - Fix: `getSession()` antes de CADA chamada autenticada (renova token ES256 expirado)

- [ ] **JWT ES256 expirado**: token Supabase expira após 1h — `JWTError ES256 — Signature has expired`
  - Fix: chamar `supabase.auth.getSession()` imediatamente antes de montar o header `Authorization`
  - `getSession()` renova automaticamente, mas só se chamado no momento do request

- [ ] **Investigar wilsonchiade61@gmail.com** — ainda chegando como AUSENTE após hard refresh
  - Possível JS cache antigo (service worker?) ou versão Lovable diferente
  - Verificar se resolveu com o fix JWT timing acima

### Fix Lovable (Frontend) — UX Avulso

- [ ] **Banner crédito avulso**: após compra, mostrar "Você tem N análise(s) avulsa(s) disponíveis! Clique em qualquer jogo para usar."
  - Frontend deve ler `avulso_credits` de `/usuario/assinatura` e exibir banner
  - Atualmente o frontend não exibe feedback após compra avulsa (UX confusa)

### Diagnóstico / Investigação

- [ ] **Investigar josin-7@outlook.com 403s** — spain-cape-verde-islands e belgium-egypt retornando 403
  - premium_until=2026-07-15T15:15 UTC — verificar se são jogos dentro ou fora da janela
  - Confirmar se é bug de janela de datas ou jogo não liberado por outro motivo

- [ ] **Confirmar product_ids Kiwify SEMANAL e MENSAL** em compra real
  - IDs atuais (7f8404a0, 7de8c0a0) vieram de URL de redirect — provavelmente corretos
  - Primeira venda real de cada plano vai logar o product_id — comparar com mapeado

### DIAG logs (remover após confirmar Lovable OK)

- [ ] **Remover DIAG logs de partidas.py** — `[DIAG] /copa/jogos token=...`
- [ ] **Remover DIAG log de mercadopago_webhook.py** — `criar_preferencia [DIAG]: cpf=...`

---

## ⏳ BACKLOG — Média Prioridade

- [ ] **Stash Fase 2 jogadores**: `stash@{0} fase2-jogadores-8campos-crus-e-selecao`
  - Adicionar `MAX_APARECOES_POR_JOGADOR=2` em `selecionar_destaques`
  - `git stash pop`, compilar, commitar
  - Regenerar seeds/cache_partidas.json para 3 jogos (novos 8 campos)

- [ ] **Encoding slugs Türkiye/Congo DR** — 6 jogos sem odds (caracteres especiais no slug)

- [ ] **ADMIN_TOKEN**: trocar se aparecer em canais públicos novamente

---

## ⏳ BACKLOG — Baixa Prioridade

### Dados e modelo
- [ ] Registrar resultados reais após cada jogo (`scripts/registrar_resultado.py` pronto)
- [ ] Recalibrar `ALPHA_REG` após fase de grupos (0.5 provisório, subestima favoritos)
- [ ] `seeds/h2h_seed.json` — confrontos históricos Copa (muitos H2H vazios)
- [ ] Fix definitivo `_forma_do_seed` sem fixture_id (cartões None quando API falha)

### Produto
- [ ] Validar cobertura fase de grupos à medida que jogos são disputados
- [ ] "Insights da IA" — usar 8 campos Fase 2 para texto contextual nos cards
- [ ] Página de performance pública — acertos históricos do modelo
- [ ] Prewarm periódico durante a Copa (`/admin/prewarm?dias=14` — idempotente)

### Monitoramento
- [ ] Sentry DSN real no Railway (SENTRY_DSN atualmente não configurado)
- [ ] UptimeRobot para `/health`

### Limpeza
- [ ] Scripts diagnóstico: `diag_*.py`, `test_seasons*.py`, `coverage_check.py`, `count_leagues.py`
- [ ] Backups temporários: `seeds/cache_partidas.antes_cirurgia*.json`, `*.backup*.json`
- [ ] Scripts `scripts/_*.py` (check, find, fire, validate)
- [ ] seeds/cache_partidas.json local tem Vini×4 — **NÃO commitar sem fix**
