"""
Agente de dados — Copa do Mundo FIFA 2026.

Fonte de fixtures : seeds/copa_2026.json  (dados reais, zero quota)
Fonte de stats    : API-Football v3       (sob demanda, cache 1h)

Chamadas por detalhe de partida (estimativa):
  - /teams/statistics × 2  (stats históricas de cada time)
  - /fixtures?team&last=5  × 2  (forma recente)
  - /fixtures/headtohead   × 1  (H2H)
  - /fixtures?id=          × 1  (árbitro)
  - /fixtures?referee=     × 1  (stats do árbitro)
  Total ≈ 7 chamadas, todas cacheadas por 1h.

Regra: nunca inventa dados — dados_insuficientes=True quando a API não retorna.
"""
import asyncio
import json
import os
from math import exp, factorial
from pathlib import Path

import httpx
from cachetools import TTLCache

from app.models.schemas import (
    Arbitro, EntradaForma, EstatisticasTemporada, Partida,
    PartidaResumo, PerformanceLocal, PlacarProvavel, Probabilidades,
)

BASE_URL   = "https://v3.football.api-sports.io"
HEADERS    = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}
WC_SEASONS = [2022, 2018, 2014, 2010]

_cache: TTLCache = TTLCache(maxsize=400, ttl=3600)


# ── Seed ─────────────────────────────────────────────────────────────────────

def _carregar_seed() -> dict:
    path = Path(__file__).parent.parent.parent / "seeds" / "copa_2026.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)

_SEED = _carregar_seed()
_JOGOS: list[dict] = _SEED["jogos"]
_POR_SLUG: dict[str, dict] = {j["slug"]: j for j in _JOGOS}


# ── HTTP com cache ─────────────────────────────────────────────────────────────

async def _get(client: httpx.AsyncClient, path: str, params: dict) -> dict:
    key = f"{path}:{sorted(params.items())}"
    if key in _cache:
        return _cache[key]
    resp = await client.get(f"{BASE_URL}{path}", headers=HEADERS, params=params)
    resp.raise_for_status()
    data = resp.json()
    _cache[key] = data
    return data


# ── Poisson ───────────────────────────────────────────────────────────────────

def _poisson(lam: float, k: int) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * exp(-lam) / factorial(k)


def _calcular_probabilidades(lc: float, lf: float) -> Probabilidades:
    MAX = 9
    pv = pe = pd = 0.0
    for i in range(MAX):
        for j in range(MAX):
            p = _poisson(lc, i) * _poisson(lf, j)
            if i > j:    pv += p
            elif i == j: pe += p
            else:        pd += p
    t = pv + pe + pd
    return Probabilidades(
        vitoria_casa=round(pv / t * 100),
        empate=round(pe / t * 100),
        vitoria_fora=round(pd / t * 100),
        lambda_casa=round(lc, 2),
        lambda_fora=round(lf, 2),
        metodo="poisson",
        dados_insuficientes=False,
    )


def _calcular_placares_provaveis(lc: float, lf: float, top: int = 3) -> list[PlacarProvavel]:
    """Retorna os top N placares mais prováveis via Poisson."""
    MAX = 7
    scores: list[PlacarProvavel] = []
    for i in range(MAX):
        for j in range(MAX):
            prob = round(_poisson(lc, i) * _poisson(lf, j) * 100, 2)
            scores.append(PlacarProvavel(placar=f"{i}-{j}", probabilidade=prob))
    scores.sort(key=lambda x: -x.probabilidade)
    return scores[:top]


# ── Stats históricas via /teams/statistics ────────────────────────────────────

