"""
Testa o odds_agent.py com México x África do Sul (Copa 2026).
"""
import asyncio, os, sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

from app.agents.odds_agent import (
    listar_eventos_copa, buscar_event_id,
    buscar_odds_evento, buscar_odds_partida,
)


async def main():

    # 1. Eventos disponíveis
    print("[1] Listando eventos Copa 2026...")
    eventos = await listar_eventos_copa()
    print(f"    Total: {len(eventos)} eventos")
    for ev in eventos[:5]:
        dt = ev.get("commence_time","")[:16]
        print(f"    {dt}  {ev['home_team']} x {ev['away_team']}  id={ev['id'][:16]}...")

    # 2. Encontra México x África do Sul
    print("\n[2] Buscando event_id de México x África do Sul...")
    eid = await buscar_event_id("Mexico", "South Africa")
    print(f"    event_id: {eid}")

    # 3. Odds do evento
    if eid:
        print(f"\n[3] Buscando odds para evento {eid[:16]}...")
        odds = await buscar_odds_evento(eid)
        if odds:
            print("    ODDS ENCONTRADAS:")
            print(json.dumps(odds, ensure_ascii=False, indent=4))
        else:
            print("    Sem odds disponíveis ainda para este evento.")
    else:
        print("\n    Evento não encontrado — verificar nomes dos times.")

    # 4. Busca por nome (fluxo completo)
    print("\n[4] Teste do fluxo completo buscar_odds_partida('Mexico','South Africa')...")
    odds2 = await buscar_odds_partida("Mexico", "South Africa")
    if odds2:
        print("    OK — odds retornadas:")
        for k, v in odds2.items():
            print(f"      {k}: {v}")
    else:
        print("    Sem odds disponíveis (normal para jogo futuro sem mercado aberto).")


asyncio.run(main())
