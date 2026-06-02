"""
Agente de dados — Copa do Mundo FIFA 2026.

Fonte de fixtures: seeds/copa_2026.json (dados reais da API com IDs oficiais).
  - Lido uma vez no startup, sem gastar quota da API.
  - IDs, slugs, grupos, rodadas, horários já estão corretos.

Fonte de stats/H2H/forma: API-Football v3 (chamada sob demanda).
  - /teams/statistics nas Copas anteriores (2022 → 2018 → 2014 → 2010)
  - /fixtures/headtohead  (últimos 10 confrontos, sem filtro de data)
  - /fixtures?team={id}&last=5  (forma recente em qualquer competição)

Regra: nunca inventa dados — dados_insuficientes=True quando a API não retorna.
Cache: 1 hora (fixtures do seed não expiram; API responses sim).
"""
import asyncio
import json
import os
from math import exp, factorial
from pathlib import Path

import httpx
from cachetools import TTLCache

from app.models.schemas import (
    EstatisticasTime, EntradaForma, Partida, PartidaResumo, Probabilidades,
)

BASE_URL    = "https://v3.football.api-sports.io"
HEADERS     = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}
WC_SEASONS  = [2022, 2018, 2014, 2010]

_cache: TTLCache = TTLCache(maxsize=300, ttl=3600)

# ── Seed carregado uma vez no startup ────────────────────────────────────────

def _carregar_seed() -> dict:
    path = Path(__file__).parent.parent.parent / "seeds" / "copa_2026.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)

_SEED  = _carregar_seed()
_TIMES = _SEED["times"]           # nome -> {api_football_id, logo, ...}
_JOGOS = _SEED["jogos"]           # lista de 72 jogos
_POR_SLUG: dict[str, dict] = {j["slug"]: j for j in _JOGOS}


# ── HTTP com cache ────────────────────────────────────────────────────────────

async def _get(client: httpx.AsyncClient, path: str, params: dict) -> dict:
    key = f"{path}:{sorted(params.items())}"
    if key in _cache:
        return _cache[key]
    resp = await client.get(f"{BASE_URL}{path}", headers=HEADERS, params=params)
    resp.raise_for_status()
    data = resp.json()
    _cache[key] = data
    return data


# ── Modelo de Poisson ─────────────────────────────────────────────────────────

def _poisson(lam: float, k: int) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * exp(-lam) / factorial(k)


def _calcular_probabilidades(lambda_casa: float, lambda_fora: float) -> Probabilidades:
    MAX = 9
    p_v = p_e = p_d = 0.0
    for i in range(MAX):
        for j in range(MAX):
            p = _poisson(lambda_casa, i) * _poisson(lambda_fora, j)
            if i > j:   p_v += p
            elif i == j: p_e += p
            else:        p_d += p
    total = p_v + p_e + p_d
    return Probabilidades(
        vitoria_casa=round(p_v / total * 100),
        empate=round(p_e / total * 100),
        vitoria_fora=round(p_d / total * 100),
        lambda_casa=round(lambda_casa, 2),
        lambda_fora=round(lambda_fora, 2),
        metodo="poisson",
        dados_insuficientes=False,
    )


# ── Dados por time (via API) ──────────────────────────────────────────────────

async def _stats_time(client: httpx.AsyncClient, team_id: int) -> EstatisticasTime:
    """Stats históricas do time nas Copas do Mundo disponíveis (2022→2010)."""
    for season in WC_SEASONS:
        try:
            data  = await _get(client, "/teams/statistics", {
                "league": 1, "season": season, "team": team_id,
            })
            resp  = data.get("response", {})
            jogos = resp.get("fixtures", {}).get("played", {}).get("total", 0)
            if not resp or jogos == 0:
                continue
            return EstatisticasTime(
                media_gols_marcados=float(resp["goals"]["for"]["average"]["total"]),
                media_gols_sofridos=float(resp["goals"]["against"]["average"]["total"]),
                vitorias=resp["fixtures"]["wins"]["total"],
                empates=resp["fixtures"]["draws"]["total"],
                derrotas=resp["fixtures"]["loses"]["total"],
                jogos=jogos,
                fonte=f"Copa {season}",
                dados_insuficientes=False,
            )
        except Exception:
            continue
    return EstatisticasTime(dados_insuficientes=True)


