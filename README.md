# Palpites da IA — Backend

API FastAPI que alimenta **palpitesdaia.com.br** com dados reais de futebol,
probabilidades estatísticas e recomendações de IA para apostas esportivas.

## Arquitetura

```
palpites-backend/
├── app/
│   ├── main.py                        # FastAPI + CORS + Sentry + middlewares
│   ├── agents/
│   │   ├── football_agent.py          # Dados API-Football + cache 4h
│   │   ├── ia_agent.py                # 5 camadas estatísticas + Claude
│   │   ├── odds_agent.py              # Odds API (The Odds API)
│   │   └── odds_engine.py             # Shin method + z-score + value bets
│   ├── auth/
│   │   └── supabase_client.py         # JWT Supabase + CRUD usuários
│   ├── models/
│   │   └── schemas.py                 # Schemas Pydantic
│   ├── monitoring/
│   │   └── telegram_bot.py            # Alertas + resumo diário 08h BRT
│   ├── payments/
│   │   └── mercadopago_webhook.py     # Webhook pagamentos
│   └── routes/
│       ├── admin.py                   # Endpoints de monitoramento
│       └── partidas.py                # Endpoints públicos + premium
├── seeds/
│   ├── copa_2026.json                 # 72 jogos Copa 2026 (fixture IDs reais)
│   └── squads_copa_2026.json          # Elencos por seleção
├── scripts/
│   ├── validacao_completa.py          # Suite de validação pré-deploy
│   └── precalcular_jogos.py           # Aquece cache manualmente
├── docs/
│   ├── lovable_supabase_integration.md
│   └── mercadopago_setup.md
├── Procfile                           # uvicorn --workers 2
├── railway.toml                       # região southamerica-east1
├── requirements.txt
└── .env.example
```

### Camadas do modelo estatístico (endpoint `/recomendacao`)
| Camada | O que faz |
|--------|-----------|
| 1 — Rating Dinâmico | Elo + Pi-rating + FIFA Ranking + normalização regional |
| 2 — Modelo de Gols | Dixon-Coles + Skellam + calibração |
| 3 — Odds Engine | Shin Method + consensus + z-score + value bets |
| 4 — Context Engine | Fadiga, Rodada 1, zebra, H2H, home advantage |
| 4B — Tail Risk | Fat Tail (Taleb), Fragility, Uncertainty, Barbell |
| 5 — Claude | Narrativa em PT-BR baseada nos outputs das camadas acima |

---

## Setup local

```bash
# 1. Clone
git clone https://github.com/bfontanetti33/palpites-backend.git
cd palpites-backend

# 2. Ambiente virtual
python -m venv venv
source venv/bin/activate       # Linux/Mac
venv\Scripts\activate          # Windows

# 3. Dependências
pip install -r requirements.txt

# 4. Variáveis de ambiente
cp .env.example .env
# Edite o .env com suas chaves (veja seção abaixo)

# 5. Rode
uvicorn app.main:app --reload
```

Swagger disponível em: http://localhost:8000/docs

---

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `API_FOOTBALL_KEY` | ✅ | rapidapi.com — 100 req/dia free |
| `ANTHROPIC_API_KEY` | ✅ | console.anthropic.com |
| `ODDS_API_KEY` | ✅ | the-odds-api.com — 500 req/mês free |
| `SUPABASE_URL` | ✅ | Supabase Dashboard → Settings → API |
| `SUPABASE_KEY` | ✅ | Chave anon do Supabase |
| `SUPABASE_JWT_SECRET` | ✅ | JWT secret (Settings → API → JWT Settings) |
| `PREMIUM_TOKEN` | ✅ | Token fixo de admin (override auth) |
| `TELEGRAM_BOT_TOKEN` | ⚡ | Token do bot (@BotFather) |
| `TELEGRAM_CHAT_ID` | ⚡ | ID do chat para alertas |
| `MERCADOPAGO_ACCESS_TOKEN` | ⚡ | Token de produção do MP |
| `MERCADOPAGO_WEBHOOK_SECRET` | ⚡ | Secret para verificar assinatura MP |
| `SENTRY_DSN` | ⚡ | DSN do projeto Sentry (opcional) |
| `ADMIN_TOKEN` | ⚡ | Protege /admin/health-check |
| `ANTHROPIC_CREDIT_REMAINING` | ⚡ | Saldo manual — alerta Telegram se < $2 |

✅ = obrigatória para funcionar | ⚡ = opcional mas recomendada

---

## Endpoints

### Públicos
| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/health` | Status + versão + cache |
| GET | `/api/v1/copa/jogos` | 72 jogos da Copa 2026 |
| GET | `/api/v1/copa/jogos/{slug}` | Detalhe: stats, forma, H2H, probabilidades |

### Premium (requer JWT Supabase ou PREMIUM_TOKEN)
| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/v1/copa/jogos/{slug}/recomendacao` | Análise completa com 5 camadas + Claude |

### Admin
| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/v1/admin/stats` | Métricas: cache, uptime, requests |
| GET | `/api/v1/admin/health-check` | Status completo + vars + Supabase + Telegram |
| GET | `/api/v1/admin/telegram-test` | Envia mensagem de teste no Telegram |
| GET | `/api/v1/admin/supabase-test` | CRUD de teste no Supabase |

### Webhooks
| Método | Endpoint | Descrição |
|--------|----------|-----------|
| POST | `/api/v1/webhooks/mercadopago` | Recebe notificações de pagamento |

### Rate limits (por IP)
| Endpoint | Limite |
|----------|--------|
| Global | 200 req/min |
| `/copa/jogos` | 60 req/min |
| `/copa/jogos/{slug}` | 20 req/min |
| `/recomendacao` | 5 req/min |

---

## Como rodar a validação

```bash
# Usa ~20-30 requests da API-Football e ~3 da Odds API
python scripts/validacao_completa.py

# Meta: 0 críticos (warnings são OK)
# Resultado salvo em scripts/relatorio_validacao.json
```

---

## Deploy no Railway

O projeto já está configurado para Railway com `railway.toml` (região São Paulo).

```bash
# Deploy via git push (Railway auto-deploya ao push no main)
git push origin main

# Pré-cache manual dos 72 jogos após deploy
python scripts/precalcular_jogos.py

# Ou deixe o startup automático fazer (demora ~2 min após deploy)
```

### Após o deploy, confirme:
```bash
curl https://palpites-backend-production.up.railway.app/health
curl https://palpites-backend-production.up.railway.app/api/v1/admin/health-check
```

---

## Integração com Lovable

Veja [`docs/lovable_supabase_integration.md`](docs/lovable_supabase_integration.md) para o guia completo.

```typescript
// Partidas da Copa 2026
const res = await fetch("https://palpites-backend-production.up.railway.app/api/v1/copa/jogos");
const { partidas } = await res.json();

// Recomendação IA (usuário premium)
const { data: { session } } = await supabase.auth.getSession();
const res = await fetch(
  `https://palpites-backend-production.up.railway.app/api/v1/copa/jogos/${slug}/recomendacao`,
  { headers: { Authorization: `Bearer ${session.access_token}` } }
);
```

---

## Configuração de pagamentos

Veja [`docs/mercadopago_setup.md`](docs/mercadopago_setup.md) para o guia completo do Mercado Pago.

Webhook: `POST /api/v1/webhooks/mercadopago`
- `external_reference` formato: `"email@usuario.com|mensal"` ou `"email@usuario.com|avulso"`
