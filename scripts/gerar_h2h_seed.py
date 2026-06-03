"""
Pré-busca o histórico de confrontos diretos (H2H) para todos os 72 jogos
da Copa 2026 e salva em seeds/h2h_seed.json.

Roda 1x (ou quando necessário atualizar). Elimina 1 chamada por jogo.

Uso:
    python scripts/gerar_h2h_seed.py
    python scripts/gerar_h2h_seed.py --dry-run
"""
import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

SEED_IN  = ROOT / "seeds" / "copa_2026.json"
SEED_OUT = ROOT / "seeds" / "h2h_seed.json"
BASE_URL = "https://v3.football.api-sports.io"
HEADERS  = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}
DELAY    = 1.5


async def _buscar_h2h(client: httpx.AsyncClient, id1: int, id2: int) -> list[dict]:
    try:
        r = await client.get(
            f"{BASE_URL}/fixtures/headtohead",
            headers=HEADERS,
            params={"h2h": f"{id1}-{id2}", "last": 10},
            timeout=15,
        )
        r.raise_for_status()
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
            for f in r.json().get("response", [])
        ]
    except Exception as e:
        print(f"    [aviso] {e}")
        return []


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    jogos = json.loads(SEED_IN.read_text(encoding="utf-8"))["jogos"]
    total = len(jogos)

    existente: dict = {}
    if SEED_OUT.exists():
        try:
            existente = json.loads(SEED_OUT.read_text(encoding="utf-8")).get("jogos", {})
            print(f"Seed existente: {len(existente)} jogos ja cacheados\n")
        except Exception:
            pass

    print(f"{'='*55}")
    print(f"  Gerando h2h_seed.json — {total} jogos")
    if args.dry_run:
        print("  [DRY RUN]")
    print(f"{'='*55}\n")

    resultado: dict = dict(existente)
    ok = sem_h2h = pulados = 0

    async with httpx.AsyncClient() as client:
        for idx, jogo in enumerate(jogos):
            slug  = jogo["slug"]
            casa  = jogo["time_casa"]
            fora  = jogo["time_fora"]
            id1   = jogo["time_casa_id"]
            id2   = jogo["time_fora_id"]

            if slug in existente:
                print(f"[{idx+1:02d}/{total}] {casa} x {fora:<25} PULADO")
                pulados += 1
                continue

            print(f"[{idx+1:02d}/{total}] {casa} x {fora:<25} ...", end=" ", flush=True)

            if args.dry_run:
                print("(dry-run)")
                continue

            h2h = await _buscar_h2h(client, id1, id2)
            resultado[slug] = h2h

            if h2h:
                print(f"OK — {len(h2h)} confronto(s)")
                ok += 1
            else:
                print("sem historico")
                sem_h2h += 1

            await asyncio.sleep(DELAY)

    if not args.dry_run:
        SEED_OUT.write_text(
            json.dumps({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_jogos":  len(resultado),
                "jogos":        resultado,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"\n{'='*55}")
        print(f"  [OK] Com H2H      : {ok}")
        print(f"  [--] Sem historico: {sem_h2h}")
        print(f"  [>>] Pulados      : {pulados}")
        print(f"  Salvo em: {SEED_OUT.name}")
        print(f"{'='*55}")


if __name__ == "__main__":
    asyncio.run(main())
