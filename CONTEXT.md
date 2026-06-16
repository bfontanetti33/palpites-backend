# CONTEXT — Palpites da IA (Copa 2026)

> Documento único de contexto. Atualizado: 2026-06-15 (Copa em andamento — Rodada 2)
> Branch: main | HEAD: `badd350` | Supersede: CONTEXT_PALPITES_DA_IA.md (snapshot 08/06)

---

## 1. O Produto

**Palpites da IA** — análise estatística de apostas esportivas para Copa do Mundo 2026. Modelo de IA 5 camadas, palpites em português acessível, honestidade intelectual.

| | |
|--|--|
| **Frontend** | https://palpitesdaia.com.br (também magic-guess-stream.lovable.app) |
| **Backend** | https://palpites-backend-production.up.railway.app |
| **GitHub Frontend** | github.com/bfontanetti33/palpitesdaia |
| **GitHub Backend** | github.com/bfontanetti33/palpites-backend |
| **Dono** | Brunno Fontanetti (bfontanetti33) |
| **Sócio** | Chi — publicidade/marketing, TikTok @palpitesdaia (~20k seguidores) |
| **Diferencial** | Modelo robusto + linguagem acessível + sem "78% de acerto" inventado |

---

## 2. Stack Técnica

| Camada | Tecnologia | Detalhe |
|--------|-----------|---------|
| Frontend | React, TanStack, Tailwind | Lovable Cloud (CI/CD automático via GitHub) |
| Backend | Python 3.11, FastAPI 0.111 | Uvicorn 2 workers |
| Deploy Backend | Railway | Região southamerica-east1 (São Paulo) |
| Banco de dados | Supabase | jwzvuixvuptazfyasmlm.supabase.co |
| Domínio | palpitesdaia.com.br | Registro.br |
| Email | Resend | contato@palpitesdaia.com.br |
| AI narrativa | Anthropic Claude SDK | claude-sonnet-4-6, timeout 45s |
| Auth JWT | python-jose 3.5.0 | Verifica tokens Supabase Auth (HS256 + ES256/RS256 via JWKS) |
| Cache | cachetools TTLCache 5.3.3 | |
| Rate limit | slowapi 0.1.9 | |
| HTTP client | httpx 0.27.0 | |

---

## 3. Estrutura de Arquivos

```
palpites-backend/
├── app/
│   ├── agents/
│   │   ├── football_agent.py   # Busca dados API-Football; seed fallback para forma
│   │   ├── ia_agent.py         # Pipeline 5 camadas + narrativa Claude
│   │   ├── odds_agent.py       # The Odds API — h2h + totals + btts (consenso)
│   │   ├── odds_engine.py      # Shin Method + z-score + value bet detection
│   │   └── players_agent.py    # Jogadores de destaque dos elencos
│   ├── auth/
│   │   └── supabase_client.py  # JWT verification + premium status + usage log
│   │                           # Funções: verify_jwt_token, get_user_premium_status,
│   │                           # set_premium, add_avulso_credit, deduct_avulso_credit,
│   │                           # get_user_id_by_email, register_usage
│   ├── cache/
│   │   ├── static_cache.py     # Cache disco (cache_partidas.json) + TTL tiered
│   │   └── odds_cache.py       # Cache memória odds (TTLCache 25h, 80 slots)
│   ├── models/
│   │   └── schemas.py          # Pydantic models: Partida, RecomendacaoIA, etc.
│   ├── monitoring/
│   │   ├── cron_jobs.py        # 4 background tasks asyncio
│   │   └── telegram_bot.py     # Alertas Telegram + estado global + send_telegram()
│   ├── payments/
│   │   ├── mercadopago_webhook.py  # Webhook MP (HMAC-SHA256) + /criar-preferencia
│   │   │                           # Acumulação premium: base = max(now, current_until)
│   │   │                           # CPF obrigatório (400 se ausente)
│   │   │                           # DIAG log temporário em criar_preferencia
│   │   └── kiwify_webhook.py       # Webhook Kiwify (HMAC-SHA1, ?signature=)
│   │                               # Product IDs mapeados (semanal/mensal/avulso)
│   │                               # TrackingParameters.src como email primário
│   └── routes/
│       ├── partidas.py         # Endpoints públicos, premium, assinatura
│       │                       # /copa/jogos personaliza palpite por usuário (janela premium)
│       │                       # Cache: Vary: Authorization, auth=no-store, anon=max-age=300
│       │                       # DIAG log temporário para diagnóstico JWT
│       └── admin.py            # Endpoints administrativos
├── seeds/
│   ├── copa_2026.json          # 72 jogos, 48 times, grupos (fonte da verdade)
│   ├── forma_recente_seed.json # Forma real de 48 seleções (até mai/2026) ← FALLBACK ATIVO
│   ├── squads_copa_2026.json   # Elencos 47/48 times (Curaçao sem dados)
│   ├── arbitros_copa_2026.json # 52 árbitros com stats Copa 2022/2018
│   └── cache_partidas.json     # ⚠️  MODIFICADO localmente — NÃO commitar (tem Vini×4)
├── scripts/
│   ├── prewarm_copa2026.py     # Prewarm manual (warm-up 10s + retry 5×)
│   ├── backtest_copa.py
│   └── registrar_resultado.py
├── docs/
│   ├── lovable_supabase_integration.md
│   ├── mercadopago_setup.md
│   └── backlog_dados_jogador.md
├── CONTEXT.md                  # Este arquivo (fonte da verdade)
├── TASKS.md                    # Lista de tarefas
└── requirements.txt
```