async def _stats_time(client: httpx.AsyncClient, team_id: int) -> EstatisticasTemporada:
    """
    Busca estatísticas históricas do time nas Copas anteriores (2022→2010).
    Casa/fora são IGNORADOS pois a Copa é disputada em campo neutro.
    BTTS/Over/médias recentes são preenchidos depois via _enriquecer_btts_over.
    """
    for season in WC_SEASONS:
        try:
            data  = await _get(client, "/teams/statistics", {
                "league": 1, "season": season, "team": team_id,
            })
            resp  = data.get("response", {})
            jogos = resp.get("fixtures", {}).get("played", {}).get("total") or 0
            if not resp or jogos == 0:
                continue

            fix   = resp["fixtures"]
            goals = resp["goals"]
            cards = resp.get("cards", {})
            pen   = resp.get("penalty", {})
            clean = resp.get("clean_sheet", {})

            total_yellow = sum(
                (v.get("total") or 0) for v in cards.get("yellow", {}).values()
            )
            total_red = sum(
                (v.get("total") or 0) for v in cards.get("red", {}).values()
            )

            return EstatisticasTemporada(
                fonte=f"Copa {season}",
                dados_insuficientes=False,
                sede_neutra=True,          # Copa = campo neutro, sem split casa/fora
                casa=None,
                fora=None,
                jogos=jogos,
                vitorias=fix["wins"]["total"],
                empates=fix["draws"]["total"],
                derrotas=fix["loses"]["total"],
                gols_marcados=goals["for"]["total"]["total"],
                gols_sofridos=goals["against"]["total"]["total"],
                media_gols_marcados=float(goals["for"]["average"]["total"]),
                media_gols_sofridos=float(goals["against"]["average"]["total"]),
                clean_sheets=clean.get("total"),
                media_amarelos=round(total_yellow / jogos, 2) if jogos else None,
                media_vermelhos=round(total_red / jogos, 2) if jogos else None,
                penaltis_marcados=pen.get("scored", {}).get("total"),
                penaltis_total=pen.get("total"),
            )
        except Exception:
            continue

    return EstatisticasTemporada(dados_insuficientes=True)


# ── Forma recente (últimos 10 jogos, apenas masculino sênior) ─────────────────

# Termos que indicam competição não-sênior ou feminina — excluídos do cálculo
_EXCLUIR_LIGA = (
    "women", "feminino", "female",
    "u-17", "u-20", "u-21", "u-23", "u17", "u20", "u21", "u23",
    "youth", "junior", "sub-", "olímpic", "olympic",
)

def _e_jogo_senior_masculino(f: dict) -> bool:
    nome = f["league"]["name"].lower()
    return not any(t in nome for t in _EXCLUIR_LIGA)


async def _forma_recente(client: httpx.AsyncClient, team_id: int) -> list[EntradaForma]:
    """
    Últimos 10 jogos profissionais masculinos do time em qualquer competição
    (amistosos, eliminatórias, copa continental, etc.).
    Filtra competições femininas e de base.
    """
    try:
        data     = await _get(client, "/fixtures", {"team": team_id, "last": 10})
        fixtures = [
            f for f in data.get("response", [])
            if _e_jogo_senior_masculino(f)
        ]
    except Exception:
        return []

    forma = []
    for f in sorted(fixtures, key=lambda x: x["fixture"]["date"]):
        is_home     = f["teams"]["home"]["id"] == team_id
        winner      = f["teams"]["home"]["winner"] if is_home else f["teams"]["away"]["winner"]
        adversario  = f["teams"]["away"]["name"]   if is_home else f["teams"]["home"]["name"]
        gols_pro    = f["goals"]["home"]            if is_home else f["goals"]["away"]
        gols_contra = f["goals"]["away"]            if is_home else f["goals"]["home"]
        resultado   = "W" if winner is True else ("L" if winner is False else "D")
        forma.append(EntradaForma(
            data=f["fixture"]["date"][:10],
            adversario=adversario,
            placar_proprio=gols_pro,
            placar_adversario=gols_contra,
            resultado=resultado,
            competicao=f["league"]["name"],
        ))
    return forma


# ── Enriquece stats com BTTS/Over/médias dos últimos 10 jogos ────────────────

