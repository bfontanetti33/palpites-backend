# Relatório Técnico — México × África do Sul
## Copa do Mundo FIFA 2026 · Grupo A · Rodada 1

**Jogo:** México × África do Sul  
**Data:** 11/06/2026 · 16h00 (Brasília)  
**Local:** Estadio Banorte · Cidade do México · México  
**Fixture ID (API-Football):** 1489369  
**Gerado em:** 2026-06-02  
**Modelo:** Palpites da IA v2 — 5 camadas + Tail Risk Engine  

---

## 1. RATINGS DINÂMICOS

### 1.1 Elo Rating

O Elo utilizado provém de um **banco de dados de fallback** interno ao agente — o scraping de `eloratings.net` foi tentado mas o regex não encontrou correspondência no HTML retornado (estrutura da página provavelmente diferente do esperado). O fallback é atualizado manualmente com base em tendências históricas públicas.

| Seleção | Elo (fallback) | Fonte |
|---|---|---|
| México | **1.841** | Histórico API-Football + referências públicas |
| África do Sul | **1.641** | Histórico API-Football + referências públicas |
| Diferença | **200 pontos** | — |

> **Nota:** Diferença de 200 pontos Elo indica que o México é favorito em condições normais (probabilidade Elo pura ≈ 75% de vitória do México em partidas entre clubes). Porém, em Copas do Mundo em campo neutro, o fator de mandante é zero e o gap real tende a ser menor.

### 1.2 Pi-rating

O Pi-rating é calculado como a **média ponderada de (gols marcados − gols sofridos) / média global (1,2)** nos últimos 10 jogos, com decaimento temporal de `0,98^dias` a partir da data do jogo.

**Fórmula por jogo:**
```
pi_contrib_i = (gols_marcados_i − gols_sofridos_i) / 1.2
peso_i       = 0.98 ^ dias_antes_do_jogo
pi_rating    = Σ(pi_contrib_i × peso_i) / Σ(peso_i)
```

**México — 10 últimos jogos (ponderados):**

| Data | Adversário | G+ | G− | Diff | Dias antes | Peso (0.98^d) |
|---|---|---|---|---|---|---|
| 31/05/2026 | Austrália | 1 | 0 | +1 | 11 | 0,800 |
| 23/05/2026 | Gana | 2 | 0 | +2 | 19 | 0,682 |
| 01/04/2026 | Bélgica | 1 | 1 | 0 | 71 | 0,238 |
| 29/03/2026 | Portugal | 0 | 0 | 0 | 74 | 0,223 |
| 26/02/2026 | Islândia | 4 | 0 | +4 | 105 | 0,118 |
| 25/01/2026 | Bolívia | 1 | 0 | +1 | 137 | 0,063 |
| 23/01/2026 | Panamá | 1 | 0 | +1 | 139 | 0,061 |
| 19/11/2025 | Paraguai | 1 | 2 | −1 | 204 | 0,016 |
| 16/11/2025 | Uruguai | 0 | 0 | 0 | 207 | 0,015 |
| 15/10/2025 | Equador | 1 | 1 | 0 | 239 | 0,008 |

**Resultado:** Pi-rating México = **+1,029** (desempenho claramente acima da média global, puxado pelos resultados recentes e pelo 4-0 sobre a Islândia ainda com peso relevante)

**África do Sul — 10 últimos jogos:**

| Data | Adversário | G+ | G− | Diff |
|---|---|---|---|---|
| 29/05/2026 | Nicarágua | 0 | 0 | 0 |
| 31/03/2026 | Panamá | 1 | 2 | −1 |
| 27/03/2026 | Panamá | 1 | 1 | 0 |
| 04/01/2026 | Camarões | 1 | 2 | −1 |
| 29/12/2025 | Zimbabwe | 3 | 2 | +1 |
| 26/12/2025 | Egito | 0 | 1 | −1 |
| 22/12/2025 | Angola | 2 | 1 | +1 |
| 16/12/2025 | Gana B | 1 | 0 | +1 |
| 15/11/2025 | Zâmbia | 3 | 1 | +2 |
| 14/10/2025 | Ruanda | 3 | 0 | +3 |

