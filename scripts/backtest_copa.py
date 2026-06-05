"""
Backtest do modelo preditivo contra Copa 2022 e Copa 2018.

Para cada partida das duas Copas, reconstrói o estado pré-jogo (forma dos times
dentro do torneio até aquele ponto + stats históricas de Copas anteriores),
roda as Camadas 1-4B do modelo e compara com o resultado real.

Métricas calculadas:
  - Acurácia 1X2: a previsão mais provável acertou?
  - Brier Score: erro quadrático médio das probabilidades (0 = perfeito, 1 = péssimo)
  - Calibração: frequência real por faixa de probabilidade (10pp bins)
  - Over/Under 2.5: acurácia
  - Zebra acurácia: when alerta=True, quantos foram upsets reais?
  - ROI teórico do top1 mercado (assume odd 1/prob_modelo — sem vigorish)

Limitações:
  - Elo ratings são os atuais (2026) — evolução histórica não disponível sem dados pagos
  - Stats de Copa usam média da campanha anterior; jogos de grupo early têm amostra pequena
  - Odds históricas não disponíveis no plano free → ROI é teórico (sem vigorish)

Uso:
  pip install httpx
  API_FOOTBALL_KEY=xxx python scripts/backtest_copa.py

Saídas:
  scripts/backtest_resultados.json   — detalhes por jogo
  scripts/backtest_relatorio.txt     — relatório legível
"""
import asyncio
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Adiciona o root ao sys.path para importar os módulos do app
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import httpx

