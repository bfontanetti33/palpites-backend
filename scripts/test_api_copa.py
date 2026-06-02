import asyncio, os, sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv()
import httpx

BASE    = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}

async def main():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{BASE}/fixtures", headers=HEADERS,
                        params={"league": 1, "season": 2026, "next": 10})
        d = r.json()
        total = len(d.get("response", []))
        print(f"Total retornado: {total}")
        print(f"Status HTTP: {r.status_code}")
        err = d.get("errors", [])
        if err:
            print(f"Erros: {err}")
        for f in d.get("response", [])[:3]:
            print(f"  {f['fixture']['date'][:10]}  {f['teams']['home']['name']} x {f['teams']['away']['name']}  [ID={f['fixture']['id']}]")

asyncio.run(main())
