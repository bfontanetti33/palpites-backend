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
import logging
import os
import time
from datetime import datetime, timezone
from math import exp, factorial
from pathlib import Path

import httpx
from cachetools import TTLCache

from app.models.schemas import (
    Arbitro, EntradaForma, EstatisticasTemporada, Partida,
    PartidaResumo, PerformanceLocal, PlacarProvavel, Probabilidades,
)

log = logging.getLogger(__name__)

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

_cache: TTLCache = TTLCache(maxsize=400, ttl=28800)   # 8h — chamadas individuais API-Football
_partida_cache: TTLCache = TTLCache(maxsize=72, ttl=28800)  # 8h — resposta completa por slug

# Rate limiter: API-Football Pro permite ~30 req/min → 1 req a cada 2s é seguro
_last_api_call: float = 0.0
_API_MIN_INTERVAL = 2.0  # segundos entre chamadas reais à API

# ── Cache persistente de respostas da API-Football ────────────────────────────
# Sobrevive redeploys — zera custo de quota em cada novo deploy.
_API_DISK_PATH = Path(__file__).parent.parent.parent / "seeds" / "football_api_cache.json"
_API_DISK_TTL  = 28800  # 8h — mesmo TTL do cache em memória


def _load_api_disk_cache() -> None:
    """Restaura respostas da API do disco para o cache em memória ao iniciar."""
    try:
        if not _API_DISK_PATH.exists():
            return
        with open(_API_DISK_PATH, encoding="utf-8") as f:
            saved: dict = json.load(f)
        agora = time.time()
        restaurados = 0
        for key, entry in saved.items():
            if agora - entry.get("ts", 0) < _API_DISK_TTL and len(_cache) < _cache.maxsize:
                _cache[key] = entry["data"]
                restaurados += 1
        if restaurados:
            log.info("football_agent: %d respostas API restauradas do disco (quota preservada)", restaurados)
    except Exception as e:
        log.warning("football_agent: falha ao restaurar api_cache do disco: %s", e)


def _save_api_disk_cache() -> None:
    """Persiste o cache atual em disco (chamado após cada nova resposta da API)."""
    try:
        agora = time.time()
        data = {k: {"data": v, "ts": agora} for k, v in _cache.items()}
        _API_DISK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_API_DISK_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        log.warning("football_agent: falha ao persistir api_cache: %s", e)


# Carrega cache do disco na inicialização do módulo
_load_api_disk_cache()

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


# ── Seeds ────────────────────────────────────────────────────────────────────

def _carregar_seed() -> dict:
    path = Path(__file__).parent.parent.parent / "seeds" / "copa_2026.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)

_SEED = _carregar_seed()
_JOGOS: list[dict] = _SEED["jogos"]

def _slug_ascii(s: str) -> str:
    """Normaliza slug para ASCII puro (remove diacríticos): türkiye → turkiye, curaçao → curacao."""
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")

# Aceita tanto o slug Unicode original quanto a versão ASCII (sem diacríticos).
# Necessário porque URLs como australia-turkiye e australia-türkiye devem resolver o mesmo jogo.
_POR_SLUG: dict[str, dict] = {}
for _j in _JOGOS:
    _POR_SLUG[_j["slug"]] = _j
    _ascii = _slug_ascii(_j["slug"])
    if _ascii != _j["slug"]:
        _POR_SLUG[_ascii] = _j

# Statuses da API-Football usados pelo sync de placar
_STATUS_LIVE = {"1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT", "LIVE"}
_STATUS_FT   = {"FT", "AET", "PEN"}


def _carregar_seed_forma() -> dict[str, list]:
    """Retorna {team_id_str: [EntradaForma-dict, ...]} a partir do seed."""
    path = Path(__file__).parent.parent.parent / "seeds" / "forma_recente_seed.json"
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return {k: v.get("jogos", []) for k, v in raw.get("times", {}).items()}
    except Exception:
        return {}