def _enriquecer_btts_over(
    stats: EstatisticasTemporada, forma: list[EntradaForma]
) -> EstatisticasTemporada:
    """
    A partir dos últimos 10 jogos reais calcula:
    - BTTS%, Over/Under 2.5%
    - Média de gols marcados e sofridos (mais representativa do momento atual)
    Zero chamadas adicionais à API.
    """
    jogos_validos = [
        j for j in forma
        if j.placar_proprio is not None and j.placar_adversario is not None
    ]
    if not jogos_validos:
        return stats

    n = len(jogos_validos)
    btts = sum(1 for j in jogos_validos if j.placar_proprio > 0 and j.placar_adversario > 0)
    over = sum(1 for j in jogos_validos if j.placar_proprio + j.placar_adversario > 2)

    gols_pro    = [j.placar_proprio    for j in jogos_validos]
    gols_contra = [j.placar_adversario for j in jogos_validos]

    stats.jogos_forma                  = n
    stats.btts_pct                     = round(btts / n * 100)
    stats.over25_pct                   = round(over / n * 100)
    stats.under25_pct                  = 100 - stats.over25_pct
    stats.media_gols_marcados_recente  = round(sum(gols_pro)    / n, 2)
    stats.media_gols_sofridos_recente  = round(sum(gols_contra) / n, 2)
    return stats


# ── H2H ──────────────────────────────────────────────────────────────────────

async def _h2h(client: httpx.AsyncClient, id1: int, id2: int) -> list[dict]:
    try:
        data = await _get(client, "/fixtures/headtohead", {
            "h2h": f"{id1}-{id2}", "last": 10,
        })
        return [
            {
                "data":       f["fixture"]["date"][:10],
                "competicao": f["league"]["name"],
                "casa":       f["teams"]["home"]["name"],
                "fora":       f["teams"]["away"]["name"],
                "gols_casa":  f["goals"]["home"],
                "gols_fora":  f["goals"]["away"],
                "vencedor": (
                    f["teams"]["home"]["name"] if f["teams"]["home"]["winner"] else
                    f["teams"]["away"]["name"] if f["teams"]["away"]["winner"] else
                    "empate"
                ),
            }
            for f in data.get("response", [])
        ]
    except Exception:
        return []


# ── Árbitro ───────────────────────────────────────────────────────────────────

async def _arbitro(client: httpx.AsyncClient, fixture_id: int) -> Arbitro | None:
    """
    Busca o árbitro do jogo via /fixtures?id={fixture_id}.
    Depois tenta estimar médias de cartões/pênaltis pelos jogos recentes do árbitro.
    """
    try:
        data = await _get(client, "/fixtures", {"id": fixture_id})
        resp = data.get("response", [{}])[0]
        nome_raw = resp.get("fixture", {}).get("referee")
        if not nome_raw:
            return None

        # API retorna "Nome Sobrenome, País" — pega só o nome
        nome = nome_raw.split(",")[0].strip()

        # Busca últimos 20 jogos do árbitro para calcular médias
        jogos_data = await _get(client, "/fixtures", {"referee": nome, "last": 20})
        jogos = jogos_data.get("response", [])

        if not jogos:
            return Arbitro(nome=nome)

        total = len(jogos)
        total_yellow = total_red = total_pen = 0

        for f in jogos:
            # Cartões e pênaltis estão nos eventos, mas buscar evento por jogo
            # usaria muita quota. Usamos score como proxy de pênaltis não é confiável.
            # Retornamos só o total de jogos por enquanto.
            pass

        return Arbitro(nome=nome, jogos_apitados=total)

    except Exception:
        return None


# ── Odds ─────────────────────────────────────────────────────────────────────

def _parsear_odds(bets: list) -> dict:
    """Extrai odds de 1X2, BTTS e Over/Under de uma lista de bets da Bet365."""
    mapa = {b["name"]: b["values"] for b in bets}
    odds: dict = {}

    if "Match Winner" in mapa:
        for v in mapa["Match Winner"]:
            chave = {"Home": "vitoria_casa", "Draw": "empate", "Away": "vitoria_fora"}.get(v["value"])
            if chave:
                odds[chave] = float(v["odd"])

    if "Both Teams Score" in mapa:
        for v in mapa["Both Teams Score"]:
            chave = {"Yes": "btts_sim", "No": "btts_nao"}.get(v["value"])
            if chave:
                odds[chave] = float(v["odd"])

    for nome in ["Goals Over/Under", "Total Goals"]:
        if nome in mapa:
            for v in mapa[nome]:
                label = v["value"]  # ex: "Over 2.5", "Under 2.5"
                if "Over 1.5" in label:  odds["over15"] = float(v["odd"])
                elif "Under 1.5" in label: odds["under15"] = float(v["odd"])
                elif "Over 2.5" in label:  odds["over25"] = float(v["odd"])
                elif "Under 2.5" in label: odds["under25"] = float(v["odd"])
                elif "Over 3.5" in label:  odds["over35"] = float(v["odd"])
                elif "Under 3.5" in label: odds["under35"] = float(v["odd"])
            break

    return odds or {}


