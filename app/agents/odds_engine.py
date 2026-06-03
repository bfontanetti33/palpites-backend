"""
Odds Engine — Camada 3 (substituição) do ia_agent.py
Pipeline estatístico robusto: Shin Method, consensus ponderado, z-score, value bets.

Regra crítica: se não há odds reais disponíveis, retorna odds_disponiveis=False
e NUNCA simula ou estima odds próprias.
"""
import math
import statistics
from typing import Any

# ── Pesos por qualidade de casa ───────────────────────────────────────────────
# Pinnacle = sharp money; Betfair exchange = zero margem; recreativas = baixo peso
BOOKMAKER_WEIGHTS: dict[str, float] = {
    "pinnacle":    1.00,
    "betfair":     0.95,
    "bet365":      0.85,
    "unibet":      0.75,
    "williamhill": 0.70,
    "bwin":        0.65,
    "betway":      0.60,
    "default":     0.50,
}


def _normalizar_bm(key: str) -> str:
    """Lowercase + remove underscores, hífens e sufixos regionais (eu, au, us)."""
    k = key.lower().replace("-", "").replace("_", "").replace(" ", "")
    for suf in ("exeu", "eu", "au", "us", "uk", "br"):
        if k.endswith(suf) and len(k) > len(suf) + 2:
            k = k[: -len(suf)]
    return k


def _peso_bm(key: str) -> float:
    k = _normalizar_bm(key)
    for bm_key, w in BOOKMAKER_WEIGHTS.items():
        if bm_key == "default":
            continue
        if bm_key in k or k in bm_key:
            return w
    return BOOKMAKER_WEIGHTS["default"]


# ── Shin (1993) ───────────────────────────────────────────────────────────────

def shin_probabilities(odds_list: list[float]) -> list[float]:
    """
    Método de Shin (1993) — remove margem via parâmetro z (insider trading).
    Usa entradas não-normalizadas para obter o z correto.

    Passos:
    1. q_i = 1/odd_i   (probabilidade implícita bruta, soma > 1)
    2. Solve para z: sum(p_i(z)) = 1
       onde p_i(z) = (sqrt(z² + 4*(1-z)*q_i²) - z) / (2*(1-z))
    3. Retorna p_i normalizados
    """
    q = [1.0 / o for o in odds_list]

    def _compute(z: float) -> list[float]:
        out = []
        denom = 2.0 * (1.0 - z)
        for qi in q:
            if abs(denom) < 1e-10:
                out.append(1.0 / len(q))
                continue
            inner = z * z + 4.0 * (1.0 - z) * qi * qi
            numer = math.sqrt(max(inner, 0.0)) - z
            out.append(numer / denom)
        return out

    # At z=0: sum = sum(q_i) > 1. Increase z until sum = 1.
    lo, hi = 0.0, 1.0 - 1e-9
    for _ in range(200):
        z = (lo + hi) / 2.0
        probs = _compute(z)
        s = sum(probs)
        if abs(s - 1.0) < 1e-9:
            break
        if s > 1.0:
            lo = z
        else:
            hi = z

    probs = _compute((lo + hi) / 2.0)
    total = sum(probs) or 1.0
    return [p / total for p in probs]


# ── Detecção de Sharp Money ───────────────────────────────────────────────────

