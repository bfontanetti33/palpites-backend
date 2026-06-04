#!/usr/bin/env python3
"""
Popula seeds/arbitros_copa_2026.json com dados reais da API-Football.

NOTA: O endpoint /fixtures?referee= não funciona mesmo no plano Pro.
Esta versão usa uma abordagem alternativa:
  1. Busca todos os fixtures da Copa 2022 e 2018 (1 req cada)
  2. Para cada fixture, busca /fixtures/statistics (cartões amarelos/vermelhos)
  3. Agrupa por árbitro e calcula média de cartões/jogo
  4. Mapeia para os nomes canônicos do seed via tabela de conversão

Uso:
    python scripts/gerar_seed_arbitros.py

Usa ~130 requests da API-Football (64 Copa 2022 + 64 Copa 2018 statistics).
"""
import asyncio
import json
import os
import sys
import time
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

# ── Tabela de conversão: nome API → nome canônico do seed ─────────────────────
# API usa formato abreviado ("S. Marciniak") ou nome completo em inglês
_API_PARA_SEED: dict[str, str] = {
    # Abreviados Copa 2022
    "S. Marciniak":           "Szymon Marciniak",
    "Slavko Vincic":          "Slavko Vincic",
    "C. Ramos":               "Cesar Ramos",
    "I. Elfath":              "Ismail Elfath",
    "F. Tello":               "Facundo Tello",
    "Ivan Cisneros":          "Ivan Barton",   # assistente/próximo
    "Ivan Barton":            "Ivan Barton",
    "Raphael Claus":          "Raphael Claus",
    "Victor Gomes":           "Victor Gomes",
    "V. Gomes":               "Victor Gomes",
    "Abdulrahman Al Jassim":  "Abdulrahman Al-Jassim",
    "A. Faghani":             "Alireza Faghani",
    "Alireza Faghani":        "Alireza Faghani",
    "M. A. Hassan":           "Mohammed Abdulla Hassan",
    "Mohammed Abdulla Hassan":"Mohammed Abdulla Hassan",
    "Ma Ning":                "Ma Ning",
    "J. Valenzuela":          "Jesus Valenzuela",
    "Jesus Valenzuela":       "Jesus Valenzuela",
    "Wilton Pereira Sampaio": "Wilton Sampaio",
    "Wilton Sampaio":         "Wilton Sampaio",
    "P. Maza":                "Piero Maza",
    "F. Rapallini":           "Fernando Rapallini",
    "Fernando Rapallini":     "Fernando Rapallini",
    "M. Oliver":              "Michael Oliver",
    "Michael Oliver":         "Michael Oliver",
    "F. Zwayer":              "Felix Zwayer",
    "Felix Zwayer":           "Felix Zwayer",
    "F. Letexier":            "Francois Letexier",
    "C. Turpin":              "Clement Turpin",
    "Clement Turpin":         "Clement Turpin",
    "D. Orsato":              "Daniele Orsato",
    "Daniele Orsato":         "Daniele Orsato",
    "D. Makkelie":            "Danny Makkelie",
    "A. Taylor":              "Anthony Taylor",
    "Anthony Taylor":         "Anthony Taylor",
    "I. Kovacs":              "Istvan Kovacs",
    "G. Nyberg":              "Glenn Nyberg",
    "A. Ekberg":              "Andreas Ekberg",
    "R. Saggi":               "Rohit Saggi",
    "M. Ghorbal":             "Mustapha Ghorbal",
    "J. Sikazwe":             "Janny Sikazwe",
    "B. Tessema":             "Bamlak Tessema",
    "R. Jiyed":               "Redouane Jiyed",
    "M. Ndiaye":              "Maguette Ndiaye",
    "J. Ndala":               "Jean-Jacques Ndala",
    "S. Mukansanga":          "Salima Mukansanga",
    "Y. Yamashita":           "Yoshimi Yamashita",
    "Yoshimi Yamashita":      "Yoshimi Yamashita",
    "K. Nesbitt":             "Kathryn Nesbitt",
    "S. Frappart":            "Stephanie Frappart",
    "Stephanie Frappart":     "Stephanie Frappart",
    "E. Alves":               "Edina Alves",
    "Edina Alves":            "Edina Alves",
    "C. Foster":              "Cheryl Foster",
    "T. Penso":               "Tori Penso",
    "R. Welch":               "Rebecca Welch",
    "C. Umpierrez":           "Claudia Umpierrez",
    "R. Hussein":             "Riem Hussein",
    "Antonio Mateu":          None,   # não está na Copa 2026
}