async def _buscar_odds(client: httpx.AsyncClient, fixture_id: int) -> dict | None:
    """Busca odds da Bet365 para o fixture. Retorna None se indisponíveis."""
    try:
        data = await _get(client, "/odds", {"fixture": fixture_id, "bookmaker": 6})
        bets = data["response"][0]["bookmakers"][0]["bets"]
        parsed = _parsear_odds(bets)
        return parsed if parsed else None
    except (IndexError, KeyError, Exception):
        return None


# ── Seed → schema ─────────────────────────────────────────────────────────────

def _jogo_para_resumo(j: dict) -> PartidaResumo:
    return PartidaResumo(
        id=j["api_fixture_id"],
        slug=j["slug"],
        rodada=j["rodada"],
        horario=j["data_hora_brasilia"],
        status=j.get("status") or "NS",
        estadio=j.get("estadio") or "",
        cidade=j.get("cidade") or "",
        time_casa_nome=j["time_casa"],
        time_casa_logo=j.get("time_casa_logo") or "",
        time_fora_nome=j["time_fora"],
        time_fora_logo=j.get("time_fora_logo") or "",
        gols_casa=j.get("gols_casa"),
        gols_fora=j.get("gols_fora"),
    )


# ── API pública ───────────────────────────────────────────────────────────────

async def buscar_todos_jogos_copa() -> list[PartidaResumo]:
    """72 jogos da fase de grupos — lidos do seed, zero quota."""
    return [_jogo_para_resumo(j) for j in _JOGOS]


