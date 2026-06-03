"""
Agente estatístico avançado — 5 camadas + 4B.

CAMADA 1   Rating Dinâmico  : Elo (eloratings.net scraping + fallback) + Pi-rating próprio
CAMADA 2   Modelo de Gols   : Dixon-Coles + Skellam + calibração
CAMADA 3   Odds Engine      : Shin Method + consensus ponderado + z-score + value bets
CAMADA 4   Context Engine   : fadiga, rodada, zebra (critérios robustos), H2H, campo neutro
CAMADA 4B  Tail Risk Engine : Fat Tail (Taleb), Fragility, Uncertainty, Barbell
CAMADA 5   Claude (narrativa): só texto, nunca inventa dados

Separação rígida:
  API-Football  → dados brutos (imutáveis)
  Camadas 1-4B  → probabilidades e scores (calculados)
  Camada 5      → narrativa (baseada nos outputs acima)
"""
import math
import os
import re
import statistics
from datetime import datetime, date

import httpx
from anthropic import AsyncAnthropic

from app.models.schemas import (
    EntradaForma, FatorContexto, MercadoRecomendado,
    ModeloGols, Partida, RecomendacaoIA, RatingDinamico,
    TailRiskResult,
)

_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""), timeout=45.0)

# ── Constantes ────────────────────────────────────────────────────────────────
GLOBAL_AVG   = 1.2      # média de gols por time por jogo no futebol internacional
DECAY        = 0.98     # decaimento temporal por dia
DC_RHO       = -0.1     # correção Dixon-Coles para placares baixos
MAX_GOALS    = 6        # máximo de gols na matriz (0..5)
VALUE_MIN    = 0.05     # value mínimo para recomendar (5%)
ELO_CENTER   = 1500.0   # centro de normalização do Elo
ELO_SCALE    = 200.0    # escala (±1 SD ≈ 200 pontos)

# ── PONTO 3: Elo fallback abrangente para todos os 48 times da Copa 2026 ─────
# eloratings.net é um SPA (Single Page App) — não retorna dados no HTML estático.
# Fallback calculado com base em valores históricos públicos (Elo World Football, abril/2026).
_ELO_FALLBACK: dict[str, float] = {
    "Argentina": 2142, "France": 2003, "Spain": 1989, "England": 1972,
    "Portugal": 1946, "Germany": 1930, "Netherlands": 1907, "Brazil": 1900,
    "Belgium": 1874, "Colombia": 1874, "Uruguay": 1867, "Morocco": 1856,
    "USA": 1853, "United States": 1853, "Japan": 1849, "Mexico": 1841,
    "Croatia": 1838, "Senegal": 1825, "Switzerland": 1824, "Ecuador": 1788,
    "South Korea": 1782, "Australia": 1781, "Austria": 1780, "Norway": 1779,
    "Türkiye": 1770, "Turkey": 1770, "Iran": 1760, "Canada": 1756,
    "Sweden": 1745, "Ivory Coast": 1740, "Algeria": 1720, "Paraguay": 1718,
    "Egypt": 1715, "Ghana": 1700, "Tunisia": 1698, "Saudi Arabia": 1695,
    "Czech Republic": 1694, "Czechia": 1694, "Scotland": 1690,
    "South Africa": 1641, "Panama": 1605, "New Zealand": 1598,
    "Jordan": 1590, "Iraq": 1585, "Haiti": 1560,
    "Cape Verde Islands": 1555, "Curaçao": 1540, "Qatar": 1530,
    "Uzbekistan": 1525, "Bosnia & Herzegovina": 1520, "Congo DR": 1515,
}

# ── PONTO 4: Mapeamento confederação → times da Copa 2026 ─────────────────────
_CONFEDERACAO: dict[str, str] = {
    # CONMEBOL
    "Brazil": "CONMEBOL", "Argentina": "CONMEBOL", "Colombia": "CONMEBOL",
    "Ecuador": "CONMEBOL", "Paraguay": "CONMEBOL", "Uruguay": "CONMEBOL",
    # UEFA
    "Germany": "UEFA", "France": "UEFA", "Spain": "UEFA", "England": "UEFA",
    "Portugal": "UEFA", "Netherlands": "UEFA", "Belgium": "UEFA",
    "Switzerland": "UEFA", "Croatia": "UEFA", "Austria": "UEFA",
    "Sweden": "UEFA", "Norway": "UEFA", "Scotland": "UEFA",
    "Bosnia & Herzegovina": "UEFA", "Czech Republic": "UEFA", "Czechia": "UEFA",
    "Türkiye": "UEFA", "Turkey": "UEFA",
    # CONCACAF
    "Mexico": "CONCACAF", "USA": "CONCACAF", "United States": "CONCACAF",
    "Canada": "CONCACAF", "Panama": "CONCACAF", "Haiti": "CONCACAF",
    "Curaçao": "CONCACAF",
    # CAF
    "Morocco": "CAF", "Senegal": "CAF", "Ivory Coast": "CAF", "Egypt": "CAF",
    "Tunisia": "CAF", "Ghana": "CAF", "South Africa": "CAF", "Congo DR": "CAF",
    "Algeria": "CAF", "Cape Verde Islands": "CAF",
    # AFC
    "Japan": "AFC", "South Korea": "AFC", "Saudi Arabia": "AFC", "Iran": "AFC",
    "Iraq": "AFC", "Australia": "AFC", "Qatar": "AFC", "Uzbekistan": "AFC",
    "Jordan": "AFC",
    # OFC
    "New Zealand": "OFC",
}

# ── PONTO 2: FIFA Ranking dos 48 times da Copa 2026 ──────────────────────────
# Fontes: Wikipedia FIFA World Rankings + estimativas (abril/2026).
# posição MUNDIAL (1 = melhor do mundo). Normalização usa posição ENTRE OS 48 DA COPA.
_FIFA_RANKING: dict[str, int] = {
    "France": 1, "Spain": 2, "Argentina": 3, "England": 4,
    "Portugal": 5, "Brazil": 6, "Netherlands": 7, "Morocco": 8,
    "Belgium": 9, "Germany": 10, "Croatia": 11, "Colombia": 13,
    "Senegal": 14, "Mexico": 15, "Uruguay": 16, "Switzerland": 19,
    "USA": 11, "United States": 11, "Japan": 17, "South Korea": 22,
    "Australia": 23, "Austria": 24, "Norway": 23, "Türkiye": 27,
    "Turkey": 27, "Algeria": 30, "Sweden": 34, "Czech Republic": 36,
    "Czechia": 36, "Tunisia": 38, "Iran": 44, "Saudi Arabia": 48,
    "Ivory Coast": 51, "Paraguay": 52, "Qatar": 53, "Uzbekistan": 58,
    "Egypt": 40, "Scotland": 40, "Bosnia & Herzegovina": 58,
    "Ghana": 62, "Cape Verde Islands": 64, "Jordan": 66, "Iraq": 66,
    "South Africa": 68, "Panama": 75, "Congo DR": 76, "Haiti": 83,
    "Curaçao": 85, "New Zealand": 101, "Canada": 48,
    "Ecuador": 44,
}

# Pré-computa stats regionais (Elo) para os 48 times da Copa 2026
def _stats_regionais() -> dict[str, dict]:
    """Média e desvio do Elo de cada confederação entre os 48 times da Copa."""
    conf_elos: dict[str, list[float]] = {}
    for team, conf in _CONFEDERACAO.items():
        elo = _ELO_FALLBACK.get(team)
        if elo is not None:
            conf_elos.setdefault(conf, []).append(elo)
    result: dict[str, dict] = {}
    for conf, elos in conf_elos.items():
        media = statistics.mean(elos)
        std   = statistics.stdev(elos) if len(elos) > 1 else 1.0
        result[conf] = {"media": round(media, 1), "std": round(std, 1), "n": len(elos)}
    return result

