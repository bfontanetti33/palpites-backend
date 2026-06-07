"""
Players Agent — jogadores de destaque por seleção, Copa 2026.

Passo 1: Squad via Wikipedia (scraping HTML, cache em JSON)
Passo 2: Stats da temporada 2025/26 no clube via API-Football
Passo 3: Métricas P90 (mín 270 min), ranking por categoria
Passo 4: Top 6 por time com mercados sugeridos
Passo 5: Integrado em /copa/jogos/{slug} via buscar_jogadores_destaque()
"""
import asyncio
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cachetools import TTLCache

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent.parent.parent
SQUADS_PATH = ROOT / "seeds" / "squads_copa_2026.json"

API_KEY  = os.getenv("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
API_HDR  = {"x-apisports-key": API_KEY}
UA       = "Mozilla/5.0 (compatible; PalpitesIA/2)"

# Stats cache 24h
_stats_cache: TTLCache = TTLCache(maxsize=500, ttl=86400)
# Squad cache (sessão)
_squad_cache: dict = {}

# ── Constantes ────────────────────────────────────────────────────────────────
MIN_MINUTOS = 270   # mínimo para ser elegível no P90
SEASON      = 2025  # 2025/26
MAX_JUGADORES = 6   # máximo por time no output
TOP_POR_CAT   = 2   # top N por categoria

# ── League Strength Score (LSS) ──────────────────────────────────────────────
# stat_ajustada = stat_p90 × LSS
# Benchmark: Premier League = 1.00
_LSS: dict[str, float] = {
    # Ligas de clubes — nível máximo
    "Champions League":          1.10,
    "UEFA Champions League":     1.10,
    "Premier League":            1.00,
    "La Liga":                   0.97,
    "Bundesliga":                0.94,
    "Serie A":                   0.93,
    "Ligue 1":                   0.90,
    "Europa League":             0.88,
    "UEFA Europa League":        0.88,
    "Conference League":         0.80,
    "Brasileirão Série A":       0.78,
    "Serie A BR":                0.78,
    "Eredivisie":                0.76,
    "Liga MX":                   0.75,
    "Liga Portugal":             0.74,
    "Liga NOS":                  0.74,
    "Primeira Liga":             0.74,
    "Campeonato Argentino":      0.72,
    "Primera División":          0.72,
    "Turkish Süper Lig":         0.71,
    "Süper Lig":                 0.71,
    "Scottish Premiership":      0.68,
    "Belgian Pro League":        0.67,
    "First Division A":          0.67,
    "MLS":                       0.62,
    "Major League Soccer":       0.62,
    "Saudi Pro League":          0.60,
    "Saudi Professional League": 0.60,
    # Copas domésticas — menos jogos, médias infladas
    "FA Cup":                    0.75,
    "Copa del Rey":              0.76,
    "DFB Pokal":                 0.76,
    "Copa do Brasil":            0.68,
    "League Cup":                0.72,
    "EFL Cup":                   0.72,
    "Carabao Cup":               0.72,
    "Copa de la Liga MX":        0.65,
    "Copa MX":                   0.65,
    # Ligas africanas
    "Premier Soccer League":     0.42,
    "PSL":                       0.42,
    "South African PSL":         0.42,
    "NFD":                       0.32,           # 2ª divisão África do Sul
    "CAF Champions League":      0.58,
    "AFCON":                     0.65,
    "Africa Cup of Nations":     0.65,
    "African Nations Championship": 0.55,
}

# Copas nacionais: têm poucos jogos e distorcem métricas ofensivas
# Jogadores com stats exclusivamente de copa são marcados como copa_apenas=True
_LSS_COPA_FALLBACK   = 0.65   # fallback para nome que contenha "Cup" / "Copa"
_LSS_LIGA_FALLBACK   = 0.50   # fallback para nome que contenha "League" / "Liga"
_LSS_OUTROS_EUROPA   = 0.58
_LSS_OUTROS_AMERICA  = 0.52
_LSS_FALLBACK        = 0.50

# Palavras que indicam copa doméstica (estatísticas infladas, poucos jogos)
# "8 Cup", "10 Cup" etc são nomes de torneios africanos de copa
_COPA_KEYWORDS = {"cup", "copa", "pokal", "coupe", "coppa", "taca", "taça",
                  "supercup", "supercopa", "shield", "community",
                  "campeón de campeones", "campeones"}

# Palavras que indicam pré-temporada ou amistosos — stats não refletem nível competitivo
_PRESEASON_KEYWORDS = {
    "summer series", "pre-season", "preseason", "friendly", "amistoso",
    "pretemporada", "international champions cup", "summer tour",
    "club friendly", "friendlies", "test match",
}

# Ligas europeias conhecidas (para fallback "outros Europa")
_EUROPA_KEYWORDS = {"league", "liga", "ligue", "serie", "premiership",
                    "superliga", "allsvenskan", "eliteserien", "eredivisie"}
# Ligas americanas
_AMERICA_KEYWORDS = {"brasileirão", "argentina", "chile", "colombia", "ecuador",
                     "perú", "venezuela", "mls", "liga mx", "concacaf"}


def _lss_da_liga(nome_liga: str) -> float:
    """Retorna o League Strength Score para o nome da liga retornado pela API."""
    nl = nome_liga.lower()
    # Match parcial bidirecional na tabela principal
    for key, val in _LSS.items():
        if key.lower() in nl or nl in key.lower():
            return val
    # Fallbacks por tipo de competição
    if any(kw in nl for kw in _COPA_KEYWORDS):
        return _LSS_COPA_FALLBACK
    if any(kw in nl for kw in _EUROPA_KEYWORDS):
        return _LSS_OUTROS_EUROPA
    if any(kw in nl for kw in _AMERICA_KEYWORDS):
        return _LSS_OUTROS_AMERICA
    if "league" in nl or "liga" in nl:
        return _LSS_LIGA_FALLBACK
    return _LSS_FALLBACK


def _e_copa(nome_liga: str) -> bool:
    """Retorna True se a competição é uma copa doméstica (poucos jogos, stats infladas)."""
    nl = nome_liga.lower()
    return any(kw in nl for kw in _COPA_KEYWORDS)


def _e_pretemporada(nome_liga: str) -> bool:
    """Retorna True se for pré-temporada ou amistoso — exclui da agregação de stats."""
    nl = nome_liga.lower()
    return any(kw in nl for kw in _PRESEASON_KEYWORDS)


CATEGORIAS = [
    ("goleadores",   "goals",          "🥇", "gols/90",          "Marcar a qualquer momento"),
    ("assistentes",  "assists",        "🎯", "assists/90",        "Dar assistência"),
    ("chutadores",   "shots_on_goal",  "🔥", "chutes no gol/90",  "Chutes ao gol"),
    ("dribladores",  "dribbles",       "⚡", "dribles/90",        "Dribles"),
    ("passes_chave", "key_passes",     "📊", "passes chave/90",   "Criação de jogadas"),
    ("cartoes",      "yellow_cards",   "🟨", "cartões/90",        "Receber cartão amarelo"),
]

POSICOES = {"GK": "Goleiro", "DF": "Defensor", "MF": "Meio-campo", "FW": "Atacante"}


# ════════════════════════════════════════════════════════════════════════════════
# PASSO 1 — Squads via Wikipedia
# ════════════════════════════════════════════════════════════════════════════════

def _limpar_nome(raw: str) -> str:
    """Remove parênteses e wiki markup de nomes de jogadores."""
    name = re.sub(r'\s*\(.*?\)', '', raw).strip()
    name = re.sub(r'\[\[([^|\]]+\|)?([^\]]+)\]\]', r'\2', name)
    return name.strip()


def _parse_squad_html(html: str, team_name: str) -> list[dict]:
    """
    Extrai os 26 jogadores de uma seleção da página HTML da Wikipedia.
    Wikipedia 2026: <div class="mw-heading mw-heading3"><h3 id="Mexico">Mexico</h3></div>
    Linhas de jogadores: <tr class="nat-fs-player">
    Colunas: No. | Pos | Nome | Nascimento | Caps | Gols | Clube
    """
    # Wikipedia usa underscores no id para espaços (South Africa → South_Africa)
    team_id = team_name.replace(" ", "_")

    # Localiza o início da seção pelo id do h3 (ignora TOC que usa id="toc-Mexico")
    anchor_m = re.search(rf'<h[23] id="{re.escape(team_id)}"', html, re.IGNORECASE)
    if not anchor_m:
        # Fallback: procura pelo texto exato (sem id)
        anchor_m = re.search(
            rf'<h[23][^>]*>{re.escape(team_name)}</h[23]>',
            html, re.IGNORECASE,
        )
    if not anchor_m:
        return []

    # Extrai tudo até o próximo heading de nível igual ou superior
    content_start = anchor_m.end()
    end_m = re.search(r'<div class="mw-heading', html[content_start:])
    section = html[content_start: content_start + (end_m.start() if end_m else 300_000)]
    rows    = re.findall(r'<tr class="nat-fs-player">(.*?)</tr>', section, re.DOTALL)
    players = []

    for row in rows:
        # Posição: link text dentro da 2ª <td>
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(tds) < 6:
            continue

        # Colunas <td>: No.(0) | Pos(1) | DoB(2) | Caps(3) | Goals(4) | Club(5)
        # NOTA: Nome fica em <th>, não <td> — não entra no índice de tds
        no_str   = re.sub(r'<[^>]+>', '', tds[0]).strip()
        pos_text = re.sub(r'<[^>]+>', '', tds[1]).strip()
        # Extrai sigla da posição (GK/DF/MF/FW) do link text
        pos_m    = re.search(r'>(GK|DF|MF|FW)<', tds[1])
        pos      = pos_m.group(1) if pos_m else pos_text[:2]

        # Nome: dentro de <th>
        th_m = re.search(r'<th[^>]*>.*?<a[^>]*>([^<]+)</a>', row, re.DOTALL)
        nome = _limpar_nome(th_m.group(1)) if th_m else "?"

        # Caps(3) e Gols(4) — índices corretos após excluir o <th>
        def safe_int(txt: str) -> int:
            cleaned = re.sub(r'<[^>]+>', '', txt).strip()
            try:
                return int(cleaned.split()[0])
            except (ValueError, IndexError):
                return 0

        caps = safe_int(tds[3]) if len(tds) > 3 else 0
        gols = safe_int(tds[4]) if len(tds) > 4 else 0

        # Clube: link text na última <td>
        clube_m = re.search(r'<a[^>]*>([^<]+)</a>', tds[-1])
        clube   = clube_m.group(1).strip() if clube_m else "?"

        players.append({
            "no":    int(no_str) if no_str.isdigit() else 0,
            "pos":   pos,
            "nome":  nome,
            "caps":  caps,
            "gols_int": gols,
            "clube": clube,
        })

    return players


async def buscar_squad(team_name: str) -> list[dict]:
    """
    Passo 1: Retorna os 26 jogadores da seleção.
    Lê do cache JSON primeiro. Se não existir, scrapa a Wikipedia.
    """
    # Cache em memória
    if team_name in _squad_cache:
        return _squad_cache[team_name]

    # Cache em disco
    if SQUADS_PATH.exists():
        try:
            data = json.loads(SQUADS_PATH.read_text(encoding="utf-8"))
            if team_name in data.get("squads", {}):
                players = data["squads"][team_name]
                _squad_cache[team_name] = players
                return players
        except Exception:
            pass

    # Scraping da Wikipedia
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(
                "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads",
                headers={"User-Agent": UA},
            )
        players = _parse_squad_html(r.text, team_name)
    except Exception:
        players = []

    if players:
        _squad_cache[team_name] = players
        _salvar_squad_cache(team_name, players)

    return players


def _salvar_squad_cache(team_name: str, players: list[dict]) -> None:
    """Persiste o squad no JSON de cache."""
    try:
        data: dict = {"squads": {}}
        if SQUADS_PATH.exists():
            data = json.loads(SQUADS_PATH.read_text(encoding="utf-8"))
        data.setdefault("squads", {})[team_name] = players
        SQUADS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════════
# PASSO 2 — Stats da temporada 2025/26 via API-Football
# ════════════════════════════════════════════════════════════════════════════════

async def _api_get(client: httpx.AsyncClient, path: str, params: dict) -> dict:
    key = f"{path}:{sorted(params.items())}"
    if key in _stats_cache:
        return _stats_cache[key]
    for tentativa in range(5):
        r = await client.get(f"{BASE_URL}{path}", headers=API_HDR, params=params)
        if r.status_code == 429:
            await asyncio.sleep(2 ** tentativa)  # 1s, 2s, 4s, 8s, 16s
            continue
        r.raise_for_status()
        data = r.json()
        _stats_cache[key] = data
        return data
    r.raise_for_status()  # propaga o 429 se todas as tentativas falharem
    return {}


def _agregar_stats(response_list: list[dict]) -> dict | None:
    """
    Agrega stats de todas as competições do CLUBE na temporada.
    Exclui:
      - Seleção nacional: INTL_IDS + league.type == "International"   [FIX 3]
      - Pré-temporada e amistosos: _e_pretemporada()                  [FIX 1]
    liga_nome = liga onde o jogador mais jogou (não a primeira da lista).[FIX 2]
    """
    # FIX 3: lista ampliada de IDs de competições de seleção
    INTL_IDS = {
        1,   # FIFA World Cup
        4,   # UEFA Euro
        5,   # UEFA Nations League
        6,   # AFC Asian Cup
        7,   # African Nations Championship (CHAN)
        8,   # Copa América
        9,   # CONCACAF Gold Cup
        10,  # Africa Cup of Nations (AFCON)
        29,  # WC Qualifying — CAF
        30,  # WC Qualifying — CONCACAF
        31,  # WC Qualifying — AFC
        32,  # WC Qualifying — OFC
        33,  # WC Qualifying — AFC (2ª fase)
        34,  # WC Qualifying — UEFA
    }
    total: dict = {
        "goals": 0, "assists": 0, "shots_on_goal": 0,
        "key_passes": 0, "dribbles": 0, "yellow_cards": 0,
        "minutes": 0, "appearances": 0,
        "clube_nome": "", "clube_logo": "",
        "liga_nome": "", "liga_lss": _LSS_FALLBACK,
        "_lss_min_weighted": 0.0,
        "_minutos_liga": 0,   # minutos em ligas (não copas) — para detectar copa_apenas
    }
    _mins_por_liga: dict[str, float] = {}   # FIX 2: tracking para liga principal
    found = False
    for entry in response_list:
        stats = entry.get("statistics", [])
        for st in stats:
            lg = st.get("league", {})
            # FIX 3: exclui por ID *e* por campo type="International"
            if lg.get("id") in INTL_IDS or lg.get("type") == "International":
                continue
            g = st.get("games", {})
            mins = g.get("minutes") or 0
            if not mins:
                continue
            liga_nm = lg.get("name", "")
            # FIX 1: exclui pré-temporada e amistosos
            if _e_pretemporada(liga_nm):
                continue
            found = True
            lss = _lss_da_liga(liga_nm)
            total["minutes"]           += mins
            total["appearances"]       += g.get("appearences") or 0
            total["_lss_min_weighted"] += lss * mins
            _mins_por_liga[liga_nm]     = _mins_por_liga.get(liga_nm, 0) + mins  # FIX 2
            if not _e_copa(liga_nm):
                total["_minutos_liga"] += mins
            gl = st.get("goals", {})
            total["goals"]        += gl.get("total") or 0
            total["assists"]      += gl.get("assists") or 0
            sh = st.get("shots", {})
            total["shots_on_goal"] += sh.get("on") or 0
            ps = st.get("passes", {})
            kp = ps.get("key") or 0
            total["key_passes"]   += int(kp) if isinstance(kp, (int, float)) else 0
            dr = st.get("dribbles", {})
            total["dribbles"]     += dr.get("success") or 0
            ca = st.get("cards", {})
            total["yellow_cards"] += ca.get("yellow") or 0
            if not total["clube_nome"]:
                tm = st.get("team", {})
                total["clube_nome"] = tm.get("name", "")
                total["clube_logo"] = tm.get("logo", "")

    if found and total["minutes"] > 0:
        total["liga_lss"] = round(total["_lss_min_weighted"] / total["minutes"], 3)
        total["copa_apenas"] = total.get("_minutos_liga", 0) == 0
        # FIX 2: liga_nome = liga com mais minutos (não a primeira encontrada)
        if _mins_por_liga:
            total["liga_nome"] = max(_mins_por_liga, key=_mins_por_liga.__getitem__)

    return total if found else None


# Cache de club team IDs (sessão)
_club_id_cache: dict[str, int | None] = {}

# Aliases: nome da Wikipedia → search term na API-Football
# Só para nomes genuinamente diferentes (não resolvíveis por normalização de diacríticos).
_CLUB_ALIASES: dict[str, str] = {
    # ── Ligue 1 ──────────────────────────────────────────────────────────
    "Paris Saint-Germain":      "Paris Saint Germain",   # ID=85  (hífen vs. espaço)
    # ── Premier League ───────────────────────────────────────────────────
    "Tottenham Hotspur":        "Tottenham",             # ID=47
    "West Ham United":          "West Ham",              # ID=48
    "Wolverhampton Wanderers":  "Wolves",                # ID=39
    # ── Bundesliga ───────────────────────────────────────────────────────
    "Bayern Munich":            "Bayern München",        # ID=157 (Munich vs. München)
    "TSG Hoffenheim":           "Hoffenheim",            # ID=167
    "Mainz 05":                 "FSV Mainz 05",          # ID=164
    "Schalke 04":               "FC Schalke 04",         # ID=174
    "FC St. Pauli":             "Pauli",                 # ID=186
    # ── Serie A ──────────────────────────────────────────────────────────
    "Milan":                    "AC Milan",              # ID=489
    "Inter Milan":              "Inter",                 # ID=505
    "Roma":                     "AS Roma",               # ID=497
    # ── Süper Lig ────────────────────────────────────────────────────────
    "Fenerbahçe":               "Fenerbahce",            # ID=611
    "İstanbul Başakşehir":      "Basaksehir",            # ID=564
    "Çaykur Rizespor":          "Rizespor",              # ID=1007
    # ── Czech ────────────────────────────────────────────────────────────
    "Slavia Prague":            "Slavia Praha",          # ID=560
    # ── Danish ───────────────────────────────────────────────────────────
    "Brøndby":                  "Brondby",               # ID=407 (ø não decompõe via NFKD)
    # ── Greek ────────────────────────────────────────────────────────────
    "Olympiacos":               "Olympiakos Piraeus",    # ID=553
    # ── Serbian ──────────────────────────────────────────────────────────
    "Red Star Belgrade":        "Crvena zvezda",         # ID=598
    # ── Brazilian ────────────────────────────────────────────────────────
    "Grêmio":                   "Gremio",                # ID=130
    "Atlético Mineiro":         "Atletico Mineiro",      # ID=117
    # ── Spanish ──────────────────────────────────────────────────────────
    "Atlético Madrid":          "Atletico Madrid",       # ID=530
    "Atletico Madrid":          "Atletico Madrid",
    "Atletico de Madrid":       "Atletico Madrid",
}


def _ascii_normalizar(nome: str) -> str:
    """Remove diacríticos via NFKD: Grêmio→Gremio, Fenerbahçe→Fenerbahce.
    Não resolve ø (Brøndby) — esse caso está no _CLUB_ALIASES."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", nome)
        if unicodedata.category(c) != "Mn"
    )


async def _buscar_club_id(client: httpx.AsyncClient, clube: str) -> int | None:
    """Busca team_id em 3 camadas para robustez contra mismatches de nome.

    1. ?name=clube         — exato, sem risco de retornar time errado (ex: Inter Milan ≠ Inter Miami)
    2. ?name=alias         — exato para 18/21 aliases (Inter→505, Tottenham→47, Bayern München→157…)
       → ?search=alias     — sub-fallback para aliases sem exact match (Hoffenheim, Pauli, Crvena zvezda)
    3. ?search=normalizado — remove diacríticos automaticamente (Grêmio→Gremio, Fenerbahçe→Fenerbahce…)
    """
    if clube in _club_id_cache:
        return _club_id_cache[clube]

    async def _nome(termo: str) -> int | None:
        try:
            data = await _api_get(client, "/teams", {"name": termo})
            teams = data.get("response", [])
            if teams:
                return teams[0]["team"]["id"]
        except Exception:
            pass
        return None

    async def _search(termo: str) -> int | None:
        try:
            data = await _api_get(client, "/teams", {"search": termo})
            teams = data.get("response", [])
            if teams:
                return teams[0]["team"]["id"]
        except Exception:
            pass
        return None

    # 1. Nome exato do squad
    tid = await _nome(clube)

    # 2. Alias manual: ?name= primeiro (evita ambiguidade do ?search= para "Inter", etc.)
    #    Sub-fallback ?search= para aliases sem exact match (Hoffenheim, Pauli, Crvena zvezda)
    if tid is None and clube in _CLUB_ALIASES:
        alias_val = _CLUB_ALIASES[clube]
        tid = await _nome(alias_val)
        if tid is None:
            tid = await _search(alias_val)

    # 3. ASCII normalizado — remove diacríticos automaticamente
    if tid is None:
        normalizado = _ascii_normalizar(clube)
        if normalizado != clube:
            tid = await _search(normalizado)

    _club_id_cache[clube] = tid
    return tid


def _score_nome(api_name: str, nome_busca: str) -> int:
    """Score de similaridade de nome: palavras em comum (case-insensitive)."""
    words_api  = set(api_name.lower().split())
    words_nome = set(nome_busca.lower().split())
    return len(words_api & words_nome)


async def buscar_stats_jogador(nome: str, clube: str) -> dict | None:
    """
    Passo 2 (Ajuste 2): Busca stats do jogador em 3 tentativas em cascata.

    Tentativa 1: /players?search={nome}&team={club_id}&season={season}
      → Busca direta por nome dentro do clube — mais precisa.

    Tentativa 2: /players?team={club_id}&season={season} → match por nome
      → Fallback: varre todos os jogadores do clube.

    Tentativa 3: /players?search={nome}&season={season} (qualquer liga)
      → Último recurso para clubes menos conhecidos.

    Após encontrar o player_id, pode-se usar /players?id={id}&season={season}
    para obter stats mais completas se necessário.
    """
    nome_busca = nome.split("(")[0].strip()

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            club_id = await _buscar_club_id(client, clube)

            # ── Tentativa 1: search + team (mais preciso) ─────────────────────
            # 1a: nome completo; 1b: só sobrenome — a API rejeita nomes multi-token
            # (ex: "Joshua Kimmich" → 0; "Kimmich" → 1 resultado)
            entry = None
            if club_id:
                d1 = await _api_get(client, "/players", {
                    "search": nome_busca,
                    "team":   club_id,
                    "season": SEASON,
                })
                for e in d1.get("response", []):
                    if _score_nome(e.get("player", {}).get("name", ""), nome_busca) > 0:
                        entry = e
                        break

                # 1b: fallback por sobrenome quando nome completo retorna 0
                if not entry and " " in nome_busca:
                    sobrenome = nome_busca.split()[-1]
                    d1b = await _api_get(client, "/players", {
                        "search": sobrenome,
                        "team":   club_id,
                        "season": SEASON,
                    })
                    for e in d1b.get("response", []):
                        if _score_nome(e.get("player", {}).get("name", ""), nome_busca) > 0:
                            entry = e
                            break

            # ── Tentativa 2: todos os jogadores do clube ───────────────────────
            if not entry and club_id:
                d2 = await _api_get(client, "/players", {
                    "team":   club_id,
                    "season": SEASON,
                })
                melhor_score = 0
                for e in d2.get("response", []):
                    sc = _score_nome(e.get("player", {}).get("name", ""), nome_busca)
                    if sc > melhor_score:
                        melhor_score = sc
                        entry = e
                if melhor_score == 0:
                    entry = None

            # ── Tentativa 3: search global (qualquer clube) ─────────────────────
            if not entry:
                # Requer league; tenta com ligas mais comuns
                for league_id in [39, 140, 78, 135, 61, 262, 288]:  # PL,LaLiga,BL,SerieA,L1,LigaMX,PSL
                    d3 = await _api_get(client, "/players", {
                        "search": nome_busca,
                        "league": league_id,
                        "season": SEASON,
                    })
                    for e in d3.get("response", []):
                        if _score_nome(e.get("player", {}).get("name", ""), nome_busca) > 0:
                            entry = e
                            break
                    if entry:
                        break

            if not entry:
                return None

            # ── Busca stats completas pelo player_id ────────────────────────────
            player_id = entry.get("player", {}).get("id")
            if player_id:
                d_full = await _api_get(client, "/players", {
                    "id":     player_id,
                    "season": SEASON,
                })
                full_entries = d_full.get("response", [])
                if full_entries:
                    entry = full_entries[0]  # stats completas de todas as ligas

    except Exception:
        return None

    agregado = _agregar_stats([entry])
    if not agregado:
        return None

    player_info = entry.get("player", {})
    agregado["foto"]     = player_info.get("photo", "")
    agregado["api_nome"] = player_info.get("name", nome)
    return agregado


# ════════════════════════════════════════════════════════════════════════════════
# PASSO 3 — Métricas P90
# ════════════════════════════════════════════════════════════════════════════════

def calcular_p90(raw: dict) -> dict:
    """
    Passo 3: Calcula P90 e aplica League Strength Score.
    stat_ajustada = stat_p90 × LSS
    Exibe: "0.72 gols/90 × 0.94 (Bundesliga) = 0.68 ajustado"
    Filtra jogadores com < 270 minutos (amostra_insuficiente=True).
    """
    mins = raw.get("minutes", 0)
    ok   = mins >= MIN_MINUTOS
    lss  = raw.get("liga_lss", _LSS_FALLBACK)
    liga = raw.get("liga_nome", "")

    def p90(campo: str) -> float | None:
        if not ok or not mins:
            return None
        return round((raw.get(campo, 0) or 0) / mins * 90, 2)

    def p90_adj(campo: str) -> float | None:
        val = p90(campo)
        return round(val * lss, 2) if val is not None else None

    copa_apenas = raw.get("copa_apenas", False)

    return {
        "minutes":              mins,
        "appearances":          raw.get("appearances", 0),
        "amostra_insuficiente": not ok,
        "copa_apenas":          copa_apenas,
        "clube_nome":           raw.get("clube_nome", ""),
        "clube_logo":           raw.get("clube_logo", ""),
        "foto":                 raw.get("foto", ""),
        "liga_nome":            liga,
        "liga_lss":             round(lss, 2),
        # totais
        "goals_total":          raw.get("goals", 0),
        "assists_total":        raw.get("assists", 0),
        "shots_on_goal_total":  raw.get("shots_on_goal", 0),
        "key_passes_total":     raw.get("key_passes", 0),
        "dribbles_total":       raw.get("dribbles", 0),
        "yellow_cards_total":   raw.get("yellow_cards", 0),
        # P90 bruto
        "goals_p90":            p90("goals"),
        "assists_p90":          p90("assists"),
        "shots_on_goal_p90":    p90("shots_on_goal"),
        "key_passes_p90":       p90("key_passes"),
        "dribbles_p90":         p90("dribbles"),
        "yellow_cards_p90":     p90("yellow_cards"),
        # P90 ajustado pelo LSS (usado para ranking)
        "goals_p90_adj":        p90_adj("goals"),
        "assists_p90_adj":      p90_adj("assists"),
        "shots_on_goal_p90_adj": p90_adj("shots_on_goal"),
        "key_passes_p90_adj":   p90_adj("key_passes"),
        "dribbles_p90_adj":     p90_adj("dribbles"),
        "yellow_cards_p90_adj": p90_adj("yellow_cards"),
    }


# ════════════════════════════════════════════════════════════════════════════════
# PASSO 4 — Seleção de destaques
# ════════════════════════════════════════════════════════════════════════════════

def _card_jogador(player: dict, stats_p90: dict, cat_key: str,
                  stat_campo: str, icone: str, label: str, mercado: str) -> dict:
    val_p90  = stats_p90.get(f"{stat_campo}_p90")
    val_adj  = stats_p90.get(f"{stat_campo}_p90_adj")
    val_tot  = stats_p90.get(f"{stat_campo}_total", 0)
    mins     = stats_p90.get("minutes", 0)
    lss      = stats_p90.get("liga_lss", _LSS_FALLBACK)
    liga     = stats_p90.get("liga_nome", "")
    insuf    = stats_p90.get("amostra_insuficiente", True)

    if val_p90 is not None and val_adj is not None:
        resumo = (
            f"{val_p90} {label} × {lss} ({liga}) = {val_adj} ajustado · "
            f"{val_tot} total em {mins} min"
        )
    else:
        resumo = "sem dados suficientes"

    return {
        "nome":             player["nome"],
        "posicao":          POSICOES.get(player["pos"], player["pos"]),
        "pos_sigla":        player["pos"],
        "clube":            stats_p90.get("clube_nome") or player["clube"],
        "clube_logo":       stats_p90.get("clube_logo", ""),
        "foto_jogador":     stats_p90.get("foto", ""),
        "caps":             player.get("caps"),
        "categoria":        cat_key,
        "icone_categoria":  icone,
        "stat_label":       label,
        "stat_p90":         val_p90,
        "stat_p90_adj":     val_adj,
        "liga_lss":         lss,
        "liga_nome":        liga,
        "stat_total":       val_tot,
        "minutos_jogados":  mins,
        "resumo":           resumo,
        "mercado_sugerido": mercado,
        "odd_mercado":      None,   # The Odds API player props raramente disponíveis
        "amostra_insuficiente": insuf,
        "dados_insuficientes":  val_p90 is None,
    }


def selecionar_destaques(
    squad: list[dict],
    stats_map: dict[str, dict],   # {nome: stats_p90}
) -> list[dict]:
    """
    Passo 3-4: Seleciona top 2 por categoria, máx 6 no total.
    Ordena por P90. Exclui jogadores com amostra_insuficiente.
    """
    vistos:    set[str] = set()
    resultado: list[dict] = []

    for cat_key, campo, icone, label, mercado in CATEGORIAS:
        if len(resultado) >= MAX_JUGADORES:
            break

        # Categorias ofensivas que não devem usar jogadores copa_apenas
        CATEGORIAS_OFENSIVAS = {"goleadores", "assistentes", "chutadores", "passes_chave"}
        exclui_copa = cat_key in CATEGORIAS_OFENSIVAS

        candidatos = []
        for p in squad:
            nome = p["nome"]
            if nome in vistos:
                continue
            st = stats_map.get(nome)
            if not st or st.get("amostra_insuficiente"):
                continue
            # Ajuste 3: exclui copa_apenas de categorias ofensivas
            if exclui_copa and st.get("copa_apenas"):
                continue
            val = st.get(f"{campo}_p90_adj") or st.get(f"{campo}_p90")
            if val is None or val <= 0:
                continue
            candidatos.append((val, p, st))

        candidatos.sort(key=lambda x: -x[0])
        adicionados = 0
        for val, p, st in candidatos:
            if adicionados >= TOP_POR_CAT:
                break
            if len(resultado) >= MAX_JUGADORES:
                break
            vistos.add(p["nome"])
            resultado.append(_card_jogador(p, st, cat_key, campo, icone, label, mercado))
            adicionados += 1

    return resultado


# ════════════════════════════════════════════════════════════════════════════════
# API pública
# ════════════════════════════════════════════════════════════════════════════════

async def buscar_jogadores_destaque(team_name: str) -> dict:
    """
    Orquestra os 5 passos e retorna o dict para o campo jogadores_destaque_*.
    Busca stats apenas para os 10 jogadores com mais caps (economiza quota).
    """
    # Passo 1 — squad
    squad = await buscar_squad(team_name)
    if not squad:
        return {
            "time_nome": team_name,
            "jogadores": [],
            "fonte_squad": "indisponível",
            "dados_insuficientes": True,
        }

    # Ordena por caps desc para priorizar os titulares
    squad_sorted = sorted(squad, key=lambda p: p.get("caps", 0), reverse=True)
    top_squad    = squad_sorted[:10]  # máx 10 para economizar quota

    # Passo 2 — stats em paralelo (máx 5 simultâneos para não sobrecarregar)
    stats_map: dict[str, dict] = {}

    async def fetch_one(p: dict) -> None:
        raw = await buscar_stats_jogador(p["nome"], p["clube"])
        if raw:
            stats_map[p["nome"]] = calcular_p90(raw)

    semaphore = asyncio.Semaphore(3)
    async def fetch_limited(p):
        async with semaphore:
            await fetch_one(p)

    await asyncio.gather(*[fetch_limited(p) for p in top_squad])

    # Passo 3-4 — destaques
    destaques = selecionar_destaques(squad_sorted, stats_map)

    # Inclui jogadores sem stats como "dados_insuficientes" se não atingiu 3
    if len(destaques) < 3:
        for p in squad_sorted[:6]:
            if p["nome"] not in {d["nome"] for d in destaques}:
                destaques.append({
                    "nome":            p["nome"],
                    "posicao":         POSICOES.get(p["pos"], p["pos"]),
                    "pos_sigla":       p["pos"],
                    "clube":           p["clube"],
                    "clube_logo":      "",
                    "foto_jogador":    "",
                    "caps":            p.get("caps"),
                    "categoria":       "squad",
                    "icone_categoria": "👤",
                    "stat_label":      "caps internacionais",
                    "stat_p90":        None,
                    "stat_total":      p.get("caps", 0),
                    "minutos_jogados": 0,
                    "resumo":          f"{p.get('caps',0)} caps · {p.get('gols_int',0)} gols internacionais",
                    "mercado_sugerido": "—",
                    "odd_mercado":      None,
                    "amostra_insuficiente": True,
                    "dados_insuficientes":  True,
                })
            if len(destaques) >= MAX_JUGADORES:
                break

    return {
        "time_nome":           team_name,
        "jogadores":           destaques[:MAX_JUGADORES],
        "total_squad":         len(squad),
        "fonte_squad":         "Wikipedia 2026_FIFA_World_Cup_squads",
        "jogadores_analisados": len(stats_map),
        "dados_insuficientes": len(destaques) == 0,
    }
