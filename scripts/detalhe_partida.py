"""
Simula a pagina /partida/flamengo-palmeiras do site palpitesdaia.lovable.app
usando dados reais do jogo Palmeiras x Flamengo - Brasileirao 2024.
"""
import asyncio
import os
import sys
import httpx
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

BASE_URL     = "https://v3.football.api-sports.io"
HEADERS      = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}
FLAMENGO_ID  = 127
PALMEIRAS_ID = 121
BRASILEIRAO  = 71
SEASON       = 2024
TARGET_FID   = 1180380  # Palmeiras x Flamengo  2024-04-21
TARGET_DATE  = "2024-04-21"

_cache = {}


async def get(client, path, params):
    key = f"{path}:{sorted(params.items())}"
    if key in _cache:
        return _cache[key]
    r = await client.get(f"{BASE_URL}{path}", headers=HEADERS, params=params)
    r.raise_for_status()
    data = r.json()
    _cache[key] = data
    return data


async def jogos_antes_da_data(client, team_id: int, antes_de: str, n: int = 5) -> list:
    """Retorna os ultimos N jogos do time ANTES de uma data, no Brasileirao 2024."""
    d = await get(client, "/fixtures", {
        "team": team_id, "league": BRASILEIRAO, "season": SEASON,
    })
    todos = d.get("response", [])
    anteriores = [
        f for f in todos
        if f["fixture"]["date"][:10] < antes_de
        and f["fixture"]["status"]["short"] == "FT"
    ]
    anteriores.sort(key=lambda f: f["fixture"]["date"], reverse=True)
    return anteriores[:n]


async def stats_media_fixtures(client, fixtures: list, team_id: int) -> dict:
    acumulado, contagem = {}, {}
    for f in fixtures:
        fid = f["fixture"]["id"]
        try:
            st = await get(client, "/fixtures/statistics", {"fixture": fid, "team": team_id})
        except Exception:
            continue
        for entry in st.get("response", []):
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


def forma_do_time(fixtures: list, team_id: int) -> list:
    res = []
    for f in sorted(fixtures, key=lambda x: x["fixture"]["date"]):
        winner = f["teams"]["home"]["winner"] if f["teams"]["home"]["id"] == team_id \
                 else f["teams"]["away"]["winner"]
        adv = f["teams"]["away"]["name"] if f["teams"]["home"]["id"] == team_id \
              else f["teams"]["home"]["name"]
        gh = f["goals"]["home"] if f["teams"]["home"]["id"] == team_id else f["goals"]["away"]
        ga = f["goals"]["away"] if f["teams"]["home"]["id"] == team_id else f["goals"]["home"]
        res.append({
            "letra": "W" if winner is True else ("L" if winner is False else "D"),
            "adv": adv, "gh": gh, "ga": ga,
            "data": f["fixture"]["date"][:10],
        })
    return res


def odds_para_prob(odds: dict) -> dict:
    raw = {k: 1 / v for k, v in odds.items() if v > 0}
    total = sum(raw.values())
    return {k: round(v / total * 100) for k, v in raw.items()}


def nivel_str(pct: int) -> str:
    if pct >= 70: return "ALTA  "
    if pct >= 55: return "MEDIA "
    return "BAIXA "


def barra_prob(pct: int, w: int = 20) -> str:
    n = round(pct / 100 * w)
    return "[" + "#" * n + "." * (w - n) + "]"