def detectar_sharp_money(
    odds_atuais: dict[str, float],
    odds_abertura: dict[str, float] | None,
) -> dict:
    """
    Compara odds atuais vs abertura.
    Movimento > 15% numa direção → sharp_money_detected = True.
    Se odds_abertura=None → detectado=None.
    """
    if odds_abertura is None:
        return {
            "detectado": None,
            "direcao": None,
            "magnitude": None,
            "descricao": "Sem dados de odds de abertura disponíveis",
        }

    _MAP = {"home": "vitoria_casa", "draw": "empate", "away": "vitoria_fora"}
    maior_mov = 0.0
    dir_principal: str | None = None

    for res, chave in _MAP.items():
        o_atual = odds_atuais.get(chave)
        o_ab    = odds_abertura.get(chave)
        if not o_atual or not o_ab or o_atual <= 0 or o_ab <= 0:
            continue
        # Queda de odd = mais dinheiro nesse resultado (sharp bet IN)
        mov = (o_ab - o_atual) / o_ab
        if abs(mov) > abs(maior_mov):
            maior_mov      = mov
            dir_principal  = res

    detectado = abs(maior_mov) > 0.15
    if not detectado:
        return {
            "detectado": False,
            "direcao": None,
            "magnitude": round(abs(maior_mov), 3),
            "descricao": "Sem movimento significativo de linha",
        }

    label = {"home": "casa", "draw": "empate", "away": "fora"}.get(dir_principal or "", "?")
    pct   = round(abs(maior_mov) * 100, 1)
    return {
        "detectado": True,
        "direcao":   dir_principal,
        "magnitude": round(abs(maior_mov), 3),
        "descricao": (
            f"Apostadores profissionais moveram a odd do {label} em {pct}% "
            f"— sinal de dinheiro esperto no mercado"
        ),
    }


# ── Mediana ponderada ─────────────────────────────────────────────────────────

def _weighted_median(values: list[float], weights: list[float]) -> float:
    if not values:
        return 0.0
    pairs = sorted(zip(values, weights), key=lambda x: x[0])
    total_w = sum(weights) or 1.0
    cum_w   = 0.0
    for v, w in pairs:
        cum_w += w
        if cum_w >= total_w / 2.0:
            return v
    return pairs[-1][0]


# ── Consensus robusto ─────────────────────────────────────────────────────────

def calcular_consensus(bookmakers_h2h: list[dict]) -> dict | None:
    """
    Para cada resultado (home/draw/away):
    1. Aplica Shin Method em cada bookmaker individualmente
    2. Pondera pela qualidade (BOOKMAKER_WEIGHTS)
    3. Usa MEDIANA ponderada (resistente a outliers)
    Retorna {home, draw, away, metodo} ou None se sem dados.
    """
    home_probs: list[float] = []
    draw_probs: list[float] = []
    away_probs: list[float] = []
    weights:    list[float] = []
    margens:    list[float] = []

    for bm in bookmakers_h2h:
        h = bm.get("home", 0)
        d = bm.get("draw", 0)
        a = bm.get("away", 0)
        if not h or not d or not a or h <= 0 or d <= 0 or a <= 0:
            continue
        try:
            shin_p = shin_probabilities([h, d, a])
        except Exception:
            # Fallback: normalização simples
            impl   = [1/h, 1/d, 1/a]
            total  = sum(impl) or 1.0
            shin_p = [x / total for x in impl]

        margem = round(1/h + 1/d + 1/a - 1.0, 4)
        margens.append(margem)
        w = _peso_bm(bm.get("key", ""))

        home_probs.append(shin_p[0])
        draw_probs.append(shin_p[1])
        away_probs.append(shin_p[2])
        weights.append(w)

    if not home_probs:
        return None

    p_home = _weighted_median(home_probs, weights)
    p_draw = _weighted_median(draw_probs, weights)
    p_away = _weighted_median(away_probs, weights)

    # Normaliza para garantir soma = 1
    total = p_home + p_draw + p_away or 1.0
    p_home = round(p_home / total, 4)
    p_draw = round(p_draw / total, 4)
    p_away = round(1.0 - p_home - p_draw, 4)

    return {
        "home":         p_home,
        "draw":         p_draw,
        "away":         p_away,
        "n_casas":      len(home_probs),
        "margem_media": round(statistics.mean(margens), 4) if margens else None,
        "metodo":       "shin_mediana_ponderada",
    }


# ── Z-score ───────────────────────────────────────────────────────────────────