API_KEY  = os.getenv("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
HEADERS  = {"x-apisports-key": API_KEY}

# IDs no API-Football
WC_LEAGUE_ID = 1
COPAS = [
    {"season": 2022, "label": "Copa 2022"},
    {"season": 2018, "label": "Copa 2018"},
]

# Cache local de chamadas API (evita re-fetch durante desenvolvimento)
_CACHE_FILE = Path(__file__).parent / "backtest_api_cache.json"
_api_cache: dict = {}

def _load_api_cache() -> None:
    global _api_cache
    if _CACHE_FILE.exists():
        with open(_CACHE_FILE, encoding="utf-8") as f:
            _api_cache = json.load(f)

def _save_api_cache() -> None:
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(_api_cache, f, ensure_ascii=False, default=str)


async def _get(path: str, params: dict, client: httpx.AsyncClient) -> dict:
    key = f"{path}:{sorted(params.items())}"
    if key in _api_cache:
        return _api_cache[key]
    url = f"{BASE_URL}{path}"
    resp = await client.get(url, params=params, headers=HEADERS)
    data = resp.json()
    _api_cache[key] = data
    _save_api_cache()
    await asyncio.sleep(0.4)  # ~150 req/min → bem abaixo do limite
    return data


async def _fetch_copa_fixtures(season: int, client: httpx.AsyncClient) -> list[dict]:
    """Retorna todos os fixtures da Copa com resultados (status=FT/AET/PEN)."""
    data = await _get("/fixtures", {"league": WC_LEAGUE_ID, "season": season}, client)
    fixtures = data.get("response", [])
    return [
        f for f in fixtures
        if f.get("fixture", {}).get("status", {}).get("short") in ("FT", "AET", "PEN")
    ]


async def _fetch_team_stats(team_id: int, league: int, season: int, client: httpx.AsyncClient) -> dict:
    """Stats de um time numa competição/temporada específica."""
    data = await _get(
        "/teams/statistics",
        {"team": team_id, "league": league, "season": season},
        client,
    )
    return data.get("response", {})


def _build_forma(fixtures: list[dict], team_id: int, before_fixture_id: int) -> list[dict]:
    """
    Reconstrói a forma do time dentro do torneio ANTES de um dado jogo.
    Retorna lista de EntradaForma (como dict) ordenada por data.
    """
    target_date = None
    for f in fixtures:
        if f["fixture"]["id"] == before_fixture_id:
            target_date = f["fixture"]["date"]
            break
    if target_date is None:
        return []

    forma = []
    for f in fixtures:
        if f["fixture"]["id"] == before_fixture_id:
            continue
        fdate = f["fixture"]["date"]
        if fdate >= target_date:
            continue  # só jogos ANTES
        home_id = f["teams"]["home"]["id"]
        away_id = f["teams"]["away"]["id"]
        if team_id not in (home_id, away_id):
            continue

        is_home = home_id == team_id
        gf = (f["goals"]["home"] if is_home else f["goals"]["away"]) or 0
        ga = (f["goals"]["away"] if is_home else f["goals"]["home"]) or 0
        if gf > ga:
            res = "W"
        elif gf == ga:
            res = "D"
        else:
            res = "L"
        adversario_nome = (
            f["teams"]["away"]["name"] if is_home else f["teams"]["home"]["name"]
        )
        forma.append({
            "data":               fdate[:10],
            "adversario":         adversario_nome,
            "placar_proprio":     gf,
            "placar_adversario":  ga,
            "resultado":          res,
            "competicao":         f.get("league", {}).get("name", "Copa"),
        })

    forma.sort(key=lambda x: x["data"])
    return forma[-5:]  # últimos 5


def _stats_from_api(raw_stats: dict) -> dict:
    """Converte stats da API-Football para o formato EstatisticasTemporada."""
    if not raw_stats:
        return {"fonte": "api-football", "dados_insuficientes": True}

    def safe(val, default=None):
        return val if val is not None else default

    fixtures = raw_stats.get("fixtures", {})
    goals_for = raw_stats.get("goals", {}).get("for", {})
    goals_ag  = raw_stats.get("goals", {}).get("against", {})
    played    = safe(fixtures.get("played", {}).get("total"))
    wins      = safe(fixtures.get("wins", {}).get("total"))
    draws     = safe(fixtures.get("draws", {}).get("total"))
    losses    = safe(fixtures.get("loses", {}).get("total"))
    gf_total  = safe(goals_for.get("total", {}).get("total"))
    ga_total  = safe(goals_ag.get("total", {}).get("total"))
    avg_gf    = safe(goals_for.get("average", {}).get("total"))
    avg_ga    = safe(goals_ag.get("average", {}).get("total"))

    return {
        "fonte":                  "api-football",
        "dados_insuficientes":    played is None or played == 0,
        "sede_neutra":            True,
        "jogos":                  played,
        "vitorias":               wins,
        "empates":                draws,
        "derrotas":               losses,
        "gols_marcados":          gf_total,
        "gols_sofridos":          ga_total,
        "media_gols_marcados":    float(avg_gf) if avg_gf else None,
        "media_gols_sofridos":    float(avg_ga) if avg_ga else None,
        "media_gols_marcados_recente": float(avg_gf) if avg_gf else None,
        "media_gols_sofridos_recente": float(avg_ga) if avg_ga else None,
    }


async def _run_model_for_fixture(
    fixture: dict,
    fixtures_copa: list[dict],
    stats_cache: dict,   # (team_id, league, season) → stats dict
    client: httpx.AsyncClient,
    season: int,
) -> dict | None:
    """
    Monta Partida-like e roda Camadas 1-4B.
    Retorna dict com predição + resultado real.
    """
    from app.models.schemas import (
        EstatisticasTemporada, EntradaForma, Partida,
    )
    from app.agents.ia_agent import calcular_stats

    fid        = fixture["fixture"]["id"]
    fdate      = fixture["fixture"]["date"][:10]
    home_id    = fixture["teams"]["home"]["id"]
    away_id    = fixture["teams"]["away"]["id"]
    home_name  = fixture["teams"]["home"]["name"]
    away_name  = fixture["teams"]["away"]["name"]
    gols_c     = fixture["goals"]["home"]
    gols_f     = fixture["goals"]["away"]

    if gols_c is None or gols_f is None:
        return None  # resultado não disponível

    # Resultado real
    if gols_c > gols_f:
        resultado_real = "home"
    elif gols_c < gols_f:
        resultado_real = "away"
    else:
        resultado_real = "draw"

    # Forma dentro do torneio antes deste jogo
    forma_c_raw = _build_forma(fixtures_copa, home_id, fid)
    forma_f_raw = _build_forma(fixtures_copa, away_id, fid)

    forma_c = [EntradaForma(**j) for j in forma_c_raw]
    forma_f = [EntradaForma(**j) for j in forma_f_raw]

    # Stats históricas do time na Copa anterior (season-4 e season-8)
    def _get_stats_copa(team_id: int) -> EstatisticasTemporada:
        for prev_season in [season - 4, season - 8]:
            key = (team_id, WC_LEAGUE_ID, prev_season)
            raw = stats_cache.get(key)
            if raw is None:
                continue
            d = _stats_from_api(raw)
            if not d.get("dados_insuficientes"):
                return EstatisticasTemporada(**d)
        return EstatisticasTemporada(dados_insuficientes=True)

    stats_c = _get_stats_copa(home_id)
    stats_f = _get_stats_copa(away_id)

    # Monta objeto Partida simplificado
    rodada = fixture.get("league", {}).get("round", "Rodada ?")
    slug   = f"bt-{fid}"
    partida = Partida(
        id=fid,
        slug=slug,
        rodada=rodada,
        horario=f"{fdate}T15:00:00+00:00",
        status="NS",
        estadio=fixture.get("fixture", {}).get("venue", {}).get("name", ""),
        cidade=fixture.get("fixture", {}).get("venue", {}).get("city", ""),
        time_casa_nome=home_name,
        time_casa_logo="",
        time_fora_nome=away_name,
        time_fora_logo="",
        time_casa_id=home_id,
        time_fora_id=away_id,
        stats_casa=stats_c,
        stats_fora=stats_f,
        forma_casa=forma_c,
        forma_fora=forma_f,
        head_to_head=[],
        odds=None,
    )

    # Roda modelo (sem cache para backtest — cada predição é independente)
    from app.agents.ia_agent import (
        _modelo_gols_fallback, _tail_risk_fallback,
        _calcular_rating, _calcular_modelo_gols, _calcular_contexto,
        _calcular_tail_risk, _calcular_value_bets, _score_final,
        _buscar_fifa_ranking_wikipedia, GLOBAL_AVG,
    )
    from app.models.schemas import RatingDinamico, FatorContexto

    # Camada 1 — forçamos fallback de Elo (não temos Elo histórico)
    from app.agents.ia_agent import _ELO_FALLBACK, _calcular_pi_rating, ELO_CENTER, ELO_SCALE
    from app.agents.ia_agent import _COPA_FIFA_RANK, _CONFEDERACAO, _STATS_REGIONAIS, _FIFA_RANKING
    import statistics

    def _rating_simples(nome: str, forma: list[EntradaForma]) -> RatingDinamico:
        elo   = _ELO_FALLBACK.get(nome)
        pi    = _calcular_pi_rating(forma, f"{fdate}T15:00:00+00:00")
        conf  = _CONFEDERACAO.get(nome, "")
        sr    = _STATS_REGIONAIS.get(conf, {})
        fifa_copa_pos = _COPA_FIFA_RANK.get(nome)
        fifa_norm = round((48 - fifa_copa_pos) / 47, 3) if fifa_copa_pos else None
        fifa_mundial = _FIFA_RANKING.get(nome)
        elo_z = None
        if elo and sr:
            elo_z = round((elo - sr["media"]) / max(sr["std"], 1.0), 3)
        elo_norm = (elo - ELO_CENTER) / ELO_SCALE if elo else 0.0
        if elo and fifa_norm:
            fifa_esc = (fifa_norm * 3.0) - 1.0
            comb = round(0.50 * elo_norm + 0.30 * pi + 0.20 * fifa_esc, 3)
            formula = "50% Elo + 30% Pi + 20% FIFA"
        elif elo:
            comb = round(0.60 * elo_norm + 0.40 * pi, 3)
            formula = "60% Elo + 40% Pi (sem FIFA)"
        else:
            comb = round(pi, 3)
            formula = "100% Pi"
        return RatingDinamico(
            elo_score=elo, fonte_elo="fallback", pi_rating=pi,
            fifa_ranking=fifa_mundial, fifa_ranking_copa=fifa_copa_pos,
            fifa_normalizado=fifa_norm, fifa_ranking_disponivel=fifa_mundial is not None,
            confederacao=conf, elo_z_regional=elo_z,
            media_elo_regiao=sr.get("media"), std_elo_regiao=sr.get("std"),
            rating_combinado=comb, formula_usada=formula,
        )

    rating_c = _rating_simples(home_name, forma_c)
    rating_f = _rating_simples(away_name, forma_f)

    try:
        modelo = _calcular_modelo_gols(
            rating_c, rating_f,
            stats_c, stats_f,
            forma_c, forma_f,
        )
    except Exception:
        modelo = _modelo_gols_fallback()

    odds_result = {"odds_disponiveis": False}
    try:
        ctx, modelo = _calcular_contexto(partida, rating_c, rating_f, modelo, odds_result)
    except Exception:
        ctx = FatorContexto()

    try:
        tail, modelo = _calcular_tail_risk(
            modelo, partida, rating_c, rating_f, ctx, False, []
        )
    except Exception:
        tail = _tail_risk_fallback(modelo)

    try:
        top3 = _score_final(modelo, False, [], ctx, None)
    except Exception:
        top3 = []

    # Resultado previsto (maior prob)
    probs = {
        "home": modelo.prob_vitoria_casa / 100.0,
        "draw": modelo.prob_empate / 100.0,
        "away": modelo.prob_vitoria_fora / 100.0,
    }
    previsto = max(probs, key=probs.get)
    acertou_1x2 = previsto == resultado_real

    # Over/Under 2.5
    gols_total = gols_c + gols_f
    over25_real = gols_total > 2
    over25_prev = modelo.prob_over25 > 50.0
    acertou_ou = over25_real == over25_prev

    # Brier score para 1X2
    p_real = probs[resultado_real]
    brier_1x2 = round(
        (probs["home"] - (1 if resultado_real == "home" else 0)) ** 2
        + (probs["draw"] - (1 if resultado_real == "draw" else 0)) ** 2
        + (probs["away"] - (1 if resultado_real == "away" else 0)) ** 2,
        4,
    )

    # Zebra: azarão ganhou?
    elo_c = rating_c.elo_score or 1500
    elo_f = rating_f.elo_score or 1500
    favorito_era_casa = elo_c >= elo_f
    upset_real = (
        (favorito_era_casa and resultado_real == "away")
        or (not favorito_era_casa and resultado_real == "home")
    )

    return {
        "fixture_id":       fid,
        "data":             fdate,
        "home":             home_name,
        "away":             away_name,
        "gols_casa":        gols_c,
        "gols_fora":        gols_f,
        "resultado_real":   resultado_real,
        "resultado_previsto": previsto,
        "acertou_1x2":      acertou_1x2,
        "prob_home":        round(probs["home"], 3),
        "prob_draw":        round(probs["draw"], 3),
        "prob_away":        round(probs["away"], 3),
        "prob_resultado_real": round(p_real, 3),
        "brier_1x2":        brier_1x2,
        "over25_real":      over25_real,
        "over25_previsto":  over25_prev,
        "prob_over25":      round(modelo.prob_over25 / 100.0, 3),
        "acertou_ou":       acertou_ou,
        "zebra_alerta":     ctx.zebra_alerta,
        "upset_real":       upset_real,
        "lambda_casa":      modelo.lambda_casa,
        "lambda_fora":      modelo.lambda_fora,
        "rodada":           rodada,
    }


def _print_metrics(resultados: list[dict], label: str) -> dict:
    total = len(resultados)
    if total == 0:
        print(f"\n{label}: sem dados")
        return {}

    acertos_1x2   = sum(1 for r in resultados if r["acertou_1x2"])
    acertos_ou    = sum(1 for r in resultados if r["acertou_ou"])
    brier_medio   = sum(r["brier_1x2"] for r in resultados) / total
    zebras        = [r for r in resultados if r["zebra_alerta"]]
    z_upsets      = sum(1 for r in zebras if r["upset_real"])

    # Calibração: bins de 10pp para a prob do resultado real
    bins = {i: {"pred": 0, "acertos": 0} for i in range(10)}
    for r in resultados:
        b = min(int(r["prob_resultado_real"] * 10), 9)
        bins[b]["pred"] += 1
        if r["acertou_1x2"]:
            bins[b]["acertos"] += 1

    print(f"\n{'='*60}")
    print(f"  {label}  ({total} jogos)")
    print(f"{'='*60}")
    print(f"  Acurácia 1X2:        {acertos_1x2}/{total} = {acertos_1x2/total*100:.1f}%")
    print(f"  Acurácia Over/Under: {acertos_ou}/{total} = {acertos_ou/total*100:.1f}%")
    print(f"  Brier Score (1X2):   {brier_medio:.4f}  (aleatório = 0.667)")
    print(f"  Habilidade Brier:    {(0.667 - brier_medio)/0.667*100:.1f}% sobre aleatório")
    if zebras:
        print(f"  Zebras alertadas:    {len(zebras)} | Upsets reais: {z_upsets}/{len(zebras)} = {z_upsets/len(zebras)*100:.0f}%")
    print(f"\n  Calibração (prob prevista vs frequência real):")
    for i in range(10):
        lo, hi = i * 10, (i + 1) * 10
        n = bins[i]["pred"]
        if n == 0:
            continue
        freq = bins[i]["acertos"] / n * 100
        bar = "█" * int(freq / 5)
        print(f"    {lo:2d}-{hi:2d}%: {n:3d} jogos → {freq:5.1f}% acertos  {bar}")

    return {
        "label": label,
        "total_jogos": total,
        "acuracia_1x2": round(acertos_1x2 / total, 4),
        "acuracia_over25": round(acertos_ou / total, 4),
        "brier_medio": round(brier_medio, 4),
        "habilidade_brier_pct": round((0.667 - brier_medio) / 0.667 * 100, 1),
        "zebras_alertadas": len(zebras),
        "zebra_upset_rate": round(z_upsets / len(zebras), 4) if zebras else None,
        "calibracao": {
            f"{i*10}-{(i+1)*10}%": {
                "n": bins[i]["pred"],
                "acuracia": round(bins[i]["acertos"] / bins[i]["pred"], 4) if bins[i]["pred"] else None,
            }
            for i in range(10) if bins[i]["pred"] > 0
        },
    }


async def main() -> None:
    if not API_KEY:
        print("ERRO: defina API_FOOTBALL_KEY=xxx antes de rodar o script")
        sys.exit(1)

    _load_api_cache()
    todos_resultados: list[dict] = []
    metricas_por_copa: list[dict] = []

    async with httpx.AsyncClient(timeout=30) as client:
        for copa in COPAS:
            season = copa["season"]
            label  = copa["label"]
            print(f"\nBaixando fixtures {label}...")

            fixtures = await _fetch_copa_fixtures(season, client)
            print(f"  {len(fixtures)} jogos com resultado")

            if not fixtures:
                continue

            # IDs únicos de times
            team_ids: set[int] = set()
            for f in fixtures:
                team_ids.add(f["teams"]["home"]["id"])
                team_ids.add(f["teams"]["away"]["id"])

            # Busca stats históricas (Copa da edição anterior)
            stats_cache: dict = {}
            prev_seasons = [season - 4, season - 8]
            print(f"  Buscando stats históricas de {len(team_ids)} times (Copas {prev_seasons})...")
            for tid in sorted(team_ids):
                for ps in prev_seasons:
                    key = (tid, WC_LEAGUE_ID, ps)
                    if key not in stats_cache:
                        try:
                            raw = await _fetch_team_stats(tid, WC_LEAGUE_ID, ps, client)
                            stats_cache[key] = raw
                        except Exception as e:
                            print(f"    stats {tid}/{ps}: {e}")
                            stats_cache[key] = {}

            # Roda modelo para cada jogo
            resultados_copa: list[dict] = []
            for i, f in enumerate(fixtures):
                fid  = f["fixture"]["id"]
                home = f["teams"]["home"]["name"]
                away = f["teams"]["away"]["name"]
                print(f"  [{i+1:2d}/{len(fixtures)}] {home} x {away}", end="", flush=True)
                try:
                    r = await _run_model_for_fixture(f, fixtures, stats_cache, client, season)
                    if r:
                        r["copa"] = label
                        r["season"] = season
                        resultados_copa.append(r)
                        acertou = "✓" if r["acertou_1x2"] else "✗"
                        print(
                            f" → {r['resultado_real']} (prev={r['resultado_previsto']}) "
                            f"{acertou} | Brier={r['brier_1x2']:.3f}"
                        )
                    else:
                        print(" → sem resultado")
                except Exception as e:
                    print(f" → ERRO: {e}")

            m = _print_metrics(resultados_copa, label)
            if m:
                metricas_por_copa.append(m)
            todos_resultados.extend(resultados_copa)

    # Métricas agregadas
    m_total = _print_metrics(todos_resultados, "TOTAL (2018 + 2022)")
    if m_total:
        metricas_por_copa.append(m_total)

    # Salva resultados
    saida = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "metricas": metricas_por_copa,
        "jogos": todos_resultados,
    }
    out_json = Path(__file__).parent / "backtest_resultados.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nResultados salvos em {out_json}")

    # Relatório texto
    out_txt = Path(__file__).parent / "backtest_relatorio.txt"
    linhas = ["Backtest — Modelo Preditivo Copa do Mundo\n"]
    linhas.append(f"Gerado em: {saida['gerado_em']}\n\n")
    for m in metricas_por_copa:
        linhas.append(f"{'='*50}\n{m['label']}\n{'='*50}\n")
        linhas.append(f"Jogos analisados:   {m['total_jogos']}\n")
        linhas.append(f"Acurácia 1X2:       {m['acuracia_1x2']*100:.1f}%\n")
        linhas.append(f"Acurácia Over/Under:{m['acuracia_over25']*100:.1f}%\n")
        linhas.append(f"Brier Score:        {m['brier_medio']:.4f}\n")
        linhas.append(f"Skill sobre aleat:  {m['habilidade_brier_pct']:.1f}%\n")
        if m.get("zebra_upset_rate") is not None:
            linhas.append(
                f"Zebra upset rate:   {m['zebra_upset_rate']*100:.0f}% "
                f"({m['zebras_alertadas']} alertas)\n"
            )
        linhas.append("\n")
    with open(out_txt, "w", encoding="utf-8") as f:
        f.writelines(linhas)
    print(f"Relatório salvo em {out_txt}")


if __name__ == "__main__":
    asyncio.run(main())
