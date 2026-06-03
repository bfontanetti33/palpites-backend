"""
Pré-cacheia todos os 72 jogos da Copa 2026 no Railway.
Chama GET /api/v1/copa/jogos/{slug} para cada jogo, aquecendo o TTLCache do servidor.
Prioriza Rodada 1 (24 jogos) antes das demais rodadas.

Uso:
    python scripts/precalcular_jogos.py                  # Railway (produção)
    python scripts/precalcular_jogos.py --local          # localhost:8000
    python scripts/precalcular_jogos.py --rodada 1       # só Rodada 1
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parent.parent
SEED_PATH = ROOT / "seeds" / "copa_2026.json"

BASE_PROD  = "https://palpites-backend-production.up.railway.app"
BASE_LOCAL = "http://localhost:8000"

# Delay entre requests para não sobrecarregar a API-Football (100 req/dia free)
DELAY_ENTRE_JOGOS = 2.0   # segundos
TIMEOUT_REQUEST   = 60    # segundos por jogo (inclui API-Football + ratings)


async def cachear_jogo(
    client: httpx.AsyncClient,
    slug: str,
    base_url: str,
    idx: int,
    total: int,
    time_casa: str,
    time_fora: str,
) -> tuple[str, bool, float, str]:
    url = f"{base_url}/api/v1/copa/jogos/{slug}"
    t0 = time.perf_counter()
    try:
        r = await client.get(url, timeout=TIMEOUT_REQUEST)
        elapsed = round(time.perf_counter() - t0, 1)
        if r.status_code == 200:
            data = r.json()
            insuf = data.get("dados_insuficientes", False)
            status = "! dados_insuf" if insuf else "OK"
            return slug, True, elapsed, status
        else:
            return slug, False, round(time.perf_counter() - t0, 1), f"HTTP {r.status_code}"
    except httpx.TimeoutException:
        return slug, False, TIMEOUT_REQUEST, "TIMEOUT"
    except Exception as e:
        return slug, False, round(time.perf_counter() - t0, 1), f"ERRO: {e}"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local",   action="store_true", help="usa localhost:8000")
    parser.add_argument("--rodada",  type=int, default=0, help="só uma rodada (1, 2 ou 3)")
    parser.add_argument("--concorrencia", type=int, default=3, help="requests em paralelo (default 3)")
    args = parser.parse_args()

    base_url = BASE_LOCAL if args.local else BASE_PROD

    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    jogos = seed["jogos"]

    # Ordena: Rodada 1 primeiro, depois 2, depois 3
    jogos_ordenados = sorted(jogos, key=lambda j: j.get("rodada_numero", 99))

    if args.rodada:
        jogos_ordenados = [j for j in jogos_ordenados if j.get("rodada_numero") == args.rodada]

    total = len(jogos_ordenados)
    print(f"\n{'='*60}")
    print(f"  Pré-cache Copa 2026 — {total} jogos")
    print(f"  Base URL : {base_url}")
    print(f"  Timeout  : {TIMEOUT_REQUEST}s/jogo | Delay: {DELAY_ENTRE_JOGOS}s | Concorrência: {args.concorrencia}")
    print(f"{'='*60}\n")

    ok = 0
    falha = 0
    resultados = []

    # Agrupa em lotes para controlar concorrência e quota da API
    semaphore = asyncio.Semaphore(args.concorrencia)

    async def cachear_com_limite(client, jogo, idx):
        async with semaphore:
            slug = jogo["slug"]
            casa = jogo.get("time_casa", "")
            fora = jogo.get("time_fora", "")
            rodada = jogo.get("rodada_numero", "?")
            print(f"[{idx+1:02d}/{total}] R{rodada} | {casa} x {fora} ...", end=" ", flush=True)
            result = await cachear_jogo(client, slug, base_url, idx, total, casa, fora)
            _, sucesso, elapsed, msg = result
            print(f"{msg} ({elapsed}s)")
            if idx < total - 1:
                await asyncio.sleep(DELAY_ENTRE_JOGOS)
            return result

    async with httpx.AsyncClient() as client:
        # Verifica se o servidor está no ar
        try:
            r = await client.get(f"{base_url}/health", timeout=10)
            print(f"Health check: {r.json()}\n")
        except Exception as e:
            print(f"ERRO: servidor não acessível em {base_url}\n{e}")
            sys.exit(1)

        tasks = [
            cachear_com_limite(client, jogo, idx)
            for idx, jogo in enumerate(jogos_ordenados)
        ]
        resultados = await asyncio.gather(*tasks)

    # Resumo
    ok    = sum(1 for _, s, _, _ in resultados if s)
    falha = sum(1 for _, s, _, _ in resultados if not s)
    tempos_ok = [t for _, s, t, _ in resultados if s]
    media = round(sum(tempos_ok) / len(tempos_ok), 1) if tempos_ok else 0

    print(f"\n{'='*60}")
    print(f"  RESULTADO FINAL")
    print(f"  [OK]   Sucesso : {ok}/{total}")
    print(f"  [FAIL] Falha   : {falha}/{total}")
    print(f"  Tempo médio por jogo: {media}s")
    print(f"{'='*60}")

    if falha:
        print("\nJogos com falha:")
        for slug, s, t, msg in resultados:
            if not s:
                print(f"  - {slug}: {msg} ({t}s)")


if __name__ == "__main__":
    asyncio.run(main())
