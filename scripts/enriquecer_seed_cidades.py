"""
Enriquece seeds/copa_2026.json com cidade e estádio faltantes.
Usa mapeamento estático para estádios conhecidos e API-Football como fallback.
"""
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import httpx

ROOT      = Path(__file__).parent.parent
SEED_PATH = ROOT / "seeds" / "copa_2026.json"

ESTADIO_CIDADE: dict[str, str] = {
    "SoFi Stadium":             "Los Angeles",
    "MetLife Stadium":          "East Rutherford",
    "AT&T Stadium":             "Arlington",
    "Levi's Stadium":           "Santa Clara",
    "Lumen Field":              "Seattle",
    "Lincoln Financial Field":  "Philadelphia",
    "Gillette Stadium":         "Foxborough",
    "Arrowhead Stadium":        "Kansas City",
    "Hard Rock Stadium":        "Miami Gardens",
    "Mercedes-Benz Stadium":    "Atlanta",
    "NRG Stadium":              "Houston",
    "BMO Field":                "Toronto",
    "BC Place":                 "Vancouver",
    "Estadio Azteca":           "Mexico City",
    "Estadio Banorte":          "Mexico City",
    "Estadio Akron":            "Guadalajara",
    "Estadio BBVA":             "Monterrey",
}

FB_KEY = os.getenv("API_FOOTBALL_KEY", "")
FB_HDR = {"x-apisports-key": FB_KEY}


async def buscar_venue(fixture_id: int) -> tuple[str, str]:
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(
                "https://v3.football.api-sports.io/fixtures",
                headers=FB_HDR,
                params={"id": fixture_id},
            )
        resp = r.json().get("response", [])
        if resp:
            venue = resp[0].get("fixture", {}).get("venue", {})
            return (venue.get("name") or "A confirmar",
                    venue.get("city") or "A confirmar")
    except Exception as e:
        print(f"    Erro na API para fixture {fixture_id}: {e}")
    return "A confirmar", "A confirmar"


async def main():
    seed  = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    jogos = seed["jogos"]

    sem_cidade = [j for j in jogos if not (j.get("cidade") or "").strip()]
    print(f"Jogos sem cidade: {len(sem_cidade)}")

    ids_sem_estadio = [
        j["api_fixture_id"] for j in sem_cidade
        if not (j.get("estadio") or "").strip()
    ]
    print(f"Sem estádio também (precisam API): {len(ids_sem_estadio)}")

    # Busca via API-Football para jogos sem estádio
    venue_map: dict[int, tuple[str, str]] = {}
    if ids_sem_estadio:
        print("\nBuscando venues via API-Football...")
        for fid in ids_sem_estadio:
            print(f"  fixture {fid}...", end=" ", flush=True)
            estadio, cidade = await buscar_venue(fid)
            venue_map[fid] = (estadio, cidade)
            print(f"{estadio} / {cidade}")

    # Aplica correções
    corrigidos_mapa = 0
    corrigidos_api  = 0
    a_confirmar     = []

    for j in jogos:
        cidade_atual = (j.get("cidade") or "").strip()
        if cidade_atual and cidade_atual != "A confirmar":
            continue

        estadio = (j.get("estadio") or "").strip()
        fid     = j["api_fixture_id"]

        if estadio and estadio in ESTADIO_CIDADE:
            j["cidade"] = ESTADIO_CIDADE[estadio]
            corrigidos_mapa += 1

        elif fid in venue_map:
            new_estadio, new_cidade = venue_map[fid]
            if not estadio or estadio == "A confirmar":
                j["estadio"] = new_estadio
            j["cidade"] = new_cidade
            if new_cidade != "A confirmar":
                corrigidos_api += 1
            else:
                a_confirmar.append(j["slug"])

        else:
            # Não deveria acontecer — fallback seguro
            if not estadio:
                j["estadio"] = "A confirmar"
            j["cidade"] = "A confirmar"
            a_confirmar.append(j["slug"])

    SEED_PATH.write_text(
        json.dumps(seed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n{'='*50}")
    print(f"Corrigidos pelo mapa estático : {corrigidos_mapa}")
    print(f"Corrigidos pela API-Football  : {corrigidos_api}")
    print(f"Marcados 'A confirmar'        : {len(a_confirmar)}")
    if a_confirmar:
        print(f"  Slugs: {a_confirmar}")
    print(f"{'='*50}")

    # Verifica resultado final
    sem_cidade_final = [j for j in jogos if not (j.get("cidade") or "").strip() or j.get("cidade") == "A confirmar"]
    sem_estadio_final = [j for j in jogos if not (j.get("estadio") or "").strip() or j.get("estadio") == "A confirmar"]
    print(f"\nResultado final:")
    print(f"  Ainda sem cidade real : {len(sem_cidade_final)}")
    print(f"  Ainda sem estádio real: {len(sem_estadio_final)}")
    print(f"\nSeed salvo em: {SEED_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