---

## 4. Modelo Estatístico — 5 Camadas

| # | Nome | Descrição |
|---|------|-----------|
| 1 | **Rating Dinâmico** | Elo 50% + Pi-rating 30% + FIFA Ranking 20%. Z-score regional. Decaimento: peso = 0.98^dias. Elo via eloratings.net TSV (validado 07/06). |
| 2 | **Dixon-Coles + Skellam** | Poisson aprimorado. Gera matriz de placares, prob 1X2, BTTS, Over/Under. |
| 3 | **Value Bet Detector** | Shin Method (remoção de margem), consensus ponderado, z-score. Só com odds reais. Filtros A+B: rejeita azarão-favorito (<25% vs >50% impl); edge mínimo gradual. |
| 4 | **Context Engine** | Home advantage (MEX×1.25+altitude, EUA×1.10, CAN×1.10), fadiga, rodada 1, zebra detector fator 2× Copa. |
| 4B | **Tail Risk (Taleb)** | 85% Dixon-Coles + 15% Student-t (ν=4). Fragility score. Uncertainty index. Barbell signal. |
| 5 | **Claude Narrativa** | claude-sonnet-4-6, AsyncAnthropic timeout 45s. PT-BR user-friendly. |

**Regra de ouro:** nunca retorna 500 — cada camada tem fallback independente.
**Calibração:** `ALPHA_REG = 0.5` (provisório). `ALPHA_PESOS = 58/32/10` (auditado 08/06 — não normalizar).

---

## 5. Fontes de Dados

| Fonte | Dados | Custo |
|-------|-------|-------|
| API-Football v3 (Pro) | Fixtures, H2H, forma recente, stats, jogadores | $19/mês |
| The Odds API | Odds reais (Pinnacle, 40+ casas) — h2h + totals + btts | $30/mês |
| Wikipedia | Squads, Elo ratings, FIFA Ranking | Grátis |
| seeds/copa_2026.json | 72 jogos fase de grupos (IDs oficiais) | Grátis |
| seeds/forma_recente_seed.json | Últimos 10 jogos de cada seleção (até mai/2026) | Grátis |
| Anthropic Claude | Narrativa PT-BR | ~$2/mês |

---

## 6. Pipeline de Dados

```
Usuário → /copa/jogos/{slug}/recomendacao
    │
    ├─ Cache hit? → Retorna <100ms, zero API
    │
    └─ Miss → football_agent.buscar_detalhe_partida()
            ├─ API-Football /teams/statistics      (stats históricas)
            ├─ API-Football /fixtures?team&last=20  (forma recente; fallback: seed)
            │        └─ /fixtures/statistics por fixture → cartões ✅
            ├─ API-Football /fixtures/headtohead   (H2H)
            ├─ API-Football /fixtures/statistics   (escanteios — últimos 5 jogos)
            └─ The Odds API buscar_odds_partida()
                    ├─ h2h (1X2): bookmaker preferido (Pinnacle > Bet365 > ...)
                    ├─ totals (Over/Under): consenso mediana, min N_CASAS_MIN_TOTALS=3
                    └─ btts: consenso mediana, min N_CASAS_MIN_BTTS=3
                            │
                            └─ ia_agent.gerar_recomendacao()
                                    └─ C1 → C2 → C3 → C4 → C4B → C5 (Claude)
```

---

## 7. Sistema de Cache — TTL Tiered

| Camada | Onde | TTL | Uso |
|--------|------|-----|-----|
| `_cache` | RAM (TTLCache) | 8h | Respostas brutas API-Football |
| `_partida_cache` | RAM (TTLCache) | 8h | Objetos Partida completos |
| `odds_cache` | RAM (TTLCache) | 25h | Odds por slug |
| `football_api_cache.json` | Disco | 8h | Backup do `_cache` — sobrevive restart/redeploy |
| `cache_partidas.json` | Disco + git | tiered | Partidas + stats + narrativa |