_SEED_FORMA: dict[str, list] = _carregar_seed_forma()


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
    global _last_api_call
    key = f"{path}:{sorted(params.items())}"
    if key in _cache:
        return _cache[key]

    # Rate limiting: garante mínimo de 2s entre chamadas reais à API
    elapsed = time.time() - _last_api_call
    if elapsed < _API_MIN_INTERVAL:
        await asyncio.sleep(_API_MIN_INTERVAL - elapsed)

    _last_api_call = time.time()
    resp = await client.get(f"{BASE_URL}{path}", headers=HEADERS, params=params)

    # Retry em 429 — até 5 tentativas com backoff exponencial (1,2,4,8,16s)
    for attempt in range(5):
        if resp.status_code != 429:
            break
        retry_after = int(resp.headers.get("retry-after", 0)) or (2 ** attempt)
        log.warning("API-Football 429 (tentativa %d/5) — aguardando %ds", attempt + 1, retry_after)
        await asyncio.sleep(retry_after)
        _last_api_call = time.time()
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
    # Persiste no disco para sobreviver redeploys (zero quota em reinicializações)
    _save_api_disk_cache()
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
                log.debug("_stats_time team=%d %s: sem dados (jogos=%d)", team_id, fonte_label, jogos)
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
                media_amarelos=None,    # derivado da forma recente — ver _enriquecer_forma_com_cartoes
                media_vermelhos=None,
                penaltis_marcados=pen.get("scored", {}).get("total"),
                penaltis_total=pen.get("total"),
            )
        except Exception as e:
            log.debug("_stats_time team=%d %s: erro %s", team_id, fonte_label, e)
            continue

    log.warning("_stats_time team=%d: nenhuma liga retornou dados — usando fallback Elo", team_id)
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


def _forma_do_seed(team_id: int) -> list[EntradaForma]:
    """Retorna forma recente do seed local (fallback sem custo de API)."""
    jogos = _SEED_FORMA.get(str(team_id), [])
    forma = []
    for j in jogos:
        try:
            forma.append(EntradaForma(
                data=j["data"],
                adversario=j["adversario"],
                placar_proprio=j.get("placar_proprio"),
                placar_adversario=j.get("placar_adversario"),
                resultado=j["resultado"],
                competicao=j.get("competicao", ""),
            ))
        except Exception:
            continue
    return forma[-5:]


async def _forma_recente(client: httpx.AsyncClient, team_id: int) -> list[EntradaForma]:
    """
    Últimos jogos da seleção masculina profissional em qualquer competição.
    Tenta API-Football primeiro; se retornar vazio ou falhar, usa seed local.
    """
    fixtures = []
    try:
        data = await _get(client, "/fixtures", {"team": team_id, "last": 20})
        fixtures = [
            f for f in data.get("response", [])
            if _e_jogo_senior_masculino(f)
        ]
    except Exception as e:
        log.warning("_forma_recente team=%d: erro %s — usando seed", team_id, e)
        return _forma_do_seed(team_id)

    if not fixtures:
        log.warning("_forma_recente team=%d: API retornou 0 fixtures — usando seed", team_id)
        return _forma_do_seed(team_id)

    forma = []
    for f in sorted(fixtures, key=lambda x: x["fixture"]["date"]):
        is_home     = f["teams"]["home"]["id"] == team_id
        winner      = f["teams"]["home"]["winner"] if is_home else f["teams"]["away"]["winner"]
        adversario  = f["teams"]["away"]["name"]   if is_home else f["teams"]["home"]["name"]
        gols_pro    = f["goals"]["home"]            if is_home else f["goals"]["away"]
        gols_contra = f["goals"]["away"]            if is_home else f["goals"]["home"]
        resultado   = "W" if winner is True else ("L" if winner is False else "D")
        forma.append(EntradaForma(
            fixture_id=f["fixture"]["id"],
            data=f["fixture"]["date"][:10],
            adversario=adversario,
            placar_proprio=gols_pro,
            placar_adversario=gols_contra,
            resultado=resultado,
            competicao=f["league"]["name"],
        ))
    return forma[-10:]


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

    # Cartões — derivados da forma (fonte: /fixtures/statistics, mesma temporalidade dos gols)
    jogos_com_cartoes = [j for j in forma if j.cartoes_amarelos is not None]
    if jogos_com_cartoes:
        stats.media_amarelos  = round(
            sum(j.cartoes_amarelos                for j in jogos_com_cartoes) / len(jogos_com_cartoes), 2
        )
        stats.media_vermelhos = round(
            sum((j.cartoes_vermelhos or 0)        for j in jogos_com_cartoes) / len(jogos_com_cartoes), 2
        )
    # Se nenhum jogo tem dado, deixa None (stats de _stats_time já foram zeradas)

    return stats


