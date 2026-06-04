#!/usr/bin/env python3
"""
Popula seeds/arbitros_copa_2026.json com histórico real de cartões.

Estratégia: busca fixtures por liga doméstica/continental, filtra pelo
nome do árbitro no campo fixture.referee, acumula estatísticas de
/fixtures/statistics. Para quando tiver >= 20 jogos por árbitro.

Nota: /fixtures?referee= não funciona mesmo no plano Pro.

Uso:
    python scripts/gerar_seed_arbitros.py
    python scripts/gerar_seed_arbitros.py --min-jogos 15   (padrão 20)
    python scripts/gerar_seed_arbitros.py --dry-run        (sem salvar)
"""
import argparse
import asyncio
import json
import os
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx

API_KEY   = os.getenv("API_FOOTBALL_KEY", "")
BASE      = "https://v3.football.api-sports.io"
HDR       = {"x-apisports-key": API_KEY}
SEED_PATH = ROOT / "seeds" / "arbitros_copa_2026.json"

# ── Ligas por árbitro ─────────────────────────────────────────────────────────
LIGA_ARBITROS: list[dict] = [
    # Torneios internacionais (prioridade alta — cobre muitos árbitros)
    {"nome": "Euro 2024",            "league_id": 4,   "season": 2024,
     "arbitros": ["Szymon Marciniak","Slavko Vincic","Istvan Kovacs","Glenn Nyberg",
                  "Clement Turpin","Felix Zwayer","Danny Makkelie","Michael Oliver",
                  "Francois Letexier","Daniele Orsato","Anthony Taylor",
                  "Serdar Gozubuyuk","Andreas Ekberg","Rohit Saggi","Stephanie Frappart"]},
    {"nome": "Copa America 2024",    "league_id": 9,   "season": 2024,
     "arbitros": ["Facundo Tello","Fernando Rapallini","Cesar Ramos","Ivan Barton",
                  "Ismail Elfath","Jesus Valenzuela","Piero Maza","Wilton Sampaio",
                  "Raphael Claus","Tori Penso","Kathryn Nesbitt","Maria Carvajal",
                  "Claudia Umpierrez","Edina Alves","Stephanie Frappart"]},
    {"nome": "African Nations Cup 2024", "league_id": 6, "season": 2024,
     "arbitros": ["Victor Gomes","Janny Sikazwe","Mustapha Ghorbal","Bamlak Tessema",
                  "Maguette Ndiaye","Jean-Jacques Ndala","Salima Mukansanga",
                  "Redouane Jiyed","Eric Otogo-Castane","Elameer Hassan"]},
    {"nome": "Champions League 2024","league_id": 2,   "season": 2024,
     "arbitros": ["Szymon Marciniak","Slavko Vincic","Istvan Kovacs","Glenn Nyberg",
                  "Clement Turpin","Felix Zwayer","Danny Makkelie","Michael Oliver",
                  "Francois Letexier","Daniele Orsato","Anthony Taylor",
                  "Serdar Gozubuyuk","Andreas Ekberg","Rohit Saggi"]},
    {"nome": "Europa League 2024",   "league_id": 3,   "season": 2024,
     "arbitros": ["Szymon Marciniak","Slavko Vincic","Istvan Kovacs","Glenn Nyberg",
                  "Serdar Gozubuyuk","Andreas Ekberg","Rohit Saggi","Stephanie Frappart"]},
    {"nome": "Copa Libertadores 2024","league_id": 13, "season": 2024,
     "arbitros": ["Raphael Claus","Wilton Sampaio","Facundo Tello","Fernando Rapallini",
                  "Jesus Valenzuela","Piero Maza","Claudia Umpierrez"]},
    {"nome": "CONMEBOL Sudamericana 2024","league_id": 11,"season": 2024,
     "arbitros": ["Facundo Tello","Fernando Rapallini","Piero Maza","Claudia Umpierrez"]},
    {"nome": "CAF Champions League 2024","league_id": 12,"season": 2024,
     "arbitros": ["Victor Gomes","Janny Sikazwe","Mustapha Ghorbal","Bamlak Tessema",
                  "Maguette Ndiaye","Jean-Jacques Ndala","Salima Mukansanga",
                  "Redouane Jiyed","Eric Otogo-Castane","Elameer Hassan"]},
    {"nome": "AFC Champions League 2024","league_id": 17,"season": 2024,
     "arbitros": ["Alireza Faghani","Ma Ning","Abdulrahman Al-Jassim",
                  "Mohammed Abdulla Hassan","Yoshimi Yamashita","Ryuji Sato"]},
    {"nome": "CONCACAF Champions Cup 2024","league_id": 26,"season": 2024,
     "arbitros": ["Cesar Ramos","Ivan Barton","Ismail Elfath","Tori Penso"]},
    # Ligas domésticas
    {"nome": "Premier League 2024",  "league_id": 39,  "season": 2024,
     "arbitros": ["Michael Oliver","Anthony Taylor","Rebecca Welch","Cheryl Foster"]},
    {"nome": "Championship 2024",    "league_id": 40,  "season": 2024,
     "arbitros": ["Rebecca Welch","Cheryl Foster"]},
    {"nome": "Ligue 1 2024",         "league_id": 61,  "season": 2024,
     "arbitros": ["Clement Turpin","Francois Letexier","Stephanie Frappart","Bouchra Karboubi"]},
    {"nome": "Serie A 2024",         "league_id": 135, "season": 2024,
     "arbitros": ["Daniele Orsato"]},
    {"nome": "Bundesliga 2024",      "league_id": 78,  "season": 2024,
     "arbitros": ["Felix Zwayer","Riem Hussein"]},
    {"nome": "Eredivisie 2024",      "league_id": 88,  "season": 2024,
     "arbitros": ["Danny Makkelie","Serdar Gozubuyuk"]},
    {"nome": "La Liga 2024",         "league_id": 140, "season": 2024,
     "arbitros": ["Jesus Valenzuela","Maria Carvajal"]},
    {"nome": "Allsvenskan 2024",     "league_id": 113, "season": 2024,
     "arbitros": ["Glenn Nyberg","Andreas Ekberg"]},
    {"nome": "Eliteserien 2024",     "league_id": 103, "season": 2024,
     "arbitros": ["Rohit Saggi"]},
    {"nome": "Superliga Romania 2024","league_id": 283,"season": 2024,
     "arbitros": ["Istvan Kovacs"]},
    {"nome": "Brasileirao 2024",     "league_id": 71,  "season": 2024,
     "arbitros": ["Raphael Claus","Wilton Sampaio","Edina Alves"]},
    {"nome": "Liga MX 2024",         "league_id": 262, "season": 2024,
     "arbitros": ["Cesar Ramos","Ivan Barton"]},
    {"nome": "MLS 2024",             "league_id": 253, "season": 2024,
     "arbitros": ["Ismail Elfath","Tori Penso","Kathryn Nesbitt"]},
    {"nome": "J-League 2024",        "league_id": 98,  "season": 2024,
     "arbitros": ["Yoshimi Yamashita","Ryuji Sato"]},
    {"nome": "Chinese Super League 2024","league_id": 169,"season": 2024,
     "arbitros": ["Ma Ning"]},
    {"nome": "A-League 2024",        "league_id": 188, "season": 2024,
     "arbitros": ["Alireza Faghani"]},
    {"nome": "Primeira Liga 2024",   "league_id": 94,  "season": 2024,
     "arbitros": ["Sandra Braz"]},
    {"nome": "Copa 2022",            "league_id": 1,   "season": 2022, "arbitros": []},
    {"nome": "Copa 2018",            "league_id": 1,   "season": 2018, "arbitros": []},
]


