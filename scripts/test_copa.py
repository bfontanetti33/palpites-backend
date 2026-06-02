"""
Script de teste: busca Mexico x Africa do Sul na Copa 2026
e monta os dados completos com estatisticas de jogos PASSADOS.
"""
import asyncio
import os
import sys
import httpx
from dotenv import load_dotenv

# Forca UTF-8 para evitar erros de encoding no Windows
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

BASE_URL = "https://v3.football.api-sports.io"
API_KEY  = os.getenv("API_FOOTBALL_KEY", "")
HEADERS  = {"x-apisports-key": API_KEY}


async def get(client: httpx.AsyncClient, path: str, params: dict) -> dict:
    resp = await client.get(f"{BASE_URL}{path}", headers=HEADERS, params=params)
    resp.raise_for_status()
    return resp.json()


def fmt_stats(stats: dict, label: str) -> str:
    if not stats:
        return f"  {label}: sem dados\n"
    linhas = [f"  {label}:"]
    for k, v in stats.items():
        if v is not None:
            linhas.append(f"    - {k}: {v}")
    return "\n".join(linhas)


async def main():
    async with httpx.AsyncClient(timeout=20) as client:

        # 1. Buscar fixture Mexico vs Africa do Sul na Copa 2026
        print("[1/6] Buscando fixture Mexico x Africa do Sul na Copa 2026...")
        all_fx = await get(client, "/fixtures", {"league": 1, "season": 2026})
        total = len(all_fx.get("response", []))
        print(f"      Total de fixtures Copa 2026 na API: {total}")

        fixture = None
        for f in all_fx.get("response", []):
            home_name = f["teams"]["home"]["name"].lower()
            away_name = f["teams"]["away"]["name"].lower()
            nomes = home_name + " " + away_name
            if ("mexico" in nomes) and ("south africa" in nomes or "africa" in nomes):
                fixture = f
                break

        if not fixture:
            print("\n[!] Fixture Mexico x Africa do Sul nao encontrado.")
            print("    Primeiros 15 jogos da Copa 2026 disponiveis:\n")
            for f in all_fx.get("response", [])[:15]:
                d = f["fixture"]["date"][:10]
                h = f["teams"]["home"]["name"]
                a = f["teams"]["away"]["name"]
                print(f"    {d}  {h} x {a}")
            return

        home       = fixture["teams"]["home"]
        away       = fixture["teams"]["away"]
        liga       = fixture["league"]
        horario    = fixture["fixture"]["date"]
        fixture_id = fixture["fixture"]["id"]
        estadio    = fixture["fixture"].get("venue", {}).get("name", "---")
        cidade     = fixture["fixture"].get("venue", {}).get("city", "---")

        print(f"      OK -> fixture ID {fixture_id}: {home['name']} x {away['name']}")
        print(f"      Data: {horario[:10]}  |  {estadio}, {cidade}")

        # 2. H2H historico
        print("\n[2/6] Buscando historico H2H (ultimos 5 jogos)...")
        h2h_data = await get(client, "/fixtures/headtohead", {
            "h2h": f"{home['id']}-{away['id']}",
            "last": 5,
        })
        h2h = []
        for f in h2h_data.get("response", []):
            h2h.append({
                "data":        f["fixture"]["date"][:10],
                "casa":        f["teams"]["home"]["name"],
                "fora":        f["teams"]["away"]["name"],
                "placar_casa": f["goals"]["home"],
                "placar_fora": f["goals"]["away"],
            })
        print(f"      {len(h2h)} confrontos historicos encontrados.")

        # 3. Ultimos 5 jogos de cada time
        print(f"\n[3/6] Buscando ultimos 5 jogos do {home['name']}...")
        mx_fix = await get(client, "/fixtures", {"team": home["id"], "last": 5})

        print(f"[4/6] Buscando ultimos 5 jogos do {away['name']}...")
        sa_fix = await get(client, "/fixtures", {"team": away["id"], "last": 5})

        # 4. Media das estatisticas dos jogos PASSADOS
        async def stats_media(fixtures_resp: list, team_id: int, team_name: str) -> dict:
            acumulado = {}
            contagem  = {}
            total_fixs = len(fixtures_resp)
            for i, f in enumerate(fixtures_resp, 1):
                fid = f["fixture"]["id"]
                data = f["fixture"]["date"][:10]
                print(f"      ({i}/{total_fixs}) buscando stats fixture {fid} ({data})...")
                try:
                    st_data = await get(client, "/fixtures/statistics", {
                        "fixture": fid, "team": team_id
                    })
                except Exception as e:
                    print(f"      Erro: {e}")
                    continue
                for entry in st_data.get("response", []):
                    if entry["team"]["id"] != team_id:
                        continue
                    for s in entry.get("statistics", []):
                        k, v = s["type"], s["value"]
                        if v is None:
                            continue
                        if isinstance(v, str) and "%" in v:
                            try:
                                v = float(v.replace("%", ""))
                            except ValueError:
                                continue
                        try:
                            v = float(v)
                        except (TypeError, ValueError):
                            continue
                        acumulado[k] = acumulado.get(k, 0) + v
                        contagem[k]  = contagem.get(k, 0) + 1
            return {k: round(acumulado[k] / contagem[k], 1) for k in acumulado}

        print(f"\n[5/6] Calculando estatisticas medias do {home['name']} (jogos passados)...")
        stats_home = await stats_media(mx_fix.get("response", []), home["id"], home["name"])

        print(f"\n[5/6] Calculando estatisticas medias do {away['name']} (jogos passados)...")
        stats_away = await stats_media(sa_fix.get("response", []), away["id"], away["name"])

        # 5. Forma recente
        def forma(fixtures_resp: list, team_id: int) -> str:
            resultado = []
            for f in fixtures_resp:
                if f["teams"]["home"]["id"] == team_id:
                    winner = f["teams"]["home"]["winner"]
                else:
                    winner = f["teams"]["away"]["winner"]
                if winner is True:
                    resultado.append("W")
                elif winner is False:
                    resultado.append("L")
                else:
                    resultado.append("D")
            return "".join(resultado)

        forma_home = forma(mx_fix.get("response", []), home["id"])
        forma_away = forma(sa_fix.get("response", []), away["id"])

        # 6. Odds
        print(f"\n[6/6] Buscando odds Bet365 para fixture {fixture_id}...")
        odds_data = await get(client, "/odds", {"fixture": fixture_id, "bookmaker": 6})
        mercados_linhas = []
        try:
            bets = odds_data["response"][0]["bookmakers"][0]["bets"]
            for b in bets[:4]:
                vals = ", ".join(f"{v['value']}={v['odd']}" for v in b["values"])
                mercados_linhas.append(f"  - {b['name']}: {vals}")
        except (IndexError, KeyError):
            mercados_linhas = ["  (sem odds disponiveis para este fixture)"]

        # EXIBICAO FINAL
        sep = "=" * 65
        print(f"\n{sep}")
        print(f"  COPA DO MUNDO 2026")
        print(f"  {home['name']}  x  {away['name']}")
        print(f"  {horario[:10]}  |  {estadio}, {cidade}")
        print(f"  Liga: {liga['name']} {liga['season']}")
        print(sep)

        print("\n  FORMA RECENTE (W=vitoria, D=empate, L=derrota):")
        print(f"  {home['name']}: {forma_home or '---'}")
        print(f"  {away['name']}: {forma_away or '---'}")

        print("\n  ESTATISTICAS MEDIAS (media dos ultimos 5 jogos PASSADOS):")
        print(fmt_stats(stats_home, home["name"]))
        print(fmt_stats(stats_away, away["name"]))

        print("\n  HISTORICO H2H (confrontos anteriores):")
        if h2h:
            for h in h2h:
                print(f"  {h['data']}  {h['casa']} {h['placar_casa']} x {h['placar_fora']} {h['fora']}")
        else:
            print("  Sem confrontos historicos encontrados.")

        print("\n  ODDS (Bet365):")
        for m in mercados_linhas:
            print(m)

        print(f"\n{sep}")
        print("  DADOS PRONTOS PARA ALIMENTAR O SITE!")
        print(sep)


if __name__ == "__main__":
    asyncio.run(main())