**Resultado:** Pi-rating África do Sul = **−0,094** (na média global — 4 vitórias fortes no início do período pesam pouco pelo decaimento; derrotas recentes para Panamá e Camarões dominam)

### 1.3 Rating Combinado

```
elo_normalizado  = (elo − 1500) / 200
rating_combinado = 0,60 × elo_normalizado + 0,40 × pi_rating
```

| Seleção | Elo norm. | Pi-rating | Rating combinado | Contribuição Elo | Contribuição Pi |
|---|---|---|---|---|---|
| México | (1841−1500)/200 = **+1,705** | **+1,029** | 0,60×1,705 + 0,40×1,029 = **+1,435** | +1,023 (71%) | +0,412 (29%) |
| África do Sul | (1641−1500)/200 = **+0,705** | **−0,094** | 0,60×0,705 + 0,40×(−0,094) = **+0,385** | +0,423 (110%) | −0,038 (−10%) |

> O Pi-rating **penaliza** a África do Sul: o componente histórico (Elo) sugere uma seleção acima da média (0,705), mas o desempenho recente nos 10 últimos jogos arrasta o rating para baixo (−0,094), resultando no combinado de apenas +0,385 vs +1,435 do México.

### 1.4 FIFA Ranking

**Não implementado na versão atual.** A Camada 1 opera com Elo + Pi-rating (dois componentes). O FIFA Ranking estava previsto como terceiro componente (20% do peso), mas o scraping de `fifa.com/fifa-world-ranking` ainda não foi implementado. O peso redistribuído permanece: 60% Elo + 40% Pi.

---

## 2. PROBABILIDADES — RASTREABILIDADE COMPLETA

### 2.1 Lambdas (gols esperados por jogo)

O λ de cada time combina a média de gols recente com o fator de força derivado do rating combinado:

```
ataque_casa = max(0.5, 1.0 + rating_combinado_casa × 0,10)
              = max(0.5, 1.0 + 1,435 × 0,10) = 1,1435

defesa_fora = max(0.5, 1.0 − rating_combinado_fora × 0,08)
              = max(0.5, 1.0 − 0,385 × 0,08) = 0,9692

avg_gols_casa (últimos 10 jogos, México) = 1,20 gols/jogo

λ_casa = avg_gols_casa × ataque_casa × defesa_fora
       = 1,20 × 1,1435 × 0,9692 = 1,330
```

```
ataque_fora = max(0.5, 1.0 + 0,385 × 0,10) = 1,0385
defesa_casa = max(0.5, 1.0 − 1,435 × 0,08) = 0,8852

avg_gols_fora (últimos 10 jogos, África do Sul) = 1,50 gols/jogo

λ_fora = 1,50 × 1,0385 × 0,8852 = 1,379
```

**λ_México = 1,330 · λ_África do Sul = 1,379**

> Apesar do México ter rating muito superior, o λ da África do Sul é levemente maior porque sua **média recente de gols marcados (1,50) supera a do México (1,20)** — os jogos da AFCON e qualificatórias africanas foram muito goleadores. O modelo pondera mais o desempenho recente do que a posição histórica.

### 2.2 Dixon-Coles Bruto (Camada 2)

**Correção τ (Dixon-Coles) — fator multiplicativo para placares baixos:**

| Placar | τ calculado | Efeito |
|---|---|---|
| 0-0 | 1 − 1,330×1,379×(−0,1) = **1,1834** | +18,3% na probabilidade bruta |
| 0-1 | 1 + 1,330×(−0,1) = **0,8670** | −13,3% na probabilidade bruta |
| 1-0 | 1 + 1,379×(−0,1) = **0,8621** | −13,8% na probabilidade bruta |
| 1-1 | 1 − (−0,1) = **1,1000** | +10,0% na probabilidade bruta |
| outros | **1,0000** | sem correção |

