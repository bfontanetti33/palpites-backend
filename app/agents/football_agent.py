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

# Competições internacionais tentadas em cascata quando time não tem histórico de Copa.
# Ordem importa: tenta WC primeiro, depois confederações por relevância.
_INTL_LEAGUES: list[tuple[int, list[int], str]] = [
    (4,  [2024, 2021, 2016],       "Euro"),           # UEFA Euro
    (9,  [2024, 2021, 2019, 2016], "Copa América"),    # CONMEBOL Copa América
    (29, [2023, 2021, 2019, 2017], "AFCON"),           # Africa Cup of Nations
    (17, [2023, 2021, 2019, 2017], "Gold Cup"),        # CONCACAF Gold Cup
    (6,  [2023, 2019, 2015],       "Asian Cup"),       # AFC Asian Cup
    (5,  [2024, 2022, 2020],       "Nations League"),  # UEFA Nations League
]

_cache: TTLCache = TTLCache(maxsize=400, ttl=14400)   # 4h — chamadas individuais API-Football
_partida_cache: TTLCache = TTLCache(maxsize=72, ttl=14400)  # 4h — resposta completa por slug

# ── Seed árbitros Copa 2026 ───────────────────────────────────────────────────
def _carregar_seed_arbitros() -> dict:
    path = Path(__file__).parent.parent.parent / "seeds" / "arbitros_copa_2026.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"meta": {}, "arbitros": []}

_SEED_ARBITROS = _carregar_seed_arbitros()
_MEDIA_COPA = _SEED_ARBITROS.get("meta", {}).get("media_copa", {
    "cartoes_por_jogo": 3.4, "penaltis_por_jogo": 0.15
})


