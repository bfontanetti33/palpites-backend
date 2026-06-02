"""
Odds Agent — The Odds API (the-odds-api.com)
Sport key: soccer_fifa_world_cup  (Copa 2026 ativa com 72 eventos)

Mercados buscados:
  h2h      → 1X2 (vitória casa, empate, vitória fora)
  totals   → Over/Under (1.5, 2.5, 3.5)
  spreads  → handicap asiático (opcional)

Retorna dict normalizado compatível com o campo Partida.odds
e com o Value Bet Detector da Camada 3 do ia_agent.py.

Quota: 500 requests/mês no plano free.
Cache: 30 minutos (odds mudam, mas não a cada segundo).
"""
import os
from datetime import datetime, timezone
from cachetools import TTLCache
import httpx

ODDS_API_KEY  = os.getenv("ODDS_API_KEY", "")
BASE          = "https://api.the-odds-api.com/v4"
SPORT         = "soccer_fifa_world_cup"
REGIONS       = "eu"                      # odds europeias (Bet365, Pinnacle, etc.)
ODDS_FORMAT   = "decimal"
DATE_FORMAT   = "iso"
BOOKMAKER_PREF = ["pinnacle", "bet365", "betfair_ex_eu", "unibet_eu"]

_cache: TTLCache = TTLCache(maxsize=200, ttl=1800)  # 30 min


# ── HTTP ──────────────────────────────────────────────────────────────────────

async def _get(client: httpx.AsyncClient, path: str, params: dict = {}) -> dict | list:
    key = f"{path}:{sorted(params.items())}"
    if key in _cache:
        return _cache[key]
    params["apiKey"] = ODDS_API_KEY
    r = await client.get(f"{BASE}{path}", params=params)
    r.raise_for_status()
    remaining = r.headers.get("x-requests-remaining", "?")
    used      = r.headers.get("x-requests-used", "?")
    data = r.json()
    _cache[key] = data
    return data


# ── Busca de eventos ──────────────────────────────────────────────────────────

async def listar_eventos_copa() -> list[dict]:
    """Retorna todos os 72 jogos da Copa 2026 com seus IDs na The Odds API."""
    async with httpx.AsyncClient(timeout=15) as client:
        data = await _get(client, f"/sports/{SPORT}/events", {
            "dateFormat": DATE_FORMAT,
        })
        return data if isinstance(data, list) else []


async def buscar_event_id(home: str, away: str) -> str | None:
    """
    Encontra o event_id na The Odds API pelo nome dos times.
    Normaliza os nomes para comparação (lowercase, sem acentos).
    """
    eventos = await listar_eventos_copa()
    home_l = home.lower().replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u")
    away_l = away.lower().replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u")

    for ev in eventos:
        h = ev.get("home_team", "").lower()
        a = ev.get("away_team", "").lower()
        # Correspondência por substring bidirecional
        if (home_l in h or h in home_l) and (away_l in a or a in away_l):
            return ev["id"]
        if (away_l in h or h in away_l) and (home_l in a or a in home_l):
            return ev["id"]  # times invertidos na API
    return None


# ── Busca de odds ─────────────────────────────────────────────────────────────

def _melhor_bookmaker(bookmakers: list) -> dict | None:
    """Prioriza Pinnacle > Bet365 > outros pela ordem de BOOKMAKER_PREF."""
    bm_map = {bm["key"]: bm for bm in bookmakers}
    for pref in BOOKMAKER_PREF:
        if pref in bm_map:
            return bm_map[pref]
    return bookmakers[0] if bookmakers else None


def _parsear_h2h(mercado: dict) -> dict:
    """Extrai vitória casa, empate, vitória fora do mercado h2h."""
    odds: dict = {}
    outcomes = {o["name"]: float(o["price"]) for o in mercado.get("outcomes", [])}
    # A API retorna os nomes reais dos times + "Draw"
    for nome, odd in outcomes.items():
        nome_l = nome.lower()
        if "draw" in nome_l:
            odds["empate"] = odd
        # Os outros dois são os times — o primeiro listado é o "home"
    teams = [n for n in outcomes if "draw" not in n.lower()]
    if len(teams) >= 2:
        odds["vitoria_casa"] = outcomes[teams[0]]
        odds["vitoria_fora"] = outcomes[teams[1]]
    return odds