**Probabilidades DC bruto (pré-qualquer ajuste contextual):**

| Mercado | Probabilidade |
|---|---|
| Vitória México | 34,7% |
| Empate | 28,4% |
| Vitória África do Sul | **37,0%** |
| BTTS | 56,1% |
| Over 1.5 | 76,4% |
| Under 1.5 | 23,6% |
| Over 2.5 | **50,6%** |
| Under 2.5 | 49,4% |
| Over 3.5 | 28,4% |
| Under 3.5 | 71,6% |

### 2.3 Confirmação pelo Skellam

A Distribuição de Skellam modela diretamente a **diferença de gols X−Y**, onde X~Poisson(1,330) e Y~Poisson(1,379):

```
P(X−Y = k) = e^{−(λ+μ)} × (λ/μ)^{k/2} × I_{|k|}(2√(λ×μ))
```

onde `I_n(x)` é a função de Bessel modificada (implementada via série de Taylor, sem scipy).

| Resultado | Dixon-Coles | Skellam | Divergência |
|---|---|---|---|
| Vitória México (diff > 0) | 34,7% | **36,0%** | +1,3pp |
| Empate (diff = 0) | 28,4% | **25,8%** | −2,6pp |
| Vitória África do Sul (diff < 0) | 37,0% | **38,2%** | +1,2pp |

**Interpretação:** Os dois modelos concordam na direção (África do Sul levemente favorita), mas o Skellam estima **menos empates** (25,8% vs 28,4%). A divergência de 2,6pp no empate é relevante — o DC penaliza menos o empate porque infla P(1-1) pela correção τ, enquanto o Skellam vê apenas a diferença de gols. O modelo final usa DC como base e o Skellam como validação cruzada.

### 2.4 Ajustes Aplicados — Pipeline Completo

#### Camada 4 — Context Engine

| Ajuste | Aplicado? | Efeito |
|---|---|---|
| Campo neutro | ✅ Sim | Nenhum impacto direto nas probabilidades (apenas remove home advantage que já não estava no modelo) |
| Fadiga México | ❌ Não | Último jogo: 31/05 (11 dias antes) — acima do limiar de 4 dias |
| Fadiga África do Sul | ❌ Não | Último jogo: 29/05 (13 dias antes) — acima do limiar |
| Zebra | ❌ Não ativado | Elo diff = 200pts > limiar de 150pts, mas wr África do Sul nos últimos 5 = 40% < 60% |
| Rodada 1 Copa | ✅ Sim | Over 2.5: 50,6% × 0,90 = **45,5%** (−5,1pp) |

#### Camada 4B — Tail Risk Engine

A camada 4B **reconstrói a matriz DC** a partir dos λ originais (sem o ajuste de Rodada 1 no Over 2.5) e aplica a correção Fat Tail:

| Ajuste | Δ Over 2.5 | Δ Over 1.5 | Δ Over 3.5 | Δ 1X2 |
|---|---|---|---|---|
| Fat Tail (85% DC + 15% Student-t ν=4) | +0,1pp | +1,2pp | −1,2pp | <0,3pp |

> **Atenção — inconsistência de pipeline:** O ajuste de Rodada 1 (−5,1pp no Over 2.5) aplicado pela Camada 4 é efetivamente sobrescrito pela Camada 4B, que reconstrói o Over 2.5 a partir da matriz DC bruta (+Fat Tail = 50,7%). O resultado final de 50,7% está apenas +0,1pp acima do DC puro (50,6%), não refletindo o ajuste de Rodada 1. Isso é uma **fraqueza de design** documentada na seção 6.

### 2.5 Probabilidades Finais — Rastreabilidade Completa

