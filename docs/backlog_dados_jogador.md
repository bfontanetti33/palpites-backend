# Backlog: Enriquecimento de Dados de Jogador

**Criado:** 2026-06-05  
**Contexto:** Inventário realizado antes do lançamento Copa 2026 para mapear o que existe vs o que queremos citar na narrativa. Não bloqueia o lançamento.

---

## Estado atual — campos de JogadorDestaque populados

Auditoria sobre 335 jogadores no cache (31 jogos × ~5 jogadores por time):

| Campo | Cobertura | O que é | Pode citar |
|-------|-----------|---------|-----------|
| `nome` | **100%** | Nome completo do jogador | ✓ sempre |
| `clube` | **100%** | Clube atual | ✓ sempre |
| `posicao` / `pos_sigla` | **100%** | Posição (Atacante, MF, DF...) | ✓ sempre |
| `caps` | **100%** | Jogos pela seleção nacional | ✓ sempre |
| `categoria` | **100%** | "goleadores" ou "assistentes" | ✓ sempre |
| `stat_label` | **100%** | "gols/90" ou "assists/90" | ✓ sempre |
| `stat_total` | **100%** | Total gols/assists na temporada (todos competições) | ✓ sempre |
| `minutos_jogados` | **100%** | Minutos totais jogados na temporada | ✓ sempre |
| `mercado_sugerido` | **100%** | "Marcar a qualquer momento" / "Dar assistência" | ✓ como contexto |
| `resumo` | **100%** | Texto técnico do cálculo p90 | ✗ técnico demais |
| `amostra_insuficiente` | **100%** | Flag de confiabilidade | ✓ para avisar |
| `stat_p90` | **31%** | Gols/assists por 90 minutos | ✓ quando presente |
| `stat_p90_adj` | **31%** | p90 ajustado pela força da liga | ✓ quando presente |
| `liga_nome` | **31%** | Liga de onde veio o dado | ✓ quando presente |
| `liga_lss` | **31%** | Fator de ajuste da liga (0-1) | ✗ técnico |
| `clube_logo` | **31%** | URL do escudo | ✗ visual apenas |
| `foto_jogador` | **31%** | URL da foto | ✗ visual apenas |
| `odd_mercado` | **0%** | Odd para o mercado sugerido | ✗ sempre null |

### Regra de citação implementada (testar_narrativa.py + _SYSTEM B/C)

```
"De olho no [nome] do [clube] — [stat_total] [gols/assists] na temporada, [caps] jogos pela seleção"
+ se stat_p90 presente: "média de [stat_p90] por jogo"
+ mercado_sugerido como contexto
```

---

## O que falta para citações mais ricas

### 1. Odd de jogador (odd_mercado) — Prioridade ALTA

**O que queremos:** "o mercado paga 3.50 pra [nome] marcar"  
**Por que está null:** O `odds_agent.py` não busca mercados de jogadores na The Odds API (apenas h2h, totals, spreads). O endpoint `/sports/{sport}/events/{event_id}/odds` tem o parâmetro `markets=player_props` disponível no plano atual.

**Como implementar:**
1. Adicionar `player_props` ao parâmetro `markets` em `buscar_odds_evento()` em `odds_agent.py`
2. Parsear os outcomes de player_props (formato: `{"name": "Vinicius Junior", "description": "Anytime Goalscorer", "price": 3.5}`)
3. Fazer matching entre o nome retornado pela Odds API e o `nome` do `JogadorDestaque` (fuzzy match por sobrenome)
4. Popular `odd_mercado` no objeto retornado

**Custo de quota:** +1 request por jogo no The Odds API (já está nos 500/mês do plano free — viável dentro da cota)  
**Esforço estimado:** 3-4h  
**Risco:** nomes podem não bater — precisar de tabela de alias (ex: "Vini Jr" vs "Vinicius Junior")

---

### 2. Gols absolutos da temporada completa — Prioridade MÉDIA

**O que queremos:** "17 gols em 38 jogos pelo Manchester City"  
**Por que não temos:** `stat_total` é calculado sobre os dados de forma recente disponíveis na API-Football (últimos ~30 jogos), não a temporada completa official.  

O `stat_total` atual É a contagem real dos jogos cobertos — é verdadeiro, mas pode ser sub-contagem se a temporada começou antes da janela de dados.

**Como implementar:**
1. Chamar o endpoint `/players` da API-Football com `season=2025` para cada jogador (team + season stats)
2. Endpoint: `GET /players?id={player_id}&season=2025`
3. Extrair `statistics[0].goals.total` e `statistics[0].games.appearences`
4. Adicionar campos `gols_temporada_oficial` e `jogos_temporada` ao schema

**Custo:** +1 request por jogador por jogo → potencialmente 300+ requests adicionais (problema de quota no free tier)  
**Alternativa:** Fazer apenas para o top-1 jogador de cada time (2 requests por jogo = aceitável)  
**Esforço estimado:** 1-2 dias (incluindo schema + cache update)

---

### 3. Títulos e troféus — Prioridade BAIXA

**O que queremos:** "campeão da UCL pelo Real Madrid"  
**Disponibilidade:** A API-Football tem `/trophies?player={id}` mas a cobertura é incompleta (depende da liga). Títulos de seleção (Copa do Mundo, AFCON, Copa América) raramente aparecem.  

**Risco elevado:** dados incompletos vão fazer a IA citar troféu errado ou omitir título importante → dano de credibilidade maior que o benefício.  

**Recomendação:** não implementar por API-Football. Se necessário no futuro, usar seed manual (JSON com troféus por jogador) para os ~50 jogadores mais conhecidos da Copa.  
**Esforço estimado:** 3-5 dias para seed manual com qualidade suficiente

---

### 4. Cobertura stat_p90 de 31% → 100% — Prioridade MÉDIA

**Por que 31%:** O `players_agent.py` busca estatísticas por temporada via API-Football. Para times de ligas menores ou jogadores com menos de X minutos, os dados de p90 não chegam. Os 69% sem p90 ficam apenas com `stat_total` e `minutos_jogados`.

**Como melhorar:** calcular p90 localmente quando `stat_total > 0` e `minutos_jogados > 0`:
```python
stat_p90 = stat_total / (minutos_jogados / 90)
```
Essa fórmula já existe no `players_agent.py` para os casos que têm — basta aplicar como fallback quando a API não retorna.  
**Esforço estimado:** 2h  
**Impacto:** eleva cobertura de p90 de 31% → ~90%+ (só falha se minutos=0)

---

## Resumo de prioridades para próximas sprints

| Feature | Impacto na narrativa | Esforço | Quota API | Prioridade |
|---------|---------------------|---------|-----------|-----------|
| odd_mercado (player_props) | Alto — "o mercado paga X" | 3-4h | baixo | **Sprint pós-Copa grupo** |
| stat_p90 fallback local | Médio — cobertura 31%→90% | 2h | nenhum | **Sprint pós-Copa grupo** |
| Gols temporada oficial | Médio — "17 gols em 38j" | 1-2d | médio | Após grupo |
| Títulos/troféus | Alto se correto | 3-5d (seed) | nenhum | Backlog |

---

## Referências

- `app/agents/players_agent.py` — onde buscar stat_p90 e onde implementar odd_mercado
- `app/agents/odds_agent.py` — onde adicionar `player_props` ao parâmetro `markets`
- `app/models/schemas.py:JogadorDestaque` — schema a estender
- `scripts/testar_narrativa.py` — script de teste de narrativa que usa estes dados
