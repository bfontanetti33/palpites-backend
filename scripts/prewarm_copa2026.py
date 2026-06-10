"""
scripts/prewarm_copa2026.py — Prewarm final Copa 2026 com logging detalhado.

Popula seeds/cache_partidas.json com stats de todos os jogos da janela.
Loga: quota API-Football a cada 5 jogos, jogadores_analisados por time,
e roda Teste de Fogo ao final (Marrocos, Hakimi, Casemiro, Bruno Fernandes).

Uso:
  py scripts/prewarm_copa2026.py             # 30 dias (cobre fase de grupos)
  py scripts/prewarm_copa2026.py --dias 10   # só Semana 1
  py scripts/prewarm_copa2026.py --force     # re-calcula mesmo com cache fresco
  py scripts/prewarm_copa2026.py --dry-run   # lista jogos sem chamar API
"""
import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import warnings
warnings.filterwarnings("ignore")

SEP  = "─" * 80
SEP2 = "═" * 80


async def _quota_atual() -> int | None:
    """Consulta a quota restante na API-Football via /status."""
    import httpx
    key = os.getenv("API_FOOTBALL_KEY", "")
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(
                "https://v3.football.api-sports.io/status",
                headers={"x-apisports-key": key},
            )
            data = r.json()
            sub = data.get("response", {}).get("requests", {})
            limit = sub.get("limit_day", 0)
            used  = sub.get("current", 0)
            return limit - used
    except Exception:
        return None


def _jogadores_info(partida_dict: dict) -> list[str]:
    """Extrai linha de log de jogadores_analisados para cada time."""
    linhas = []
    for key, label in [("jogadores_destaque_casa", "casa"),
                       ("jogadores_destaque_fora", "fora")]:
        jd = partida_dict.get(key) or {}
        time_nome   = jd.get("time_nome", "?")
        analisados  = jd.get("jogadores_analisados", 0)
        total_jogs  = len(jd.get("jogadores", []))
        dados_insuf = jd.get("dados_insuficientes", False)
        flag = " ⚠️ dados_insuf" if dados_insuf else ""
        linhas.append(
            f"      {label}: {time_nome:<22} "
            f"jogadores_analisados={analisados}/{total_jogs}{flag}"
        )
    return linhas