**TTL por componente (static_cache.py):**

| Componente | TTL |
|-----------|-----|
| team_stats | 168h (7 dias) |
| forma | 72h |
| h2h | 720h (30 dias) |
| player_stats | 72h |
| narrativa | 8h |

---

## 8. Endpoints

### Públicos (sem auth)
| Endpoint | Rate limit | Descrição |
|----------|-----------|-----------|
| `GET /health` | — | Status básico |
| `GET /api/v1/copa/jogos` | 60/min | Lista 72 jogos — personaliza palpite/bloqueado por usuário se JWT presente |
| `GET /api/v1/copa/jogos/{slug}` | 20/min | Detalhe completo (JOGOS_LIBERADOS acessíveis sem login) |
| `GET /api/v1/copa/zebras` | 30/min | Azarões com embasamento estatístico |
| `GET /api/v1/copa/bingo` | 30/min | Acumulada: under 2.5 + BTTS alinhados |
| `GET /api/v1/copa/odds-baixa` | 30/min | Value bets: odd > 2.0 + prob modelo > 40% |

### Premium (Bearer JWT ou PREMIUM_TOKEN)
| Endpoint | Rate limit | Descrição |
|----------|-----------|-----------|
| `GET /api/v1/copa/jogos/{slug}/recomendacao` | 5/min | Análise completa 5 camadas + narrativa. JOGOS_LIBERADOS sem auth. |
| `GET /api/v1/usuario/assinatura` | 30/min | Status premium/créditos do usuário logado |

### Admin (ADMIN_TOKEN)
| Endpoint | Descrição |
|----------|-----------|
| `GET /api/v1/admin/health-check` | Status completo (quota, Supabase, erros 24h, vars) |
| `GET /api/v1/admin/prewarm?dias=N` | Dispara prewarm em background |
| `GET /api/v1/admin/validar-semana` | Valida jogos semana 1 |
| `GET /api/v1/admin/cache-snapshot` | Exporta cache_partidas.json |
| `GET /api/v1/admin/odds-debug` | Testa Odds API |
| `GET /api/v1/admin/acuracia` | Métricas de acerto |
| `GET /api/v1/admin/stats` | Métricas gerais de uso |
| `GET /api/v1/admin/telegram-status` | Mensagem go-live + estado |

### Pagamentos
| Endpoint | Descrição |
|----------|-----------|
| `POST /api/v1/webhooks/mercadopago` | Recebe eventos MP (HMAC-SHA256 fail-closed) |
| `POST /api/v1/pagamentos/criar-preferencia` | Cria preference Checkout Pro MP |
| `POST /api/v1/webhooks/kiwify` | Recebe eventos Kiwify (HMAC-SHA1 via ?signature=) |

---

## 9. JOGOS_LIBERADOS — Acesso Gratuito Permanente

```python
JOGOS_LIBERADOS: frozenset = {
    "mexico-south-africa",
    "brazil-morocco",
    "south-korea-czech-republic",
    "usa-paraguay",
    "canada-bosnia-and-herzegovina",
    "qatar-switzerland",
    "haiti-scotland",
    "australia-türkiye",
    "germany-curaçao",
    "netherlands-japan",
    "ivory-coast-ecuador",
    "sweden-tunisia",
}
```

- 12 slugs têm `/recomendacao` e lista acessíveis **sem login**.
- Jogos fora da lista exigem JWT + premium ativo dentro da janela de datas.

---

## 10. Cron Jobs (iniciam no startup)

| Job | Frequência | Função |
|-----|-----------|--------|
| cache_diario | 1×/dia (06h BRT) | Resumo Telegram com estado do cache |
| odds_tiered | tick 30min | Atualiza odds por proximidade do jogo |
| prewarm_stats | tick 30min | Pré-aquece stats próximos 14 dias |
| healthcheck | 15min | Alerta Telegram se quota < 500 |

---

## 11. Critérios Zebra e Bingo

### Zebra
- `value_score > 0.15` E `z_score > 1.96` E `odds_disponiveis=True`
- `prob_modelo azarão > 25%` + ao menos 1 evidência concreta
- Fator 2× Copa; sharp money contra → rejeita
- Flag `is_zebra = True` no value_bet (via ia_agent.py roteamento)

### Bingo
- `prob_modelo > 60%` E `fair_odd > 1.30` E `value_score >= 0`
- Mercados permitidos: Over 1.5/2.5, BTTS Sim, Vitória favorito, Chance Dupla
- 3–5 jogos diferentes, odd total 2.0–8.0
- Rejeita: `uncertainty_index > 70`, `odds_disponiveis=False`

---