def calcular_z_score(
    prob_modelo: float,
    prob_consenso: float,
    n_casas: int,
) -> float:
    """
    Testa se divergência modelo vs mercado é estatisticamente significativa.
    prob_modelo e prob_consenso em [0, 1].

    |z| > 1.65 → 10%  |z| > 1.96 → 5%  |z| > 2.58 → 1%
    """
    se = math.sqrt(prob_consenso * (1.0 - prob_consenso) / max(n_casas, 1))
    return round((prob_modelo - prob_consenso) / se, 4) if se > 1e-10 else 0.0


# ── Função principal ──────────────────────────────────────────────────────────

def processar_odds(
    odds_raw: dict | None,
    prob_modelo: dict[str, float],
) -> dict:
    """
    Recebe odds brutas da The Odds API + probabilidades do modelo (escala 0-1).
    Retorna análise completa com consensus Shin, z-score e value bets.

    REGRA CRÍTICA: se odds_raw=None → retorna odds_disponiveis=False.
    NUNCA simula ou estima odds próprias.
    """
    _vazio: dict[str, Any] = {
        "odds_disponiveis": False,
        "n_casas": 0,
        "margem_media": None,
        "sharp_money": {
            "detectado": None, "direcao": None,
            "magnitude": None, "descricao": "Odds não disponíveis",
        },
        "consensus":   None,
        "fair_odds":   None,
        "divergencia": None,
        "value_bets":  [],
    }

    if not odds_raw:
        return _vazio

    # Coleta bookmakers para consensus
    bms_h2h: list[dict] = odds_raw.get("bookmakers_h2h", [])

    # Fallback: usa o bookmaker principal se não há lista completa
    if not bms_h2h:
        h = odds_raw.get("vitoria_casa")
        d = odds_raw.get("empate")
        a = odds_raw.get("vitoria_fora")
        if h and d and a and h > 0 and d > 0 and a > 0:
            bms_h2h = [{"key": odds_raw.get("bookmaker", "default"), "home": h, "draw": d, "away": a}]

    if not bms_h2h:
        return _vazio

    # Consensus
    consensus = calcular_consensus(bms_h2h)
    if not consensus:
        return _vazio

    n_casas      = consensus["n_casas"]
    margem_media = consensus["margem_media"]

    # Fair odds (1 / prob_consenso)
    fair_odds = {
        "home": round(1.0 / consensus["home"], 3) if consensus["home"] > 0 else None,
        "draw": round(1.0 / consensus["draw"], 3) if consensus["draw"] > 0 else None,
        "away": round(1.0 / consensus["away"], 3) if consensus["away"] > 0 else None,
    }

    # Sharp money
    abertura = odds_raw.get("odds_abertura")  # None se não disponível
    sharp = detectar_sharp_money(
        {"vitoria_casa": odds_raw.get("vitoria_casa"), "empate": odds_raw.get("empate"),
         "vitoria_fora": odds_raw.get("vitoria_fora")},
        abertura,
    )

    # Divergência modelo vs consensus (1X2)
    _RES_MAP = {
        "home": "vitoria_casa",
        "draw": "empate",
        "away": "vitoria_fora",
    }
    divergencia: dict[str, dict] = {}
    for res, campo in _RES_MAP.items():
        p_mod  = prob_modelo.get(campo, 0.0)
        p_cons = consensus.get(res, 0.0)
        if p_cons <= 0:
            divergencia[res] = {
                "prob_modelo":   round(p_mod, 4),
                "prob_consenso": None,
                "z_score":       None,
                "significativo": False,
            }
            continue
        z = calcular_z_score(p_mod, p_cons, n_casas)
        divergencia[res] = {
            "prob_modelo":   round(p_mod, 4),
            "prob_consenso": round(p_cons, 4),
            "z_score":       z,
            "significativo": abs(z) > 1.96,
        }

    # Value bets (só para 1X2; requer z > 1.65 = significativo a 10%)
    value_bets: list[dict] = []
    for res in ("home", "draw", "away"):
        div = divergencia.get(res, {})
        z   = div.get("z_score")
        if z is None or abs(z) <= 1.65:
            continue
        p_mod  = div["prob_modelo"]
        p_cons = div["prob_consenso"]
        fo     = fair_odds.get(res)
        if not fo or fo <= 0 or not p_cons:
            continue
        vs = round(p_mod * fo - 1.0, 4)  # value_score = (prob_modelo * fair_odd) - 1
        confianca = (
            "alta"  if abs(z) > 2.58 else
            "media" if abs(z) > 1.96 else
            "baixa"
        )
        sharp_confirma = (
            bool(sharp.get("detectado"))
            and sharp.get("direcao") == res
        )
        value_bets.append({
            "resultado":      res,
            "prob_modelo":    round(p_mod, 4),
            "prob_consenso":  round(p_cons, 4),
            "z_score":        round(z, 4),
            "value_score":    vs,
            "confianca":      confianca,
            "sharp_confirma": sharp_confirma,
        })

    value_bets.sort(key=lambda x: -(x["z_score"] * max(x["value_score"], 0)))

    return {
        "odds_disponiveis": True,
        "n_casas":          n_casas,
        "margem_media":     margem_media,
        "sharp_money":      sharp,
        "consensus":        {
            "home":   consensus["home"],
            "draw":   consensus["draw"],
            "away":   consensus["away"],
            "metodo": consensus["metodo"],
        },
        "fair_odds":  fair_odds,
        "divergencia": divergencia,
        "value_bets":  value_bets,
    }


