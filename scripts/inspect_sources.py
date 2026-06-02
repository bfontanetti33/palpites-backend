"""
Inspeciona o HTML real de eloratings.net e as APIs do FIFA ranking
para descobrir os seletores corretos antes de implementar o scraping.
"""
import asyncio, os, sys, re, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
import httpx

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

async def main():
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:

        # ── 1. eloratings.net ─────────────────────────────────────────────
        print("=" * 60)
        print("[1] ELORATINGS.NET — inspecionando HTML")
        print("=" * 60)
        try:
            r = await c.get("https://www.eloratings.net/World",
                            headers={"User-Agent": UA})
            html = r.text
            print(f"  Status: {r.status_code}  |  Content-Type: {r.headers.get('content-type','?')}")
            print(f"  Tamanho: {len(html)} chars")

            # Procura "Mexico" no HTML
            idx = html.lower().find("mexico")
            if idx >= 0:
                trecho = html[max(0,idx-200):idx+400]
                print(f"\n  Contexto ao redor de 'Mexico' (idx={idx}):")
                print("  " + trecho.replace("\n"," ").replace("\r",""))
            else:
                print("  'Mexico' NÃO encontrado no HTML!")
                # Mostra primeiros 500 chars
                print(f"\n  Primeiros 500 chars:")
                print(html[:500])

            # Procura padrões de tabela com números de 4 dígitos (ratings Elo)
            elos = re.findall(r'(\d{4})', html)
            elos_validos = [int(e) for e in elos if 1200 <= int(e) <= 2400]
            print(f"\n  Números de 4 dígitos no range 1200-2400 (candidatos Elo): {elos_validos[:20]}")

        except Exception as e:
            print(f"  ERRO: {e}")

        # ── 2. eloratings.net — página específica do time ─────────────────
        print("\n" + "=" * 60)
        print("[2] ELORATINGS.NET/Mexico — página individual")
        print("=" * 60)
        try:
            r2 = await c.get("https://www.eloratings.net/Mexico",
                             headers={"User-Agent": UA})
            html2 = r2.text
            print(f"  Status: {r2.status_code}")
            # Procura o rating atual
            matches = re.findall(r'(\d{4})', html2)
            validos = [int(m) for m in matches if 1200 <= int(m) <= 2400]
            print(f"  Ratings candidatos: {validos[:10]}")
            # Acha "current rating" ou similar
            for pat in [r'rating.*?(\d{4})', r'(\d{4}).*?rating', r'class.*?rating.*?(\d{4})']:
                m = re.search(pat, html2, re.IGNORECASE)
                if m:
                    print(f"  Match '{pat}': {m.group(0)[:100]}")
        except Exception as e:
            print(f"  ERRO: {e}")

        # ── 3. API FIFA ───────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("[3] API FIFA — api.fifa.com/api/v3/ranking/FIFA")
        print("=" * 60)
        try:
            r3 = await c.get(
                "https://api.fifa.com/api/v3/ranking/FIFA",
                params={"locale": "en", "dateId": "latest"},
                headers={"User-Agent": UA, "Origin": "https://www.fifa.com",
                         "Referer": "https://www.fifa.com/"}
            )
            print(f"  Status: {r3.status_code}  |  Content-Type: {r3.headers.get('content-type','?')}")
            if r3.status_code == 200:
                data = r3.json()
                print(f"  Keys: {list(data.keys()) if isinstance(data,dict) else type(data)}")
                # Tenta achar México
                text = json.dumps(data)
                idx = text.lower().find("mexico")
                if idx >= 0:
                    print(f"  Contexto México: {text[max(0,idx-50):idx+200]}")
                else:
                    print(f"  'Mexico' não encontrado. Primeiros 500 chars:")
                    print(text[:500])
            else:
                print(f"  Body: {r3.text[:300]}")
        except Exception as e:
            print(f"  ERRO: {e}")

        # ── 4. Wikipedia FIFA Ranking ─────────────────────────────────────
        print("\n" + "=" * 60)
        print("[4] WIKIPEDIA — FIFA World Rankings")
        print("=" * 60)
        try:
            r4 = await c.get(
                "https://en.wikipedia.org/wiki/FIFA_World_Rankings",
                headers={"User-Agent": UA}
            )
            html4 = r4.text
            print(f"  Status: {r4.status_code}  |  tamanho: {len(html4)} chars")
            idx = html4.lower().find("mexico")
            if idx >= 0:
                trecho = html4[max(0,idx-100):idx+300]
                # Limpa HTML tags
                clean = re.sub(r'<[^>]+>', '', trecho)
                print(f"  Contexto México (limpo):\n  {clean[:300]}")
            # Procura tabela com rankings
            ranks = re.findall(r'<td>(\d{1,3})</td>.*?<td>([A-Z][a-zA-Z ]+)</td>', html4)
            if ranks:
                print(f"\n  Primeiros rankings encontrados: {ranks[:10]}")
        except Exception as e:
            print(f"  ERRO: {e}")

asyncio.run(main())