def _normalizar_nome_arb(nome: str) -> str:
    """Lowercase + remove acentos para fuzzy match de árbitros."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", nome)
    return nfkd.encode("ASCII", "ignore").decode("ASCII").lower().strip()


def _buscar_no_seed_arb(nome_raw: str) -> dict | None:
    """Procura árbitro no seed por correspondência de nome (case+accent insensitive)."""
    if not nome_raw:
        return None
    norm = _normalizar_nome_arb(nome_raw)
    for a in _SEED_ARBITROS.get("arbitros", []):
        a_norm = _normalizar_nome_arb(a.get("nome", ""))
        if norm in a_norm or a_norm in norm:
            return a
    return None


# ── Seed ─────────────────────────────────────────────────────────────────────

def _carregar_seed() -> dict:
    path = Path(__file__).parent.parent.parent / "seeds" / "copa_2026.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)

_SEED = _carregar_seed()
_JOGOS: list[dict] = _SEED["jogos"]
_POR_SLUG: dict[str, dict] = {j["slug"]: j for j in _JOGOS}


# ── Seed forma recente (fallback quando API retorna vazio) ────────────────────

def _carregar_seed_forma() -> dict:
    path = Path(__file__).parent.parent.parent / "seeds" / "forma_recente_seed.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_SEED_FORMA = _carregar_seed_forma()


# ── Seed H2H (fallback quando API retorna vazio) ──────────────────────────────

def _carregar_seed_h2h() -> dict:
    path = Path(__file__).parent.parent.parent / "seeds" / "h2h_seed.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_SEED_H2H = _carregar_seed_h2h()


# ── HTTP com cache ─────────────────────────────────────────────────────────────

async def _get(client: httpx.AsyncClient, path: str, params: dict) -> dict:
    key = f"{path}:{sorted(params.items())}"
    if key in _cache:
        return _cache[key]
    resp = await client.get(f"{BASE_URL}{path}", headers=HEADERS, params=params)
    # Captura quota restante para o monitoring
    remaining = resp.headers.get("x-ratelimit-requests-remaining")
    if remaining is not None:
        try:
            from app.monitoring.telegram_bot import atualizar_quota_api_football
            atualizar_quota_api_football(remaining)
        except Exception:
            pass
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
    Busca estatísticas históricas do time em competições internacionais.
    Tenta Copa do Mundo primeiro (melhor fonte), depois confederações em cascata:
    Euro → Copa América → AFCON → Gold Cup → Asian Cup → Nations League.
    Casa/fora são IGNORADOS pois todas são disputadas em campo neutro.
    """
    # Monta lista de (league_id, season, fonte_label) para tentar em ordem
    candidates: list[tuple[int, int, str]] = [
        (1, s, f"Copa {s}") for s in WC_SEASONS
    ]
    for league_id, seasons, label in _INTL_LEAGUES:
        for season in seasons:
            candidates.append((league_id, season, f"{label} {season}"))

    for league_id, season, fonte_label in candidates:
        try:
            data  = await _get(client, "/teams/statistics", {
                "league": league_id, "season": season, "team": team_id,
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
                fonte=fonte_label,
                dados_insuficientes=False,
                sede_neutra=True,
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


# ── Forma recente (últimos 5 jogos, apenas masculino sênior) ──────────────────

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
    Últimos jogos da seleção masculina profissional em qualquer competição.
    Busca 20 candidatos da API; fallback automático para forma_recente_seed.json
    quando a API retorna vazio (comum em seleções nacionais fora de janela FIFA).
    """
    fixtures = []
    try:
        data = await _get(client, "/fixtures", {"team": team_id, "last": 20})
        fixtures = [
            f for f in data.get("response", [])
            if _e_jogo_senior_masculino(f)
        ]
    except Exception:
        pass

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

    if forma:
        return forma[-10:]

    # Fallback: seed forma recente (keyed por team_id como string)
    seed_time = _SEED_FORMA.get("times", {}).get(str(team_id), {})
    if seed_time:
        return [
            EntradaForma(
                data=j["data"],
                adversario=j["adversario"],
                placar_proprio=j.get("placar_proprio"),
                placar_adversario=j.get("placar_adversario"),
                resultado=j["resultado"],
                competicao=j.get("competicao", "Amistoso"),
            )
            for j in seed_time.get("jogos", [])
        ]
    return []


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

async def _h2h(client: httpx.AsyncClient, id1: int, id2: int, slug: str = "") -> list[dict]:
    """H2H via API-Football com fallback para h2h_seed.json quando API retorna vazio."""
    try:
        data = await _get(client, "/fixtures/headtohead", {
            "h2h": f"{id1}-{id2}", "last": 10,
        })
        result = [
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
        if result:
            return result
    except Exception:
        pass
    # Fallback: seed histórico de Copa do Mundo / competições maiores
    if slug:
        seed_data = _SEED_H2H.get("h2h", {}).get(slug, [])
        if seed_data:
            return seed_data
    return []


# ── Árbitro ───────────────────────────────────────────────────────────────────

def _tendencia_de_cartoes(cpj: float | None) -> str | None:
    if cpj is None:
        return None
    if cpj >= 4.5:
        return "Rigoroso"
    if cpj >= 3.0:
        return "Moderado"
    return "Permissivo"


async def _arbitro(client: httpx.AsyncClient, fixture_id: int) -> Arbitro:
    """
    Busca o árbitro do jogo:
    1. Consulta seed arbitros_copa_2026.json (se fonte != 'pendente': usa direto)
    2. Se pendente ou não encontrado: calcula da API-Football
    3. Se fixture não tem árbitro: retorna médias da Copa 2026
    """
    _default = Arbitro(
        nome=None,
        pais=None,
        cartoes_por_jogo=_MEDIA_COPA.get("cartoes_por_jogo"),
        penaltis_por_jogo=_MEDIA_COPA.get("penaltis_por_jogo"),
        tendencia="Moderado",
        fonte="media_copa_2026",
        nota="Árbitro ainda não designado — baseado na média dos 52 árbitros da Copa",
    )

    try:
        data = await _get(client, "/fixtures", {"id": fixture_id})
        resp = data.get("response", [{}])[0]
        nome_raw = resp.get("fixture", {}).get("referee")

        if not nome_raw:
            return _default

        partes = nome_raw.split(",")
        nome = partes[0].strip()
        pais = partes[1].strip() if len(partes) > 1 else None

        # 1. Verifica seed
        seed_entry = _buscar_no_seed_arb(nome)
        if seed_entry and seed_entry.get("fonte") not in (None, "pendente"):
            return Arbitro(
                nome=seed_entry.get("nome", nome),
                pais=seed_entry.get("pais", pais),
                cartoes_por_jogo=seed_entry.get("cartoes_por_jogo"),
                penaltis_por_jogo=seed_entry.get("penaltis_por_jogo"),
                tendencia=seed_entry.get("tendencia"),
                fonte="seed",
            )

        # 2. Calcula da API-Football (últimos 20 jogos)
        jogos_data = await _get(client, "/fixtures", {"referee": nome, "last": 20})
        jogos = jogos_data.get("response", [])

        pais_seed = seed_entry.get("pais") if seed_entry else pais

        if not jogos:
            cpj = _MEDIA_COPA.get("cartoes_por_jogo")
            return Arbitro(
                nome=nome, pais=pais_seed, jogos_apitados=0,
                cartoes_por_jogo=cpj,
                penaltis_por_jogo=_MEDIA_COPA.get("penaltis_por_jogo"),
                tendencia=_tendencia_de_cartoes(cpj),
                fonte="media_copa_2026",
                nota="Histórico não encontrado na API — usando média da Copa",
            )

        total = len(jogos)
        total_yellow = total_red = 0
        for f in jogos:
            for s in (f.get("statistics") or []):
                for item in s.get("statistics", []):
                    tipo = (item.get("type") or "").lower()
                    val  = item.get("value") or 0
                    try: val = int(val)
                    except (TypeError, ValueError): val = 0
                    if "yellow" in tipo:
                        total_yellow += val
                    elif "red" in tipo:
                        total_red += val

        cpj = round((total_yellow + total_red) / total, 2) if total else _MEDIA_COPA.get("cartoes_por_jogo")
        return Arbitro(
            nome=nome,
            pais=pais_seed,
            jogos_apitados=total,
            cartoes_por_jogo=cpj,
            penaltis_por_jogo=_MEDIA_COPA.get("penaltis_por_jogo"),
            tendencia=_tendencia_de_cartoes(cpj),
            fonte="api-football",
        )

    except Exception:
        return _default


# ── Escanteios — busca via /fixtures/statistics ───────────────────────────────

async def _media_escanteios(client: httpx.AsyncClient, team_id: int) -> float | None:
    """
    Calcula média de escanteios do time nos últimos 5 jogos sênior.
    Re-usa o cache de /fixtures?team&last=20 já feito por _forma_recente.
    Para cada fixture, chama /fixtures/statistics (cacheado por 4h).
    """
    try:
        data = await _get(client, "/fixtures", {"team": team_id, "last": 20})
        fixtures = [f for f in data.get("response", []) if _e_jogo_senior_masculino(f)]
        fixtures = sorted(fixtures, key=lambda x: x["fixture"]["date"])[-5:]

        escanteios: list[int] = []
        for f in fixtures:
            fid = f["fixture"]["id"]
            is_home = f["teams"]["home"]["id"] == team_id
            try:
                sdata = await _get(client, "/fixtures/statistics", {"fixture": fid})
                for team_stats in sdata.get("response", []):
                    if team_stats.get("team", {}).get("id") != team_id:
                        continue
                    for stat in team_stats.get("statistics", []):
                        if "Corner" in str(stat.get("type", "")):
                            val = stat.get("value")
                            if val is not None:
                                try:
                                    escanteios.append(int(val))
                                except (TypeError, ValueError):
                                    pass
                    break
            except Exception:
                continue

        return round(sum(escanteios) / len(escanteios), 1) if escanteios else None
    except Exception:
        return None


# ── Chances criadas — estimativa via modelo Dixon-Coles ───────────────────────

def _calc_chances_criadas(
    media_gols: float | None, btts_pct: int | None, lambda_ataque: float
) -> float:
    """
    Proxy calibrado: media histórica 8-15 chances/jogo em futebol de elite.
    Fórmula: (gols × conversão) + (btts × frequência) + (lambda × escala DC)
    """
    mg   = media_gols or 1.2
    btts = (btts_pct or 50) / 100
    raw  = (mg * 3.2) + (btts * 2.0) + (lambda_ataque * 1.5)
    return round(max(8.0, min(15.0, raw)), 1)


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

def _favorito_e_prob(
    nome_casa: str, nome_fora: str, prob: "Probabilidades | None"
) -> tuple[str, float | None]:
    """Retorna (nome_favorito, prob_favorito) a partir das probabilidades."""
    if not prob or prob.dados_insuficientes:
        return "", None
    vc, emp, vf = prob.vitoria_casa, prob.empate, prob.vitoria_fora
    if vc >= vf and vc >= emp:
        return nome_casa, float(vc)
    if vf > vc and vf >= emp:
        return nome_fora, float(vf)
    return "Empate", float(emp)


def _insight_curto(nome_casa: str, nome_fora: str, prob: "Probabilidades | None") -> str:
    """Gera 1 frase curtíssima sobre o confronto sem chamar Claude."""
    if not prob or prob.dados_insuficientes:
        return f"{nome_casa} x {nome_fora}"
    vc, emp, vf = prob.vitoria_casa, prob.empate, prob.vitoria_fora
    if vc >= 55:
        return f"{nome_casa} favorito ({vc}%)"
    if vf >= 55:
        return f"{nome_fora} favorito ({vf}%)"
    if vc >= 45:
        return f"{nome_casa} com leve vantagem ({vc}%)"
    if vf >= 45:
        return f"{nome_fora} com leve vantagem ({vf}%)"
    return f"Confronto equilibrado — {nome_casa} {vc}% / Empate {emp}% / {nome_fora} {vf}%"


def _jogo_para_resumo(j: dict, partida: "Partida | None" = None) -> PartidaResumo:
    nome_casa = j["time_casa"]
    nome_fora = j["time_fora"]
    prob = partida.probabilidades if partida else None

    fav, prob_fav = _favorito_e_prob(nome_casa, nome_fora, prob)

    return PartidaResumo(
        id=j["api_fixture_id"],
        slug=j["slug"],
        rodada=j["rodada"],
        horario=j["data_hora_brasilia"],
        status=j.get("status") or "NS",
        estadio=j.get("estadio") or "",
        cidade=j.get("cidade") or "",
        time_casa_nome=nome_casa,
        time_casa_logo=j.get("time_casa_logo") or "",
        time_fora_nome=nome_fora,
        time_fora_logo=j.get("time_fora_logo") or "",
        gols_casa=j.get("gols_casa"),
        gols_fora=j.get("gols_fora"),
        # Probabilidades (do cache, se disponível)
        prob_vitoria_casa=float(prob.vitoria_casa) if prob else None,
        prob_empate=float(prob.empate)              if prob else None,
        prob_vitoria_fora=float(prob.vitoria_fora)  if prob else None,
        favorito=fav,
        prob_favorito=prob_fav,
        insight_curto=_insight_curto(nome_casa, nome_fora, prob),
        resumo_rapido=partida.insight_probabilidades if partida else "",
    )


# ── Pré-cache de todos os jogos (chamado no startup) ─────────────────────────

async def precalcular_todos_jogos(delay: float = 1.5) -> int:
    """
    Itera pelos 72 slugs do seed e chama buscar_detalhe_partida para cada um.
    Popula _partida_cache e captura quota da API-Football.
    Retorna número de slugs cacheados com sucesso.
    Roda em background — não bloqueia o startup.
    """
    import logging
    log = logging.getLogger(__name__)
    total = len(_JOGOS)
    log.info(f"Iniciando pré-cache de {total} jogos em background...")
    ok = 0
    for jogo in _JOGOS:
        try:
            await buscar_detalhe_partida(jogo["slug"])
            ok += 1
        except Exception:
            pass
        await asyncio.sleep(delay)
    log.info(f"Pré-cache concluído: {ok}/{total} jogos cacheados")
    return ok


# ── Geração de insights textuais (rule-based, zero chamadas externas) ─────────

def _gerar_insight_forma(nome: str, forma: list[EntradaForma]) -> str:
    if not forma:
        return f"Dados de forma de {nome} indisponíveis — sem jogos recentes na API."
    ultimos = forma[-5:]
    v = sum(1 for j in ultimos if j.resultado == "W")
    e = sum(1 for j in ultimos if j.resultado == "D")
    d = sum(1 for j in ultimos if j.resultado == "L")
    gols_pro = [j.placar_proprio for j in ultimos if j.placar_proprio is not None]
    media = round(sum(gols_pro) / len(gols_pro), 1) if gols_pro else 0.0
    if v >= 4:
        avaliacao = "excelente momento"
    elif v >= 3:
        avaliacao = "boa fase"
    elif d >= 4:
        avaliacao = "má fase preocupante"
    elif d >= 3:
        avaliacao = "fase difícil"
    else:
        avaliacao = "forma irregular"
    return (
        f"{nome} chega em {avaliacao}: {v}V {e}E {d}D nos últimos {len(ultimos)} jogos, "
        f"média de {media} gols marcados por partida."
    )


def _gerar_insight_probabilidades(
    nome_casa: str, nome_fora: str, prob: "Probabilidades | None"
) -> str:
    if not prob:
        return "Probabilidades indisponíveis."
    if prob.dados_insuficientes:
        return (
            f"Probabilidades estimadas com fallback histórico (1.2 gols/jogo): "
            f"{nome_casa} {prob.vitoria_casa}% · Empate {prob.empate}% · {nome_fora} {prob.vitoria_fora}%."
        )
    vc, emp, vf = prob.vitoria_casa, prob.empate, prob.vitoria_fora
    lc, lf = prob.lambda_casa, prob.lambda_fora
    if vc >= 55:
        lider = f"{nome_casa} é favorito com {vc}% de vitória"
    elif vf >= 55:
        lider = f"{nome_fora} é favorito com {vf}% de vitória"
    elif vc >= 45:
        lider = f"{nome_casa} tem leve vantagem ({vc}% vs {vf}%)"
    else:
        lider = f"Confronto equilibrado — {nome_casa} {vc}% · Empate {emp}% · {nome_fora} {vf}%"
    return f"{lider}. Gols esperados: {lc} (casa) e {lf} (fora). Empate: {emp}%."


# ── API pública ───────────────────────────────────────────────────────────────

async def buscar_todos_jogos_copa() -> list[PartidaResumo]:
    """
    72 jogos da fase de grupos — lidos do seed, zero quota.
    Enriquece com probabilidades e insights do _partida_cache quando disponível.
    """
    return [_jogo_para_resumo(j, _partida_cache.get(j["slug"])) for j in _JOGOS]


async def buscar_detalhe_partida(slug: str) -> Partida | None:
    if slug in _partida_cache:
        return _partida_cache[slug]

    jogo = _POR_SLUG.get(slug)
    if not jogo:
        return None

    home_id    = jogo["time_casa_id"]
    away_id    = jogo["time_fora_id"]
    fixture_id = jogo["api_fixture_id"]
    home_nome  = jogo["time_casa"]
    away_nome  = jogo["time_fora"]

    # ── 8 chamadas paralelas à API-Football ──────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            (
                stats_casa_raw,
                stats_fora_raw,
                forma_casa,
                forma_fora,
                h2h,
                arb,
                esc_casa,
                esc_fora,
            ) = await asyncio.gather(
                _stats_time(client, home_id),
                _stats_time(client, away_id),
                _forma_recente(client, home_id),
                _forma_recente(client, away_id),
                _h2h(client, home_id, away_id, slug),
                _arbitro(client, fixture_id),
                _media_escanteios(client, home_id),
                _media_escanteios(client, away_id),
            )
    except Exception:
        stats_casa_raw = stats_fora_raw = EstatisticasTemporada(dados_insuficientes=True)
        forma_casa = forma_fora = []
        h2h = []
        arb = None
        esc_casa = esc_fora = None

    # ── Enriquece stats com BTTS/Over + escanteios ────────────────────────────
    stats_casa = _enriquecer_btts_over(stats_casa_raw, forma_casa)
    stats_fora = _enriquecer_btts_over(stats_fora_raw, forma_fora)
    stats_casa.media_escanteios = esc_casa
    stats_fora.media_escanteios = esc_fora

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
    placares_provaveis: list[PlacarProvavel] = []

    # Prefere médias dos últimos 10 jogos (mais representativas) sobre histórico de Copa.
    # Fallback de 1.2 gols/jogo (média histórica internacional) quando stats indisponíveis.
    lc_raw = stats_casa.media_gols_marcados_recente or stats_casa.media_gols_marcados
    lf_raw = stats_fora.media_gols_marcados_recente or stats_fora.media_gols_marcados
    lc = lc_raw if lc_raw is not None else 1.2
    lf = lf_raw if lf_raw is not None else 1.2

    probabilidades     = _calcular_probabilidades(lc, lf)
    if lc_raw is None or lf_raw is None:
        probabilidades = probabilidades.model_copy(update={"dados_insuficientes": True})
    placares_provaveis = _calcular_placares_provaveis(lc, lf, top=3)

    # ── Chances criadas estimadas (proxy DC) ──────────────────────────────────
    stats_casa.chances_criadas = _calc_chances_criadas(
        stats_casa.media_gols_marcados_recente or stats_casa.media_gols_marcados,
        stats_casa.btts_pct, lc,
    )
    stats_fora.chances_criadas = _calc_chances_criadas(
        stats_fora.media_gols_marcados_recente or stats_fora.media_gols_marcados,
        stats_fora.btts_pct, lf,
    )
    stats_casa.chances_criadas_metodo = "estimado"
    stats_fora.chances_criadas_metodo = "estimado"

    partida = Partida(
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
            len(forma_casa) == 0
            or len(forma_fora) == 0
        ),
        insight_forma_casa=_gerar_insight_forma(jogo["time_casa"], forma_casa),
        insight_forma_fora=_gerar_insight_forma(jogo["time_fora"], forma_fora),
        insight_probabilidades=_gerar_insight_probabilidades(
            jogo["time_casa"], jogo["time_fora"], probabilidades
        ),
    )
    _partida_cache[slug] = partida
    return partida