async def _forma_recente(client: httpx.AsyncClient, team_id: int) -> list[EntradaForma]:
    """Últimos 5 jogos do time em qualquer competição."""
    try:
        data     = await _get(client, "/fixtures", {"team": team_id, "last": 5})
        fixtures = data.get("response", [])
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


async def _h2h(client: httpx.AsyncClient, id1: int, id2: int) -> list[dict]:
    """Últimos 10 confrontos diretos, sem filtro de data ou liga."""
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
    """
    Retorna todos os 72 jogos da fase de grupos.
    Lê do seed — sem chamada à API, sem gastar quota.
    """
    return [_jogo_para_resumo(j) for j in _JOGOS]


async def buscar_detalhe_partida(slug: str) -> Partida | None:
    """
    Retorna detalhes completos de um jogo pelo slug.
    Fixture: do seed (IDs reais, zero quota).
    Stats, forma e H2H: chamadas paralelas à API.
    """
    jogo = _POR_SLUG.get(slug)
    if not jogo:
        return None

    home_id = jogo["time_casa_id"]
    away_id = jogo["time_fora_id"]

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            # 5 chamadas em paralelo — se a API falhar, retorna defaults do seed
            stats_casa, stats_fora, forma_casa, forma_fora, h2h = await asyncio.gather(
                _stats_time(client, home_id),
                _stats_time(client, away_id),
                _forma_recente(client, home_id),
                _forma_recente(client, away_id),
                _h2h(client, home_id, away_id),
            )
    except Exception:
        # API completamente inacessível: retorna fixture do seed com dados_insuficientes
        stats_casa = stats_fora = EstatisticasTime(dados_insuficientes=True)
        forma_casa = forma_fora = []
        h2h = []

    # Probabilidades via Poisson — só se ambos tiverem médias
    if (
        not stats_casa.dados_insuficientes
        and not stats_fora.dados_insuficientes
        and stats_casa.media_gols_marcados is not None
        and stats_fora.media_gols_marcados is not None
    ):
        probabilidades = _calcular_probabilidades(
            stats_casa.media_gols_marcados,
            stats_fora.media_gols_marcados,
        )
    else:
        probabilidades = Probabilidades(
            vitoria_casa=0, empate=0, vitoria_fora=0,
            lambda_casa=0.0, lambda_fora=0.0,
            dados_insuficientes=True,
        )

    return Partida(
        id=jogo["api_fixture_id"],
        slug=jogo["slug"],
        rodada=jogo["rodada"],
        horario=jogo["data_hora_brasilia"],
        status=jogo.get("status", "NS"),
        estadio=jogo.get("estadio", ""),
        cidade=jogo.get("cidade", ""),
        time_casa_nome=jogo["time_casa"],
        time_casa_logo=jogo.get("time_casa_logo", ""),
        time_casa_id=home_id,
        time_fora_nome=jogo["time_fora"],
        time_fora_logo=jogo.get("time_fora_logo", ""),
        time_fora_id=away_id,
        gols_casa=jogo.get("gols_casa"),
        gols_fora=jogo.get("gols_fora"),
        stats_casa=stats_casa,
        stats_fora=stats_fora,
        forma_casa=forma_casa,
        forma_fora=forma_fora,
        head_to_head=h2h,
        probabilidades=probabilidades,
        dados_insuficientes=(
            stats_casa.dados_insuficientes
            or stats_fora.dados_insuficientes
            or len(forma_casa) == 0
            or len(forma_fora) == 0
            or len(h2h) == 0
        ),
    )
