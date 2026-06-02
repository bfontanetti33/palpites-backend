"""
Busca os endpoints de dados reais de eloratings.net e FIFA ranking via Wikipedia.
"""
import asyncio, os, sys, re, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import httpx

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

async def main():
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:

        # ── Elo: tenta endpoints JSON conhecidos ──────────────────────────
        print("[ELO] Tentando endpoints de dados eloratings.net...")
        elo_urls = [
            "https://eloratings.net/en.rank.json",
            "https://eloratings.net/data/ratings/latest.json",
            "https://api.eloratings.net/ratings",
        ]
        for url in elo_urls:
            try:
                r = await c.get(url, headers={"User-Agent": UA})
                print(f"  {url} → {r.status_code}  ({len(r.text)} chars)")
                if r.status_code == 200 and len(r.text) > 100:
                    print(f"  Amostra: {r.text[:200]}")
            except Exception as e:
                print(f"  {url} → ERRO: {e}")

        # ── Elo: página individual retorna JSON? ──────────────────────────
        print("\n[ELO] Tentando /Mexico.json...")
        try:
            r = await c.get("https://eloratings.net/Mexico.json",
                            headers={"User-Agent": UA})
            print(f"  Status: {r.status_code}  ({len(r.text)} chars)")
            if r.status_code == 200:
                print(f"  Amostra: {r.text[:300]}")
        except Exception as e:
            print(f"  ERRO: {e}")

        # ── FIFA: tenta endpoints alternativos ────────────────────────────
        print("\n[FIFA] Tentando endpoints da API FIFA...")
        fifa_urls = [
            "https://api.fifa.com/api/v3/ranking/FIFA?locale=en&dateId=latest",
            "https://api.fifa.com/api/v3/ranking/FIFA?locale=en",
            "https://www.fifa.com/api/v1/ranking/FIFA",
        ]
        for url in fifa_urls:
            try:
                r = await c.get(url, headers={"User-Agent": UA,
                    "Origin": "https://www.fifa.com", "Referer": "https://www.fifa.com/"})
                print(f"  {url[:60]} → {r.status_code}")
                if r.status_code == 200:
                    print(f"  Amostra: {r.text[:300]}")
            except Exception as e:
                print(f"  {url[:60]} → ERRO: {e}")

        # ── Wikipedia: extrai ranking da tabela HTML ──────────────────────
        print("\n[WIKI] Extraindo ranking FIFA da Wikipedia...")
        r = await c.get("https://en.wikipedia.org/wiki/FIFA_World_Rankings",
                        headers={"User-Agent": UA})
        html = r.text

        # Tenta extrair tabela wikitable com rankings
        # Padrão: linha com número de ranking, nome do país, pontos
        # <td>16</td>...<td>Mexico</td>...<td>1591</td>
        rows = re.findall(
            r'<tr[^>]*>.*?<td[^>]*>\s*(\d{1,3})\s*</td>.*?title="([^"]+)">([^<]+)</a>.*?</tr>',
            html, re.DOTALL
        )
        if rows:
            print(f"  Linhas com ranking encontradas: {len(rows)}")
            for rank, _, country in rows[:15]:
                print(f"    {rank}. {country}")
        else:
            print("  Padrão complexo não encontrado — tentando regex simples...")
            # Regex mais simples: procura pelo conteúdo da célula
            simples = re.findall(r'>\s*(\d{1,3})\s*<.*?>([A-Z][a-zA-Záéíóúñ ]+)<', html)
            simples_filtrado = [(r, c) for r, c in simples if 1 <= int(r) <= 210 and len(c) > 3]
            if simples_filtrado:
                print(f"  Candidatos simples: {simples_filtrado[:15]}")

        # Tenta Wikipedia API (wikitext)
        print("\n[WIKI] Wikipedia API — wikitext do artigo...")
        r2 = await c.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action":"query","prop":"revisions","titles":"FIFA_World_Rankings",
                    "rvprop":"content","rvslots":"main","format":"json","rvlimit":1}
        )
        if r2.status_code == 200:
            data = r2.json()
            pages = data.get("query", {}).get("pages", {})
            for pid, page in pages.items():
                wikitext = page.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("*", "")
                print(f"  Wikitext tamanho: {len(wikitext)} chars")
                # Procura México no wikitext
                idx = wikitext.lower().find("mexico")
                if idx >= 0:
                    print(f"  Contexto México:\n  {wikitext[max(0,idx-50):idx+200]}")

asyncio.run(main())
