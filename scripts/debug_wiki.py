import asyncio, sys, re
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import httpx
from app.agents.players_agent import _parse_squad_html

UA = "Mozilla/5.0 (compatible; bot)"

async def main():
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        r = await c.get("https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads",
                        headers={"User-Agent": UA})
    html = r.text
    print(f"Status: {r.status_code}  tamanho: {len(html):,} chars")

    # Testa o parser diretamente
    for team in ["Mexico", "South Africa"]:
        print(f"\n--- {team} ---")
        players = _parse_squad_html(html, team)
        print(f"  Jogadores encontrados: {len(players)}")
        for p in players[:3]:
            print(f"  {p}")

    # Debug: mostra o que acontece com o anchor para Mexico
    team_id = "Mexico"
    anchor_m = re.search(rf'<h[23] id="{re.escape(team_id)}"', html, re.IGNORECASE)
    if anchor_m:
        print(f"\nAnchor Mexico encontrado em idx={anchor_m.start()}")
        content_start = anchor_m.end()
        end_m = re.search(r'<div class="mw-heading', html[content_start:])
        section = html[content_start: content_start + (end_m.start() if end_m else 50000)]
        print(f"Section: {len(section)} chars")
        rows = re.findall(r'nat-fs-player', section)
        print(f"nat-fs-player matches: {len(rows)}")
        if rows:
            # Show first row
            first = re.search(r'<tr class="nat-fs-player">(.*?)</tr>', section, re.DOTALL)
            if first:
                print(f"First row preview:\n{first.group(1)[:400]}")
    else:
        print("Anchor Mexico NAO encontrado!")
        # Show all h3 ids
        h3s = re.findall(r'<h[23] id="([^"]+)"', html)
        print(f"Todos os h3 ids encontrados ({len(h3s)}): {h3s[:20]}")

asyncio.run(main())