# ── Helpers de nome ───────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s or "")
    return nfkd.encode("ASCII", "ignore").decode().lower().strip()


def _match(nome_seed: str, nome_api: str) -> bool:
    """Verifica se nome_api corresponde ao árbitro nome_seed."""
    if not nome_api:
        return False
    sn = _norm(nome_seed)
    an = _norm(nome_api)
    if sn == an or sn in an or an in sn:
        return True
    # Sobrenome
    partes = sn.split()
    if len(partes) >= 2 and partes[-1] in an:
        return True
    # Inicial + sobrenome: "S. Marciniak" → "szymon marciniak"
    if len(partes) >= 2 and an.startswith(partes[0][0] + ".") and partes[-1] in an:
        return True
    return False


def _tendencia(cpj: float | None) -> str:
    if cpj is None: return "Moderado"
    if cpj >= 4.5:  return "Rigoroso"
    if cpj >= 3.0:  return "Moderado"
    return "Permissivo"


# ── API ───────────────────────────────────────────────────────────────────────

_req_count = 0

async def _get(client: httpx.AsyncClient, path: str, params: dict) -> dict:
    global _req_count
    _req_count += 1
    r = await client.get(f"{BASE}{path}", headers=HDR, params=params, timeout=20)
    return r.json()


async def _stats_fixture(client: httpx.AsyncClient, fid: int) -> dict:
    data = await _get(client, "/fixtures/statistics", {"fixture": fid})
    amarelos = vermelhos = penaltis = 0
    for team_s in data.get("response", []):
        for stat in team_s.get("statistics", []):
            tipo = _norm(stat.get("type") or "")
            val  = stat.get("value") or 0
            try: val = int(val)
            except: val = 0
            if "yellow" in tipo:       amarelos += val
            elif "red"    in tipo:     vermelhos += val
            elif "penalty" in tipo and "score" in tipo: penaltis += val
    return {"amarelos": amarelos, "vermelhos": vermelhos, "penaltis": penaltis}