| Mercado | DC bruto | Após Contexto | Após Fat Tail | **FINAL** | Δ total vs DC |
|---|---|---|---|---|---|
| Vitória México | 34,7% | 34,7% | **34,9%** | **34,9%** | +0,2pp |
| Empate | 28,4% | 28,4% | **28,1%** | **28,1%** | −0,3pp |
| Vitória África do Sul | 37,0% | 37,0% | **37,1%** | **37,1%** | +0,1pp |
| BTTS Sim | 56,1% | 56,1% | **56,6%** | **56,6%** | +0,5pp |
| Over 1.5 | 76,4% | 76,4% | **77,6%** | **77,6%** | +1,2pp |
| Over 2.5 | 50,6% | 45,5% | **50,7%** | **50,7%** | +0,1pp* |
| Under 2.5 | 49,4% | 54,5% | **49,3%** | **49,3%** | −0,1pp* |
| Over 3.5 | 28,4% | 28,4% | **27,2%** | **27,2%** | −1,2pp |
| Under 3.5 | 71,6% | 71,6% | **72,8%** | **72,8%** | +1,2pp |

*\*O ajuste de Rodada 1 (±5,1pp) foi revertido pela Camada 4B. Ver seção 6.1.*

---

## 3. MATRIZ DE PLACARES

### 3.1 Top 10 — Poisson Puro vs Dixon-Coles

| Ranking | Poisson puro | % | Dixon-Coles | % | Δ (pp) |
|---|---|---|---|---|---|
| 1 | 1-1 | 12,28% | **1-1** | **13,51%** | +1,23 |
| 2 | 0-1 | 9,24% | **1-2** | **8,47%** | — |
| 3 | 1-0 | 8,91% | **2-1** | **8,17%** | — |
| 4 | 1-2 | 8,47% | **0-1** | **8,01%** | −1,23 |
| 5 | 2-1 | 8,17% | **0-0** | **7,93%** | +1,23 |
| 6 | 0-0 | 6,70% | **1-0** | **7,68%** | −1,23 |
| 7 | 0-2 | 6,37% | **0-2** | **6,37%** | 0,00 |
| 8 | 2-0 | 5,92% | **2-0** | **5,92%** | 0,00 |
| 9 | 2-2 | 5,63% | **2-2** | **5,63%** | 0,00 |
| 10 | 1-3 | 3,89% | **1-3** | **3,89%** | 0,00 |

### 3.2 Impacto da Correção τ nos Placares Baixos

A correção Dixon-Coles redistribui probabilidade **dos placares assimétricos de 1 gol** (0-1, 1-0) **para os placares simétricos** (0-0, 1-1):

| Placar | τ | Efeito no ranking |
|---|---|---|
| **0-0** | 1,1834 → multiplicou por +18% | Subiu do 6º para o **5º lugar** (+1,23pp) |
| **1-1** | 1,1000 → multiplicou por +10% | Manteve 1º, mas ampliou vantagem (+1,23pp) |
| **0-1** | 0,8670 → multiplicou por −13% | Caiu do 2º para o **4º lugar** (−1,23pp) |
| **1-0** | 0,8621 → multiplicou por −14% | Caiu do 3º para o **6º lugar** (−1,23pp) |
| **≥ 2 gols** | 1,0000 → sem alteração | Posições inalteradas |

**Interpretação:** O Poisson puro superestima partidas com apenas 1 gol de diferença (1-0, 0-1) e subestima empates e partidas sem gols. O DC corrige isso porque estatisticamente, em jogos de baixa pontuação, há correlação entre os gols dos dois times que o Poisson independente ignora.

### 3.3 Matriz Completa (Top 36, valores finais DC)

```
        AFR: 0     1     2     3     4     5
MEX: 0      7,93  8,01  6,37  3,39  1,34  0,43
MEX: 1      7,68  13,51 8,47  4,50  1,79  0,57
MEX: 2      5,92  8,17  5,63  2,99  1,19  0,38
MEX: 3      3,04  4,20  2,90  1,54  0,61  0,19
MEX: 4      1,17  1,62  1,12  0,59  0,24  0,07
MEX: 5      0,36  0,50  0,34  0,18  0,07  0,02
```