# ── H2H ──────────────────────────────────────────────────────────────────────

async def _h2h(client: httpx.AsyncClient, id1: int, id2: int, slug: str = "") -> list[dict]:
    """H2H via API-Football com fallback para h2h_seed.json quando API retorna vazio."""
    try:
        data = await _get(client, "/fixtures/headtohead", {
            "h2h": f"{id1}-{id2}", "last": 10,
        })
        resultados = [
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
        if resultados:
            return resultados
        log.warning("_h2h team=%d vs team=%d: API retornou 0 confrontos", id1, id2)
    except Exception as e:
        log.warning("_h2h team=%d vs team=%d: erro %s", id1, id2, e)
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
        cartoes_por_jogo=None,
        penaltis_por_jogo=None,
        tendencia=None,
        fonte="media_copa_2026",
        nota="Árbitro ainda não designado",
        dados_insuficientes=True,
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

async def _media_escanteios(client: httpx.AsyncClient, team_id: int) -> tuple[float | None, int]:
    """
    Calcula média de escanteios do time nos últimos 5 jogos sênior.
    Re-usa o cache de /fixtures?team&last=20 já feito por _forma_recente.
    Para cada fixture, chama /fixtures/statistics (cacheado por 4h).
    Retorna (media, n) onde n = jogos com dado real de corner.
    """
    try:
        data = await _get(client, "/fixtures", {"team": team_id, "last": 20})
        fixtures = [f for f in data.get("response", []) if _e_jogo_senior_masculino(f)]
        fixtures = sorted(fixtures, key=lambda x: x["fixture"]["date"])[-5:]

        escanteios: list[int] = []
        for f in fixtures:
            fid = f["fixture"]["id"]
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

        n = len(escanteios)
        return (round(sum(escanteios) / n, 1), n) if n > 0 else (None, 0)
    except Exception:
        return (None, 0)


# ── Cartões por jogo — busca via /fixtures/statistics (mesma fonte da forma) ──

async def _enriquecer_forma_com_cartoes(
    client: httpx.AsyncClient, team_id: int, forma: list[EntradaForma]
) -> list[EntradaForma]:
    """
    Para cada EntradaForma com fixture_id, chama /fixtures/statistics e preenche
    cartoes_amarelos/cartoes_vermelhos do time.
    Endpoint já cacheado por _media_escanteios — zero quota adicional nos 5 jogos sobrepostos.
    Jogos sem dado ficam com None: não contam na média, mas contam na amostra.
    """
    for entrada in forma:
        if entrada.fixture_id is None:
            continue
        try:
            sdata = await _get(client, "/fixtures/statistics", {"fixture": entrada.fixture_id})
            for team_stats in sdata.get("response", []):
                if team_stats.get("team", {}).get("id") != team_id:
                    continue
                amarelos = vermelhos = 0
                for stat in team_stats.get("statistics", []):
                    tipo = (stat.get("type") or "").lower()
                    val  = stat.get("value")
                    try:
                        val = int(val) if val is not None else 0
                    except (TypeError, ValueError):
                        val = 0
                    if "yellow" in tipo:
                        amarelos += val
                    elif "red" in tipo:
                        vermelhos += val
                entrada.cartoes_amarelos  = amarelos
                entrada.cartoes_vermelhos = vermelhos
                break
        except Exception:
            continue
    return forma


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
    """Retorna (nome_favorito, prob_favorito) a partir das probabilidades.
    Funciona com probabilidades estimadas (dados_insuficientes=True) desde que existam valores."""
    if not prob:
        return "", None
    vc, emp, vf = prob.vitoria_casa, prob.empate, prob.vitoria_fora
    if vc > vf and vc > emp:
        return nome_casa, float(vc)
    if vf > vc and vf > emp:
        return nome_fora, float(vf)
    return "Empate", float(emp)


def _insight_curto(nome_casa: str, nome_fora: str, prob: "Probabilidades | None") -> str:
    """Gera 1 frase curtíssima sobre o confronto sem chamar Claude."""
    if not prob:
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


def _resumo_rapido(nome_casa: str, nome_fora: str, prob: "Probabilidades | None") -> str:
    """Gera resumo de probabilidades dinamicamente a partir de prob (com lambdas).
    Mesmos thresholds de _insight_curto para consistência entre os dois campos."""
    if not prob:
        return ""
    vc, emp, vf = prob.vitoria_casa, prob.empate, prob.vitoria_fora
    lc = float(getattr(prob, "lambda_casa", None) or 1.2)
    lf = float(getattr(prob, "lambda_fora",  None) or 1.2)
    gols = f"Gols esperados: {lc:.1f} (casa) e {lf:.1f} (fora)."
    if vc >= 55:
        return f"{nome_casa} é favorito com {vc}% de vitória. {gols} Empate: {emp}%."
    if vf >= 55:
        return f"{nome_fora} é favorito com {vf}% de vitória. {gols} Empate: {emp}%."
    if vc >= 45:
        return f"{nome_casa} tem leve vantagem ({vc}% vs {vf}%). {gols} Empate: {emp}%."
    if vf >= 45:
        return f"{nome_fora} tem leve vantagem ({vf}% vs {vc}%). {gols} Empate: {emp}%."
    return f"Confronto equilibrado — {nome_casa} {vc}% · Empate {emp}% · {nome_fora} {vf}%. {gols}"


def _jogo_para_resumo(
    j: dict,
    partida: "Partida | None" = None,
    stats_dados: dict | None = None,
) -> PartidaResumo:
    nome_casa = j["time_casa"]
    nome_fora = j["time_fora"]

    # Preferência: probs pós-boost do stats cache (modelo_gols pós-Camada 4).
    # Fallback: partida.probabilidades (pré-boost, Poisson simples) — nunca quebra.
    prob: Probabilidades | None = None
    if stats_dados:
        mg = stats_dados.get("modelo_gols") or {}
        vc  = mg.get("prob_vitoria_casa")
        emp = mg.get("prob_empate")
        vf  = mg.get("prob_vitoria_fora")
        if vc is not None and emp is not None and vf is not None:
            prob = Probabilidades(
                vitoria_casa=round(vc), empate=round(emp), vitoria_fora=round(vf),
                lambda_casa=mg.get("lambda_casa", 1.2),
                lambda_fora=mg.get("lambda_fora", 1.2),
            )
    if prob is None:
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
        prob_vitoria_casa=float(prob.vitoria_casa) if prob else None,
        prob_empate=float(prob.empate)              if prob else None,
        prob_vitoria_fora=float(prob.vitoria_fora)  if prob else None,
        favorito=fav,
        prob_favorito=prob_fav,
        insight_curto=_insight_curto(nome_casa, nome_fora, prob),
        resumo_rapido=(
            _resumo_rapido(nome_casa, nome_fora, prob)
            if prob
            else (partida.insight_probabilidades if partida else "")
        ),
    )