_STATS_REGIONAIS = _stats_regionais()

def _copa_fifa_rank() -> dict[str, int]:
    """
    Ordena os 48 times pelo FIFA Ranking mundial e atribui posição 1-48 entre eles.
    Times não encontrados ficam em último.
    """
    copa_times = list({t for t in _CONFEDERACAO if t in _FIFA_RANKING})
    copa_times.sort(key=lambda t: _FIFA_RANKING[t])
    return {team: pos + 1 for pos, team in enumerate(copa_times)}

_COPA_FIFA_RANK = _copa_fifa_rank()

# Cache para scraping Wikipedia (dura a sessão)
_wiki_rankings: dict[str, int] | None = None


async def _buscar_fifa_ranking_wikipedia() -> dict[str, int]:
    """
    Extrai o FIFA ranking da Wikipedia.
    Retorna dict {nome_time: posicao_mundial} ou {} se falhar.
    """
    global _wiki_rankings
    if _wiki_rankings is not None:
        return _wiki_rankings
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get(
                "https://en.wikipedia.org/wiki/FIFA_World_Rankings",
                headers={"User-Agent": "Mozilla/5.0 (compatible; bot)"},
            )
        html = r.text
        rows = re.findall(
            r'<tr[^>]*>.*?<td[^>]*>\s*(\d{1,3})\s*</td>.*?title="([^"]+)">([^<]+)</a>.*?</tr>',
            html, re.DOTALL
        )
        result = {}
        for rank_str, _, country in rows:
            rank = int(rank_str)
            if 1 <= rank <= 210:
                result[country.strip()] = rank
        _wiki_rankings = result
        return result
    except Exception:
        _wiki_rankings = {}
        return {}


# Cache de Elo (sessão)
_elo_cache: dict[str, float | None] = {}


# ════════════════════════════════════════════════════════════════════════════════
# CAMADA 1 — Rating Dinâmico (Elo + Pi-rating + FIFA Ranking + Normalização Regional)
# ════════════════════════════════════════════════════════════════════════════════