async def main():
    async with httpx.AsyncClient(timeout=20) as client:

        print("Carregando dados do jogo Palmeiras x Flamengo (Brasileirao 2024)...")

        # 1. Stats do jogo em si (jogo ja encerrado — dados reais)
        print("  [1/5] Stats do jogo...")
        st_data = await get(client, "/fixtures/statistics", {"fixture": TARGET_FID})
        stats_jogo = {}
        for entry in st_data.get("response", []):
            tid = entry["team"]["id"]
            stats_jogo[tid] = {s["type"]: s["value"] for s in entry.get("statistics", [])}

        # 2. Fixture info
        fx_data = await get(client, "/fixtures", {"id": TARGET_FID})
        fx = fx_data.get("response", [{}])[0]
        home    = fx["teams"]["home"]
        away    = fx["teams"]["away"]
        liga    = fx["league"]
        horario = fx["fixture"]["date"]
        estadio = fx["fixture"].get("venue", {}).get("name", "---")
        cidade  = fx["fixture"].get("venue", {}).get("city", "---")
        gols_h  = fx["goals"]["home"]
        gols_a  = fx["goals"]["away"]

        # 3. Jogos anteriores de cada time (para forma e stats medias)
        print("  [2/5] Jogos anteriores ao derby para calcular forma...")
        prev_home = await jogos_antes_da_data(client, home["id"], TARGET_DATE, n=5)
        prev_away = await jogos_antes_da_data(client, away["id"], TARGET_DATE, n=5)

        print(f"  [3/5] Stats medias ({len(prev_home)} jogos anteriores do {home['name']})...")
        stats_prev_home = await stats_media_fixtures(client, prev_home, home["id"])

        print(f"  [4/5] Stats medias ({len(prev_away)} jogos anteriores do {away['name']})...")
        stats_prev_away = await stats_media_fixtures(client, prev_away, away["id"])

        forma_home = forma_do_time(prev_home, home["id"])
        forma_away = forma_do_time(prev_away, away["id"])

        # 5. H2H
        print("  [5/5] H2H...")
        h2h_data = await get(client, "/fixtures/headtohead", {
            "h2h": f"{home['id']}-{away['id']}", "last": 5,
        })
        h2h = []
        for f in h2h_data.get("response", []):
            if f["fixture"]["id"] == TARGET_FID:
                continue  # nao inclui o proprio jogo
            h2h.append({
                "data": f["fixture"]["date"][:10],
                "casa": f["teams"]["home"]["name"],
                "fora": f["teams"]["away"]["name"],
                "g_c":  f["goals"]["home"],
                "g_f":  f["goals"]["away"],
                "venc": "casa" if f["teams"]["home"]["winner"] else
                        ("fora" if f["teams"]["away"]["winner"] else "empate"),
            })

        # ─────────────────────────────────────────────────────────────────
        # RENDERIZACAO — pagina /partida/flamengo-palmeiras
        # ─────────────────────────────────────────────────────────────────
        W    = 68
        sep  = "=" * W
        sep2 = "-" * W

        data_br = f"{horario[8:10]}/{horario[5:7]}/{horario[:4]}"
        hora_br = horario[11:16]
        rodada  = liga.get("round", "").replace("Regular Season - ", "Rodada ")

        print(f"\n\n{sep}")
        print(f"  Brasileirao Serie A  |  {rodada}")
        print(sep2)
        print(f"  {home['name']:<28} x  {away['name']}")
        print(f"  {data_br}  {hora_br}  |  {estadio}, {cidade}")
        print(f"  RESULTADO FINAL:  {home['name']} {gols_h} x {gols_a} {away['name']}")
        print(sep)

        # ── MERCADOS (dados pre-jogo, se disponiveis) ────────────────────
        odds_data = await get(client, "/odds", {"fixture": TARGET_FID, "bookmaker": 6})
        mercados = []
        try:
            bets = odds_data["response"][0]["bookmakers"][0]["bets"]
            mapa = {b["name"]: b["values"] for b in bets}
            label_1x2 = {"Home": f"Vitoria {home['name']}", "Draw": "Empate", "Away": f"Vitoria {away['name']}"}
            if "Match Winner" in mapa:
                vals = {v["value"]: float(v["odd"]) for v in mapa["Match Winner"]}
                probs = odds_para_prob(vals)
                for k, pct in sorted(probs.items(), key=lambda x: -x[1]):
                    mercados.append({"tipo": "Resultado (1X2)", "desc": label_1x2.get(k, k),
                                     "prob": pct, "nivel": nivel_str(pct),
                                     "odd": round(vals[k], 2)})
            if "Both Teams Score" in mapa:
                vals = {v["value"]: float(v["odd"]) for v in mapa["Both Teams Score"]}
                probs = odds_para_prob(vals)
                melhor = max(probs, key=probs.get)
                mercados.append({"tipo": "Ambas Marcam", "desc": melhor,
                                 "prob": probs[melhor], "nivel": nivel_str(probs[melhor]),
                                 "odd": round(vals[melhor], 2)})
            for nome in ["Goals Over/Under", "Total Goals"]:
                if nome in mapa:
                    vals = {v["value"]: float(v["odd"]) for v in mapa[nome]}
                    probs = odds_para_prob(vals)
                    melhor = max(probs, key=probs.get)
                    mercados.append({"tipo": "Total de Gols", "desc": melhor,
                                     "prob": probs[melhor], "nivel": nivel_str(probs[melhor]),
                                     "odd": round(vals[melhor], 2)})
                    break
        except (IndexError, KeyError):
            pass

        if mercados:
            print(f"\n  PALPITES / PROBABILIDADES (pre-jogo, Bet365)")
            print(f"  {'Mercado':<20}  {'Entrada':<26}  {'Prob':>4}  {'Barra':<22}  {'Nivel':<7}  {'Odd'}")
            print(f"  {sep2}")
            for m in mercados:
                print(f"  {m['tipo']:<20}  {m['desc']:<26}  {m['prob']:>3}%  "
                      f"{barra_prob(m['prob']):<22}  {m['nivel']}  @{m['odd']}")

        # ── FORMA RECENTE ────────────────────────────────────────────────
        print(f"\n  FORMA RECENTE (5 jogos antes do derby, Brasileirao 2024)")
        def fmt_forma(forma: list) -> str:
            return "  ".join(
                f"[{j['letra']}] {j['data']} vs {j['adv'][:12]:<12} {j['gh']}-{j['ga']}"
                for j in forma
            ) if forma else "sem dados"

        print(f"\n  {home['name']}:")
        for j in forma_home:
            icone = "+" if j["letra"] == "W" else ("-" if j["letra"] == "L" else "=")
            print(f"    {icone} {j['data']}  vs {j['adv']:<22}  {j['gh']}-{j['ga']}  [{j['letra']}]")

        print(f"\n  {away['name']}:")
        for j in forma_away:
            icone = "+" if j["letra"] == "W" else ("-" if j["letra"] == "L" else "=")
            print(f"    {icone} {j['data']}  vs {j['adv']:<22}  {j['gh']}-{j['ga']}  [{j['letra']}]")

        # ── STATS COMPARATIVAS (pre-jogo: media dos jogos anteriores) ────
        if stats_prev_home or stats_prev_away:
            print(f"\n  ESTATISTICAS MEDIAS PRE-JOGO ({len(prev_home)} rodadas anteriores)")
            col = 24
            print(f"  {'Estatistica':<{col}}   {home['name']:<20}  {away['name']}")
            print(f"  {sep2}")
            pares = [
                ("Posse de Bola",     "Ball Possession",    True,  "%"),
                ("Chutes no Gol",     "Shots on Goal",      True,  ""),
                ("Total de Chutes",   "Total Shots",        True,  ""),
                ("Passes Certos",     "Passes accurate",    True,  ""),
                ("Precisao Passes",   "Passes %",           True,  "%"),
                ("Faltas Cometidas",  "Fouls",              False, ""),
                ("Escanteios",        "Corner Kicks",       True,  ""),
                ("Cart. Amarelos",    "Yellow Cards",       False, ""),
                ("Defesas Goleiro",   "Goalkeeper Saves",   False, ""),
                ("xG (esperado)",     "expected_goals",     True,  ""),
            ]
            for label, chave, maior_melhor, sfx in pares:
                v_h = stats_prev_home.get(chave)
                v_a = stats_prev_away.get(chave)
                if v_h is None and v_a is None:
                    continue
                s_h = f"{v_h}{sfx}" if v_h is not None else "---"
                s_a = f"{v_a}{sfx}" if v_a is not None else "---"
                if v_h is not None and v_a is not None:
                    vant = ">" if (v_h > v_a) == maior_melhor else ("<" if v_h != v_a else "=")
                else:
                    vant = " "
                print(f"  {label:<{col}} {vant}  {s_h:<20}  {s_a}")

        # ── STATS DO JOGO (dados reais do confronto) ─────────────────────
        if stats_jogo:
            print(f"\n  ESTATISTICAS DO JOGO (dados reais)")
            col = 24
            print(f"  {'Estatistica':<{col}}   {home['name']:<20}  {away['name']}")
            print(f"  {sep2}")
            s_h_dict = stats_jogo.get(home["id"], {})
            s_a_dict = stats_jogo.get(away["id"], {})
            chaves = [
                ("Ball Possession",    "Posse de Bola",      True,  ""),
                ("Shots on Goal",      "Chutes no Gol",      True,  ""),
                ("Shots off Goal",     "Chutes Fora",        False, ""),
                ("Total Shots",        "Total Chutes",       True,  ""),
                ("Fouls",              "Faltas",             False, ""),
                ("Corner Kicks",       "Escanteios",         True,  ""),
                ("Yellow Cards",       "Cart. Amarelos",     False, ""),
                ("Goalkeeper Saves",   "Defesas Goleiro",    False, ""),
                ("Passes accurate",    "Passes Certos",      True,  ""),
                ("Passes %",           "Precisao Passes",    True,  "%"),
                ("expected_goals",     "xG Esperado",        True,  ""),
            ]
            for chave, label, maior_melhor, sfx in chaves:
                v_h = s_h_dict.get(chave)
                v_a = s_a_dict.get(chave)
                if v_h is None and v_a is None:
                    continue
                s_h = f"{v_h}{sfx}" if v_h is not None else "---"
                s_a = f"{v_a}{sfx}" if v_a is not None else "---"
                try:
                    fh, fa = float(str(v_h).replace("%","")), float(str(v_a).replace("%",""))
                    vant = ">" if (fh > fa) == maior_melhor else ("<" if fh != fa else "=")
                except Exception:
                    vant = " "
                print(f"  {label:<{col}} {vant}  {s_h:<20}  {s_a}")

        # ── H2H ──────────────────────────────────────────────────────────
        print(f"\n  HISTORICO DE CONFRONTOS — H2H")
        if h2h:
            fla_v = sum(1 for h in h2h if
                (h["venc"] == "casa" and h["casa"] == away["name"]) or
                (h["venc"] == "fora" and h["fora"] == away["name"]))
            pal_v = sum(1 for h in h2h if
                (h["venc"] == "casa" and h["casa"] == home["name"]) or
                (h["venc"] == "fora" and h["fora"] == home["name"]))
            emp = sum(1 for h in h2h if h["venc"] == "empate")
            print(f"  {home['name']} {pal_v}V  |  Empates {emp}  |  {fla_v}V {away['name']}")
            print()
            for h in h2h:
                print(f"  {h['data']}   {h['casa']:<22}  {h['g_c']} x {h['g_a']}  {h['fora']}")
        else:
            print("  Sem dados H2H anteriores na API (plano free).")

        print(f"\n{sep}")
        print(f"  https://palpitesdaia.lovable.app/partida/flamengo-palmeiras")
        print(sep)


if __name__ == "__main__":
    asyncio.run(main())