async def buscar_detalhe_partida(slug: str) -> Partida | None:
    jogo = _POR_SLUG.get(slug)
    if not jogo:
        return None

    home_id    = jogo["time_casa_id"]
    away_id    = jogo["time_fora_id"]
    fixture_id = jogo["api_fixture_id"]
    home_nome  = jogo["time_casa"]
    away_nome  = jogo["time_fora"]

    # ── 6 chamadas paralelas à API-Football ──────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            (
                stats_casa_raw,
                stats_fora_raw,
                forma_casa,
                forma_fora,
                h2h,
                arb,
            ) = await asyncio.gather(
                _stats_time(client, home_id),
                _stats_time(client, away_id),
                _forma_recente(client, home_id),
                _forma_recente(client, away_id),
                _h2h(client, home_id, away_id),
                _arbitro(client, fixture_id),
            )
    except Exception:
        stats_casa_raw = stats_fora_raw = EstatisticasTemporada(dados_insuficientes=True)
        forma_casa = forma_fora = []
        h2h = []
        arb = None

    # ── Enriquece stats com BTTS/Over calculados da forma recente ─────────────
    stats_casa = _enriquecer_btts_over(stats_casa_raw, forma_casa)
    stats_fora = _enriquecer_btts_over(stats_fora_raw, forma_fora)

    # ── Odds + Jogadores + Ratings em paralelo ────────────────────────────────
    # Separado do gather principal: cada um usa cliente próprio.
    from app.agents.odds_agent import buscar_odds_partida as _odds_api
    from app.agents.players_agent import buscar_jogadores_destaque
    from app.agents.ia_agent import _calcular_rating, _buscar_fifa_ranking_wikipedia
    from app.models.schemas import JogadoresDestaque, JogadorDestaque

    async def _timed(coro, t):
        try:
            return await asyncio.wait_for(coro, timeout=t)
        except asyncio.CancelledError:
            raise  # propaga cancelamento externo — não engolir
        except Exception as e:
            return e

    resultados = await asyncio.gather(
        _timed(_odds_api(home_nome, away_nome), 15),
        _timed(buscar_jogadores_destaque(home_nome), 25),
        _timed(buscar_jogadores_destaque(away_nome), 25),
        _timed(_buscar_fifa_ranking_wikipedia(), 8),
        _timed(_calcular_rating(home_nome, forma_casa, jogo["data_hora_brasilia"]), 10),
        _timed(_calcular_rating(away_nome, forma_fora, jogo["data_hora_brasilia"]), 10),
    )

    def _safe(val):
        return None if isinstance(val, Exception) else val

    odds          = _safe(resultados[0])
    dest_casa_raw = _safe(resultados[1])
    dest_fora_raw = _safe(resultados[2])
    wiki          = _safe(resultados[3]) or {}
    rating_c      = _safe(resultados[4])
    rating_f      = _safe(resultados[5])

    # Re-calcula ratings com Wikipedia se disponível
    if wiki and rating_c is not None and rating_f is not None:
        try:
            rating_c, rating_f = await asyncio.gather(
                _calcular_rating(home_nome, forma_casa, jogo["data_hora_brasilia"], wiki),
                _calcular_rating(away_nome, forma_fora, jogo["data_hora_brasilia"], wiki),
            )
        except Exception:
            pass

    # Processa jogadores
    def _to_destaque(raw: dict) -> JogadoresDestaque:
        jogadores = [JogadorDestaque(**j) for j in raw.get("jogadores", [])]
        return JogadoresDestaque(
            time_nome=raw["time_nome"],
            jogadores=jogadores,
            total_squad=raw.get("total_squad", 0),
            fonte_squad=raw.get("fonte_squad", ""),
            jogadores_analisados=raw.get("jogadores_analisados", 0),
            dados_insuficientes=raw.get("dados_insuficientes", True),
        )

    dest_casa = _to_destaque(dest_casa_raw) if dest_casa_raw else None
    dest_fora = _to_destaque(dest_fora_raw) if dest_fora_raw else None

    # ── Probabilidades e top 3 placares via Poisson ───────────────────────────
    probabilidades   = None
    placares_provaveis: list[PlacarProvavel] = []

    # Prefere médias dos últimos 10 jogos (mais representativas) sobre histórico de Copa
    lc_raw = stats_casa.media_gols_marcados_recente or stats_casa.media_gols_marcados
    lf_raw = stats_fora.media_gols_marcados_recente or stats_fora.media_gols_marcados

    if (
        not stats_casa.dados_insuficientes
        and not stats_fora.dados_insuficientes
        and lc_raw is not None
        and lf_raw is not None
    ):
        lc = lc_raw
        lf = lf_raw
        probabilidades     = _calcular_probabilidades(lc, lf)
        placares_provaveis = _calcular_placares_provaveis(lc, lf, top=3)
    else:
        probabilidades = Probabilidades(
            vitoria_casa=0, empate=0, vitoria_fora=0,
            lambda_casa=0.0, lambda_fora=0.0,
            dados_insuficientes=True,
        )

    return Partida(
        id=fixture_id,
        slug=jogo["slug"],
        rodada=jogo["rodada"],
        horario=jogo["data_hora_brasilia"],
        status=jogo.get("status") or "NS",
        estadio=jogo.get("estadio") or "",
        cidade=jogo.get("cidade") or "",
        time_casa_nome=jogo["time_casa"],
        time_casa_logo=jogo.get("time_casa_logo") or "",
        time_casa_id=home_id,
        time_fora_nome=jogo["time_fora"],
        time_fora_logo=jogo.get("time_fora_logo") or "",
        time_fora_id=away_id,
        gols_casa=jogo.get("gols_casa"),
        gols_fora=jogo.get("gols_fora"),
        rating_casa=rating_c,
        rating_fora=rating_f,
        stats_casa=stats_casa,
        stats_fora=stats_fora,
        forma_casa=forma_casa,
        forma_fora=forma_fora,
        head_to_head=h2h,
        probabilidades=probabilidades,
        placares_provaveis=placares_provaveis,
        arbitro=arb,
        odds=odds,
        jogadores_destaque_casa=dest_casa,
        jogadores_destaque_fora=dest_fora,
        dados_insuficientes=(
            stats_casa.dados_insuficientes
            or stats_fora.dados_insuficientes
            or len(forma_casa) == 0
            or len(forma_fora) == 0
            or len(h2h) == 0
        ),
    )
