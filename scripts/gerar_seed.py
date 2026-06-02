"""
Gera seeds/copa_2026.json com dados reais da API-Football.
Busca todos os fixtures da Copa 2026 (league=1, season=2026)
e salva o JSON com IDs reais, slugs, grupos, rodadas e horários em Brasília.
"""
import asyncio, os, sys, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()
import httpx

BASE    = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}
BRT     = timezone(timedelta(hours=-3))


def para_brasilia(iso: str) -> str:
    """Converte ISO 8601 para America/Sao_Paulo (UTC-3)."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.astimezone(BRT).isoformat()


def slugify(nome: str) -> str:
    return (nome.lower()
               .replace(" ", "-")
               .replace(".", "")
               .replace("'", "")
               .replace("(", "")
               .replace(")", "")
               .replace("&", "and"))


async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        print("Buscando todos os fixtures da Copa 2026...")
        r = await c.get(f"{BASE}/fixtures", headers=HEADERS,
                        params={"league": 1, "season": 2026})
        d = r.json()
        fixtures = d.get("response", [])
        print(f"  Total recebido: {len(fixtures)} fixtures")

        # Monta dicionário de times (nome -> id, logo)
        times = {}
        jogos = []

        for f in sorted(fixtures, key=lambda x: x["fixture"]["date"]):
            home = f["teams"]["home"]
            away = f["teams"]["away"]
            liga  = f["league"]
            fix   = f["fixture"]

            # Registra times
            for t in [home, away]:
                if t["name"] not in times:
                    times[t["name"]] = {
                        "api_football_id":   t["id"],
                        "api_football_nome": t["name"],
                        "logo":              t.get("logo", ""),
                    }

            # Rodada e grupo (vem no campo "round", ex: "Group Stage - 1" ou "Group A - 1")
            rodada_raw = liga.get("round", "")

            slug = f"{slugify(home['name'])}-{slugify(away['name'])}"

            jogo = {
                "api_fixture_id":    fix["id"],
                "slug":              slug,
                "rodada_raw":        rodada_raw,
                "status":            fix["status"]["short"],
                "data_hora_utc":     fix["date"],
                "data_hora_brasilia": para_brasilia(fix["date"]),
                "estadio":           fix.get("venue", {}).get("name", ""),
                "cidade":            fix.get("venue", {}).get("city", ""),
                "time_casa":         home["name"],
                "time_casa_id":      home["id"],
                "time_casa_logo":    home.get("logo", ""),
                "time_fora":         away["name"],
                "time_fora_id":      away["id"],
                "time_fora_logo":    away.get("logo", ""),
                "gols_casa":         f["goals"]["home"],
                "gols_fora":         f["goals"]["away"],
            }
            jogos.append(jogo)

        seed = {
            "meta": {
                "fonte":       "API-Football v3 (league=1, season=2026)",
                "temporada":   2026,
                "total":       len(jogos),
                "gerado_em":   datetime.now(BRT).isoformat(),
                "nota": (
                    "Horarios em America/Sao_Paulo (UTC-3). "
                    "Fixture IDs reais da API. "
                    "Stats e H2H ainda sao buscados via API no momento da requisicao."
                ),
            },
            "times": dict(sorted(times.items())),
            "jogos": jogos,
        }

        out_path = Path(__file__).parent.parent / "seeds" / "copa_2026.json"
        out_path.parent.mkdir(exist_ok=True)
        out_path.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"\n  Seed salvo em: {out_path}")
        print(f"  Times registrados: {len(times)}")
        print(f"  Jogos registrados: {len(jogos)}")
        print(f"\n  Primeiros 5 jogos:")
        for j in jogos[:5]:
            print(f"    [{j['data_hora_brasilia'][:16]}]  {j['time_casa']} x {j['time_fora']}  ({j['rodada_raw']})")

        print(f"\n  Rodadas encontradas:")
        rodadas = sorted(set(j["rodada_raw"] for j in jogos))
        for r in rodadas[:10]:
            print(f"    {r}")
        if len(rodadas) > 10:
            print(f"    ... e mais {len(rodadas)-10}")


if __name__ == "__main__":
    asyncio.run(main())
