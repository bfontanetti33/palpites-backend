import asyncio, os, sys, json
from pathlib import Path
ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()
import httpx
KEY = os.getenv("API_FOOTBALL_KEY","")
HDR = {"x-apisports-key": KEY}
BASE = "https://v3.football.api-sports.io"

async def main():
    async with httpx.AsyncClient(timeout=10) as c:
        # Quota
        r = await c.get(f"{BASE}/status", headers=HDR)
        d = r.json()
        req = d.get("response",{}).get("requests",{})
        print(f"Requests hoje: {req.get('current','?')} / {req.get('limit_day','?')}")

        # Busca simples
        r2 = await c.get(f"{BASE}/players",
            headers=HDR, params={"search": "Jimenez", "season": 2025})
        d2 = r2.json()
        n = len(d2.get("response", []))
        print(f"Busca 'Jimenez' season=2025: {r2.status_code}, {n} resultados")
        if n:
            p = d2["response"][0]
            print(f"  {p['player']['name']} - {len(p.get('statistics',[]))} entries de stats")
        else:
            print(f"  Erros: {d2.get('errors')}")
            print(f"  Msg: {str(d2)[:200]}")

        # Tenta sem season
        r3 = await c.get(f"{BASE}/players",
            headers=HDR, params={"search": "Jimenez"})
        d3 = r3.json()
        n3 = len(d3.get("response", []))
        print(f"Busca 'Jimenez' sem season: {r3.status_code}, {n3} resultados")

asyncio.run(main())
