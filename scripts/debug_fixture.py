import asyncio, httpx, os, sys, json
from dotenv import load_dotenv
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()
HEADERS = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}
BASE = "https://v3.football.api-sports.io"

FID         = 1180380  # Palmeiras x Flamengo 2024-04-21
FLAMENGO    = 127
PALMEIRAS   = 121
BRASILEIRAO = 71

async def get(c, path, params):
    r = await c.get(f"{BASE}{path}", headers=HEADERS, params=params)
    return r.json()

async def main():
    async with httpx.AsyncClient(timeout=20) as c:

        # Stats do fixture direto
        print(f"[1] Stats do fixture {FID} (Palmeiras x Flamengo):")
        d = await get(c, "/fixtures/statistics", {"fixture": FID})
        resp = d.get("response", [])
        print(f"    {len(resp)} times retornados")
        for team_stats in resp:
            print(f"    Time: {team_stats['team']['name']}")
            for s in team_stats.get("statistics", []):
                if s["value"] is not None:
                    print(f"      {s['type']}: {s['value']}")

        # Ultimos 5 fixtures do Palmeiras no Brasileirao 2024
        print(f"\n[2] Ultimos 5 fixtures Palmeiras (ID={PALMEIRAS}) no Brasileirao 2024:")
        d2 = await get(c, "/fixtures", {"team": PALMEIRAS, "league": BRASILEIRAO, "season": 2024, "last": 5})
        for f in d2.get("response", []):
            fid = f["fixture"]["id"]
            dt  = f["fixture"]["date"][:10]
            h   = f["teams"]["home"]["name"]
            a   = f["teams"]["away"]["name"]
            st  = f["fixture"]["status"]["short"]
            print(f"    ID={fid}  {dt}  {h} x {a}  [{st}]")

        # Ultimos 5 fixtures do Flamengo no Brasileirao 2024
        print(f"\n[3] Ultimos 5 fixtures Flamengo (ID={FLAMENGO}) no Brasileirao 2024:")
        d3 = await get(c, "/fixtures", {"team": FLAMENGO, "league": BRASILEIRAO, "season": 2024, "last": 5})
        for f in d3.get("response", []):
            fid = f["fixture"]["id"]
            dt  = f["fixture"]["date"][:10]
            h   = f["teams"]["home"]["name"]
            a   = f["teams"]["away"]["name"]
            st  = f["fixture"]["status"]["short"]
            print(f"    ID={fid}  {dt}  {h} x {a}  [{st}]")

        # Requests restantes
        st2 = await get(c, "/status", {})
        req = st2.get("response", {}).get("requests", {})
        print(f"\nRequests usados: {req.get('current','?')} / {req.get('limit_day','?')}")

asyncio.run(main())
