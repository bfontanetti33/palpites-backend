"""
Registra o resultado real de um jogo da Copa 2026 e compara com a predição do modelo.

Uso:
  python scripts/registrar_resultado.py <slug> <gols_casa> <gols_fora>

Exemplo:
  python scripts/registrar_resultado.py mexico-south-africa 2 1

O script:
  1. Lê a predição do modelo (stats cacheados em seeds/cache_partidas.json)
  2. Compara com o resultado real
  3. Appenda em seeds/historico_predicoes.json
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

HISTORICO_PATH = ROOT / "seeds" / "historico_predicoes.json"
CACHE_PATH     = ROOT / "seeds" / "cache_partidas.json"
SEED_PATH      = ROOT / "seeds" / "copa_2026.json"


def _load(path: Path) -> dict | list:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def main() -> None:
    if len(sys.argv) < 4:
        print("Uso: python registrar_resultado.py <slug> <gols_casa> <gols_fora>")
        sys.exit(1)

    slug      = sys.argv[1]
    gols_casa = int(sys.argv[2])
    gols_fora = int(sys.argv[3])

    if gols_casa > gols_fora:
        resultado_real = "home"
    elif gols_casa < gols_fora:
        resultado_real = "away"
    else:
        resultado_real = "draw"

    # Busca info do jogo no seed
    seed = _load(SEED_PATH)
    jogos = {j["slug"]: j for j in seed.get("jogos", [])}
    jogo = jogos.get(slug)
    if not jogo:
        print(f"ERRO: slug '{slug}' não encontrado no seed")
        sys.exit(1)

    home = jogo["time_casa"]
    away = jogo["time_fora"]
    data = jogo.get("data_hora_utc", "")[:10]

    # Busca predição do cache
    cache = _load(CACHE_PATH)
    entry = cache.get(slug, {})
    stats_entry = entry.get("stats") or {}
    stats = stats_entry.get("dados") if stats_entry else None

    pred: dict = {
        "prob_home": None, "prob_draw": None, "prob_away": None,
        "resultado_previsto": None, "acertou_1x2": None,
        "prob_over25": None, "acertou_ou": None,
        "zebra_alerta": None, "brier_1x2": None,
        "lambda_casa": None, "lambda_fora": None,
    }

    if stats and stats.get("modelo_gols"):
        mg = stats["modelo_gols"]
        ph = round(mg.get("prob_vitoria_casa", 33.3) / 100, 3)
        pd = round(mg.get("prob_empate", 33.3) / 100, 3)
        pa = round(mg.get("prob_vitoria_fora", 33.3) / 100, 3)
        probs = {"home": ph, "draw": pd, "away": pa}
        previsto = max(probs, key=probs.get)
        p_real = probs[resultado_real]
        brier = round(
            (ph - (1 if resultado_real == "home" else 0)) ** 2
            + (pd - (1 if resultado_real == "draw" else 0)) ** 2
            + (pa - (1 if resultado_real == "away" else 0)) ** 2,
            4,
        )
        over25_real = (gols_casa + gols_fora) > 2
        over25_prev = mg.get("prob_over25", 50.0) > 50.0

        pred.update({
            "prob_home":           ph,
            "prob_draw":           pd,
            "prob_away":           pa,
            "resultado_previsto":  previsto,
            "acertou_1x2":         previsto == resultado_real,
            "prob_over25":         round(mg.get("prob_over25", 50.0) / 100, 3),
            "acertou_ou":          over25_real == over25_prev,
            "zebra_alerta":        (stats.get("contexto") or {}).get("zebra_alerta", False),
            "brier_1x2":           brier,
            "lambda_casa":         mg.get("lambda_casa"),
            "lambda_fora":         mg.get("lambda_fora"),
        })

    registro = {
        "registrado_em": datetime.now(timezone.utc).isoformat(),
        "slug":          slug,
        "data":          data,
        "home":          home,
        "away":          away,
        "gols_casa":     gols_casa,
        "gols_fora":     gols_fora,
        "resultado_real": resultado_real,
        **pred,
    }

    historico = _load(HISTORICO_PATH)
    if not isinstance(historico, dict):
        historico = {"jogos": []}
    if "jogos" not in historico:
        historico["jogos"] = []

    # Substitui se já existe (re-registrar corrige erros)
    historico["jogos"] = [j for j in historico["jogos"] if j.get("slug") != slug]
    historico["jogos"].append(registro)
    historico["jogos"].sort(key=lambda x: x.get("data", ""))

    # Recalcula métricas acumuladas
    jogos_com_pred = [j for j in historico["jogos"] if j.get("acertou_1x2") is not None]
    if jogos_com_pred:
        n     = len(jogos_com_pred)
        acc   = sum(1 for j in jogos_com_pred if j["acertou_1x2"]) / n
        acc_ou = sum(1 for j in jogos_com_pred if j.get("acertou_ou")) / n
        brier = sum(j["brier_1x2"] for j in jogos_com_pred) / n
        zebras = [j for j in jogos_com_pred if j.get("zebra_alerta")]
        z_upsets = sum(1 for j in zebras if _was_upset(j))
        historico["metricas_acumuladas"] = {
            "total_jogos":         n,
            "acuracia_1x2":        round(acc, 4),
            "acuracia_over25":     round(acc_ou, 4),
            "brier_medio":         round(brier, 4),
            "habilidade_brier_pct": round((0.667 - brier) / 0.667 * 100, 1),
            "zebras_alertadas":    len(zebras),
            "zebra_upset_rate":    round(z_upsets / len(zebras), 4) if zebras else None,
        }

    _save(HISTORICO_PATH, historico)

    acertou_str = f"✓ ACERTOU" if pred["acertou_1x2"] else f"✗ ERROU (esperava {pred['resultado_previsto']})"
    print(f"{home} {gols_casa}x{gols_fora} {away} — {acertou_str}")
    if jogos_com_pred:
        m = historico["metricas_acumuladas"]
        print(f"Acurácia acumulada: {m['acuracia_1x2']*100:.1f}% ({m['total_jogos']} jogos) | Brier: {m['brier_medio']:.4f}")
    print(f"Salvo em {HISTORICO_PATH}")


def _was_upset(jogo: dict) -> bool:
    prob_h = jogo.get("prob_home", 0.33)
    prob_a = jogo.get("prob_away", 0.33)
    favorito = "home" if prob_h >= prob_a else "away"
    return jogo["resultado_real"] != favorito and jogo["resultado_real"] != "draw"


if __name__ == "__main__":
    main()