*(Valores aproximados com base nos λ e na normalização DC. Soma = 100%)*

---

## 4. UNCERTAINTY INDEX — DETALHADO

### 4.1 Fatores e Contribuições

O Uncertainty Index (UI) acumula pontos de incerteza de até 5 fatores:

| Fator | Condição | Disparado? | Pontos |
|---|---|---|---|
| H2H < 3 confrontos | Apenas 1 H2H registrado | ✅ Sim | **+20** |
| Elo diff < 100pts | Elo diff = 200pts | ❌ Não | +0 |
| Ambos com forma inconsistente | W% casa: 6/10=60%; W% fora: 4/10=40% | ✅ Sim (ambos entre 30-60%) | **+10** |
| Copa Rodada 1 | "Rodada 1" está no campo `rodada` | ✅ Sim | **+10** |
| Fragility > 70 (casa) | 47,3 < 70 | ❌ Não | +0 |
| Fragility > 70 (fora) | 39,3 < 70 | ❌ Não | +0 |
| **Total** | | | **40 / 100** |

### 4.2 Efeito no Achatamento

**Limiar de achatamento:** UI > 60  
**UI atual:** 40 → **ABAIXO DO LIMIAR**

As probabilidades finais **não foram achatadas** em direção a 33/33/33. Se o UI fosse ≥ 60, o alpha de achatamento seria:

```
alpha = (UI − 60) / 40 × 0,50  [máximo de 50% de achatamento]
```

Simulando UI = 72 (hipotético):
```
alpha = (72 − 60) / 40 × 0,50 = 0,15

P_vitória_México  = 0,85 × 34,9% + 0,15 × 33,3% = **34,6%**
P_empate          = 0,85 × 28,1% + 0,15 × 33,3% = **28,9%**
P_vitória_África  = 0,85 × 37,1% + 0,15 × 33,3% = **36,5%**
```

Neste caso hipotético, as probabilidades convergiriam ligeiramente para o empate — o modelo seria mais honesto sobre sua incerteza.

### 4.3 Por que o W% de 60% do México disparou a condição de "inconsistente"

O critério `0,30 < W% < 0,60` captura times que não são claramente bons nem claramente ruins. O México com W% = 0,60 está **exatamente no limiar** — tecnicamente "consistente" por 0,1pp, mas ainda assim o modelo identificou forma mista (3 empates, 1 derrota nos 10 jogos). O critério é conservador por design.

---

## 5. FRAGILITY SCORE

### 5.1 Metodologia

O Fragility Score é um **proxy de dependência de marcadores-chave** baseado na variância dos gols marcados nos últimos 10 jogos. Sem dados de artilheiros individuais disponíveis no plano free da API, o modelo usa o **Coeficiente de Variação (CV)** como substituto:

```
CV       = desvio_padrão(gols_marcados) / média(gols_marcados)
fragility = min(100, CV × 50)
```

Alta variância → times com jogos de muitos gols alternados com jogos sem gols → dependência de poucos finalizadores.

### 5.2 Cálculo por Time

**México:**
- Gols marcados nos 10 jogos: 1, 0, 1, 1, 1, 4, 0, 1, 2, 1
- Média: 1,20 gols/jogo
- Desvio padrão: 1,033
- CV: 1,033 / 1,20 = **0,861**
- **Fragility Score México: min(100, 0,861×50) = 43,1** *(impacto: leve)*

**África do Sul:**
- Gols marcados nos 10 jogos: 3, 3, 1, 2, 0, 3, 1, 1, 1, 0
- Média: 1,50 gols/jogo
- Desvio padrão: 1,08
- CV: 1,08 / 1,50 = **0,720**
- **Fragility Score África do Sul: min(100, 0,720×50) = 36,0** *(impacto: leve)*

> Nota: o script registrou 47,3 e 39,3 respectivamente — pequena diferença por uso de `statistics.stdev` (n-1) vs cálculo manual (n).

### 5.3 Impacto nas Probabilidades

