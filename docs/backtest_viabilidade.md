# Viabilidade do Backtest Histórico — Copas 2010–2022

**Criado:** 2026-06-05  
**Contexto:** Alpha=0.5 aplicado como calibração conservadora pré-Copa 2026. Este documento registra a investigação sobre expandir o backtest para Copas anteriores e a decisão de fazer Fase 2 com dados reais de 2026.

---

## Situação atual (Fase 1)

Alpha calibrado contra odds de mercado, 27 jogos da semana 1 da Copa 2026.  
Resultado: alpha ótimo = 0.65 (Brier), decisão de aplicar 0.5 (conservador).  
Limitação: amostra pequena (27 jogos), calibração contra mercado como proxy — não resultados reais.

---

## Objetivo do backtest histórico

Expandir para ~250–320 jogos (2010 + 2014 + 2018 + 2022) para calibrar com mais robustez e aplicar k-fold para detectar overfitting.

**Regra central:** nenhum dado posterior à data de cada Copa pode entrar no backtest (lookahead bias invalida o resultado inteiro).

---

## Investigação por fonte

### Resultados de jogos

| Fonte | Copas cobertas | Formato | Acesso | Risco de bias |
|-------|---------------|---------|--------|---------------|
| [openfootball/worldcup](https://github.com/openfootball/worldcup) | 2010, 2014, 2018, 2022 | TXT estruturado | Git clone gratuito | Nenhum — dados históricos públicos |
| [martj42 international-football-results](https://github.com/martj42/international-football-results) | 1872–2022+ | CSV | GitHub/Kaggle gratuito | Nenhum |

**Veredicto:** 100% viável. Zero custo, zero bias. Clonar e converter é ~2h de trabalho.

---

### Odds de mercado históricas

| Fonte | Copas cobertas | Formato | Acesso | Risco de bias |
|-------|---------------|---------|--------|---------------|
| [BetExplorer](https://www.betexplorer.com/soccer/world/) | 2010, 2014, 2018, 2022 | HTML (scraping) | Público | Baixo — odds pré-jogo arquivadas |
| [football-data.co.uk](https://www.football-data.co.uk) | Ligas nacionais confirmado; Copa 2026 encontrada | CSV/XLSX | Download gratuito | Baixo |

**Veredicto:** Viável via scraping do BetExplorer. Esforço estimado: ~1 dia para scraper robusto. As odds são arquivadas e não mudam retroativamente — risco de bias baixo.

**Alternativa mais rápida:** verificar se `football-data.co.uk` tem Copa 2014/2018/2022 em CSV (não confirmado nos testes, requer inspeção manual do site).

---

### Elo ratings históricos (PROBLEMA CRÍTICO)

| Fonte | Status | Detalhe |
|-------|--------|---------|
| eloratings.net | **Inviável como download** | Site 100% JavaScript; sem API, sem CSV, sem endpoint por data. Todos os endpoints `/api/results/World/2014` retornam 404. |
| clubelo.com | Não aplicável | Cobre clubes, não seleções nacionais. |
| FIFA ranking histórico | **Inviável** | fifa.com exibe apenas ranking atual; sem download histórico. |

**Única opção viável para Elo:** calcular manualmente usando a fórmula de Elo padrão aplicada sobre os resultados históricos do dataset martj42. Isso produz uma série rolling de Elo por seleção com corte em cada data. Esforço estimado: 2–3 dias de implementação + validação spot-check contra eloratings.net via UI.

**Se o Elo histórico não for calculado, a Copa correspondente é excluída do backtest** — usar Elo atual em jogos de 2014 seria lookahead bias flagrante.

---

### Forma recente histórica

Calculável a partir de martj42 — filtrar os últimos N jogos de cada seleção antes da data da Copa. Sem custo adicional além do Elo rolling.

### Pi-rating histórico

Idem — calculável rolling a partir dos resultados históricos. Mesmo esforço do Elo.

---

## Estimativa de esforço total

| Componente | Esforço estimado |
|------------|-----------------|
| Download e parse openfootball + martj42 | 2–4h |
| Scraping BetExplorer (4 Copas) | 1 dia |
| Implementar Elo rolling histórico + validação | 2–3 dias |
| Implementar Pi-rating rolling | 1–2 dias |
| Montar dataset final + sanity checks | 1 dia |
| Script de backtest com k-fold | 1 dia |
| **Total** | **~6–9 dias** |

---

## Decisão e recomendação

**Não fazer o backtest histórico antes do lançamento.** O esforço (6–9 dias) é desproporcional ao benefício para a calibração de alpha antes da Copa 2026.

### Fase 2 — Calibração contra resultados reais de 2026 (recomendado)

Após ~20 jogos da fase de grupos da Copa 2026 (estimativa: final de junho de 2026):

- Os resultados reais substituem o mercado como "ground truth" — calibração mais honesta
- Os lambdas já foram calculados corretamente pelo modelo na época (sem reconstrução)
- Zero lookahead bias por definição
- ~48 jogos da fase de grupos = melhor amostra do que os 27 atuais

**Script a criar:** `scripts/calibrar_alpha_backtest.py` — mesma estrutura do `calibrar_alpha.py` mas lê resultados reais (`resultado_real` no cache) em vez de usar odds como proxy.

### Backtest histórico — Backlog de médio prazo

Se a calibração de Fase 2 mostrar que alpha=0.5 está bem longe do ótimo, ou para validação científica, o backtest histórico vale o investimento. Priorizar nesse caso após a Copa 2026.

---

## Referências

- `scripts/calibrar_alpha.py` — script de calibração atual (Fase 1, vs mercado)
- `app/agents/ia_agent.py` — `ALPHA_REG = 0.5` aplicado em `_lambdas_from_ratings`
- Commit de aplicação: `a7f0ce5` — "model: regressão à média alpha=0.5 nos lambdas"