def _tendencia(cpj: float | None) -> str:
    if cpj is None:
        return "Moderado"
    if cpj >= 4.5:
        return "Rigoroso"
    if cpj >= 3.0:
        return "Moderado"
    return "Permissivo"


async def _buscar_fixtures(client: httpx.AsyncClient, league: int, season: int) -> list[dict]:
    r = await client.get(f"{BASE}/fixtures", headers=HDR,
        params={"league": league, "season": season}, timeout=20)
    return r.json().get("response", [])


async def _stats_fixture(client: httpx.AsyncClient, fid: int) -> dict:
    """Retorna total de cartões amarelos e vermelhos para o fixture."""
    r = await client.get(f"{BASE}/fixtures/statistics", headers=HDR,
        params={"fixture": fid}, timeout=20)
    amarelos = vermelhos = 0
    for team_s in r.json().get("response", []):
        for stat in team_s.get("statistics", []):
            tipo = (stat.get("type") or "").lower()
            val  = stat.get("value") or 0
            try:
                val = int(val)
            except (TypeError, ValueError):
                val = 0
            if "yellow" in tipo:
                amarelos += val
            elif "red" in tipo:
                vermelhos += val
    return {"amarelos": amarelos, "vermelhos": vermelhos}


async def main():
    if not API_KEY:
        print("ERRO: API_FOOTBALL_KEY não configurado")
        sys.exit(1)

    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    arbitros_seed = {a["nome"]: a for a in seed["arbitros"]}

    # ── Coleta fixtures de Copa 2022 e 2018 ───────────────────────────────────
    ref_stats: dict[str, dict] = {}  # nome_seed → {jogos, amarelos, vermelhos}

    async with httpx.AsyncClient(timeout=20) as client:
        for league, season in [(1, 2022), (1, 2018)]:
            print(f"Buscando Copa {season}...")
            fixtures = await _buscar_fixtures(client, league, season)
            print(f"  {len(fixtures)} fixtures encontrados")
            await asyncio.sleep(1)

            for i, f in enumerate(fixtures, 1):
                ref_api = (f["fixture"].get("referee") or "").strip()
                fid     = f["fixture"]["id"]
                if not ref_api:
                    continue

                # Mapeia para nome canônico
                nome_seed = _API_PARA_SEED.get(ref_api)
                if nome_seed is None:
                    continue  # árbitro não está na Copa 2026

                # Busca estatísticas
                try:
                    stats = await _stats_fixture(client, fid)
                    entry = ref_stats.setdefault(nome_seed, {"jogos": 0, "amarelos": 0, "vermelhos": 0})
                    entry["jogos"]    += 1
                    entry["amarelos"] += stats["amarelos"]
                    entry["vermelhos"]+= stats["vermelhos"]
                    print(f"  [{i:02d}/{len(fixtures)}] {ref_api!r:30} → {nome_seed} | amarelos: {stats['amarelos']}, vermelhos: {stats['vermelhos']}")
                except Exception as e:
                    print(f"  [{i:02d}] ERRO {fid}: {e}")

                await asyncio.sleep(0.4)   # ~150 req/min, bem abaixo do limite Pro

    # ── Atualiza seed ─────────────────────────────────────────────────────────
    atualizados = 0
    print()
    print("=== RESULTADOS ===")
    for nome_seed, stats in ref_stats.items():
        jogos = stats["jogos"]
        if jogos == 0:
            continue
        cpj = round((stats["amarelos"] + stats["vermelhos"]) / jogos, 2)
        tend = _tendencia(cpj)

        if nome_seed in arbitros_seed:
            arbitros_seed[nome_seed].update({
                "cartoes_por_jogo":  cpj,
                "penaltis_por_jogo": 0.15,   # melhor estimativa disponível
                "tendencia":         tend,
                "fonte":             "api-football-copa2022-2018",
                "jogos_analisados":  jogos,
                "amarelos_media":    round(stats["amarelos"] / jogos, 2),
                "vermelhos_media":   round(stats["vermelhos"] / jogos, 2),
            })
            atualizados += 1
            print(f"  {nome_seed:<35} {jogos} jogos | cpj={cpj} | {tend}")

    # Recria lista de árbitros mantendo a ordem
    seed["arbitros"] = list(arbitros_seed.values())
    from datetime import datetime
    seed["meta"]["gerado_em"] = datetime.now().isoformat()

    SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
    total = len(seed["arbitros"])
    pendentes = sum(1 for a in seed["arbitros"] if a.get("fonte") in (None, "pendente"))
    print()
    print(f"Seed salvo: {atualizados} árbitros atualizados com dados reais")
    print(f"Pendentes (sem dados Copa 2022/18): {pendentes}/{total}")


asyncio.run(main())