async def main(dias: int, force: bool, dry_run: bool) -> None:
    from app.agents.football_agent import buscar_detalhe_partida, _JOGOS
    from app.agents.ia_agent import calcular_stats
    from app.cache import static_cache
    from app.agents.players_agent import buscar_jogadores_destaque as _pj

    n_carregados = static_cache.load_from_disk()
    print(f"{SEP}")
    print(f"  PREWARM COPA 2026 — janela: {dias} dias")
    print(f"  Cache carregado do disco: {n_carregados} entradas")
    print(SEP)

    agora     = datetime.now(timezone.utc)
    max_horas = dias * 24
    candidatos = []

    for jogo in _JOGOS:
        slug = jogo["slug"]
        try:
            dt    = datetime.fromisoformat(jogo["data_hora_utc"].replace("Z", "+00:00"))
            horas = (dt - agora).total_seconds() / 3600
        except Exception:
            continue
        if horas < -0.5 or horas > max_horas:
            continue
        status = "CACHE" if (not force and static_cache.get_partida(slug) is not None) else "NOVO"
        candidatos.append({"slug": slug, "dt": dt, "horas": horas,
                           "casa": jogo["time_casa"], "fora": jogo["time_fora"],
                           "status": status})

    candidatos.sort(key=lambda x: x["dt"])
    a_calcular = [c for c in candidatos if c["status"] == "NOVO"]
    ja_cache   = [c for c in candidatos if c["status"] == "CACHE"]

    print(f"\nJogos na janela: {len(candidatos)}")
    print(f"  Já em cache: {len(ja_cache)}")
    print(f"  A calcular:  {len(a_calcular)}")
    print()

    if dry_run:
        for c in candidatos:
            icon = "✓" if c["status"] == "CACHE" else "○"
            print(f"  {icon} {c['dt'].strftime('%d/%m %H:%M')} | "
                  f"{c['casa']:<22} x {c['fora']:<22} [{c['status']}]  "
                  f"(+{c['horas']/24:.1f}d)")
        print("\n[dry-run] Nenhuma API foi chamada.")
        return

    # Quota inicial
    quota_inicio = await _quota_atual()
    print(f"  Quota API-Football inicial: {quota_inicio or 'indisponível'}")
    print()

    # Warm-up: pausa antes do jogo 1 para garantir janela de rate limit limpa.
    # O burst de cold-start (asyncio.gather dispara 15-25 requests em paralelo)
    # estoura o rate limit da API-Football se a janela já tiver requests recentes.
    if a_calcular:
        print("  Warm-up: aguardando 10s para garantir janela de rate limit limpa...")
        await asyncio.sleep(10)
        print()

    aquecidos      = 0
    erros          = 0
    com_jogadores  = 0   # jogos com jogadores_analisados > 0 em pelo menos 1 lado
    sem_jogadores  = 0   # jogos com 0 analisados nos dois lados
    t_inicio  = time.time()
    quota_checkpoint = quota_inicio

    for i, c in enumerate(candidatos):
        slug = c["slug"]

        if c["status"] == "CACHE":
            print(f"  ✓ CACHE  [{i+1:>2}/{len(candidatos)}] "
                  f"{c['dt'].strftime('%d/%m %H:%M')} | {c['casa']} x {c['fora']}")
            continue

        n_novo = aquecidos + erros + 1
        print(f"\n  ○ BUSCA  [{i+1:>2}/{len(candidatos)}] "
              f"{c['dt'].strftime('%d/%m %H:%M')} | {c['casa']} x {c['fora']}")

        # Pre-warma player stats sequencialmente para evitar contensão do _api_lock global.
        # O _api_lock serializa todos os calls à API-Football (150ms/call). Dois times em
        # asyncio.gather gastam 160s+, estourando o timeout de 60s em buscar_detalhe_partida.
        # Pré-aquecendo sequencialmente, os resultados vão para _stats_cache (TTL 24h) e a
        # chamada interna em buscar_detalhe_partida retorna do cache em < 1s por time.
        if not static_cache.is_player_stats_fresh(slug):
            for nome_time, label in [(c["casa"], "casa"), (c["fora"], "fora")]:
                tp = time.time()
                try:
                    r = await _pj(nome_time)
                    analisados = r.get("jogadores_analisados", 0)
                    print(f"    ↓ players {label} ({nome_time}): {analisados} em {time.time()-tp:.1f}s")
                except Exception as ep:
                    print(f"    ↓ players {label} ({nome_time}): ERRO {ep}")

        t0 = time.time()
        try:
            partida = await buscar_detalhe_partida(slug)
            if partida is None:
                print(f"    → sem dados na API")
                erros += 1
            else:
                stats = await calcular_stats(partida)
                dt_ms = (time.time() - t0) * 1000

                vc   = stats.modelo_gols.prob_vitoria_casa
                vf   = stats.modelo_gols.prob_vitoria_fora
                emp  = stats.modelo_gols.prob_empate
                zebra = " 🚨ZEBRA" if stats.contexto.zebra_alerta else ""
                insuf = " ⚠️parcial" if partida.dados_insuficientes else ""
                print(f"    → OK {dt_ms:.0f}ms | {vc:.0f}%/{emp:.0f}%/{vf:.0f}%{insuf}{zebra}")

                # Loga jogadores_analisados
                pd = partida.model_dump(mode="json")
                for linha in _jogadores_info(pd):
                    print(linha)

                # Monitoramento de qualidade
                jdc_info = (pd.get("jogadores_destaque_casa") or {})
                jdf_info = (pd.get("jogadores_destaque_fora") or {})
                an_c = jdc_info.get("jogadores_analisados", 0)
                an_f = jdf_info.get("jogadores_analisados", 0)
                if an_c > 0 or an_f > 0:
                    com_jogadores += 1
                else:
                    sem_jogadores += 1
                    print(f"    ⚠️⚠️⚠️  ALERTA: 0 jogadores analisados em ambos os times ({c['casa']} + {c['fora']})")
                    print(f"    ⚠️  Verifique causa antes de continuar. Slug: {slug}")

                aquecidos += 1

        except Exception as e:
            print(f"    → ERRO: {e}")
            erros += 1

        # Checkpoint a cada 10 jogos processados (novo)
        processados = aquecidos + erros
        if processados > 0 and processados % 10 == 0:
            pct_ok = round(com_jogadores / processados * 100) if processados else 0
            print(f"\n  {'═'*60}")
            print(f"  CHECKPOINT {processados}/72 jogos processados")
            print(f"  com_jogadores={com_jogadores}  sem_jogadores={sem_jogadores}  ({pct_ok}% ok)")
            print(f"  erros={erros}  aquecidos={aquecidos}")
            print(f"  {'═'*60}\n")

        # Quota a cada 5 jogos calculados
        if (aquecidos + erros) % 5 == 0 and (aquecidos + erros) > 0:
            quota_agora = await _quota_atual()
            gasto = (quota_checkpoint or 0) - (quota_agora or 0)
            print(f"\n  {'─'*60}")
            print(f"  📊 Quota checkpoint — {aquecidos + erros} jogos processados")
            print(f"     Restante: {quota_agora} | Gasto neste bloco: {gasto}")
            print(f"  {'─'*60}\n")
            quota_checkpoint = quota_agora

        await asyncio.sleep(1.5)

    t_total = time.time() - t_inicio
    quota_final = await _quota_atual()
    quota_gasto = (quota_inicio or 0) - (quota_final or 0) if quota_inicio else "?"

    print(f"\n{SEP2}")
    print(f"  PREWARM CONCLUÍDO em {t_total:.1f}s")
    print(f"  Calculados: {aquecidos} | Em cache: {len(ja_cache)} | Erros: {erros}")
    print(f"  com_jogadores: {com_jogadores} | sem_jogadores: {sem_jogadores}")
    print(f"  Quota inicial: {quota_inicio} → final: {quota_final} (gasto: {quota_gasto})")
    print(SEP2)

    s = static_cache.summary()
    print(f"\n  Cache final: {s['com_stats']} com stats | {s['total']} total | {s['arquivo']}")

    # ── TESTE DE FOGO ──────────────────────────────────────────────────────────
    import json
    cache_path = ROOT / "seeds" / "cache_partidas.json"
    try:
        cache_raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"\n  ⚠️  Não foi possível ler cache do disco para Teste de Fogo: {e}")
        return

    print(f"\n{SEP2}")
    print("  TESTE DE FOGO")
    print(SEP2)

    # 1. Marrocos — jogadores_analisados
    print("\n  [1] MARROCOS — jogadores_analisados")
    for slug_key in ["brazil-morocco", "scotland-morocco"]:
        entry = cache_raw.get(slug_key, {})
        pj    = entry.get("partida", entry)
        for key in ["jogadores_destaque_casa", "jogadores_destaque_fora"]:
            jd = pj.get(key) or {}
            if jd.get("time_nome") == "Morocco":
                analisados = jd.get("jogadores_analisados", 0)
                ok = "✅" if analisados > 0 else "❌"
                print(f"      {ok} {slug_key}: jogadores_analisados={analisados}")

    # 2. Hakimi — encontrado com PSG?
    print("\n  [2] HAKIMI — alias PSG funcionou?")
    for slug_key in ["brazil-morocco", "scotland-morocco"]:
        entry = cache_raw.get(slug_key, {})
        pj    = entry.get("partida", entry)
        jd    = pj.get("jogadores_destaque_fora") or {}
        for j in jd.get("jogadores", []):
            if "hakimi" in j.get("nome", "").lower():
                sp90  = j.get("stat_p90")
                clube = j.get("clube", "?")
                label = j.get("stat_label", "?")
                ok    = "✅" if sp90 is not None and label != "caps internacionais" else "⚠️ fallback"
                print(f"      {ok} {slug_key}: {j['nome']} | clube={clube} | "
                      f"stat_label={label} | stat_p90={sp90}")

    # 3-5. Jogadores PL suspeitos — Casemiro, Bruno Fernandes, Nuno Mendes
    print("\n  [3-5] JOGADORES PL — stats corrigidas?")
    alvo = {
        "casemiro":        {"max_gols": 6,  "nota": "MF defensivo"},
        "bruno fernandes": {"max_gols": 10, "nota": "MF ofensivo"},
        "nuno mendes":     {"max_gols": 6,  "nota": "DF lateral PSG"},
    }
    encontrados: dict[str, dict] = {}
    for slug_key, entry in cache_raw.items():
        pj = entry.get("partida", entry)
        for key in ["jogadores_destaque_casa", "jogadores_destaque_fora"]:
            jd = pj.get(key) or {}
            for j in jd.get("jogadores", []):
                nome_lc = j.get("nome", "").lower()
                for chave in alvo:
                    if chave in nome_lc and chave not in encontrados:
                        encontrados[chave] = j

    for chave, meta in alvo.items():
        j = encontrados.get(chave)
        if not j:
            print(f"      ⚠️  {chave}: NÃO encontrado no cache")
            continue
        total = j.get("stat_total", 0)
        sp90  = j.get("stat_p90")
        liga  = j.get("liga_nome", "?")
        label = j.get("stat_label", "?")
        ok_total = total <= meta["max_gols"]
        ok_liga  = "summer series" not in liga.lower()
        flag_t   = "✅" if ok_total else "❌"
        flag_l   = "✅" if ok_liga  else "❌"
        print(f"      {flag_t}{flag_l} {j.get('nome'):<22} | "
              f"stat_total={total} (max={meta['max_gols']}) | "
              f"stat_p90={sp90} | liga='{liga}'")
        if not ok_total:
            print(f"         ⚠️  stat_total={total} > max esperado {meta['max_gols']} — ainda suspeito")
        if not ok_liga:
            print(f"         ❌  liga ainda mostra Summer Series — FIX 2 não aplicou?")

    # 6. Erros 500 (via health check)
    print("\n  [6] ERROS 500 pós-prewarm")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(
                "https://palpites-backend-production.up.railway.app/api/v1/admin/health-check"
            )
            hc = r.json()
            erros_24h = hc.get("erros_24h", "?")
            ultimo    = hc.get("ultimo_erro_500", "nenhum")
            ok = "✅" if erros_24h == 0 else "⚠️"
            print(f"      {ok} erros_24h={erros_24h} | ultimo_erro_500={ultimo}")
    except Exception as e:
        print(f"      ⚠️  health check falhou: {e}")

    print(f"\n{SEP}")
    print("  Prewarm local concluído. Para deployar o cache no Railway:")
    print("    git add seeds/cache_partidas.json")
    print("    git commit -m 'chore: cache prewarm Copa 2026 fase de grupos'")
    print("    git push origin main")
    print(SEP)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias",    type=int, default=30)
    parser.add_argument("--force",   action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.dias, args.force, args.dry_run))