## 12. Odds API — Cobertura e Comportamento

### Esporte: `soccer_fifa_world_cup` — 72 eventos ✅

### Mercados e estratégia (odds_agent.py — commit 120bcf1):

| Mercado | Fonte | Mínimo |
|---------|-------|--------|
| h2h (1X2) | Bookmaker preferido (Pinnacle > Bet365 > ...) | — |
| totals (Over/Under) | **Consenso mediana** de TODOS os bookmakers | `N_CASAS_MIN_TOTALS = 3` |
| btts | **Consenso mediana** de TODOS os bookmakers | `N_CASAS_MIN_BTTS = 3` |

**Limitações**
- **6 jogos sem odds** (Türkiye/Congo DR) — encoding de slug com caracteres especiais.
- **ODDS_API_KEY local** = plano velha/esgotada. Testes de odds sempre via Railway.

---

## 13. Comportamento de Dados — Armadilhas Conhecidas

### `_stats_time` — cascata de Copa do Mundo
Para na primeira edição com `jogos > 0`. Times em Copas antigas (2010/2014) recebem `media_amarelos=0.0` da API (sem dados de cartões). 6 times afetados. Fix: cartões derivados da forma recente via `/fixtures/statistics`.

### `_forma_recente` — inclui amistosos ✅
`_EXCLUIR_LIGA` exclui feminino/sub/olímpico. Amistosos NÃO excluídos. Correto.

### Árbitro — nunca vai ao prompt do Claude
`Partida.arbitro` é preenchido, mas `_montar_prompt()` não o inclui. Se Claude mencionar árbitro = alucinação. Fix A no `_SYSTEM` proíbe.

### palpite_principal
Populado APENAS quando nenhum mercado passa os filtros A+B. Quando há value bet, `palpite_principal = None` e o front usa `top3[0]`.

---

## 14. Variáveis de Ambiente