# ── Pré-cache dos próximos jogos (chamado no startup) ────────────────────────

async def precalcular_proximos_jogos(n: int = 8, delay: float = 1.5) -> int:
    """
    Pré-cacha os próximos N jogos por data (a partir de agora).
    Reduz consumo de quota da API-Football no startup comparado a cachear todos os 72.
    Roda em background — não bloqueia o startup.
    """
    import logging
    from datetime import datetime, timezone
    log = logging.getLogger(__name__)

    agora = datetime.now(timezone.utc)

    def _parse_dt(s: str) -> datetime:
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return datetime.max.replace(tzinfo=timezone.utc)

    jogos_futuros = [j for j in _JOGOS if _parse_dt(j["data_hora_brasilia"]) > agora]
    jogos_futuros.sort(key=lambda j: _parse_dt(j["data_hora_brasilia"]))
    proximos = jogos_futuros[:n]

    if not proximos:
        log.info("Nenhum jogo futuro encontrado para pré-cache")
        return 0

    log.info("Pré-cache dos próximos %d jogos em background...", len(proximos))
    ok = 0
    for jogo in proximos:
        try:
            await buscar_detalhe_partida(jogo["slug"])
            ok += 1
        except Exception:
            pass
        await asyncio.sleep(delay)
    log.info("Pré-cache concluído: %d/%d jogos cacheados", ok, len(proximos))
    # Re-processa entradas para garantir que probabilidades usam Elo (não GLOBAL_AVG simétrico)
    await recalcular_proximos_com_elo(n)
    return ok