async def _buscar_elo_web(team_name: str) -> tuple[float | None, str]:
    """
    PONTO 3: Tenta scraping de eloratings.net.
    O site é um SPA — retorna HTML shell de 1.8KB sem dados.
    Detecta SPA e usa fallback imediatamente.
    Retorna (valor, fonte).
    """
    if team_name in _elo_cache:
        val = _elo_cache[team_name]
        fonte = "eloratings.net" if val else "fallback"
        return _ELO_FALLBACK.get(team_name, val), fonte

    try:
        async with httpx.AsyncClient(timeout=6, follow_redirects=True) as c:
            r = await c.get("https://www.eloratings.net/World",
                            headers={"User-Agent": "Mozilla/5.0"})
        # SPA detection: página real tem >50KB; shell tem ~1.8KB
        if len(r.text) < 5000:
            raise ValueError("SPA detectado — sem dados no HTML estático")
        # Tenta extrair pelo nome do time
        pattern = rf"{re.escape(team_name)}[\s\S]{{0,150}}?(\d{{4}})"
        m = re.search(pattern, r.text, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if 1200 <= val <= 2400:
                _elo_cache[team_name] = val
                return val, "eloratings.net"
    except Exception:
        pass

    # Fallback dict
    fb = _ELO_FALLBACK.get(team_name)
    _elo_cache[team_name] = fb
    return fb, "fallback"


def _calcular_pi_rating(forma: list[EntradaForma], data_jogo: str) -> float:
    ref = datetime.strptime(data_jogo[:10], "%Y-%m-%d").date()
    total_w = total_v = 0.0
    for j in forma:
        if j.placar_proprio is None or j.placar_adversario is None:
            continue
        try:
            gd = j.placar_proprio - j.placar_adversario
            dias = max(0, (ref - datetime.strptime(j.data, "%Y-%m-%d").date()).days)
            w = DECAY ** dias
            total_w += w
            total_v += (gd / GLOBAL_AVG) * w
        except ValueError:
            continue
    return round(total_v / total_w, 3) if total_w > 0 else 0.0


async def _calcular_rating(
    team_name: str,
    forma: list[EntradaForma],
    data_jogo: str,
    wiki_rankings: dict[str, int] | None = None,
) -> RatingDinamico:
    """
    PONTO 2+3+4: Calcula rating dinâmico completo.
    Componentes: 50% Elo + 30% Pi-rating + 20% FIFA Ranking normalizado.
    Inclui normalização regional (z-score dentro da confederação na Copa).
    """
    # Elo
    elo, fonte_elo = await _buscar_elo_web(team_name)
    pi = _calcular_pi_rating(forma, data_jogo)

    # FIFA Ranking (PONTO 2)
    # Tenta Wikipedia primeiro, depois fallback hardcoded
    fifa_mundial: int | None = None
    if wiki_rankings:
        fifa_mundial = wiki_rankings.get(team_name)
    if fifa_mundial is None:
        fifa_mundial = _FIFA_RANKING.get(team_name)

    fifa_copa_pos = _COPA_FIFA_RANK.get(team_name)
    fifa_norm: float | None = None
    if fifa_copa_pos is not None:
        fifa_norm = round((48 - fifa_copa_pos) / 47, 3)
    fifa_disponivel = fifa_mundial is not None

    # Normalização regional (PONTO 4)
    conf = _CONFEDERACAO.get(team_name, "")
    stats_reg = _STATS_REGIONAIS.get(conf, {})
    elo_z: float | None = None
    elo_rank_reg: int | None = None
    if elo is not None and stats_reg:
        elo_z = round((elo - stats_reg["media"]) / max(stats_reg["std"], 1.0), 3)
        # Rank dentro da confederação (1 = melhor Elo da conf na Copa)
        conf_times = [(t, _ELO_FALLBACK[t]) for t, c in _CONFEDERACAO.items()
                      if c == conf and t in _ELO_FALLBACK]
        conf_times.sort(key=lambda x: -x[1])
        rank_map = {t: i+1 for i, (t, _) in enumerate(conf_times)}
        elo_rank_reg = rank_map.get(team_name)

    # Rating combinado
    elo_norm = (elo - ELO_CENTER) / ELO_SCALE if elo is not None else 0.0

    if elo is not None and fifa_norm is not None:
        # FIFA normalizado está em [0,1]; converte para escala similar ao elo_norm (~[-1,+2])
        fifa_escala = (fifa_norm * 3.0) - 1.0  # 0→-1.0, 0.5→0.5, 1.0→2.0
        combinado = round(0.50 * elo_norm + 0.30 * pi + 0.20 * fifa_escala, 3)
        formula = "50% Elo + 30% Pi + 20% FIFA"
    elif elo is not None:
        combinado = round(0.60 * elo_norm + 0.40 * pi, 3)
        formula = "60% Elo + 40% Pi (sem FIFA)"
    else:
        combinado = round(pi, 3)
        formula = "100% Pi (sem Elo nem FIFA)"

    return RatingDinamico(
        elo_score=elo,
        fonte_elo=fonte_elo,
        pi_rating=pi,
        fifa_ranking=fifa_mundial,
        fifa_ranking_copa=fifa_copa_pos,
        fifa_normalizado=fifa_norm,
        fifa_ranking_disponivel=fifa_disponivel,
        confederacao=conf,
        elo_rank_regional=elo_rank_reg,
        media_elo_regiao=stats_reg.get("media"),
        std_elo_regiao=stats_reg.get("std"),
        elo_z_regional=elo_z,
        rating_combinado=combinado,
        formula_usada=formula,
    )


# ════════════════════════════════════════════════════════════════════════════════
# CAMADA 2 — Modelo de Gols (Dixon-Coles + Skellam)
# ════════════════════════════════════════════════════════════════════════════════

def _poisson(lam: float, k: int) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def _tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """Correção Dixon-Coles para sub-representação de placares baixos."""
    if x == 0 and y == 0: return 1 - lam * mu * rho
    if x == 0 and y == 1: return 1 + lam * rho
    if x == 1 and y == 0: return 1 + mu * rho
    if x == 1 and y == 1: return 1 - rho
    return 1.0


def _bessel_i(n: int, x: float, termos: int = 25) -> float:
    """
    Função de Bessel modificada I_n(x) via série de Taylor.
    Converge rapidamente para |x| < 10, |n| < 7.
    """
    n = abs(n)
    result = 0.0
    half_x = x / 2.0
    for k in range(termos):
        num = half_x ** (n + 2 * k)
        den = math.factorial(k) * math.factorial(k + n)
        result += num / den if den != 0 else 0
    return result


def _skellam_pmf(k: int, lam1: float, lam2: float) -> float:
    """
    P(X - Y = k) onde X~Poisson(λ1), Y~Poisson(λ2).
    Fórmula: e^{-(λ1+λ2)} * (λ1/λ2)^{k/2} * I_|k|(2√(λ1·λ2))
    """
    if lam1 <= 0 or lam2 <= 0:
        return 1.0 if k == 0 else 0.0
    try:
        ratio = (lam1 / lam2) ** (k / 2.0)
        bessel = _bessel_i(k, 2 * math.sqrt(lam1 * lam2))
        return math.exp(-(lam1 + lam2)) * ratio * bessel
    except (ValueError, OverflowError):
        return 0.0


def _lambdas_from_ratings(
    rating_casa: RatingDinamico,
    rating_fora: RatingDinamico,
    stats_casa,
    stats_fora,
    forma_casa: list[EntradaForma],
    forma_fora: list[EntradaForma],
) -> tuple[float, float]:
    """
    Estima λ de cada time combinando rating combinado com médias de gols recentes.
    Rating combinado modula o ataque/defesa relativo ao GLOBAL_AVG.
    """
    # Força de ataque baseada no rating (+1 SD → +10% gols esperados)
    ataque_casa = max(0.5, 1.0 + rating_casa.rating_combinado * 0.10)
    ataque_fora = max(0.5, 1.0 + rating_fora.rating_combinado * 0.10)
    # Força defensiva inversa (quanto maior o rating, menos gols leva)
    defesa_fora = max(0.5, 1.0 - rating_fora.rating_combinado * 0.08)
    defesa_casa = max(0.5, 1.0 - rating_casa.rating_combinado * 0.08)

    # Médias recentes de gols como âncora (se disponíveis)
    avg_gols_casa = stats_casa.media_gols_marcados_recente or stats_casa.media_gols_marcados or GLOBAL_AVG
    avg_gols_fora = stats_fora.media_gols_marcados_recente or stats_fora.media_gols_marcados or GLOBAL_AVG

    # Lambda = média recente ajustada pelo fator de força relativa
    lc = round(avg_gols_casa * ataque_casa * defesa_fora, 3)
    lf = round(avg_gols_fora * ataque_fora * defesa_casa, 3)

    # Limites razoáveis para futebol internacional
    return max(0.3, min(lc, 4.0)), max(0.3, min(lf, 4.0))


def _dc_matrix(lam: float, mu: float) -> dict[str, float]:
    """Gera a matriz de probabilidades Dixon-Coles normalizada (0-0 até 5-5)."""
    raw: dict[str, float] = {}
    for i in range(MAX_GOALS):
        for j in range(MAX_GOALS):
            p = _poisson(lam, i) * _poisson(mu, j) * _tau(i, j, lam, mu, DC_RHO)
            raw[f"{i}-{j}"] = max(p, 0.0)
    total = sum(raw.values()) or 1.0
    return {k: round(v / total * 100, 2) for k, v in raw.items()}


def _market_probs(matrix: dict[str, float], lam: float, mu: float) -> dict[str, float]:
    def parse(k: str) -> tuple[int, int]:
        a, b = k.split("-")
        return int(a), int(b)

    def s(cond) -> float:
        return round(sum(v for k, v in matrix.items() if cond(*parse(k))), 1)

    p_vc = s(lambda a, b: a > b)
    p_e  = s(lambda a, b: a == b)
    p_vf = s(lambda a, b: a < b)
    p_bt = s(lambda a, b: a > 0 and b > 0)
    p_o15 = s(lambda a, b: a + b > 1)
    p_o25 = s(lambda a, b: a + b > 2)
    p_o35 = s(lambda a, b: a + b > 3)

    return {
        "vitoria_casa": p_vc, "empate": p_e, "vitoria_fora": p_vf,
        "btts": p_bt,
        "over15": p_o15, "under15": round(100 - p_o15, 1),
        "over25": p_o25, "under25": round(100 - p_o25, 1),
        "over35": p_o35, "under35": round(100 - p_o35, 1),
    }


def _skellam_1x2(lam: float, mu: float, max_diff: int = 8) -> tuple[float, float, float]:
    """P(vitória casa), P(empate), P(vitória fora) via Skellam."""
    pv = pe = pd = 0.0
    for k in range(-max_diff, max_diff + 1):
        p = _skellam_pmf(k, lam, mu) * 100
        if k > 0:   pv += p
        elif k == 0: pe += p
        else:        pd += p
    total = pv + pe + pd or 1.0
    return round(pv / total * 100, 1), round(pe / total * 100, 1), round(pd / total * 100, 1)


def _calcular_modelo_gols(
    rating_casa: RatingDinamico,
    rating_fora: RatingDinamico,
    stats_casa,
    stats_fora,
    forma_casa: list[EntradaForma],
    forma_fora: list[EntradaForma],
) -> ModeloGols:
    lam, mu = _lambdas_from_ratings(rating_casa, rating_fora, stats_casa, stats_fora, forma_casa, forma_fora)
    matrix  = _dc_matrix(lam, mu)
    probs   = _market_probs(matrix, lam, mu)
    sk_v, sk_e, sk_d = _skellam_1x2(lam, mu)

    top5 = sorted(
        [{"placar": k, "prob": v} for k, v in matrix.items()],
        key=lambda x: -x["prob"]
    )[:5]

    return ModeloGols(
        lambda_casa=lam, lambda_fora=mu,
        prob_vitoria_casa=probs["vitoria_casa"],
        prob_empate=probs["empate"],
        prob_vitoria_fora=probs["vitoria_fora"],
        prob_btts=probs["btts"],
        prob_over15=probs["over15"], prob_under15=probs["under15"],
        prob_over25=probs["over25"], prob_under25=probs["under25"],
        prob_over35=probs["over35"], prob_under35=probs["under35"],
        top5_placares=top5,
        skellam_vitoria=sk_v, skellam_empate=sk_e, skellam_derrota=sk_d,
    )


# ════════════════════════════════════════════════════════════════════════════════
# CAMADA 3 — Value Bet (só com odds REAIS)
# ════════════════════════════════════════════════════════════════════════════════

_ODDS_PARA_PROB = {
    "vitoria_casa": "vitoria_casa",
    "empate":       "empate",
    "vitoria_fora": "vitoria_fora",
    "btts_sim":     "btts",
    "over15":       "over15",
    "under15":      "under15",
    "over25":       "over25",
    "under25":      "under25",
    "over35":       "over35",
    "under35":      "under35",
}

_LABELS = {
    "vitoria_casa": ("Resultado 1X2",   "Vitória Casa"),
    "empate":       ("Resultado 1X2",   "Empate"),
    "vitoria_fora": ("Resultado 1X2",   "Vitória Fora"),
    "btts_sim":     ("Ambas Marcam",    "Sim"),
    "over15":       ("Total de Gols",   "Over 1.5"),
    "under15":      ("Total de Gols",   "Under 1.5"),
    "over25":       ("Total de Gols",   "Over 2.5"),
    "under25":      ("Total de Gols",   "Under 2.5"),
    "over35":       ("Total de Gols",   "Over 3.5"),
    "under35":      ("Total de Gols",   "Under 3.5"),
}


def _calcular_value_bets(modelo: ModeloGols, odds: dict | None) -> tuple[bool, list[dict]]:
    """
    REGRA CRÍTICA: só calcula se odds vier da API (não None, não vazio).
    Retorna (odds_disponiveis, value_bets).
    """
    if not odds:
        return False, []

    probs_dc = {
        "vitoria_casa": modelo.prob_vitoria_casa,
        "empate":       modelo.prob_empate,
        "vitoria_fora": modelo.prob_vitoria_fora,
        "btts_sim":     modelo.prob_btts,
        "over15":       modelo.prob_over15, "under15": modelo.prob_under15,
        "over25":       modelo.prob_over25, "under25": modelo.prob_under25,
        "over35":       modelo.prob_over35, "under35": modelo.prob_under35,
    }

    results = []
    for mercado, odd in odds.items():
        prob_key = mercado  # chave coincide com probs_dc
        prob_dc  = probs_dc.get(prob_key)
        if prob_dc is None or odd <= 0:
            continue
        prob_impl = round(1 / odd * 100, 1)
        value     = round((prob_dc / 100 * odd) - 1, 3)
        tipo, entrada = _LABELS.get(mercado, ("Outro", mercado))
        results.append({
            "mercado":   tipo,
            "entrada":   entrada,
            "prob_dc":   prob_dc,
            "prob_impl": prob_impl,
            "edge":      round(prob_dc - prob_impl, 1),
            "odd_ref":   odd,
            "value_score": value,
            "tem_value": value >= VALUE_MIN,
        })

    results.sort(key=lambda x: -x["value_score"])
    return True, results


# ── Home advantage — países-sede Copa 2026 ───────────────────────────────────
# Quando USA, México ou Canadá jogam EM CASA, campo_neutro = False.
# Fator de ajuste baseado em pesquisa de home advantage em Copas:
#   λ_home × 1.25 — time da casa marca ~25% mais (altitude, torcida, familiaridade)
#   λ_away × 0.80 — visitante sofre ~20% de penalidade
# Altitude de 2240m (Cidade do México) está implícita no fator do visitante.
HOME_BOOST   = 1.25
AWAY_PENALTY = 0.80

# Selecões que são países-sede da Copa 2026
_HOST_NATIONS = {"Mexico", "USA", "United States", "Canada"}

# Mapeamento cidade → país-sede (baseado nos estádios do seed)
_CIDADE_PARA_PAIS_SEDE: dict[str, str] = {
    # México
    "Mexico City": "Mexico", "Zapopan": "Mexico",
    "Monterrey": "Mexico", "Guadalajara": "Mexico",
    # Canadá
    "Toronto": "Canada", "Vancouver": "Canada",
    # EUA
    "Los Angeles": "USA", "Inglewood": "USA",
    "San Jose": "USA", "Santa Clara": "USA",
    "Seattle": "USA", "Arlington": "USA", "Dallas": "USA",
    "Houston": "USA", "Kansas City": "USA",
    "Philadelphia": "USA", "East Rutherford": "USA",
    "Foxborough": "USA", "Boston": "USA",
    "Miami": "USA", "Miami Gardens": "USA", "Atlanta": "USA",
}

def _pais_sede_da_cidade(cidade: str) -> str | None:
    return _CIDADE_PARA_PAIS_SEDE.get(cidade)


# ════════════════════════════════════════════════════════════════════════════════
# CAMADA 4 — Context Engine
# ════════════════════════════════════════════════════════════════════════════════

def _win_rate_last_n(forma: list[EntradaForma], n: int = 5) -> float:
    last = forma[-n:] if len(forma) >= n else forma
    if not last:
        return 0.0
    return sum(1 for j in last if j.resultado == "W") / len(last)


def _calcular_contexto(
    partida: Partida,
    rating_casa: RatingDinamico,
    rating_fora: RatingDinamico,
    modelo: ModeloGols,
    odds_engine_result: dict | None = None,
) -> tuple[FatorContexto, ModeloGols]:
    """
    Detecta fatores contextuais e aplica ajustes ao ModeloGols.
    Retorna (contexto, modelo_ajustado).
    odds_engine_result: output do processar_odds (Camada 3) para critérios robustos de zebra.
    """
    data_jogo = datetime.strptime(partida.horario[:10], "%Y-%m-%d").date()

    # Fadiga: último jogo < 4 dias antes
    def fadiga(forma: list[EntradaForma]) -> bool:
        if not forma:
            return False
        try:
            ult = max(forma, key=lambda j: j.data)
            dias = (data_jogo - datetime.strptime(ult.data, "%Y-%m-%d").date()).days
            return 0 < dias < 4
        except ValueError:
            return False

    fad_c = fadiga(partida.forma_casa)
    fad_f = fadiga(partida.forma_fora)

    # Home advantage — país-sede jogando em casa
    pais_sede = _pais_sede_da_cidade(partida.cidade or "")
    home_adv  = False
    home_time = ""
    lam_boost   = 1.0
    away_pen    = 1.0

    if pais_sede:
        home_nome = partida.time_casa_nome
        away_nome = partida.time_fora_nome
        # Time da casa é o país-sede?
        if home_nome in _HOST_NATIONS or home_nome == pais_sede:
            home_adv  = True
            home_time = home_nome
            lam_boost   = HOME_BOOST
            away_pen    = AWAY_PENALTY
        # Time visitante é o país-sede jogando fora (não tem vantagem extra)
        # — nenhum ajuste necessário

    # Primeira rodada
    primeira = "Rodada 1" in partida.rodada

    # ── Zebra: critérios robustos (Camada 3 + Elo + forma) ─────────────────────
    zebra = False
    zebra_desc = ""
    elo_c    = rating_casa.elo_score or ELO_CENTER
    elo_f    = rating_fora.elo_score or ELO_CENTER
    elo_diff = abs(elo_c - elo_f)

    azarao_e_fora  = elo_c > elo_f
    underdog_nome  = partida.time_fora_nome if azarao_e_fora else partida.time_casa_nome
    favorito_nome  = partida.time_casa_nome if azarao_e_fora else partida.time_fora_nome
    underdog_forma = partida.forma_fora     if azarao_e_fora else partida.forma_casa
    favorito_forma = partida.forma_casa     if azarao_e_fora else partida.forma_fora
    wr_underdog    = _win_rate_last_n(underdog_forma, 5)
    fad_favorito   = fadiga(favorito_forma)

    # Prob do modelo para o azarão (em [0, 1])
    prob_az = (modelo.prob_vitoria_fora if azarao_e_fora else modelo.prob_vitoria_casa) / 100.0

    # Critério 2 (obrigatório): prob_modelo azarão > 25%
    crit2 = prob_az > 0.25

    # Critério 3 (pelo menos 1): evidência que azarão pode ganhar
    crit3 = wr_underdog > 0.60 or elo_diff < 150 or fad_favorito

    # Critério 4: dados suficientes (>= 3 jogos na forma do azarão)
    crit4 = len(underdog_forma) >= 3

    # Critério 1 + sharp money (requer odds_engine)
    crit1          = False
    sharp_confirma = False
    sharp_rejeita  = False
    value_score_az = None
    z_score_az     = None

    if odds_engine_result and odds_engine_result.get("odds_disponiveis"):
        resultado_az = "away" if azarao_e_fora else "home"
        div = (odds_engine_result.get("divergencia") or {}).get(resultado_az, {})
        z_score_az     = div.get("z_score")
        # Busca value_score no value_bets
        for vb in odds_engine_result.get("value_bets", []):
            if vb.get("resultado") == resultado_az:
                value_score_az = vb.get("value_score", 0)
                break
        crit1 = (
            (value_score_az or 0) > 0.15
            and (z_score_az or 0) > 1.96
        )
        # Sharp money
        sharp = odds_engine_result.get("sharp_money", {})
        if sharp.get("detectado"):
            if sharp.get("direcao") == resultado_az:
                sharp_confirma = True
            else:
                sharp_rejeita  = True

    # Detecta zebra
    if crit2 and crit3 and crit4 and not sharp_rejeita:
        if odds_engine_result and odds_engine_result.get("odds_disponiveis"):
            # Com odds: exige value + z_score significativos (Condição 1)
            zebra = crit1
        else:
            # Sem odds: usa critérios clássicos (Elo diff > 150 + forma > 60%)
            zebra = elo_diff > 150 and wr_underdog > 0.60

    if zebra:
        elo_az = min(elo_c, elo_f)
        elo_fav = max(elo_c, elo_f)
        prioridade = " 🔥 Sharp money confirma!" if sharp_confirma else ""
        vs_txt = (
            f"value={value_score_az:+.2f}, z={z_score_az:.2f}" if value_score_az is not None
            else f"Elo diff={elo_diff:.0f}pts, forma={wr_underdog*100:.0f}%"
        )
        zebra_desc = (
            f"{underdog_nome} é o azarão (Elo {elo_az:.0f} vs {elo_fav:.0f}) "
            f"mas o modelo identifica edge real: {vs_txt}. "
            f"Em Copas do Mundo, zebras ocorrem 2× mais que em ligas domésticas.{prioridade}"
        )

    # H2H sample
    n_h2h = len(partida.head_to_head)
    confianca_h2h = 0.85 if n_h2h < 3 else 1.0

    # Aplica ajustes ao modelo
    lam = modelo.lambda_casa
    mu  = modelo.lambda_fora

    # Home advantage (país-sede) — aplicado antes da fadiga
    if home_adv:
        lam = round(lam * lam_boost, 3)
        mu  = round(mu  * away_pen,  3)

    if fad_c: lam = round(lam * 0.95, 3)
    if fad_f: mu  = round(mu  * 0.95, 3)

    ajuste_under = 0.0
    over25_adj = modelo.prob_over25
    under25_adj = modelo.prob_under25
    if primeira:
        ajuste_under = round(over25_adj * 0.10, 1)
        over25_adj   = round(over25_adj - ajuste_under, 1)
        under25_adj  = round(100 - over25_adj, 1)

    # Reconstrói modelo sempre que algum lambda mudou (home advantage ou fadiga)
    lam_adj = round(max(0.3, lam), 3)
    mu_adj  = round(max(0.3, mu),  3)
    modelo_adj = modelo

    if lam_adj != modelo.lambda_casa or mu_adj != modelo.lambda_fora:
        from app.agents import football_agent as fa
        try:
            probs_adj  = fa._calcular_probabilidades(lam_adj, mu_adj)
            placares   = fa._calcular_placares_provaveis(lam_adj, mu_adj, top=3)
            modelo_adj = modelo.model_copy(update={
                "lambda_casa":       lam_adj,
                "lambda_fora":       mu_adj,
                "prob_vitoria_casa": probs_adj.vitoria_casa,
                "prob_empate":       probs_adj.empate,
                "prob_vitoria_fora": probs_adj.vitoria_fora,
                "placares_provaveis": placares,
            })
        except Exception:
            pass

    if primeira:
        modelo_adj = modelo_adj.model_copy(update={
            "prob_over25": over25_adj,
            "prob_under25": under25_adj,
        })

    ctx = FatorContexto(
        campo_neutro=not home_adv,
        home_advantage=home_adv,
        home_advantage_time=home_time,
        home_lambda_boost=lam_boost if home_adv else 0.0,
        away_lambda_penalty=away_pen if home_adv else 0.0,
        fadiga_casa=fad_c,
        fadiga_fora=fad_f,
        primeira_rodada=primeira,
        zebra_alerta=zebra,
        zebra_descricao=zebra_desc,
        confianca_h2h=confianca_h2h,
        ajuste_under25_aplicado=ajuste_under,
    )
    return ctx, modelo_adj


# ════════════════════════════════════════════════════════════════════════════════
# CAMADA 4B — Tail Risk Engine (Taleb)
# ════════════════════════════════════════════════════════════════════════════════

def _fat_tail_matrix(
    matrix_dc: dict[str, float],
    lam: float, mu: float,
    nu: int = 4, peso_dc: float = 0.85,
) -> dict[str, float]:
    """
    Mistura 85% DC + 15% componente Student-t com ν=4 graus de liberdade.
    O componente t pondera cada score pelo quanto ele desvia do total esperado,
    aumentando a probabilidade de resultados extremos (caudas gordas).
    """
    expected_total = lam + mu
    var_total = lam + mu          # variância da soma de dois Poisson independentes

    fat: dict[str, float] = {}
    for k, p_dc in matrix_dc.items():
        i, j = map(int, k.split("-"))
        total = i + j
        # Peso t: maior para totais de gols distantes do esperado
        desvio = (total - expected_total) ** 2
        t_peso = (1 + desvio / (nu * var_total)) ** (-(nu + 1) / 2)
        fat[k] = p_dc * t_peso

    # Normaliza componente fat para 100%
    soma_fat = sum(fat.values()) or 1.0
    fat = {k: v / soma_fat * 100 for k, v in fat.items()}

    # Mistura
    mixed = {k: round(peso_dc * matrix_dc[k] + (1 - peso_dc) * fat[k], 2) for k in matrix_dc}

    # Renormaliza para garantir soma exata 100
    soma = sum(mixed.values()) or 1.0
    return {k: round(v / soma * 100, 2) for k, v in mixed.items()}


def _probs_do_matrix(matrix: dict[str, float]) -> dict[str, float]:
    """Recalcula probabilidades de mercado a partir de uma matriz de scores."""
    def parse(k: str) -> tuple[int, int]:
        a, b = k.split("-")
        return int(a), int(b)

    def s(cond) -> float:
        return round(sum(v for k, v in matrix.items() if cond(*parse(k))), 1)

    p_vc = s(lambda a, b: a > b)
    p_e  = s(lambda a, b: a == b)
    p_vf = s(lambda a, b: a < b)
    p_bt = s(lambda a, b: a > 0 and b > 0)
    p_o15 = s(lambda a, b: a + b > 1)
    p_o25 = s(lambda a, b: a + b > 2)
    p_o35 = s(lambda a, b: a + b > 3)

    return {
        "vitoria_casa": p_vc, "empate": p_e, "vitoria_fora": p_vf,
        "btts": p_bt,
        "over15": p_o15, "under15": round(100 - p_o15, 1),
        "over25": p_o25, "under25": round(100 - p_o25, 1),
        "over35": p_o35, "under35": round(100 - p_o35, 1),
    }


def _fragility_score(forma: list[EntradaForma]) -> float:
    """
    Fragility score 0-100 baseado na variância dos gols marcados.
    Alta variância (poucos jogos com muitos gols, muitos com zero) sugere
    dependência de poucos jogadores — proxy sem precisar de dados individuais.
    Coeficiente de variação (CV) normalizado: CV=0→0, CV=2→100.
    """
    gols = [j.placar_proprio for j in forma if j.placar_proprio is not None]
    if len(gols) < 3:
        return 50.0   # incerteza padrão por amostra pequena
    media = statistics.mean(gols)
    if media == 0:
        return 80.0   # time que não marca é frágil por definição
    desvio = statistics.stdev(gols)
    cv = desvio / media
    return round(min(100.0, cv * 50.0), 1)


def _uncertainty_index(
    h2h: list[dict],
    elo_diff: float,
    forma_casa: list[EntradaForma],
    forma_fora: list[EntradaForma],
    primeira_rodada: bool,
    fragility_c: float,
    fragility_f: float,
) -> tuple[float, list[str]]:
    """Acumula incerteza contextual. Retorna (índice 0-100, fatores)."""
    ui = 0.0
    fatores: list[str] = []

    if len(h2h) < 3:
        ui += 20
        fatores.append(f"H2H < 3 confrontos ({len(h2h)} registrado(s)) → +20")

    if elo_diff < 100:
        ui += 15
        fatores.append(f"Diferença de Elo < 100pts ({elo_diff:.0f}pts) — times muito equilibrados → +15")

    def inconsistente(forma: list[EntradaForma]) -> bool:
        ultimos = forma[-10:] if len(forma) >= 10 else forma
        if not ultimos:
            return False
        wr = sum(1 for j in ultimos if j.resultado == "W") / len(ultimos)
        return 0.30 < wr < 0.60

    if inconsistente(forma_casa) and inconsistente(forma_fora):
        ui += 10
        fatores.append("Ambos times com forma inconsistente (30-60% vitórias) → +10")

    if primeira_rodada:
        ui += 10
        fatores.append("Copa do Mundo Rodada 1 — times cautelosos, resultados imprevisíveis → +10")

    if fragility_c > 70:
        ui += 10
        fatores.append(f"Alta dependência de poucos marcadores — time casa (fragility={fragility_c:.0f}) → +10")
    if fragility_f > 70:
        ui += 10
        fatores.append(f"Alta dependência de poucos marcadores — time fora (fragility={fragility_f:.0f}) → +10")

    return min(ui, 100.0), fatores


def _achatar_probabilidades(
    p_vc: float, p_e: float, p_vf: float, alpha: float
) -> tuple[float, float, float]:
    """Mistura linear em direção a 33.33/33.33/33.33 proporcionalmente."""
    flat = 100.0 / 3
    p_vc_adj = round((1 - alpha) * p_vc + alpha * flat, 1)
    p_e_adj  = round((1 - alpha) * p_e  + alpha * flat, 1)
    p_vf_adj = round(100 - p_vc_adj - p_e_adj, 1)
    return p_vc_adj, p_e_adj, p_vf_adj


def _barbell_signal(
    probs_adj: dict[str, float],
    odds_disponiveis: bool,
    value_bets: list[dict],
) -> tuple[bool, str | None, float | None, str | None, float | None]:
    """
    Detecta oportunidade barbell: entrada segura (prob > 65%) +
    entrada especulativa (prob_dc/prob_impl > 2.0, i.e. value > 100%).
    Só sugere se odds reais disponíveis.
    """
    if not odds_disponiveis or not value_bets:
        return False, None, None, None, None

    labels = {
        "vitoria_casa": "Vitória Casa", "empate": "Empate", "vitoria_fora": "Vitória Fora",
        "over25": "Over 2.5", "under25": "Under 2.5",
        "over15": "Over 1.5", "btts": "Ambas Marcam — Sim",
    }

    # Entrada segura: prob ajustada > 65%
    segura = max(
        ((labels.get(k, k), v) for k, v in probs_adj.items() if v > 65),
        key=lambda x: x[1], default=None
    )

    # Entrada especulativa: DC/impl > 2.0
    especulativa = next(
        (vb for vb in value_bets
         if vb["prob_dc"] > 0 and vb["prob_impl"] > 0
         and vb["prob_dc"] / vb["prob_impl"] >= 2.0
         and vb["prob_dc"] >= 5.0),
        None,
    )

    if segura and especulativa:
        return (
            True,
            segura[0], round(segura[1], 1),
            especulativa["entrada"], round(especulativa["value_score"], 3),
        )
    return False, segura[0] if segura else None, segura[1] if segura else None, None, None


def _calcular_tail_risk(
    modelo: ModeloGols,
    partida: Partida,
    rating_casa: RatingDinamico,
    rating_fora: RatingDinamico,
    ctx: FatorContexto,
    odds_disponiveis: bool,
    value_bets: list[dict],
) -> tuple[TailRiskResult, ModeloGols]:
    """
    Camada 4B — Tail Risk Engine.
    Retorna (TailRiskResult, ModeloGols ajustado com fat tail + uncertainty).
    """
    # ── 1. Reconstrói matriz DC a partir dos lambdas do modelo ───────────────
    matrix_dc = _dc_matrix(modelo.lambda_casa, modelo.lambda_fora)

    # ── 2. Fat Tail Correction ────────────────────────────────────────────────
    matrix_ft = _fat_tail_matrix(matrix_dc, modelo.lambda_casa, modelo.lambda_fora)
    probs_ft  = _probs_do_matrix(matrix_ft)

    delta = {
        k: round(probs_ft.get(k, 0) - getattr(modelo, f"prob_{k}", 0), 2)
        for k in ["vitoria_casa", "empate", "vitoria_fora", "over25", "under25", "over35"]
    }

    # ── 3. Fragility Score ────────────────────────────────────────────────────
    frag_c = _fragility_score(partida.forma_casa)
    frag_f = _fragility_score(partida.forma_fora)
    frag_max = max(frag_c, frag_f)
    frag_impacto = (
        "alto" if frag_max > 70 else
        "moderado" if frag_max > 50 else
        "leve" if frag_max > 30 else
        "nenhum"
    )

    # ── 4. Uncertainty Index ──────────────────────────────────────────────────
    elo_c = rating_casa.elo_score or ELO_CENTER
    elo_f = rating_fora.elo_score or ELO_CENTER
    elo_diff = abs(elo_c - elo_f)

    ui, fatores = _uncertainty_index(
        partida.head_to_head, elo_diff,
        partida.forma_casa, partida.forma_fora,
        ctx.primeira_rodada, frag_c, frag_f,
    )

    # ── 5. Aplica achatamento se ui > 60 ─────────────────────────────────────
    achatado = ui > 60
    alpha = round(min((ui - 60) / 40 * 0.50, 0.50), 3) if achatado else 0.0

    p_vc = probs_ft["vitoria_casa"]
    p_e  = probs_ft["empate"]
    p_vf = probs_ft["vitoria_fora"]

    if achatado:
        p_vc, p_e, p_vf = _achatar_probabilidades(p_vc, p_e, p_vf, alpha)

    probs_adj = dict(probs_ft)
    probs_adj.update({"vitoria_casa": p_vc, "empate": p_e, "vitoria_fora": p_vf})

    # ── 6. Barbell Signal ─────────────────────────────────────────────────────
    barbell, ent_seg, prob_seg, ent_esp, val_esp = _barbell_signal(
        probs_adj, odds_disponiveis, value_bets
    )

    # ── 7. Monta TailRiskResult ───────────────────────────────────────────────
    tail = TailRiskResult(
        prob_vitoria_casa_antes=modelo.prob_vitoria_casa,
        prob_empate_antes=modelo.prob_empate,
        prob_vitoria_fora_antes=modelo.prob_vitoria_fora,
        prob_vitoria_casa_depois=p_vc,
        prob_empate_depois=p_e,
        prob_vitoria_fora_depois=p_vf,
        over25_antes=modelo.prob_over25,
        over25_depois=probs_adj["over25"],
        over35_antes=modelo.prob_over35,
        over35_depois=probs_adj["over35"],
        fat_tail_delta=delta,
        fragility_score_casa=frag_c,
        fragility_score_fora=frag_f,
        fragility_impacto=frag_impacto,
        uncertainty_index=ui,
        uncertainty_fatores=fatores,
        probabilidades_achatadas=achatado,
        achatamento_alpha=alpha,
        barbell_sugerido=barbell,
        barbell_entrada_segura=ent_seg,
        barbell_prob_segura=prob_seg,
        barbell_entrada_especulativa=ent_esp,
        barbell_value_especulativo=val_esp,
    )

    # ── 8. Modelo ajustado com probabilidades corrigidas ─────────────────────
    modelo_adj = modelo.model_copy(update={
        "prob_vitoria_casa": p_vc,
        "prob_empate":        p_e,
        "prob_vitoria_fora":  p_vf,
        "prob_over25":        probs_adj["over25"],
        "prob_under25":       probs_adj["under25"],
        "prob_over35":        probs_adj["over35"],
        "prob_under35":       probs_adj["under35"],
        "prob_btts":          probs_adj["btts"],
        "prob_over15":        probs_adj["over15"],
        "prob_under15":       probs_adj["under15"],
    })

    return tail, modelo_adj


# ════════════════════════════════════════════════════════════════════════════════
# Score Final — ranqueia top 3 mercados
# ════════════════════════════════════════════════════════════════════════════════

def _score_final(
    modelo: ModeloGols,
    odds_disponiveis: bool,
    value_bets: list[dict],
    ctx: FatorContexto,
    odds: dict | None,
) -> list[MercadoRecomendado]:
    candidatos = [
        ("Resultado 1X2",  "Vitória Casa",  modelo.prob_vitoria_casa, "vitoria_casa"),
        ("Resultado 1X2",  "Empate",        modelo.prob_empate,       "empate"),
        ("Resultado 1X2",  "Vitória Fora",  modelo.prob_vitoria_fora, "vitoria_fora"),
        ("Total de Gols",  "Over 2.5",      modelo.prob_over25,       "over25"),
        ("Total de Gols",  "Under 2.5",     modelo.prob_under25,      "under25"),
        ("Total de Gols",  "Over 1.5",      modelo.prob_over15,       "over15"),
        ("Ambas Marcam",   "Sim",           modelo.prob_btts,         "btts_sim"),
    ]

    value_map = {vb["entrada"]: vb for vb in value_bets}
    h2h_mult  = ctx.confianca_h2h

    resultados = []
    for tipo, entrada, prob, chave in candidatos:
        odd_ref    = (odds or {}).get(chave) if odds_disponiveis else None
        value_sc   = None
        vb         = value_map.get(entrada)
        score_v    = 50.0   # neutro quando sem odds

        if odds_disponiveis and vb:
            value_sc = vb["value_score"]
            score_v  = min(max((value_sc + 0.5) * 100, 0), 100)

        # Bônus contextual
        bonus = 0.0
        if ctx.primeira_rodada and "Under" in entrada:  bonus += 8.0
        if ctx.primeira_rodada and entrada == "Empate":  bonus += 5.0
        if ctx.zebra_alerta and "Vitória" in entrada:    bonus += 6.0

        score = round((0.55 * prob + 0.30 * score_v + 0.15 * bonus) * h2h_mult, 1)
        score = min(score, 99.0)

        confianca = "Alta" if score >= 70 else ("Média" if score >= 50 else "Baixa")

        resultados.append(MercadoRecomendado(
            mercado=tipo, entrada=entrada,
            prob_dc=prob,
            odd_ref=odd_ref,
            value_score=value_sc,
            score_final=score,
            confianca=confianca,
        ))

    resultados.sort(key=lambda x: -x.score_final)
    return resultados[:3]


# ════════════════════════════════════════════════════════════════════════════════
# CAMADA 5 — Claude (só narrativa)
# ════════════════════════════════════════════════════════════════════════════════

_SYSTEM = """Você é o narrador analítico do site Palpites da IA — Copa do Mundo 2026.
Você recebe o output completo de 5 camadas estatísticas e gera APENAS texto.

Regras absolutas:
1. NUNCA invente probabilidades, ratings ou placares — use EXATAMENTE os números recebidos.
2. NUNCA altere dados brutos da API (forma, H2H, stats históricas).
3. Se odds_disponiveis=false, mencione EXPLICITAMENTE que value bets não puderam ser calculados
   e recomende o usuário verificar as odds nas casas de aposta antes de apostar.
4. Se uncertainty_index > 60: mencione EXPLICITAMENTE que o jogo é genuinamente imprevisível
   e que as probabilidades foram achatadas para refletir essa incerteza.
5. Cite sempre a fonte do dado: "pelo Dixon-Coles...", "o Elo rating indica...", "a Camada 4B mostra...".
6. Linguagem acessível para apostadores casuais brasileiros — começa simples e aprofunda.
7. Responda em português brasileiro.

Gere EXATAMENTE estes 4 campos (uma linha por campo, sem quebras de linha internas):
NARRATIVA: [parágrafo de contexto do jogo — 3-4 frases, jornalístico]
RESUMO_RAPIDO: [1 frase com a recomendação principal]
ALERTAS: [alertas separados por | — máx 5]
ANALISE_COMPLETA: [análise detalhada citando top 3 mercados, tail risk, uncertainty e fat tail — 6-8 frases]
"""


def _montar_prompt(
    partida: Partida,
    rating_c: RatingDinamico, rating_f: RatingDinamico,
    modelo: ModeloGols,
    odds_disp: bool, value_bets: list[dict],
    ctx: FatorContexto,
    top3: list[MercadoRecomendado],
    tail: TailRiskResult,
) -> str:
    top3_txt = "\n".join(
        f"  {i+1}. {m.mercado} — {m.entrada}: score={m.score_final} | "
        f"DC={m.prob_dc}% | value={'N/A (sem odds)' if m.value_score is None else f'{m.value_score:+.3f}'} | {m.confianca}"
        for i, m in enumerate(top3)
    )
    forma_c = " ".join(j.resultado for j in partida.forma_casa[-5:])
    forma_f = " ".join(j.resultado for j in partida.forma_fora[-5:])
    vb_txt  = (
        "\n".join(f"  {v['entrada']}: value={v['value_score']:+.3f}, tem_value={v['tem_value']}" for v in value_bets[:3])
        if value_bets else "  Não calculado — odds indisponíveis na API"
    )
    delta_txt = " | ".join(
        f"{k}: {'+' if v >= 0 else ''}{v}pp" for k, v in tail.fat_tail_delta.items()
    )
    unc_txt = "\n".join(f"  • {f}" for f in tail.uncertainty_fatores) or "  Nenhum"
    barbell_txt = (
        f"SUGERIDO — Segura: {tail.barbell_entrada_segura} ({tail.barbell_prob_segura}%) + "
        f"Especulativa: {tail.barbell_entrada_especulativa} (value={tail.barbell_value_especulativo:+.3f})"
        if tail.barbell_sugerido else "Não sugerido (sem odds ou sem combinação válida)"
    )

    return f"""Analise a partida e gere a narrativa com base nos dados abaixo.

PARTIDA: {partida.time_casa_nome} x {partida.time_fora_nome}
Copa do Mundo 2026 | {partida.rodada}
Data: {partida.horario[:10]} | {partida.estadio}, {partida.cidade}

=== CAMADA 1 — RATINGS ===
{partida.time_casa_nome}: Elo={rating_c.elo_score} ({rating_c.fonte_elo}) | Pi={rating_c.pi_rating} | Combinado={rating_c.rating_combinado}
{partida.time_fora_nome}: Elo={rating_f.elo_score} ({rating_f.fonte_elo}) | Pi={rating_f.pi_rating} | Combinado={rating_f.rating_combinado}

=== CAMADA 2 — MODELO DE GOLS (Dixon-Coles + Skellam) ===
λ casa={modelo.lambda_casa} | λ fora={modelo.lambda_fora}
1X2 (DC final): Vitória casa={modelo.prob_vitoria_casa}% | Empate={modelo.prob_empate}% | Vitória fora={modelo.prob_vitoria_fora}%
1X2 (Skellam): Vitória={modelo.skellam_vitoria}% | Empate={modelo.skellam_empate}% | Derrota={modelo.skellam_derrota}%
BTTS={modelo.prob_btts}% | Over2.5={modelo.prob_over25}% | Under2.5={modelo.prob_under25}%
Placar mais provável: {modelo.top5_placares[0]['placar']} ({modelo.top5_placares[0]['prob']}%)

=== CAMADA 3 — VALUE BETS ===
odds_disponiveis: {odds_disp}
{vb_txt}

=== CAMADA 4 — CONTEXTO ===
Campo neutro: {ctx.campo_neutro} | Primeira rodada: {ctx.primeira_rodada}
Fadiga: casa={ctx.fadiga_casa} | fora={ctx.fadiga_fora}
Zebra alerta: {ctx.zebra_alerta}{' — ' + ctx.zebra_descricao if ctx.zebra_alerta else ''}
Confiança H2H: {ctx.confianca_h2h} ({len(partida.head_to_head)} confronto(s))
Ajuste Under25 aplicado: {ctx.ajuste_under25_aplicado}pp

=== CAMADA 4B — TAIL RISK (Taleb) ===
Fat Tail Correction (85% DC + 15% Student-t ν=4):
  Antes: VC={tail.prob_vitoria_casa_antes}% | E={tail.prob_empate_antes}% | VF={tail.prob_vitoria_fora_antes}%
  Depois: VC={tail.prob_vitoria_casa_depois}% | E={tail.prob_empate_depois}% | VF={tail.prob_vitoria_fora_depois}%
  Deltas: {delta_txt}
  Over2.5: {tail.over25_antes}% → {tail.over25_depois}% | Over3.5: {tail.over35_antes}% → {tail.over35_depois}%
Fragility: casa={tail.fragility_score_casa:.1f} | fora={tail.fragility_score_fora:.1f} | impacto={tail.fragility_impacto}
Uncertainty Index: {tail.uncertainty_index:.0f}/100 (achatamento: {'SIM — alpha=' + str(tail.achatamento_alpha) if tail.probabilidades_achatadas else 'NÃO'})
Fatores de incerteza:
{unc_txt}
Barbell Signal: {barbell_txt}

=== SCORE FINAL — TOP 3 ===
{top3_txt}

=== DADOS BRUTOS API (não alterar) ===
Forma {partida.time_casa_nome} (últimos 5): {forma_c}
Forma {partida.time_fora_nome} (últimos 5): {forma_f}
H2H: {len(partida.head_to_head)} confronto(s)
Stats casa: fonte={partida.stats_casa.fonte} | dados_insuficientes={partida.stats_casa.dados_insuficientes}
Stats fora: fonte={partida.stats_fora.fonte} | dados_insuficientes={partida.stats_fora.dados_insuficientes}
"""


def _parse_claude(texto: str) -> dict:
    """Parser multi-linha — captura tudo após o marcador até o próximo."""
    campos = {"NARRATIVA": "", "RESUMO_RAPIDO": "", "ALERTAS": "", "ANALISE_COMPLETA": ""}
    ordem  = list(campos.keys())
    linhas = texto.splitlines()
    atual  = None
    buf    = []
    for linha in linhas:
        achado = next((c for c in ordem if linha.startswith(f"{c}:")), None)
        if achado:
            if atual:
                campos[atual] = " ".join(buf).strip()
            atual = achado
            buf   = [linha[len(achado) + 1:].strip()]
        elif atual:
            buf.append(linha.strip())
    if atual:
        campos[atual] = " ".join(buf).strip()
    return campos


# ════════════════════════════════════════════════════════════════════════════════
# Ponto de entrada
# ════════════════════════════════════════════════════════════════════════════════

async def gerar_recomendacao(partida: Partida) -> RecomendacaoIA:
    """
    Orquestra as 5 camadas e retorna RecomendacaoIA completo.
    Dados brutos da API (partida.*) nunca são alterados.
    """
    # Camada 1 — Ratings + Wikipedia FIFA ranking em paralelo
    import asyncio
    wiki_rankings, rating_c, rating_f = await asyncio.gather(
        _buscar_fifa_ranking_wikipedia(),
        _calcular_rating(partida.time_casa_nome, partida.forma_casa, partida.horario),
        _calcular_rating(partida.time_fora_nome, partida.forma_fora, partida.horario),
    )
    # Re-calcula ratings com Wikipedia se trouxe dados extras
    if wiki_rankings:
        rating_c, rating_f = await asyncio.gather(
            _calcular_rating(partida.time_casa_nome, partida.forma_casa, partida.horario, wiki_rankings),
            _calcular_rating(partida.time_fora_nome, partida.forma_fora, partida.horario, wiki_rankings),
        )

    # Camada 2 — Modelo de gols
    modelo = _calcular_modelo_gols(
        rating_c, rating_f,
        partida.stats_casa, partida.stats_fora,
        partida.forma_casa, partida.forma_fora,
    )

    # Camada 3 — Odds Engine (Shin + consensus + z-score + value bets)
    from app.agents.odds_engine import processar_odds as _processar_odds
    _prob_modelo_01 = {
        "vitoria_casa": modelo.prob_vitoria_casa / 100.0,
        "empate":       modelo.prob_empate       / 100.0,
        "vitoria_fora": modelo.prob_vitoria_fora / 100.0,
        "btts":         modelo.prob_btts         / 100.0,
        "over15":       modelo.prob_over15       / 100.0,
        "under15":      modelo.prob_under15      / 100.0,
        "over25":       modelo.prob_over25       / 100.0,
        "under25":      modelo.prob_under25      / 100.0,
        "over35":       modelo.prob_over35       / 100.0,
        "under35":      modelo.prob_under35      / 100.0,
    }
    odds_result = _processar_odds(partida.odds, _prob_modelo_01)
    odds_disp   = odds_result["odds_disponiveis"]
    # value_bets legado (formato _LABELS + "entrada") para _score_final
    _, value_bets = _calcular_value_bets(modelo, partida.odds)

    # Camada 4 — Contexto + ajustes (recebe odds_engine para zebra robusta)
    ctx, modelo_c4 = _calcular_contexto(partida, rating_c, rating_f, modelo, odds_result)

    # Camada 4B — Tail Risk
    tail_risk, modelo_final = _calcular_tail_risk(
        modelo_c4, partida, rating_c, rating_f, ctx, odds_disp, value_bets
    )

    # Score final (usa modelo com tail risk aplicado)
    top3 = _score_final(modelo_final, odds_disp, value_bets, ctx, partida.odds)

    # Camada 5 — Claude narrativa
    prompt = _montar_prompt(
        partida, rating_c, rating_f, modelo_final,
        odds_disp, value_bets, ctx, top3, tail_risk,
    )
    msg    = await _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=900,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    parsed = _parse_claude(msg.content[0].text)

    alertas = [a.strip() for a in parsed["ALERTAS"].split("|") if a.strip()]
    top1    = top3[0] if top3 else None

    return RecomendacaoIA(
        partida_id=partida.id,
        rating_casa=rating_c,
        rating_fora=rating_f,
        modelo_gols=modelo_final,
        odds_disponiveis=odds_disp,
        value_bets=value_bets,
        odds_analise=odds_result,
        contexto=ctx,
        tail_risk=tail_risk,
        top3=top3,
        narrativa=parsed["NARRATIVA"],
        resumo_rapido=parsed["RESUMO_RAPIDO"],
        alertas=alertas,
        analise_completa=parsed["ANALISE_COMPLETA"],
        # legado
        mercado=top1.mercado     if top1 else "—",
        entrada=top1.entrada     if top1 else "—",
        confianca=top1.confianca if top1 else "Baixa",
        analise=parsed["ANALISE_COMPLETA"] or parsed["NARRATIVA"],
        texto_completo=msg.content[0].text,
    )
