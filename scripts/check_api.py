"""
Diagnóstico: verifica o que a API tem sobre Copa do Mundo 2026.
"""
import asyncio
import os
import sys
import httpx
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

BASE_URL = "https://v3.football.api-sports.io"
HEADERS  = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}


async def get(client, path, params):
    resp = await client.get(f"{BASE_URL}{path}", headers=HEADERS, params=params)
    resp.raise_for_status()
    return resp.json()


async def main():
    async with httpx.AsyncClient(timeout=20) as client:

        # Verifica quota da API
        print("[INFO] Verificando quota da API...")
        status = await get(client, "/status", {})
        sub = status.get("response", {}).get("subscription", {})
        req = status.get("response", {}).get("requests", {})
        print(f"  Plano: {sub.get('plan', '?')}")
        print(f"  Requests hoje: {req.get('current', '?')} / {req.get('limit_day', '?')}")

        # Busca ligas com "World Cup" no nome para temporada 2026
        print("\n[INFO] Buscando ligas com 'World Cup' na temporada 2026...")
        data = await get(client, "/leagues", {"name": "FIFA World Cup", "season": 2026})
        for l in data.get("response", []):
            lg = l["league"]
            seasons = [s["year"] for s in l.get("seasons", [])]
            print(f"  Liga ID={lg['id']} | {lg['name']} | temporadas: {seasons}")

        # Busca pelo ID 1 em várias temporadas
        print("\n[INFO] Verificando fixtures para liga ID=1 em diferentes temporadas...")
        for season in [2022, 2023, 2024, 2025, 2026]:
            d = await get(client, "/fixtures", {"league": 1, "season": season})
            n = len(d.get("response", []))
            print(f"  season={season}: {n} fixtures")

        # Busca Mexico na Copa do Mundo
        print("\n[INFO] Buscando time 'Mexico' nas ligas de Copa...")
        teams = await get(client, "/teams", {"name": "Mexico"})
        for t in teams.get("response", []):
            print(f"  ID={t['team']['id']} | {t['team']['name']} | {t['team']['country']}")

        # Busca South Africa
        print("\n[INFO] Buscando time 'South Africa'...")
        teams2 = await get(client, "/teams", {"name": "South Africa"})
        for t in teams2.get("response", []):
            print(f"  ID={t['team']['id']} | {t['team']['name']} | {t['team']['country']}")

        # Tenta buscar fixtures do México sem filtro de liga
        print("\n[INFO] Ultimos 10 fixtures do Mexico (sem filtro de liga)...")
        mx_fix = await get(client, "/fixtures", {"team": 164, "last": 10})
        for f in mx_fix.get("response", [])[:10]:
            d = f["fixture"]["date"][:10]
            h = f["teams"]["home"]["name"]
            a = f["teams"]["away"]["name"]
            lg = f["league"]["name"]
            print(f"  {d}  {h} x {a}  [{lg}]")

        # Proximos fixtures do Mexico
        print("\n[INFO] Proximos 10 fixtures do Mexico...")
        mx_next = await get(client, "/fixtures", {"team": 164, "next": 10})
        for f in mx_next.get("response", [])[:10]:
            d = f["fixture"]["date"][:10]
            h = f["teams"]["home"]["name"]
            a = f["teams"]["away"]["name"]
            lg = f["league"]["name"]
            print(f"  {d}  {h} x {a}  [{lg}]")


if __name__ == "__main__":
    asyncio.run(main())