async def recalcular_proximos_com_elo(n: int = 8) -> int:
    """
    Apaga as entradas do _partida_cache dos próximos N jogos e re-executa
    buscar_detalhe_partida usando dados já em _cache (sem chamadas novas à API).
    Garante que probabilidades reflitam o Elo de cada time em vez de GLOBAL_AVG simétrico.
    """
    import logging
    from datetime import datetime, timezone
    log = logging.getLogger(__name__)

    agora = datetime.now(timezone.utc)

    def _parse_dt(s: str) -> datetime:
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return datetime.max.replace(tzinfo=timezone.utc)

    jogos_futuros = [j for j in _JOGOS if _parse_dt(j["data_hora_brasilia"]) > agora]
    jogos_futuros.sort(key=lambda j: _parse_dt(j["data_hora_brasilia"]))
    proximos = jogos_futuros[:n]

    ok = 0
    for jogo in proximos:
        slug = jogo["slug"]
        try:
            del _partida_cache[slug]
        except KeyError:
            pass
        try:
            await buscar_detalhe_partida(slug)
            ok += 1
        except Exception as e:
            log.error("recalcular_proximos_com_elo falhou para %s: %s", slug, e)
        await asyncio.sleep(0.1)  # yield para não bloquear o event loop

    log.info("recalcular_proximos_com_elo: %d/%d jogos reprocessados com Elo", ok, len(proximos))
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
            f"Probabilidades estimadas via modelo Elo: "
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
    Enriquece com probs pós-boost do stats cache (modelo_gols pós-Camada 4).
    Fallback: partida.probabilidades (pré-boost) quando stats não disponível.
    """
    from app.cache import static_cache
    return [
        _jogo_para_resumo(j, _partida_cache.get(j["slug"]), static_cache.get_stats(j["slug"]))
        for j in _JOGOS
    ]


async def sincronizar_status_jogos() -> int:
    """
    Sincroniza status e placar dos jogos ao vivo e recém-terminados.

    Janela ativa (únicos jogos que geram chamada à API):
      - jogo sabidamente ao vivo (_STATUS_LIVE)
      - iniciado há menos de 3h (cobre 90min + prorrogação + pênaltis)
      - começa em menos de 10min

    Atualiza _JOGOS in-memory → propaga imediatamente para buscar_todos_jogos_copa.
    Quando um jogo termina (FT/AET/PEN), expulsa do _partida_cache para que a próxima
    chamada de /recomendacao recalcule com o resultado final.

    Bypassa _cache (TTL 8h seria longo demais para placar ao vivo).
    Retorna número de jogos cujo status/placar mudou.
    """
    agora = datetime.now(timezone.utc)
    atualizados = 0

    async with httpx.AsyncClient(timeout=10) as client:
        for jogo in _JOGOS:
            fid = jogo.get("api_fixture_id")
            if not fid:
                continue

            dt_str = jogo.get("data_hora_utc") or jogo.get("data_hora_brasilia", "")
            try:
                dt = datetime.fromisoformat(dt_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            horas_desde = (agora - dt).total_seconds() / 3600
            horas_ate   = (dt - agora).total_seconds() / 3600
            status_atual = jogo.get("status", "NS")

            # Pula jogos já encerrados há mais de 30min (resultado estável)
            if status_atual in _STATUS_FT and horas_desde > 0.5:
                continue

            # Pula NS que não começam em menos de 10min
            em_janela = (
                status_atual in _STATUS_LIVE
                or (0 <= horas_desde < 3.0)
                or (0 <= horas_ate < (10 / 60))
                # Bootstrap: seed ainda tem NS para jogo que já deveria ter terminado
                # (ex: servidor reiniciou após o jogo). Cobre só até 72h para não
                # re-verificar jogos antigos em todo tick.
                or (status_atual == "NS" and 3.0 <= horas_desde < 72.0)
            )
            if not em_janela:
                continue

            try:
                r = await client.get(
                    f"{BASE_URL}/fixtures",
                    headers=HEADERS,
                    params={"id": fid},
                )
                r.raise_for_status()
                resp = r.json().get("response", [])
                if not resp:
                    continue

                f          = resp[0]
                novo_status = f["fixture"]["status"]["short"]
                gols_casa   = f["goals"]["home"]
                gols_fora   = f["goals"]["away"]

                mudou = (
                    jogo.get("status")    != novo_status
                    or jogo.get("gols_casa") != gols_casa
                    or jogo.get("gols_fora") != gols_fora
                )
                if mudou:
                    jogo["status"]    = novo_status
                    jogo["gols_casa"] = gols_casa
                    jogo["gols_fora"] = gols_fora
                    atualizados += 1
                    log.info(
                        "sync_status: %s → %s  %s×%s",
                        jogo["slug"], novo_status, gols_casa, gols_fora,
                    )

                    # Jogo encerrado: expulsa do _partida_cache para forçar recálculo
                    if novo_status in _STATUS_FT:
                        _partida_cache.pop(jogo["slug"], None)

            except Exception as e:
                log.warning("sync_status %s: %s", jogo.get("slug", fid), e)

            await asyncio.sleep(1)  # 1 req/s — bem abaixo do rate limit Pro (30 req/min)

    return atualizados


def _enriquecer_odds(partida: "Partida", slug: str) -> "Partida":
    """
    Preenche odds (se ausentes) e enriquece probs pós-boost do stats cache.
    Chamada em todos os caminhos de retorno de buscar_detalhe_partida (L1 e L2).
    """
    updates: dict = {}

    # Odds
    if partida.odds is None:
        try:
            from app.cache.odds_cache import get_odds_dinamicas
            odds = get_odds_dinamicas(slug)
            if odds:
                updates["odds"] = odds
        except Exception:
            pass

    # Probs pós-boost — sobrepõe prob_vitoria_* pré-boost da Partida
    try:
        from app.cache import static_cache as _sc
        sd = _sc.get_stats(slug)
        if sd:
            mg  = sd.get("modelo_gols") or {}
            vc  = mg.get("prob_vitoria_casa")
            emp = mg.get("prob_empate")
            vf  = mg.get("prob_vitoria_fora")
            if vc is not None and emp is not None and vf is not None:
                prob_b = Probabilidades(
                    vitoria_casa=round(vc), empate=round(emp), vitoria_fora=round(vf),
                    lambda_casa=mg.get("lambda_casa", 1.2),
                    lambda_fora=mg.get("lambda_fora", 1.2),
                )
                fav_b, prob_fav_b = _favorito_e_prob(
                    partida.time_casa_nome, partida.time_fora_nome, prob_b
                )
                updates.update({
                    "prob_vitoria_casa": vc,
                    "prob_empate":       emp,
                    "prob_vitoria_fora": vf,
                    "favorito":          fav_b,
                    "prob_favorito":     prob_fav_b,
                    "insight_curto":     _insight_curto(
                        partida.time_casa_nome, partida.time_fora_nome, prob_b
                    ),
                    "resumo_rapido":     _gerar_insight_probabilidades(
                        partida.time_casa_nome, partida.time_fora_nome, prob_b
                    ),
                })
    except Exception:
        pass

    return partida.model_copy(update=updates) if updates else partida


async def buscar_detalhe_partida(slug: str) -> Partida | None:
    # L1 — in-memory TTL
    if slug in _partida_cache:
        p = _enriquecer_odds(_partida_cache[slug], slug)
        if p is not _partida_cache[slug]:
            _partida_cache[slug] = p   # persiste enriquecimento
        return p

    # L2 — disk cache com TTL diferenciado por componente
    cached_dict: dict | None = None
    try:
        from app.cache import static_cache
        cached_dict = static_cache.get_partida_raw(slug)
        if cached_dict and (
            static_cache.is_team_stats_fresh(slug)
            and static_cache.is_player_stats_fresh(slug)
            and static_cache.is_forma_fresh(slug)
            and static_cache.is_h2h_fresh(slug)
        ):
            # Todos os componentes frescos — zero chamadas de API
            partida = _enriquecer_odds(Partida.model_validate(cached_dict), slug)
            _partida_cache[slug] = partida
            return partida
    except Exception:
        cached_dict = None

    jogo = _POR_SLUG.get(slug)
    if not jogo:
        return None

    home_id    = jogo["time_casa_id"]
    away_id    = jogo["time_fora_id"]
    fixture_id = jogo["api_fixture_id"]
    home_nome  = jogo["time_casa"]
    away_nome  = jogo["time_fora"]

    # Determina quais componentes precisam de rebusca
    needs_team  = cached_dict is None or not static_cache.is_team_stats_fresh(slug)
    needs_forma = cached_dict is None or not static_cache.is_forma_fresh(slug)
    needs_h2h   = cached_dict is None or not static_cache.is_h2h_fresh(slug)
    needs_plyr  = cached_dict is None or not static_cache.is_player_stats_fresh(slug)

    # ── Wrappers condicionais: retorna valor do cache se fresco, senão busca API ──
    async def _get_team_stats(team_id: int, cache_key: str) -> EstatisticasTemporada:
        if not needs_team and cached_dict and cache_key in cached_dict:
            return EstatisticasTemporada.model_validate(cached_dict[cache_key])
        return await _stats_time(client, team_id)

    async def _get_forma_enriched(team_id: int, cache_key: str) -> list[EntradaForma]:
        if not needs_forma and cached_dict:
            # Cache fresco — cartoes_amarelos/vermelhos já estão no cached_dict
            return [EntradaForma.model_validate(j) for j in (cached_dict.get(cache_key) or [])]
        forma = await _forma_recente(client, team_id)
        return await _enriquecer_forma_com_cartoes(client, team_id, forma)

    async def _get_h2h() -> list[dict]:
        if not needs_h2h and cached_dict:
            return cached_dict.get("head_to_head") or []
        return await _h2h(client, home_id, away_id, slug)

    # ── Chamadas paralelas à API-Football (só para componentes stale) ─────────
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            (
                stats_casa_raw,
                stats_fora_raw,
                forma_casa,
                forma_fora,
                h2h,
                arb,
                esc_casa_raw,
                esc_fora_raw,
            ) = await asyncio.gather(
                _get_team_stats(home_id, "stats_casa"),
                _get_team_stats(away_id, "stats_fora"),
                _get_forma_enriched(home_id, "forma_casa"),
                _get_forma_enriched(away_id, "forma_fora"),
                _get_h2h(),
                _arbitro(client, fixture_id),
                _media_escanteios(client, home_id),
                _media_escanteios(client, away_id),
            )
    except Exception:
        stats_casa_raw = stats_fora_raw = EstatisticasTemporada(dados_insuficientes=True)
        forma_casa = forma_fora = []
        h2h = []
        arb = None
        esc_casa_raw = esc_fora_raw = (None, 0)

    # ── Enriquece stats com BTTS/Over + escanteios ────────────────────────────
    stats_casa = _enriquecer_btts_over(stats_casa_raw, forma_casa)
    stats_fora = _enriquecer_btts_over(stats_fora_raw, forma_fora)
    esc_c_mean, esc_c_n = esc_casa_raw
    esc_f_mean, esc_f_n = esc_fora_raw
    stats_casa.media_escanteios = esc_c_mean
    stats_fora.media_escanteios = esc_f_mean
    stats_casa.escanteios_amostra_n = esc_c_n
    stats_fora.escanteios_amostra_n = esc_f_n
    stats_casa.escanteios_baixa_confianca = 0 < esc_c_n < 3
    stats_fora.escanteios_baixa_confianca = 0 < esc_f_n < 3

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

    async def _get_jogadores(team_nome: str, cache_key: str):
        if not needs_plyr and cached_dict and cached_dict.get(cache_key):
            return cached_dict[cache_key]  # dict no formato esperado por _to_destaque
        return await buscar_jogadores_destaque(team_nome)

    resultados = await asyncio.gather(
        _timed(_odds_api(home_nome, away_nome), 15),
        _timed(_get_jogadores(home_nome, "jogadores_destaque_casa"), 60),
        _timed(_get_jogadores(away_nome, "jogadores_destaque_fora"), 60),
        _timed(_buscar_fifa_ranking_wikipedia(), 8),
        _timed(_calcular_rating(home_nome, forma_casa, jogo["data_hora_brasilia"]), 10),
        _timed(_calcular_rating(away_nome, forma_fora, jogo["data_hora_brasilia"]), 10),
    )

    def _safe(val):
        return None if isinstance(val, Exception) else val

    odds          = _safe(resultados[0])
    if not odds:
        from app.cache.odds_cache import get_odds_dinamicas
        odds = get_odds_dinamicas(jogo["slug"])
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
    # Fallback 1: usa Elo ratings (já em memória) → lambdas diferenciadas por time.
    # Fallback 2: GLOBAL_AVG simétrico (1.2) só quando nem stats nem ratings disponíveis.
    lc_raw = stats_casa.media_gols_marcados_recente or stats_casa.media_gols_marcados
    lf_raw = stats_fora.media_gols_marcados_recente or stats_fora.media_gols_marcados

    if lc_raw is not None and lf_raw is not None:
        lc, lf = lc_raw, lf_raw
    elif rating_c is not None and rating_f is not None:
        # Elo fallback: ajusta GLOBAL_AVG pela força relativa de cada time
        _GAV = 1.2
        _at_c = max(0.5, 1.0 + rating_c.rating_combinado * 0.10)
        _at_f = max(0.5, 1.0 + rating_f.rating_combinado * 0.10)
        _def_f = max(0.5, 1.0 - rating_f.rating_combinado * 0.08)
        _def_c = max(0.5, 1.0 - rating_c.rating_combinado * 0.08)
        lc = round(max(0.3, min(_GAV * _at_c * _def_f, 4.0)), 3)
        lf = round(max(0.3, min(_GAV * _at_f * _def_c, 4.0)), 3)
    else:
        lc, lf = 1.2, 1.2

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

    _fav, _prob_fav = _favorito_e_prob(jogo["time_casa"], jogo["time_fora"], probabilidades)

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
        # Campos de PartidaResumo — preenchidos para que o detalhe
        # retorne os mesmos dados que os cards da lista.
        prob_vitoria_casa=float(probabilidades.vitoria_casa) if probabilidades else None,
        prob_empate=float(probabilidades.empate)              if probabilidades else None,
        prob_vitoria_fora=float(probabilidades.vitoria_fora)  if probabilidades else None,
        favorito=_fav,
        prob_favorito=_prob_fav,
        insight_curto=_insight_curto(jogo["time_casa"], jogo["time_fora"], probabilidades),
        resumo_rapido=_gerar_insight_probabilidades(
            jogo["time_casa"], jogo["time_fora"], probabilidades
        ),
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
    try:
        from app.cache import static_cache
        got_player_data = dest_casa is not None or dest_fora is not None
        static_cache.put_partida(
            slug,
            partida.model_dump(mode="json"),
            update_team_stats=needs_team,
            update_player_stats=needs_plyr and got_player_data,
            update_forma=needs_forma,
            update_h2h=needs_h2h,
        )
    except Exception:
        pass
    return partida
