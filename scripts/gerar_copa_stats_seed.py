"""
Pré-busca as estatísticas históricas de Copa do Mundo (2022/2018/2014/2010)
para todos os 48 times da Copa 2026 e salva em seeds/copa_stats_seed.json.

Roda 1x (dados históricos não mudam). Elimina 2 chamadas à API-Football
por jogo em produção.

Uso:
    python scripts/gerar_copa_stats_seed.py
    python scripts/gerar_copa_stats_seed.py --dry-run   # lista times sem chamar API
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

SEED_IN   = ROOT / "seeds" / "copa_2026.json"
SEED_OUT  = ROOT / "seeds" / "copa_stats_seed.json"
BASE_URL  = "https://v3.football.api-sports.io"
HEADERS   = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}
WC_SEASONS = [2022, 2018, 2014, 2010]
DELAY     = 1.5   # segundos entre requests (respeita rate limit)


def _times_unicos(jogos: list) -> dict[int, str]:
    times: dict[int, str] = {}
    for j in jogos:
        times[j["time_casa_id"]] = j["time_casa"]
        times[j["time_fora_id"]] = j["time_fora"]
    return dict(sorted(times.items()))


async def _buscar_stats(client: httpx.AsyncClient, team_id: int, team_name: str) -> dict:
    for season in WC_SEASONS:
        try:
            r = await client.get(
                f"{BASE_URL}/teams/statistics",
                headers=HEADERS,
                params={"league": 1, "season": season, "team": team_id},
                timeout=15,
            )
            r.raise_for_status()
            resp = r.json().get("response", {})
            jogos = resp.get("fixtures", {}).get("played", {}).get("total") or 0
            if not resp or jogos == 0:
                continue

            fix   = resp["fixtures"]
            goals = resp["goals"]
            cards = resp.get("cards", {})
            pen   = resp.get("penalty", {})
            clean = resp.get("clean_sheet", {})

            total_yellow = sum((v.get("total") or 0) for v in cards.get("yellow", {}).values())
            total_red    = sum((v.get("total") or 0) for v in cards.get("red",    {}).values())

            return {
                "fonte":              f"Copa {season}",
                "dados_insuficientes": False,
                "sede_neutra":        True,
                "jogos":              jogos,
                "vitorias":           fix["wins"]["total"],
                "empates":            fix["draws"]["total"],
                "derrotas":           fix["loses"]["total"],
                "gols_marcados":      goals["for"]["total"]["total"],
                "gols_sofridos":      goals["against"]["total"]["total"],
                "media_gols_marcados": float(goals["for"]["average"]["total"]),
                "media_gols_sofridos": float(goals["against"]["average"]["total"]),
                "clean_sheets":       clean.get("total"),
                "media_amarelos":     round(total_yellow / jogos, 2) if jogos else None,
                "media_vermelhos":    round(total_red    / jogos, 2) if jogos else None,
                "penaltis_marcados":  pen.get("scored", {}).get("total"),
                "penaltis_total":     pen.get("total"),
            }
        except Exception as e:
            print(f"    [aviso] Copa {season} falhou: {e}")
            continue

    return {"fonte": "", "dados_insuficientes": True, "sede_neutra": True}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    jogos  = json.loads(SEED_IN.read_text(encoding="utf-8"))["jogos"]
    times  = _times_unicos(jogos)
    total  = len(times)

    # Carrega seed existente para reaproveitar dados já buscados
    existente: dict = {}
    if SEED_OUT.exists():
        try:
            existente = json.loads(SEED_OUT.read_text(encoding="utf-8")).get("teams", {})
            print(f"Seed existente: {len(existente)} times ja cacheados\n")
        except Exception:
            pass

    print(f"{'='*55}")
    print(f"  Gerando copa_stats_seed.json — {total} times")
    print(f"  Seasons: {WC_SEASONS}")
    if args.dry_run:
        print("  [DRY RUN — sem chamadas a API]")
    print(f"{'='*55}\n")

    resultado: dict = dict(existente)
    ok = falha = pulados = 0

    async with httpx.AsyncClient() as client:
        for idx, (team_id, team_name) in enumerate(times.items()):
            chave = str(team_id)
            if chave in existente:
                print(f"[{idx+1:02d}/{total}] {team_name:<30} PULADO (ja existe)")
                pulados += 1
                continue

            print(f"[{idx+1:02d}/{total}] {team_name:<30} ...", end=" ", flush=True)

            if args.dry_run:
                print("(dry-run)")
                continue

            stats = await _buscar_stats(client, team_id, team_name)
            resultado[chave] = {"nome": team_name, **stats}

            if stats["dados_insuficientes"]:
                print("sem historico de Copa")
                falha += 1
            else:
                print(f"OK — {stats['fonte']} ({stats.get('jogos',0)} jogos)")
                ok += 1

            await asyncio.sleep(DELAY)

    if not args.dry_run:
        SEED_OUT.write_text(
            json.dumps({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_times":  len(resultado),
                "teams":        resultado,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"\n{'='*55}")
        print(f"  [OK]   Com historico : {ok}")
        print(f"  [--]   Sem historico : {falha} (novatos na Copa)")
        print(f"  [>>]   Pulados       : {pulados}")
        print(f"  Salvo em: {SEED_OUT.name}")
        print(f"{'='*55}")


if __name__ == "__main__":
    asyncio.run(main())
