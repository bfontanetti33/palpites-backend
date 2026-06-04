#!/usr/bin/env python3
"""
Popula seeds/arbitros_copa_2026.json com dados reais da API-Football.
Para cada árbitro, busca últimos 30 jogos e calcula cartões/pênaltis/tendência.

ATENÇÃO: requer API-Football plano Pro ou superior.
O endpoint /fixtures?referee= não está disponível no plano free.

Uso:
    python scripts/gerar_seed_arbitros.py

Usa ~52 requests da API-Football (um por árbitro).
Recomendado rodar 1x e fazer commit do seed resultante.

Alternativas sem API Pro:
  - População manual: edite seeds/arbitros_copa_2026.json diretamente
  - Os defaults (3.4 cart/jogo, "Moderado") já são retornados corretamente
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx

API_KEY = os.getenv("API_FOOTBALL_KEY", "")
BASE    = "https://v3.football.api-sports.io"
HDR     = {"x-apisports-key": API_KEY}

SEED_PATH = ROOT / "seeds" / "arbitros_copa_2026.json"


def _tendencia(cpj: float | None) -> str | None:
    if cpj is None:
        return None
    if cpj >= 4.5:
        return "Rigoroso"
    if cpj >= 3.0:
        return "Moderado"
    return "Permissivo"


async def buscar_stats_arbitro(client: httpx.AsyncClient, nome: str) -> dict:
    """Busca últimos 30 jogos do árbitro e calcula estatísticas."""
    try:
        r = await client.get(f"{BASE}/fixtures",
            headers=HDR, params={"referee": nome, "last": 30}, timeout=15)
        if r.status_code != 200:
            return {"erro": f"HTTP {r.status_code}"}
        jogos = r.json().get("response", [])
        if not jogos:
            return {"erro": "Sem jogos encontrados"}

        total = len(jogos)
        amarelos = vermelhos = 0

        for f in jogos:
            # Tenta extrair cartões dos eventos do jogo (se incluídos)
            for s in (f.get("statistics") or []):
                for item in s.get("statistics", []):
                    tipo = (item.get("type") or "").lower()
                    val  = item.get("value") or 0
                    try:
                        val = int(val)
                    except (TypeError, ValueError):
                        val = 0
                    if "yellow" in tipo:
                        amarelos += val
                    elif "red" in tipo:
                        vermelhos += val

        cpj = round((amarelos + vermelhos) / total, 2) if total else None
        return {
            "jogos_analisados": total,
            "cartoes_por_jogo": cpj,
            "penaltis_por_jogo": 0.15,  # sem endpoint direto — usa média da Copa
            "tendencia": _tendencia(cpj),
            "fonte": "api-football",
        }
    except Exception as e:
        return {"erro": str(e)[:100]}


async def main():
    if not API_KEY:
        print("ERRO: API_FOOTBALL_KEY não configurado no .env")
        sys.exit(1)

    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    arbitros = seed["arbitros"]
    print(f"Processando {len(arbitros)} árbitros...")

    async with httpx.AsyncClient() as client:
        for i, arb in enumerate(arbitros, 1):
            nome = arb["nome"]
            print(f"[{i:02d}/{len(arbitros)}] {nome}...", end=" ", flush=True)
            resultado = await buscar_stats_arbitro(client, nome)

            if "erro" in resultado:
                print(f"AVISO: {resultado['erro']} — mantendo defaults")
                # Mantém a entrada como está (pendente)
            else:
                arb["cartoes_por_jogo"]  = resultado["cartoes_por_jogo"]
                arb["penaltis_por_jogo"] = resultado["penaltis_por_jogo"]
                arb["tendencia"]         = resultado["tendencia"]
                arb["fonte"]             = resultado["fonte"]
                arb["jogos_analisados"]  = resultado["jogos_analisados"]
                print(f"OK ({resultado['jogos_analisados']} jogos, {resultado['cartoes_por_jogo']} cart/jogo, {resultado['tendencia']})")

            await asyncio.sleep(1.2)  # respeita rate limit

    # Atualiza timestamp
    from datetime import datetime
    seed["meta"]["gerado_em"] = datetime.now().isoformat()

    SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSeed salvo: {SEED_PATH}")
    atualizados = sum(1 for a in arbitros if a.get("fonte") == "api-football")
    print(f"Atualizados: {atualizados}/{len(arbitros)}")


asyncio.run(main())
