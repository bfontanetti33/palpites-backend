# Divergências Conhecidas: Modelo × Mercado

**Última atualização:** 2026-06-05  
**Contexto:** Fase de grupos Copa 2026, modelo com `ALPHA_REG=0.5` (calibração conservadora pré-Copa).

Estas divergências foram analisadas e classificadas como **estruturais e legítimas** — não são bugs.  
O modelo pode estar certo; o mercado é um piso de sanidade, não a verdade absoluta.

---

## 1. Canada × Bosnia & Herzegovina

**Modelo:** Bosnia favorita (~42% fora) | **Mercado:** Canada favorito (~53% casa)  
**Slug:** `canada-bosnia-and-herzegovina` — Rodada 1, Grupo B

### Causa

O lambda-base do Canadá após regressão `α=0.5` é **0.96** — reflexo real de uma seleção com histórico fraco de criação de chances. O `HOME_BOOST=1.25` (baseado em pesquisa empírica de vantagem de campo em torneios internacionais) eleva o lambda final para 1.20, mas Bosnia tem lambda-fora ajustado de 1.48 após `AWAY_PENALTY=0.80`.

O mercado precifica uma **home advantage de anfitrião de abertura** (Canada é co-anfitrião do torneio, jogando no próprio país pela primeira vez em décadas) que vai além do efeito físico de campo. Esse componente de "narrativa" e "pressão do torcedor local em contexto histórico" não está no modelo.

### Sweep realizado (2026-06-05)

| HOME_BOOST | Canada% | Bosnia% | Favorito |
|-----------|---------|---------|---------|
| 1.25 (atual) | 30% | 42% | Bosnia |
| 1.35 | 32% | 40% | Bosnia |
| 1.45 | 34% | 38% | Bosnia |
| 1.55 | 37% | 36% | **Canada** ← mínimo para virar |
| 1.90 | ~53% | ~27% | Canada (iguala mercado) |

### Decisão

**Não aplicar boost aumentado.** Distorcer `HOME_BOOST` de 1.25 para 1.55+ violaria a integridade do modelo para corrigir 1 jogo em 72. O parâmetro foi definido com base em evidência empírica de vantagem de campo — não deve ser inflado para forçar um resultado predeterminado que coincida com o mercado.

A divergência é de **visão sobre o valor do home advantage de anfitrião histórico**, não de dado errado. O modelo pode estar correto.

---

## 2. South Korea × Czech Republic

**Modelo:** Czech Republic favorita (~46% fora) | **Mercado:** South Korea favorito (~35% casa)  
**Slug:** `south-korea-czech-republic` — Rodada 1

### Causa

Jogo genuinamente equilibrado — as odds de mercado são 2.73 (SK) vs 2.88 (CZ), uma diferença de apenas ~4% de probabilidade implícita. A inversão de favorito se dá por ~12 pontos percentuais no modelo, mas em um contexto de altíssima incerteza.

O lambda da República Checa (1.90) é ligeiramente inflado em relação ao que o mercado precifica para o confronto específico. South Korea tem vantagem de campo e o mercado captura isso com mais granularidade.

### Decisão

Manter. O jogo é um toss-up; a divergência é ruído em cima de incerteza real. Recalibrar o alpha após os resultados reais da fase de grupos pode ajustar automaticamente.

---

## 3. Ivory Coast × Ecuador

**Modelo:** Ivory Coast favorita (~59% casa) | **Mercado:** Ecuador favorito (~40% fora)  
**Slug:** `ivory-coast-ecuador` — Rodada 1

### Causa

**Lambda da Costa do Marfim inflado:** média de gols recente elevada (1.90 base) não reflete o nível competitivo real do adversário específico. Ecuador é uma seleção CONMEBOL sólida cujo nível está subrepresentado nos dados de forma recente do modelo — o dataset de confrontos internacionais não pondera suficientemente a qualidade da CONMEBOL.

O mercado precifica Ecuador como ligeiro favorito, incorporando o histórico de desempenho sul-americano em Copas (melhor aproveitamento histórico de times CONMEBOL vs CAF no mata-mata).

### Decisão

Manter. Divergência de dado real (lambda IC) que se ajustará com calibração Fase 2.

---

## 4. Ghana × Panama

**Modelo:** Panama favorito (~52% fora) | **Mercado:** Ghana favorito (~47% casa)  
**Slug:** `ghana-panama` — Rodada 1

### Causa

**Lambda do Panama inflado:** o dado de forma recente do Panama inclui boas campanhas em confrontos CONCACAF, que têm nível competitivo abaixo do que o modelo generaliza para Copas do Mundo. O lambda-base de 1.80 para o Panama supera o que o mercado precifica para um time que participou apenas da Copa 2018 (com desempenho modesto).

Ghana é bem precificado pelo mercado, que aplica desconto ao Panama por inexperiência e ao nível da zona CONCACAF.

### Decisão

Manter. Assim como Ivory Coast, ajusta com Fase 2.

---

## Resumo

| Jogo | Modelo fav. | Mercado fav. | Causa primária | Ação |
|------|-------------|--------------|----------------|------|
| Canada × Bosnia | Bosnia | Canada | lambda-base CA baixo + home advantage anfitrião não capturado | Não corrigir — decisão consciente |
| South Korea × Czech Rep. | Czech Rep. | South Korea | jogo equilibrado, ~12pt diferença em toss-up | Não corrigir — ruído natural |
| Ivory Coast × Ecuador | Ivory Coast | Ecuador | lambda IC inflado, força CONMEBOL subprecificada | Recalibrará com Fase 2 |
| Ghana × Panama | Panama | Ghana | lambda Panama inflado (forma CONCACAF superestimada) | Recalibrará com Fase 2 |

**4 de 27 jogos com odds disponíveis** = 14.8% de inversão de favorito com `ALPHA_REG=0.5`.  
Comparativo: `ALPHA_REG=1.0` (sem regressão) tinha 5 inversões; `ALPHA_REG=0.65` (ótimo Brier) teria 4.

---

## Referências

- `scripts/calibrar_alpha.py` — calibração alpha (Fase 1 vs mercado, Fase 2 vs resultados reais)
- `docs/backtest_viabilidade.md` — plano de recalibração após fase de grupos 2026
- `app/agents/ia_agent.py:ALPHA_REG` — parâmetro aplicado, com comentário de recalibração
- Sweep Canada-Bosnia realizado em 2026-06-05 com `scripts/calibrar_alpha.py --compare 0.5` e simulação inline
