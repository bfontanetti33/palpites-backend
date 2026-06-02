# Palpites da IA — Backend

API Python/FastAPI que alimenta o site palpitesdaia.lovable.app com dados reais
de futebol e recomendações de apostas via IA.

## Estrutura

```
palpites-backend/
├── app/
│   ├── main.py                  # FastAPI app + CORS
│   ├── agents/
│   │   ├── football_agent.py    # Busca e transforma dados da API-Football
│   │   └── ia_agent.py          # Gera recomendações via Claude (premium)
│   ├── models/
│   │   └── schemas.py           # Schemas Pydantic
│   └── routes/
│       └── partidas.py          # Endpoints REST
├── requirements.txt
├── Procfile                     # Para Railway/Render
└── .env.example
```

## Setup local

```bash
# 1. Clone e entre na pasta
cd palpites-backend

# 2. Ambiente virtual
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Dependências
pip install -r requirements.txt

# 4. Variáveis de ambiente
cp .env.example .env
# Edite o .env com suas chaves

# 5. Rode
uvicorn app.main:app --reload
```

Acesse: http://localhost:8000/docs (Swagger automático)

## Chaves necessárias

### API-Football (dados de futebol)
1. Crie conta em https://rapidapi.com
2. Assine "API-Football" — plano gratuito: 100 req/dia
3. Copie a chave X-RapidAPI-Key → coloque em API_FOOTBALL_KEY

### Anthropic (IA premium)
1. Crie conta em https://console.anthropic.com
2. Gere uma API key → coloque em ANTHROPIC_API_KEY

## Endpoints

| Método | Endpoint | Acesso | Descrição |
|--------|----------|--------|-----------|
| GET | `/api/v1/partidas` | Público | Partidas do dia (todas as ligas) |
| GET | `/api/v1/partidas?liga_id=71` | Público | Filtrar por liga |
| GET | `/api/v1/partidas/{slug}` | Público | Detalhes + stats + H2H |
| GET | `/api/v1/partidas/{slug}/recomendacao` | **Premium** | Recomendação da IA |
| GET | `/health` | Público | Health check |

## Integração com o Lovable

No seu projeto Lovable, chame a API assim:

```javascript
// Partidas do dia (home)
const res = await fetch('https://sua-api.railway.app/api/v1/partidas')
const { partidas } = await res.json()

// Detalhes de uma partida
const res = await fetch('https://sua-api.railway.app/api/v1/partidas/flamengo-palmeiras')

// Recomendação IA (só para usuários premium)
const res = await fetch('https://sua-api.railway.app/api/v1/partidas/flamengo-palmeiras/recomendacao', {
  headers: { 'Authorization': `Bearer ${token_do_usuario}` }
})
```

## Deploy no Railway (recomendado)

```bash
# 1. Instale o Railway CLI
npm install -g @railway/cli

# 2. Login
railway login

# 3. Crie o projeto
railway init

# 4. Configure as variáveis de ambiente no painel Railway:
#    API_FOOTBALL_KEY, ANTHROPIC_API_KEY, ALLOWED_ORIGIN, PREMIUM_TOKEN

# 5. Deploy
railway up
```

## Próximos passos

- [ ] Integrar Supabase para gerenciar usuários e validar assinantes
- [ ] Webhook Mercado Pago / Stripe → ativa acesso premium no Supabase
- [ ] Rota `/zebras` — partidas com probabilidade de zebra
- [ ] Rota `/odds-baixas` — partidas com odds seguras (< 1.5)
- [ ] Histórico de acertos para exibir no site ("78% de acerto")
- [ ] Dataset próprio para treinar modelo proprietário (Fase 3)