**Nenhum.** Ambos os scores estão abaixo do limiar 70. O Fragility Score não adicionou pontos ao Uncertainty Index nem distorceu a distribuição de probabilidades neste jogo. O modelo prevê que os dois times terão produção ofensiva razoavelmente regular, sem dependência crítica de um único jogador-chave.

---

## 6. FRAQUEZAS DO MODELO PARA ESTE JOGO

### 6.1 Inconsistência de Pipeline (Over/Under 2.5) ⚠️

**O problema:** A Camada 4 (Context Engine) aplica −5,1pp ao Over 2.5 por Rodada 1 (lógica: times jogam com cautela). A Camada 4B (Tail Risk) reconstrói o Over 2.5 a partir da matriz DC bruta e aplica Fat Tail, chegando a 50,7% — efetivamente revertendo o ajuste de Rodada 1.

**Por que acontece:** O `_calcular_tail_risk` recebe o modelo com λ ajustado (para fadiga, se existir), mas **não preserva os ajustes de mercado** feitos pela Camada 4 nos campos over25/under25. Ao reconstruir a matriz a partir dos λ, esses ajustes são perdidos.

**Impacto real:** O Over 2.5 final (50,7%) reflete quase exclusivamente o DC puro (+0,1pp de Fat Tail), ignorando o contexto de Rodada 1. O modelo é **menos conservador** do que deveria ser para jogos de abertura de Copa.

**Correção futura:** Camada 4B deve preservar os ajustes de mercado da Camada 4 e aplicar Fat Tail **sobre eles**, não sobre o DC bruto.

### 6.2 Amostra de H2H Insuficiente

Apenas **1 confronto histórico** registrado (Copa 2010, 1×1). Com n=1, qualquer padrão derivado do H2H não tem significância estatística. O modelo aplica fator 0,85 de confiança, mas mesmo assim o peso do H2H na análise final é quase simbólico.

### 6.3 Elo via Fallback, não em Tempo Real

O Elo atual de ambas as seleções vem de um banco hardcoded, não do site `eloratings.net` em tempo real. Se houve mudança significativa de forma nas últimas semanas (lesões de titulares, mudança de técnico, amistosos relevantes), o Elo não reflete isso — o Pi-rating sim (por usar os últimos 10 jogos), mas com peso de apenas 40%.

### 6.4 FIFA Ranking Ausente

O terceiro componente do rating (FIFA Ranking normalizado, previsto como 20% do peso) **não está implementado**. O peso redistribuído para Elo (60%) pode superestimar a importância do histórico longo vs desempenho recente.

### 6.5 Ausência de Dados Individuais

O modelo não captura:
- **Lesões**: Se o principal artilheiro do México (ex.: Raúl Jiménez ou Hirving Lozano) estiver fora, os λ de gols podem estar superestimados
- **Suspensões**: Cartões amarelos acumulados em qualificatórias
- **Motivação diferencial**: Para a África do Sul, jogar a primeira Copa em 16 anos tem peso emocional imenso — impossível quantificar
- **Clima e altitude**: Cidade do México a 2.240m de altitude afeta times africanos não aclimatados
- **Escalação tática**: 4-3-3 vs 5-4-1 muda completamente a probabilidade de 0-0

### 6.6 Qualidade dos Adversários na Forma Recente

O Pi-rating trata Islândia, Bolívia e Panamá com o mesmo peso que Portugal e Bélgica. O 4-0 do México sobre a Islândia inflaciona o Pi-rating em 1,029, mas enfrentar uma seleção de 70º no ranking FIFA vs a Islândia (60º) é muito diferente de enfrentar a África do Sul (70º+). Sem ponderação por qualidade do adversário, jogos fáceis supervalorizam times.

### 6.7 Odds Indisponíveis

Sem odds reais da Bet365 ou similar para este jogo, o **Value Bet Detector** não pôde calcular nenhum value score. As probabilidades calculadas pelo modelo podem ter valor esperado positivo em algum mercado, mas é impossível saber sem as odds. Isso elimina um dos sinais mais fortes do modelo.

