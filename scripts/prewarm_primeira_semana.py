"""
Pré-aquece o cache de stats para todos os jogos da primeira rodada da Copa 2026.

Busca dados reais da API-Football (forma recente, stats históricas, H2H) e
calcula as Camadas 1-4B para cada jogo. O resultado fica salvo em
seeds/cache_partidas.json e serve imediatamente para /zebras /bingo /odds-baixa.

Uso:
  API_FOOTBALL_KEY=xxx ANTHROPIC_API_KEY=xxx python scripts/prewarm_primeira_semana.py [--dias 14]

Flags:
  --dias N    Pré-aquece jogos nos próximos N dias (padrão: 14)
  --force     Re-calcula mesmo se o cache já tiver dados frescos
  --dry-run   Mostra quais jogos seriam processados sem chamar APIs
"""
import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# Carrega .env se existir
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import warnings
warnings.filterwarnings("ignore")


async def main(dias: int, force: bool, dry_run: bool) -> None:
    from app.agents.football_agent import buscar_detalhe_partida, _JOGOS
    from app.agents.ia_agent import calcular_stats
    from app.cache import static_cache

    # Carrega cache existente do disco
    n_carregados = static_cache.load_from_disk()
    print(f"Cache carregado: {n_carregados} entradas existentes\n")

    agora      = datetime.now(timezone.utc)
    max_horas  = dias * 24
    candidatos = []

    for jogo in _JOGOS:
        slug = jogo["slug"]
        try:
            dt = datetime.fromisoformat(jogo["data_hora_utc"].replace("Z", "+00:00"))
            horas = (dt - agora).total_seconds() / 3600
        except Exception:
            continue

        if horas < -0.5 or horas > max_horas:
            continue

        status = "NOVO"
        if not force and static_cache.get_stats(slug) is not None:
            status = "CACHE"

        candidatos.append({
            "slug":    slug,
            "dt":      dt,
            "horas":   horas,
            "casa":    jogo["time_casa"],
            "fora":    jogo["time_fora"],
            "status":  status,
        })

    candidatos.sort(key=lambda x: x["dt"])

    print(f"Jogos nos próximos {dias} dias: {len(candidatos)}")
    ja_em_cache = sum(1 for c in candidatos if c["status"] == "CACHE")
    a_calcular  = sum(1 for c in candidatos if c["status"] == "NOVO")
    print(f"  Já em cache:   {ja_em_cache}")
    print(f"  A calcular:    {a_calcular}")
    print()

    if dry_run:
        for c in candidatos:
            dias_ate = c["horas"] / 24
            icon = "✓" if c["status"] == "CACHE" else "○"
            print(f"  {icon} {c['dt'].strftime('%d/%m %H:%M')} | {c['casa']:22s} x {c['fora']:22s} [{c['status']}]  (+{dias_ate:.1f}d)")
        print("\n[dry-run] Nenhuma API foi chamada.")
        return

    aquecidos = 0
    erros     = 0
    t_inicio  = time.time()

    for i, c in enumerate(candidatos):
        slug = c["slug"]
        icon = "✓" if c["status"] == "CACHE" else f"[{i+1}/{len(candidatos)}]"

        if c["status"] == "CACHE":
            print(f"  ✓ CACHE  | {c['casa']} x {c['fora']}")
            continue

        print(f"  ○ BUSCA  | {c['casa']} x {c['fora']} ... ", end="", flush=True)

        t0 = time.time()
        try:
            # Busca dados reais da API-Football (usa cache interno de 8h)
            partida = await buscar_detalhe_partida(slug)
            if partida is None:
                print("sem dados na API")
                erros += 1
                continue

            # Calcula Camadas 1-4B
            stats = await calcular_stats(partida)
            dt_ms = (time.time() - t0) * 1000

            vc   = stats.modelo_gols.prob_vitoria_casa
            vf   = stats.modelo_gols.prob_vitoria_fora
            emp  = stats.modelo_gols.prob_empate
            insuf = "⚠️ dados parciais" if partida.dados_insuficientes else ""
            zebra = " 🚨ZEBRA" if stats.contexto.zebra_alerta else ""
            print(f"OK {dt_ms:.0f}ms | {vc:.0f}%/{emp:.0f}%/{vf:.0f}% {insuf}{zebra}")
            aquecidos += 1

        except Exception as e:
            print(f"ERRO: {e}")
            erros += 1

        # Pequena pausa para não sobrecarregar a API-Football
        await asyncio.sleep(1.5)

    t_total = time.time() - t_inicio
    print(f"\n{'='*60}")
    print(f"Concluído em {t_total:.1f}s")
    print(f"  Calculados: {aquecidos} | Já em cache: {ja_em_cache} | Erros: {erros}")

    s = static_cache.summary()
    print(f"\nCache final: {s['com_stats']} com stats | {s['total']} total | {s['arquivo']}")

    # Zebras detectadas
    zebras = []
    for slug_key, entry in static_cache._store.items():
        stats_entry = entry.get("stats") or {}
        stats_dict  = stats_entry.get("dados") if stats_entry else None
        if stats_dict and (stats_dict.get("contexto") or {}).get("zebra_alerta"):
            ctx = stats_dict["contexto"]
            zebras.append(f"  🚨 {slug_key}: {ctx.get('zebra_descricao', '')[:80]}")

    if zebras:
        print(f"\n🚨 Zebras detectadas ({len(zebras)}):")
        for z in zebras:
            print(z)
    else:
        print("\nNenhuma zebra detectada (normal — odds reais aumentam as chances de detectar).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pré-aquece cache da Copa 2026")
    parser.add_argument("--dias",    type=int, default=14, help="Janela em dias (padrão 14)")
    parser.add_argument("--force",   action="store_true",  help="Re-calcula mesmo com cache fresco")
    parser.add_argument("--dry-run", action="store_true",  help="Mostra jogos sem chamar APIs")
    args = parser.parse_args()

    if not os.getenv("API_FOOTBALL_KEY") and not args.dry_run:
        print("AVISO: API_FOOTBALL_KEY não configurada — dados serão limitados (só Elo fallback)")
        print("       Para dados completos: API_FOOTBALL_KEY=xxx python scripts/prewarm_primeira_semana.py\n")

    asyncio.run(main(args.dias, args.force, args.dry_run))