| Variável | Local .env | Railway | Notas |
|----------|-----------|---------|-------|
| `ANTHROPIC_API_KEY` | ✅ | ✅ | |
| `API_FOOTBALL_KEY` | ✅ | ✅ | Pro — 20k req/mês |
| `ODDS_API_KEY` | ✅ (velha/esgotada) | ✅ (nova, 20k) | Sempre testar via Railway |
| `PREMIUM_TOKEN` | ✅ | ✅ | Admin override — **nunca embutir no frontend** |
| `ADMIN_TOKEN` | — | ✅ | Protege /admin/* |
| `SUPABASE_URL` | ❌ | ✅ | |
| `SUPABASE_KEY` | ❌ | ✅ | Service role key (bypassa RLS) |
| `SUPABASE_JWT_SECRET` | ❌ | ✅ | Para HS256; ES256 usa JWKS automático |
| `TELEGRAM_BOT_TOKEN` | ❌ | ✅ | palpitesdaia_monitor_bot |
| `TELEGRAM_CHAT_ID` | ❌ | ✅ | 8802057413 |
| `MERCADOPAGO_ACCESS_TOKEN` | — | ✅ | Produção ativa |
| `MERCADOPAGO_WEBHOOK_SECRET` | — | ✅ | HMAC-SHA256 fail-closed |
| `KIWIFY_WEBHOOK_TOKEN` | — | ✅ | HMAC-SHA1 — ver Railway |
| `SENTRY_DSN` | — | ⚠️ false | Opcional |

**CORS:** palpitesdaia.com.br, www.palpitesdaia.com.br, *.lovable.app, *.lovableproject.com, localhost:3000/5173

---

## 15. Supabase

- **URL:** https://jwzvuixvuptazfyasmlm.supabase.co
- **Tabelas:** `users` (id, email, is_premium, premium_until, avulso_credits) + `usage_log`
- **supabase_client.py** — funções:
  - `verify_jwt_token(token)` — suporta HS256 e ES256/RS256 via JWKS. Retorna None se inválido/expirado.
  - `get_user_premium_status(user_id)` — fail-closed (retorna False em erro). Verifica temporal.
  - `set_premium(user_id, iso_date, email)` — UPSERT com `resolution=merge-duplicates`
  - `add_avulso_credit(email)` / `deduct_avulso_credit(user_id)`
  - `get_user_id_by_email(email)` — busca na tabela `public.users` por email
  - `register_usage(user_id, slug)`

---

## 16. Monetização

| | |
|--|--|
| **Preços** | R$2,90/jogo (avulso) · R$6,90/semana · R$14,90/mês |
| **Paywall** | 12 jogos gratuitos permanentes; demais precisam de login + plano ativo |
| **Gateways** | Mercado Pago (Checkout Pro) + Kiwify (paralelo) |
| **Modelo** | Janela de datas: semanal=7d, mensal=30d, avulso=crédito único |
| **Break-even** | ~30 assinantes a R$14,90/mês |

### Planos MP (`_PLANOS` em mercadopago_webhook.py)
| Plano | Dias | Tipo | Preço |
|-------|------|------|-------|
| jogo/avulso | 1 | crédito | R$2,90 |
| semanal | 7 | premium | R$6,90 |
| mensal | 30 | premium | R$14,90 |

### Planos Kiwify (`_PRODUTOS` em kiwify_webhook.py)
| Product ID | Nome | Dias | Tipo |
|------------|------|------|------|
| `b83913d0-6865-11f1-a300-a796256126e9` | Análise Avulsa | 1 | crédito |
| `7f8404a0-6865-11f1-87c8-9f90b522aa21` | Semanal | 7 | premium |
| `7de8c0a0-6864-11f1-96d1-ebb444055bc7` | Mensal | 30 | premium |

### Links de checkout Kiwify
- Avulso: https://pay.kiwify.com.br/lT1XPYj
- Semanal: https://pay.kiwify.com.br/yXmTZiZ
- Mensal: https://pay.kiwify.com.br/z7xa8Gy

**Frontend DEVE gerar URL com `?src=encodeURIComponent(user.email)`** (email da conta logada) para casamento no webhook.

---

## 17. Custos Mensais

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

## 18. Sistema de Pagamentos — Fluxo Completo

### Mercado Pago (mercadopago_webhook.py)
1. Frontend chama `POST /pagamentos/criar-preferencia` com `{plano, email, cpf, device_id}`
   - CPF obrigatório (400 se ausente) — necessário para antifraude MP
2. Backend cria preference MP e retorna `init_point`
3. Usuário paga via Checkout Pro MP
4. MP dispara webhook `POST /webhooks/mercadopago` com HMAC-SHA256
5. Backend valida HMAC, busca pagamento via API MP, extrai `external_reference = "email|plano"`
6. Chama `set_premium` com acumulação: `base = max(now_utc, current_until)` + dias do plano

### Kiwify (kiwify_webhook.py)
1. Frontend gera URL: `https://pay.kiwify.com.br/{id}?src=email_conta_logada`
   - **Apenas se usuário logado** — não-logado vai para login primeiro
2. Usuário paga na Kiwify
3. Kiwify dispara `POST /webhooks/kiwify?signature=<hmac_sha1>`
4. Backend valida HMAC-SHA1 (`hmac.new(token, body, sha1)`)
5. Extrai email: `TrackingParameters.src` (prioritário) → `Customer.email` (fallback)
6. Se usuário não encontrado → alerta Telegram com order_id para resolução manual
7. Mapeia `Product.product_id` → plano → `set_premium` ou `add_avulso_credit`

### Acumulação de premium (ambos gateways)
```python
base = max(now_utc, current_until)  # nunca reseta premium ativo
premium_until = (base + timedelta(days=dias)).isoformat()
```

---

## 19. Personalização de Lista — /copa/jogos

O endpoint `GET /api/v1/copa/jogos` é dinâmico por usuário:

```
Token ausente (anon)  → todos os jogos fora de JOGOS_LIBERADOS com bloqueado=True
                         palpites zerados (segurança: DevTools não vê dados reais)

Token presente + JWT válido:
  → get_user_premium_status(user_id)
  → is_premium=True: jogos com horario <= premium_until ficam liberados
  → is_premium=False, avulso_credits>0: JOGOS_LIBERADOS + jogo_liberado=True
  → is_premium=False, sem crédito: mesma coisa que anon
```

**Campos zerados em jogos bloqueados (segurança):**
`insight_curto`, `favorito`, `prob_favorito`, `prob_vitoria_casa`, `prob_empate`, `prob_vitoria_fora`, `resumo_rapido`

**Cache (Vary: Authorization):**
- Autenticado: `private, no-store` (nunca cacheia — premium muda dinamicamente)
- Anônimo: `public, max-age=300` (5 min — era 4h, reduzido para evitar stale)
- `Vary: Authorization` em todas as respostas — separa cache de anon vs. autenticado

---

## 20. Verificação de Janela de Datas (detalhe + recomendacao)

```python
# fail-open: dúvida → libera (nunca bloqueia quem pagou)
if premium_until and user_id_auth != "admin":
    try:
        jogo_dt = datetime.fromisoformat(partida.horario)
        if jogo_dt.tzinfo is None:
            jogo_dt = jogo_dt.replace(tzinfo=timezone.utc)
        until_dt = datetime.fromisoformat(premium_until.replace("Z", "+00:00"))
        if jogo_dt > until_dt:
            raise HTTPException(403, "Jogo fora da sua janela premium.")
    except HTTPException:
        raise
    except Exception:
        pass  # qualquer erro de parse → libera
```

**Timezone:** Python compara aware datetimes normalizando para UTC. `horario` vem com offset -03:00 (Brasília), `premium_until` vem UTC +00:00 — comparação correta.

---

## 21. Diagnóstico JWT — Log Temporário Ativo

Em `partidas.py` há um log temporário de diagnóstico em `/copa/jogos`:

```python
# token=ok → loga email + is_premium + until
# token=INVALIDO → loga prefix do token (para debug)
# token=AUSENTE → loga que chegou como anon
log.warning("[DIAG] /copa/jogos token=... email=... is_premium=... until=...")
```

**Remover após confirmar que o Lovable está mandando o JWT corretamente em todos os casos.**

### Bug JWT expirado (ES256)
Usuários com sessão aberta há mais de 1 hora recebem `JWTError ES256 — Signature has expired`. O Supabase renova automaticamente via `getSession()`, mas o Lovable precisa chamar `supabase.auth.getSession()` **antes de cada chamada à API** (não usar token guardado em estado).

### Bug timing inicial (frontend)
Na primeira carga, o Lovable fazia fetch de `/copa/jogos` ANTES do Supabase carregar a sessão do localStorage → chegava como anônimo. Fix: aguardar `getSession()` resolver antes do primeiro fetch, e usar `onAuthStateChange` para re-fetch quando sessão aparecer.

---

## 22. Variáveis de Ambiente

Vide seção 14.

---

## 23. Cron Jobs

Vide seção 10.

---

## 24. Estado Atual — 2026-06-15 (Copa em andamento, Rodada 2)

### Git
```
Branch: main
HEAD:   badd350  fix: /copa/jogos cache sistematico (Vary: Authorization)
Commits desta sessão:
  09d1c42  feat: premium janela de datas (detalhe + recomendacao)
  a695e8a  feat: lista personaliza palpite e bloqueado por usuario (janela premium)
  91a5466  diag: log warning cpf/device_id em criar_preferencia
  2a9ddcf  fix: diag log usando warning (info descartado pelo uvicorn)
  7f60d79  feat: CPF obrigatório em /criar-preferencia (400 se ausente)
  c99413d  feat: skeleton webhook Kiwify (fase descoberta)
  233c331  feat: webhook Kiwify etapa 2 (HMAC-SHA1, product_id → plano, set_premium)
  e802ede  feat: kiwify webhook usa TrackingParameters.src como email primario
  271c855  diag: log temporario em /copa/jogos para diagnosticar token/premium
  7623df1  feat: mapeia product_id real do plano avulso Kiwify
  badd350  fix: /copa/jogos cache sistematico (Vary: Authorization, no-store auth, max-age=300 anon)
```

### Pagamentos em produção
- Mercado Pago: ativo, CPF obrigatório
- Kiwify: ativo, todos 3 product_ids mapeados, HMAC-SHA1 validado
- Primeiras vendas reais: pchiade (semanal Kiwify ✅), avulso Kiwify ✅

### Bugs conhecidos aguardando fix Lovable
1. JWT timing: fetch antes da sessão carregar → AUSENTE no primeiro load
2. JWT expirado: token ES256 não renovado antes de chamadas → 403
3. Fix publicado no Lovable mas usuários com JS antigo cacheado ainda afetados

### Logs DIAG ativos (remover após confirmar Lovable OK)
- `[DIAG] /copa/jogos token=...` em partidas.py
- `criar_preferencia [DIAG]: cpf=... device_id=...` em mercadopago_webhook.py

---

## 25. Histórico de Fixes por Sessão

### Sessão 1 (commit 7a5bcc8) — Fix A–F
- **A** — anti-alucinação árbitro no `_SYSTEM`
- **B** — home advantage para anfitrião listado como visitante
- **C** — retry 429 com backoff exponencial em players_agent
- **D** — `_forma_do_seed` como fallback de forma
- **E** — `_e_jogo_senior_masculino` filtra feminino/sub sem afetar amistosos
- **F** — Fase 4: cartões da forma (EntradaForma.fixture_id + `_enriquecer_forma_com_cartoes`)

### Sessão 2 — Prewarm, cirurgias, cartões
- Prewarm Fix A: warm-up `asyncio.sleep(10)` antes do jogo 1 (resolve cold-start burst 429)
- Prewarm Fix B: `range(3)→range(5)` + backoff até 16s em `_api_get`
- Cirurgia 1: 3 jogos re-fetched, 9 jogadores recuperados
- Cirurgia 2: NZ=1.25 amarelos, Ivory Coast=0.89 — causa: `_forma_do_seed` sem fixture_id

### Sessão 3 (commits 45fb011, 16252a4, dbd0afe, 74c9fb5)
- **Elo TSV** — eloratings.net TSV substituiu hardcoded (48 times mapeados)
- **Palpite 1X2 puro** (fix linha 601 em ia_agent.py — `m in _MERCADOS_1X2`)
- **Rating auditado** (58/32/10 efetivo; não normalizar)
- **Filtros A+B** em `_calcular_value_bets` (rejeita favorito-azarão + edge mínimo gradual)
- **Roteamento zebra/valor** — `is_value_pick` e `is_zebra` no value_bet
- Cache 72/72 persistido (74c9fb5)

### Sessão 4 (commits cb1c62b, 2b0e0b8, f092558, 120bcf1)
- **cb1c62b** — Mercado Pago backend: webhook fail-closed, 3 planos, endpoint /criar-preferencia
- **2b0e0b8** — Seed Copa 2026 (72 jogos) + JOGOS_LIBERADOS + fix clube_logo None
- **f092558** — Fix auth bypass: JOGOS_LIBERADOS não entram mais no fluxo de auth
- **120bcf1** — Over/Under e BTTS com consenso (mediana, min 3 casas)

### Sessão 5 (commits 09d1c42 → badd350) — Monetização em Produção
- **09d1c42** — Janela de datas premium em detalhe + recomendacao (fail-open)
- **a695e8a** — /copa/jogos personaliza palpite/bloqueado por usuário + segurança (dados zerados em jogos bloqueados)
- **7f60d79** — CPF obrigatório em /criar-preferencia (400 se ausente) — previne rejeições MP
- **c99413d** — Skeleton webhook Kiwify (responde 200, loga payload bruto para descoberta)
- **233c331** — Kiwify etapa 2: HMAC-SHA1, mapeamento product_id → plano, set_premium com acumulação
- **e802ede** — Kiwify usa TrackingParameters.src como email primário (evita mismatch de email)
- **7623df1** — Mapeia product_id real do avulso Kiwify (b83913d0, confirmado em compra real)
- **badd350** — Cache sistêmico: Vary: Authorization + no-store auth + max-age=300 anon

---

## 26. Modelo de Acesso — Resumo Técnico

```
/copa/jogos (lista)
  anon               → JOGOS_LIBERADOS liberados, resto bloqueado (palpites zerados)
  JWT inválido/expirado → tratado como anon
  JWT válido, sem premium → idem anon
  JWT válido, premium ativo, jogo dentro da janela → liberado
  JWT válido, avulso_credits > 0 → JOGOS_LIBERADOS liberados (avulso não desbloqueia lista)

/copa/jogos/{slug} (detalhe)
  JOGOS_LIBERADOS    → sem auth
  demais             → JWT obrigatório + premium ativo + jogo dentro da janela

/copa/jogos/{slug}/recomendacao
  JOGOS_LIBERADOS    → sem auth
  demais             → JWT obrigatório + premium OU avulso_credits > 0
                       avulso debita 1 crédito por chamada
                       premium verifica janela de datas

admin → ADMIN_TOKEN (ver Railway)
```

---

## 27. Slugs — Semana 1 e 2

```
Jun 11 (JOGADO): mexico-south-africa, south-korea-czech-republic
Jun 12 (JOGADO): canada-bosnia-and-herzegovina, usa-paraguay
Jun 13 (JOGADO): qatar-switzerland, brazil-morocco ★, haiti-scotland
Jun 14 (JOGADO): australia-türkiye, germany-curaçao, netherlands-japan, ivory-coast-ecuador, sweden-tunisia
Jun 15 (HOJE):   spain-cape-verde-islands, belgium-egypt, saudi-arabia-uruguay, iran-new-zealand
Jun 16:          france-senegal, iraq-norway, argentina-algeria
Jun 17:          austria-jordan, portugal-congo-dr, england-croatia, ghana-panama, uzbekistan-colombia

★ brazil-morocco = JOGOS_LIBERADOS (grátis)
```

---

## 28. Roadmap

### Fase 1 — Dados reais ✅ COMPLETA
### Fase 2 — IA + Monetização (~95%)
- ✅ Modelo 5 camadas com fallback por camada
- ✅ Cache tiered por componente
- ✅ Forma recente + fallback seed + cartões
- ✅ Mercado Pago backend (webhook + /criar-preferencia + CPF obrigatório)
- ✅ Kiwify backend (webhook + HMAC + product_ids + acumulação)
- ✅ Janela de datas premium (detalhe + lista personalizada)
- ✅ Segurança: palpites zerados em jogos bloqueados
- ✅ 12 JOGOS_LIBERADOS sem auth
- ⏳ Fix Lovable JWT timing (getSession antes do fetch)
- ⏳ Fix Lovable JWT expirado (getSession antes de cada chamada)
- ⏳ Remover DIAG logs após confirmar Lovable OK
- ⏳ Stash Fase 2 jogadores (MAX_APARECOES_POR_JOGADOR=2 pendente)

### Fase 3 — Monitoramento (em progresso)
- ✅ Alertas Telegram (erros 500 + pagamentos sem conta)
- ⏳ Sentry + UptimeRobot

### Fase 4 — Escala (futuro)
- Dataset Copa 2026, XGBoost, histórico de acertos, expansão ligas

---

## 29. Próximas Ações Prioritárias

```
1. [CRÍTICO — UX] Fix Lovable JWT timing:
   → Aguardar supabase.auth.getSession() antes do primeiro fetch de /copa/jogos
   → onAuthStateChange → re-fetch automático
   → getSession() antes de CADA chamada autenticada (renova token expirado)

2. [ALTA] Remover DIAG logs após confirmar Lovable OK:
   → partidas.py: remover bloco [DIAG]
   → mercadopago_webhook.py: remover log criar_preferencia [DIAG]

3. [ALTA] Confirmar product_ids Kiwify SEMANAL e MENSAL em compra real:
   → IDs atuais vieram de redirect URL (provavelmente corretos mas não 100% confirmados)
   → Primeira venda real vai logar o product_id — comparar com os mapeados

4. [MÉDIA] Stash Fase 2: aplicar MAX_APARECOES_POR_JOGADOR=2, pop stash, commitar

5. [MÉDIA] Encoding slugs Türkiye/Congo DR (6 jogos sem odds)

6. [BAIXA] Registrar resultados reais após cada jogo (scripts/registrar_resultado.py pronto)

7. [BAIXA] Recalibrar ALPHA_REG após fase de grupos (0.5 provisório)

8. [BAIXA] Limpar arquivos temporários:
   → diag_*.py, test_seasons*.py, coverage_check.py, count_leagues.py
   → seeds/cache_partidas.antes_cirurgia*.json, *.backup*.json
   → scripts/_*.py
```

---

## 30. Comandos Úteis

```bash
# Pasta local (Windows)
cd "C:\Users\brunn\OneDrive\Documentos\CLAUDIO\Palpites_da_IA\palpites-backend"

# Produção
$B = "https://palpites-backend-production.up.railway.app/api/v1"

# Health
curl $B/admin/health-check

# Testar jogo liberado sem login
curl "$B/copa/jogos/brazil-morocco/recomendacao"

# Testar jogo premium com PREMIUM_TOKEN
curl -H "Authorization: Bearer <PREMIUM_TOKEN>" "$B/copa/jogos/france-senegal/recomendacao"

# Verificar status premium de usuário
curl -H "Authorization: Bearer <JWT>" "$B/usuario/assinatura"

# Ver logs Railway com filtro
railway logs --lines 200 --since 10m --json | Select-String "KIWIFY|DIAG|premium"

# Prewarm manual
curl "$B/admin/prewarm?dias=14"

# Deploy (Railway auto-deploya no push)
git add <arquivos>
git commit -m "mensagem"
git push origin main

# py_compile antes de commitar
py -m py_compile app/payments/kiwify_webhook.py; if ($?) { "OK" }

# REGRA: NÃO rode git commit nem git push sem aprovação explícita por commit
# REGRA: NUNCA commitar seeds/cache_partidas.json sem fix do Vini×4
```

---

## 31. Problemas Conhecidos sem Fix Ativo

### `dados_insuficientes=True` sistêmico
`/teams/statistics` falha para seleções nacionais → flag True mesmo com forma e odds corretos.

### H2H vazio para muitos jogos
`/fixtures/headtohead` retorna vazio para confrontos raros. `confianca_h2h=0.85` de fallback.

### `_forma_do_seed` sem `fixture_id`
Quando API retorna 0 fixtures, seed cria `EntradaForma` sem `fixture_id` → cartões não enriquecem → `media_amarelos=None`.

### ES256 JWT expira e não é renovado (frontend)
Supabase emite tokens ES256 com expiração de 1h. Frontend Lovable não chama `getSession()` antes de cada request — token expirado causa 403. Fix pendente no Lovable.

---

## 32. Processo de Validação (sempre seguir)

```
1. CÓDIGO  → fix implementado, py_compile, diff revisado
2. DADO    → testar no dado real (número bate?)
3. CACHE   → cache/endpoint propaga o fix?
4. TELA ✅ → abrir o site renderizado e VER + checar logs Railway
```

**Regra:** "passou no código" ≠ "pronto". Pronto = visto na tela + logs confirmam.
