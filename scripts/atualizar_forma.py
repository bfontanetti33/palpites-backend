"""
Atualiza a forma recente (últimos 10 jogos) dos times que jogam
nos próximos N dias. Salva em seeds/forma_recente_seed.json.

Rodar 1x/dia via cron ou manualmente antes dos jogos.
Consome ~2 req/time × times_que_jogam_em_breve.

Uso:
    python scripts/atualizar_forma.py             # times que jogam nos próximos 3 dias
    python scripts/atualizar_forma.py --dias 7    # próximos 7 dias
    python scripts/atualizar_forma.py --todos     # todos os 48 times (48 req)
"""
import argparse
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

SEED_COPA = ROOT / "seeds" / "copa_2026.json"
SEED_OUT  = ROOT / "seeds" / "forma_recente_seed.json"
BASE_URL  = "https://v3.football.api-sports.io"
HEADERS   = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}
DELAY     = 1.5

_EXCLUIR_LIGA = (
    "women", "feminino", "female",
    "u-17", "u-20", "u-21", "u-23", "u17", "u20", "u21", "u23",
    "youth", "junior", "sub-", "olimpic", "olympic",
)

def _e_jogo_senior(f: dict) -> bool:
    return not any(t in f["league"]["name"].lower() for t in _EXCLUIR_LIGA)


async def _buscar_forma(client: httpx.AsyncClient, team_id: int) -> list[dict]:
    try:
        r = await client.get(
            f"{BASE_URL}/fixtures",
            headers=HEADERS,
            params={"team": team_id, "last": 10},
            timeout=15,
        )
        r.raise_for_status()
        fixtures = [f for f in r.json().get("response", []) if _e_jogo_senior(f)]
        forma = []
        for f in sorted(fixtures, key=lambda x: x["fixture"]["date"]):
            is_home     = f["teams"]["home"]["id"] == team_id
            winner      = f["teams"]["home"]["winner"] if is_home else f["teams"]["away"]["winner"]
            adversario  = f["teams"]["away"]["name"]   if is_home else f["teams"]["home"]["name"]
            gols_pro    = f["goals"]["home"]            if is_home else f["goals"]["away"]
            gols_contra = f["goals"]["away"]            if is_home else f["goals"]["home"]
            resultado   = "W" if winner is True else ("L" if winner is False else "D")
            forma.append({
                "data":             f["fixture"]["date"][:10],
                "adversario":       adversario,
                "placar_proprio":   gols_pro,
                "placar_adversario": gols_contra,
                "resultado":        resultado,
                "competicao":       f["league"]["name"],
            })
        return forma
    except Exception as e:
        print(f"    [aviso] {e}")
        return []


def _times_que_jogam_em_breve(jogos: list, dias: int) -> dict[int, str]:
    agora   = datetime.now(timezone.utc)
    limite  = agora + timedelta(days=dias)
    times: dict[int, str] = {}
    for j in jogos:
        try:
            dt = datetime.fromisoformat(j["data_hora_utc"].replace("Z", "+00:00"))
        except Exception:
            continue
        if agora <= dt <= limite:
            times[j["time_casa_id"]] = j["time_casa"]
            times[j["time_fora_id"]] = j["time_fora"]
    return times


def _todos_os_times(jogos: list) -> dict[int, str]:
    times: dict[int, str] = {}
    for j in jogos:
        times[j["time_casa_id"]] = j["time_casa"]
        times[j["time_fora_id"]] = j["time_fora"]
    return times


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias",  type=int, default=3)
    parser.add_argument("--todos", action="store_true")
    args = parser.parse_args()

    jogos = json.loads(SEED_COPA.read_text(encoding="utf-8"))["jogos"]

    if args.todos:
        times = _todos_os_times(jogos)
        print(f"Modo: TODOS os {len(times)} times")
    else:
        times = _times_que_jogam_em_breve(jogos, args.dias)
        print(f"Modo: times que jogam nos proximos {args.dias} dias ({len(times)} times)")

    # Carrega seed existente
    existente: dict = {}
    if SEED_OUT.exists():
        try:
            data = json.loads(SEED_OUT.read_text(encoding="utf-8"))
            existente = data.get("times", {})
        except Exception:
            pass

    resultado: dict = dict(existente)
    total = len(times)
    ok = sem_dados = 0

    print(f"\n{'='*55}")
    print(f"  Atualizando forma_recente_seed.json")
    print(f"{'='*55}\n")

    async with httpx.AsyncClient() as client:
        for idx, (team_id, team_name) in enumerate(times.items()):
            print(f"[{idx+1:02d}/{total}] {team_name:<30} ...", end=" ", flush=True)
            forma = await _buscar_forma(client, team_id)
            resultado[str(team_id)] = {
                "nome":        team_name,
                "atualizado":  datetime.now(timezone.utc).isoformat(),
                "jogos":       forma,
            }
            if forma:
                ult = forma[-1]
                print(f"OK — {len(forma)} jogos (ult: {ult['resultado']} vs {ult['adversario']})")
                ok += 1
            else:
                print("sem dados")
                sem_dados += 1
            await asyncio.sleep(DELAY)

    SEED_OUT.write_text(
        json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_times":  len(resultado),
            "times":        resultado,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n{'='*55}")
    print(f"  [OK] Com forma   : {ok}")
    print(f"  [--] Sem dados   : {sem_dados}")
    print(f"  Salvo em: {SEED_OUT.name}")
    print(f"{'='*55}")


if __name__ == "__main__":
    asyncio.run(main())