# ── Critérios de Bingo ────────────────────────────────────────────────────────

_BINGO_PERMITIDOS = {"over15", "over25", "btts_sim", "vitoria_casa", "chance_dupla_1x", "chance_dupla_x2"}
_BINGO_PROIBIDOS  = {"under15", "under25", "under35", "vitoria_fora", "placar_exato"}

def e_candidato_bingo(
    prob_modelo: float,      # [0, 100]
    fair_odd: float,
    value_score: float,
    z_score: float,
    mercado: str,
    uncertainty_index: float = 0.0,
    odds_disponiveis: bool = True,
) -> bool:
    """
    Retorna True se o mercado/jogo é um candidato válido para acumulada Bingo.
    prob_modelo em [0, 100].
    """
    if not odds_disponiveis:
        return False
    if uncertainty_index > 70:
        return False
    mercado_l = mercado.lower().replace(" ", "_")
    if any(p in mercado_l for p in _BINGO_PROIBIDOS):
        return False
    return (
        prob_modelo > 60.0
        and fair_odd > 1.30
        and value_score >= 0.0
        and z_score > 1.65
    )


def compor_bingo(candidatos: list[dict]) -> list[dict]:
    """
    Compõe acumulada Bingo a partir de candidatos válidos.
    Cada candidato deve ter: {slug, mercado, prob_modelo, fair_odd, value_score, z_score}
    Regras: jogos diferentes, 3-5 seleções, odd total 2.0-8.0.
    Ordena por z_score * value_score (combinação significância + valor).
    """
    # Ordena por relevância
    ordenados = sorted(
        candidatos,
        key=lambda x: -(x.get("z_score", 0) * max(x.get("value_score", 0), 0.001)),
    )

    slugs_vistos: set = set()
    selecionados: list[dict] = []
    odd_total = 1.0

    for c in ordenados:
        slug = c.get("slug", "")
        if slug in slugs_vistos:
            continue
        odd_nova = odd_total * c.get("fair_odd", 1.0)
        if odd_nova > 8.0:
            continue
        selecionados.append(c)
        slugs_vistos.add(slug)
        odd_total = odd_nova
        if len(selecionados) == 5:
            break

    if len(selecionados) < 3:
        return []  # acumulada insuficiente

    if odd_total < 2.0:
        return []  # sem valor mínimo

    return selecionados
