"""
Verifica jogos disponiveis do Mexico e Africa do Sul na Copa 2022 e 2010.
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

        # Jogos do Mexico na Copa 2022
        print("[1] Jogos do Mexico (ID=16) na Copa 2022 (liga=1, season=2022)...")
        data = await get(client, "/fixtures", {"league": 1, "season": 2022, "team": 16})
        for f in data.get("response", []):
            fid = f["fixture"]["id"]
            d   = f["fixture"]["date"][:10]
            h   = f["teams"]["home"]["name"]
            a   = f["teams"]["away"]["name"]
            gh  = f["goals"]["home"]
            ga  = f["goals"]["away"]
            print(f"  ID={fid} | {d}  {h} {gh} x {ga} {a}")

        # Jogos da Africa do Sul na Copa 2010
        print("\n[2] Jogos Africa do Sul (ID=1531) na Copa 2010 (liga=1, season=2010)...")
        data2 = await get(client, "/fixtures", {"league": 1, "season": 2010, "team": 1531})
        for f in data2.get("response", []):
            fid = f["fixture"]["id"]
            d   = f["fixture"]["date"][:10]
            h   = f["teams"]["home"]["name"]
            a   = f["teams"]["away"]["name"]
            gh  = f["goals"]["home"]
            ga  = f["goals"]["away"]
            print(f"  ID={fid} | {d}  {h} {gh} x {ga} {a}")

        # Jogos do Mexico na Copa 2010
        print("\n[3] Jogos Mexico (ID=16) na Copa 2010 (liga=1, season=2010)...")
        data3 = await get(client, "/fixtures", {"league": 1, "season": 2010, "team": 16})
        for f in data3.get("response", []):
            fid = f["fixture"]["id"]
            d   = f["fixture"]["date"][:10]
            h   = f["teams"]["home"]["name"]
            a   = f["teams"]["away"]["name"]
            gh  = f["goals"]["home"]
            ga  = f["goals"]["away"]
            print(f"  ID={fid} | {d}  {h} {gh} x {ga} {a}")

        # H2H Mexico vs Africa do Sul
        print("\n[4] H2H historico Mexico (16) x Africa do Sul (1531)...")
        h2h = await get(client, "/fixtures/headtohead", {
            "h2h": "16-1531",
            "last": 10,
        })
        for f in h2h.get("response", []):
            fid = f["fixture"]["id"]
            d   = f["fixture"]["date"][:10]
            h   = f["teams"]["home"]["name"]
            a   = f["teams"]["away"]["name"]
            gh  = f["goals"]["home"]
            ga  = f["goals"]["away"]
            lg  = f["league"]["name"]
            print(f"  ID={fid} | {d}  {h} {gh} x {ga} {a}  [{lg}]")


if __name__ == "__main__":
    asyncio.run(main())