def _parsear_totals(mercado: dict) -> dict:
    """Extrai Over/Under 1.5, 2.5 e 3.5 do mercado totals."""
    odds: dict = {}
    for outcome in mercado.get("outcomes", []):
        nome  = outcome["name"]   # "Over" ou "Under"
        ponto = outcome.get("point", 0.0)
        odd   = float(outcome["price"])
        chave = f"{'over' if nome == 'Over' else 'under'}{str(ponto).replace('.','').replace('5','5')}"
        # Simplifica para over15, over25, over35, under15, under25, under35
        if ponto == 1.5:
            chave = "over15" if nome == "Over" else "under15"
        elif ponto == 2.5:
            chave = "over25" if nome == "Over" else "under25"
        elif ponto == 3.5:
            chave = "over35" if nome == "Over" else "under35"
        else:
            continue  # ignora linhas não-padrão (ex: 4.5, 0.5)
        odds[chave] = odd
    return odds


async def buscar_odds_evento(event_id: str) -> dict | None:
    """
    Busca odds reais de um evento pelo ID.
    Retorna dict normalizado: {vitoria_casa, empate, vitoria_fora, over15, ...}
    ou None se não houver odds disponíveis.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            data = await _get(client, f"/sports/{SPORT}/events/{event_id}/odds", {
                "regions":    REGIONS,
                "markets":    "h2h,totals",
                "oddsFormat": ODDS_FORMAT,
                "dateFormat": DATE_FORMAT,
            })
        except httpx.HTTPStatusError as e:
            return None

    if not isinstance(data, dict):
        return None

    bookmakers = data.get("bookmakers", [])
    if not bookmakers:
        return None

    bm = _melhor_bookmaker(bookmakers)
    if not bm:
        return None

    odds: dict = {"bookmaker": bm["key"], "event_id": event_id}
    for mercado in bm.get("markets", []):
        key = mercado.get("key")
        if key == "h2h":
            odds.update(_parsear_h2h(mercado))
        elif key == "totals":
            odds.update(_parsear_totals(mercado))

    return odds if len(odds) > 2 else None  # retorna None se só tem metadados


# ── API pública ───────────────────────────────────────────────────────────────

async def buscar_odds_partida(home_nome: str, away_nome: str) -> dict | None:
    """
    Busca odds completas para uma partida da Copa 2026.
    Retorna dict normalizado compatível com Partida.odds, ou None.
    """
    event_id = await buscar_event_id(home_nome, away_nome)
    if not event_id:
        return None
    return await buscar_odds_evento(event_id)


async def buscar_todas_odds_copa() -> dict[str, dict]:
    """
    Busca odds de todos os jogos da Copa 2026 de uma vez (1 request).
    Retorna {event_id: odds_dict}.
    Mais eficiente para múltiplas partidas.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            data = await _get(client, f"/sports/{SPORT}/odds", {
                "regions":    REGIONS,
                "markets":    "h2h,totals",
                "oddsFormat": ODDS_FORMAT,
                "dateFormat": DATE_FORMAT,
            })
        except httpx.HTTPStatusError:
            return {}

    if not isinstance(data, list):
        return {}

    resultado: dict[str, dict] = {}
    for evento in data:
        event_id   = evento.get("id", "")
        bookmakers = evento.get("bookmakers", [])
        if not bookmakers:
            continue
        bm = _melhor_bookmaker(bookmakers)
        if not bm:
            continue
        odds: dict = {
            "bookmaker":  bm["key"],
            "event_id":   event_id,
            "home_team":  evento.get("home_team", ""),
            "away_team":  evento.get("away_team", ""),
            "commence_time": evento.get("commence_time", ""),
        }
        for mercado in bm.get("markets", []):
            key = mercado.get("key")
            if key == "h2h":
                odds.update(_parsear_h2h(mercado))
            elif key == "totals":
                odds.update(_parsear_totals(mercado))
        if len(odds) > 5:  # tem pelo menos alguns mercados além dos metadados
            resultado[event_id] = odds

    return resultado