# ── Core ──────────────────────────────────────────────────────────────────────

async def coletar(
    client: httpx.AsyncClient,
    nome_seed: str,
    acumulado: dict,
    min_jogos: int,
    delay: float,
) -> bool:
    """Retorna True se já atingiu min_jogos."""
    return acumulado.get("jogos", 0) >= min_jogos


async def processar_liga(
    client: httpx.AsyncClient,
    liga: dict,
    todos_arbitros: set[str],
    acumulados: dict[str, dict],
    min_jogos: int,
    delay: float,
):
    """Busca fixtures de uma liga e coleta stats para árbitros alvo."""
    liga_nome  = liga["nome"]
    league_id  = liga["league_id"]
    season     = liga["season"]
    alvo_liga  = set(liga.get("arbitros") or todos_arbitros)

    # Árbitros que ainda precisam de dados nesta liga
    pendentes = [a for a in alvo_liga
                 if a in todos_arbitros
                 and acumulados.get(a, {}).get("jogos", 0) < min_jogos]
    if not pendentes:
        return

    print(f"\n[{liga_nome}] buscando fixtures...", flush=True)
    data = await _get(client, "/fixtures", {"league": league_id, "season": season})
    await asyncio.sleep(delay)

    fixtures = data.get("response", [])
    if not fixtures:
        print(f"  {liga_nome}: 0 fixtures")
        return

    # Filtra fixtures cujo árbitro está na nossa lista de pendentes
    jogos_relevantes: dict[str, list[int]] = {}  # nome_seed → fixture_ids
    for f in fixtures:
        ref_api = (f.get("fixture", {}).get("referee") or "").strip()
        if not ref_api:
            continue
        for nome_seed in pendentes:
            if acumulados.get(nome_seed, {}).get("jogos", 0) >= min_jogos:
                continue
            if _match(nome_seed, ref_api):
                jogos_relevantes.setdefault(nome_seed, []).append(f["fixture"]["id"])

    # Busca estatísticas para os fixtures relevantes
    fixture_stats_cache: dict[int, dict] = {}

    for nome_seed, fids in jogos_relevantes.items():
        ja_tem = acumulados.get(nome_seed, {}).get("jogos", 0)
        precisa = max(0, min_jogos - ja_tem)
        fids_usar = fids[:precisa + 5]  # busca um pouco mais para margem

        for fid in fids_usar:
            if acumulados.get(nome_seed, {}).get("jogos", 0) >= min_jogos:
                break
            if fid not in fixture_stats_cache:
                try:
                    fixture_stats_cache[fid] = await _stats_fixture(client, fid)
                    await asyncio.sleep(delay)
                except Exception as e:
                    fixture_stats_cache[fid] = {}
                    continue

            stats = fixture_stats_cache[fid]
            if not stats:
                continue

            entry = acumulados.setdefault(nome_seed, {
                "jogos": 0, "amarelos": 0, "vermelhos": 0,
                "penaltis": 0, "fontes": [],
            })
            entry["jogos"]    += 1
            entry["amarelos"] += stats.get("amarelos", 0)
            entry["vermelhos"]+= stats.get("vermelhos", 0)
            entry["penaltis"] += stats.get("penaltis", 0)
            if liga_nome not in entry["fontes"]:
                entry["fontes"].append(liga_nome)

        jogos_coletados = acumulados.get(nome_seed, {}).get("jogos", 0)
        if jogos_coletados > 0:
            print(f"  {nome_seed:<35} +{len(jogos_relevantes[nome_seed])} fixtures "
                  f"→ total {jogos_coletados} jogos", flush=True)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-jogos", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()

    if not API_KEY:
        print("ERRO: API_FOOTBALL_KEY não configurado")
        sys.exit(1)

    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    arbitros_seed = {a["nome"]: a for a in seed["arbitros"]}
    todos = set(arbitros_seed.keys())

    # Recupera dados já coletados anteriormente
    acumulados: dict[str, dict] = {}
    for nome, a in arbitros_seed.items():
        if a.get("jogos_analisados", 0) > 0:
            cpj = a.get("cartoes_por_jogo", 0) or 0
            jogos = a.get("jogos_analisados", 0)
            acumulados[nome] = {
                "jogos": jogos,
                "amarelos": round(cpj * jogos),
                "vermelhos": 0,
                "penaltis": round((a.get("penaltis_por_jogo", 0) or 0) * jogos),
                "fontes": [a.get("fonte", "")],
            }
            print(f"  [EXISTENTE] {nome:<35} {jogos} jogos já coletados")

    async with httpx.AsyncClient(timeout=20) as client:
        for liga in LIGA_ARBITROS:
            await processar_liga(client, liga, todos, acumulados, args.min_jogos, args.delay)
            # Verifica se todos já têm dados suficientes
            completos = sum(1 for n in todos if acumulados.get(n, {}).get("jogos", 0) >= args.min_jogos)
            print(f"  → {completos}/{len(todos)} árbitros com {args.min_jogos}+ jogos", flush=True)

    # ── Atualiza seed ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Total requests API: {_req_count}")
    print(f"{'='*60}")
    print(f"\n{'Árbitro':<35} {'Jogos':>6} {'Cart/J':>7} {'Tendência':<12} Fonte")
    print("-" * 80)

    atualizados = pendentes_n = 0
    for nome in sorted(todos):
        acc = acumulados.get(nome, {})
        jogos = acc.get("jogos", 0)
        if jogos == 0:
            pendentes_n += 1
            print(f"  {nome:<35} {'---':>6} {'---':>7} {'---':<12} pendente")
            continue

        amarelos  = acc.get("amarelos", 0)
        vermelhos = acc.get("vermelhos", 0)
        penaltis  = acc.get("penaltis", 0)
        # Vermelhos pesam × 2 (geralmente precedidos de amarelo)
        cpj = round((amarelos + vermelhos * 2) / jogos, 2)
        ppj = round(penaltis / jogos, 2) if penaltis else 0.15
        tend = _tendencia(cpj)
        fontes = ", ".join(acc.get("fontes", []))

        print(f"  {nome:<35} {jogos:>6} {cpj:>7.2f} {tend:<12} {fontes[:40]}")

        arbitros_seed[nome].update({
            "cartoes_por_jogo":  cpj,
            "penaltis_por_jogo": ppj,
            "tendencia":         tend,
            "fonte":             fontes[:80],
            "jogos_analisados":  jogos,
            "amarelos_media":    round(amarelos / jogos, 2),
            "vermelhos_media":   round(vermelhos / jogos, 2),
        })
        atualizados += 1

    print(f"\nArbitros com dados: {atualizados}/{len(todos)} | Pendentes: {pendentes_n}")

    if not args.dry_run:
        from datetime import datetime
        seed["arbitros"] = list(arbitros_seed.values())
        seed["meta"]["gerado_em"] = datetime.now().isoformat()
        SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Seed salvo em {SEED_PATH}")
    else:
        print("[DRY-RUN] Seed NÃO salvo")


asyncio.run(main())
