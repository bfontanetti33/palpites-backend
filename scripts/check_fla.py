import asyncio, httpx, os, sys
from dotenv import load_dotenv
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()
HEADERS = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}
BASE = "https://v3.football.api-sports.io"

async def get(c, path, params):
    r = await c.get(f"{BASE}{path}", headers=HEADERS, params=params)
    return r.json()

async def main():
    async with httpx.AsyncClient(timeout=20) as c:
        # Proximos jogos do Flamengo em cada temporada
        for season in [2024, 2025, 2026]:
            d = await get(c, "/fixtures", {"league": 71, "season": season, "team": 127, "next": 5})
            n = len(d.get("response", []))
            print(f"Flamengo Brasileirao season={season} proximos={n}")
            for f in d.get("response", [])[:3]:
                dt = f["fixture"]["date"][:10]
                h  = f["teams"]["home"]["name"]
                a  = f["teams"]["away"]["name"]
                print(f"  {dt}  {h} x {a}")

        # Ultimos jogos Flamengo (qualquer liga)
        d2 = await get(c, "/fixtures", {"team": 127, "last": 5})
        print(f"\nFlamengo last=5 (qualquer liga): {len(d2.get('response', []))} jogos")
        for f in d2.get("response", []):
            dt = f["fixture"]["date"][:10]
            h  = f["teams"]["home"]["name"]
            a  = f["teams"]["away"]["name"]
            lg = f["league"]["name"]
            print(f"  {dt}  {h} x {a}  [{lg}]")

        # Verifica ID do Palmeiras
        d3 = await get(c, "/teams", {"name": "Palmeiras"})
        print("\nPalmeiras encontrado:")
        for t in d3.get("response", [])[:3]:
            print(f"  ID={t['team']['id']}  {t['team']['name']}  {t['team']['country']}")

asyncio.run(main())
