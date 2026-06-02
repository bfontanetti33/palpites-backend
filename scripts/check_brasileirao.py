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
        for season in [2024, 2025, 2026]:
            d = await get(c, "/fixtures", {"league": 71, "season": season})
            n = len(d.get("response", []))
            print(f"Brasileirao season={season}: {n} fixtures total")
            # mostra os 3 primeiros se houver
            for f in d.get("response", [])[:3]:
                dt = f["fixture"]["date"][:10]
                h  = f["teams"]["home"]["name"]
                a  = f["teams"]["away"]["name"]
                print(f"  {dt}  {h} x {a}")

        # Checar status das requests novamente
        st = await get(c, "/status", {})
        req = st.get("response", {}).get("requests", {})
        print(f"\nRequests usados hoje: {req.get('current','?')} / {req.get('limit_day','?')}")

asyncio.run(main())