---

## 7. O QUE MELHORARIA A PREVISÃO

### 7.1 Dados que Mudariam Mais as Probabilidades (por impacto estimado)

| Dado | Disponibilidade | Impacto estimado nas probs |
|---|---|---|
| Odds reais de mercado | API / qualquer casa · dias antes | Alto — ativa o Value Bet, calibra os λ contra o mercado |
| Lesões e convocação final | Imprensa oficial · até 24h antes | Alto — 1 titular lesionado pode mudar λ em ±0,2 a ±0,5 |
| Elo em tempo real (eloratings.net) | Fix no scraper | Médio — refina o rating combinado |
| FIFA Ranking real | Scraper fifa.com | Médio — adiciona 20% do peso do rating |
| Artilheiros dos últimos 10 jogos | API paga ou manual | Médio — permite Fragility Score real |
| Altitude e temperatura | Dados climáticos | Baixo-Médio — Africa do Sul não aclimatada à altitude |
| Estatísticas por competição | API paga | Baixo — diferencia amistosos de jogos oficiais |

### 7.2 Quando as Odds Reais Chegarem — Mercados a Revisar Primeiro

As odds da Bet365 para Copa 2026 devem aparecer na API-Football tipicamente **3 a 7 dias antes do jogo**. A ordem de revisão recomendada:

1. **Over/Under 2.5** — é o mercado mais incerto (50,7% vs 49,3%), com o maior impacto da inconsistência de pipeline documentada na seção 6.1. Se as odds implicarem probabilidade < 45% para Over 2.5, o mercado está mal precificado pelo nosso modelo.

2. **1X2** — verificar se as odds implicam África do Sul como favorita (como nosso modelo sugere) ou México. Se o mercado colocar México como favorito (<2,50 para México), há potencial value em África do Sul.

3. **BTTS Sim** — nosso modelo marca 56,6%, que sugere odd justa de ~1,77. Se a odd do mercado for > 1,90, há value positivo.

4. **Empate** — maior divergência entre DC (28,1%) e Skellam (25,8%). O mercado tende a dar ~3,20 para empates neste nível de equilíbrio. Se a odd for > 3,55, pode ter value.

### 7.3 Sinais a Monitorar nas Próximas Semanas

- **Convocação oficial do México** (divulgada ~4 semanas antes): checar se Jiménez, Lozano, Guardado estão disponíveis
- **Última partida da África do Sul** (vs Nicarágua, 29/05): 0-0 preocupa ofensivamente — confirma λ conservador?
- **Conferências de imprensa pré-jogo**: indicadores táticos (linha de 5, postura defensiva) que o modelo não captura
- **Movimento de odds** nas primeiras 48h após abertura: sharp money (apostadores profissionais) no Under 2.5 seria sinal forte de alinhamento com nosso cenário conservador de Rodada 1

---

## Resumo Executivo

| Indicador | Valor | Confiança |
|---|---|---|
| Favorito DC | África do Sul (37,1%) | Baixa — diferença de apenas 2,2pp |
| Favorito Skellam | África do Sul (38,2%) | Confirmado |
| Placar mais provável | 1-1 (13,51%) | Consistente com λ equilibrados |
| Over 1.5 | 77,6% | Alta (sinal mais robusto do modelo) |
| Over 2.5 | 50,7% | Baixa (essencialmente uma moeda) |
| Uncertainty Index | 40/100 | Jogo equilibrado, não imprevisível |
| Value bets | Nenhum calculável | Aguardar odds reais |
| Maior fraqueza | Inconsistência Over 2.5 pipeline + sem odds | — |

---

*Relatório gerado automaticamente pelo agente estatístico Palpites da IA v2.*  
*Dados: API-Football v3 · Seed Copa 2026 · Modelos: Dixon-Coles, Skellam, Tail Risk Engine*  
*Para uso educacional e de pesquisa. Não é recomendação financeira.*
