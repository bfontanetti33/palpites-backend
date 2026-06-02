from pydantic import BaseModel


# ── Sub-modelos de partida ────────────────────────────────────────────────────

class PerformanceLocal(BaseModel):
    jogos: int | None = None
    vitorias: int | None = None
    empates: int | None = None
    derrotas: int | None = None
    gols_marcados: int | None = None
    gols_sofridos: int | None = None
    media_gols_marcados: float | None = None
    media_gols_sofridos: float | None = None


class EstatisticasTemporada(BaseModel):
    fonte: str = ""
    dados_insuficientes: bool = False
    sede_neutra: bool = True
    jogos: int | None = None
    vitorias: int | None = None
    empates: int | None = None
    derrotas: int | None = None
    gols_marcados: int | None = None
    gols_sofridos: int | None = None
    media_gols_marcados: float | None = None
    media_gols_sofridos: float | None = None
    casa: PerformanceLocal | None = None
    fora: PerformanceLocal | None = None
    clean_sheets: int | None = None
    media_amarelos: float | None = None
    media_vermelhos: float | None = None
    penaltis_marcados: int | None = None
    penaltis_total: int | None = None
    # calculados da forma recente (últimos 10 jogos)
    jogos_forma: int | None = None
    btts_pct: int | None = None
    over25_pct: int | None = None
    under25_pct: int | None = None
    media_gols_marcados_recente: float | None = None
    media_gols_sofridos_recente: float | None = None


class EntradaForma(BaseModel):
    data: str
    adversario: str
    placar_proprio: int | None = None
    placar_adversario: int | None = None
    resultado: str                        # "W", "D", "L"
    competicao: str


class PlacarProvavel(BaseModel):
    placar: str
    probabilidade: float


class Probabilidades(BaseModel):
    vitoria_casa: int
    empate: int
    vitoria_fora: int
    lambda_casa: float
    lambda_fora: float
    metodo: str = "poisson"
    dados_insuficientes: bool = False


class Arbitro(BaseModel):
    nome: str
    jogos_apitados: int | None = None
    media_amarelos: float | None = None
    media_vermelhos: float | None = None
    media_penaltis: float | None = None


# ── Modelos de partida ────────────────────────────────────────────────────────

class PartidaResumo(BaseModel):
    id: int
    slug: str
    rodada: str
    horario: str
    status: str
    estadio: str
    cidade: str
    time_casa_nome: str
    time_casa_logo: str
    time_fora_nome: str
    time_fora_logo: str
    gols_casa: int | None = None
    gols_fora: int | None = None


class Partida(PartidaResumo):
    time_casa_id: int
    time_fora_id: int
    stats_casa: EstatisticasTemporada = EstatisticasTemporada(dados_insuficientes=True)
    stats_fora: EstatisticasTemporada = EstatisticasTemporada(dados_insuficientes=True)
    forma_casa: list[EntradaForma] = []
    forma_fora: list[EntradaForma] = []
    head_to_head: list[dict] = []
    probabilidades: Probabilidades | None = None
    placares_provaveis: list[PlacarProvavel] = []
    arbitro: Arbitro | None = None
    odds: dict | None = None              # odds reais da API (None se indisponíveis)
    dados_insuficientes: bool = False


# ── Modelos do agente estatístico ─────────────────────────────────────────────

class RatingDinamico(BaseModel):
    """Camada 1 — Rating combinado (Elo + Pi-rating)."""
    elo_score: float | None = None        # scraped de eloratings.net
    fonte_elo: str = "indisponível"       # "eloratings.net" ou "fallback" ou "indisponível"
    pi_rating: float = 0.0               # média ponderada de (gols_marcados - gols_sofridos) / global_avg
    rating_combinado: float = 0.0        # 60% Elo normalizado + 40% Pi (ou 100% Pi se sem Elo)


class ModeloGols(BaseModel):
    """Camada 2 — Dixon-Coles + Skellam + probabilidades de mercado."""
    lambda_casa: float
    lambda_fora: float
    # 1X2
    prob_vitoria_casa: float
    prob_empate: float
    prob_vitoria_fora: float
    # Gols
    prob_btts: float
    prob_over15: float
    prob_under15: float
    prob_over25: float
    prob_under25: float
    prob_over35: float
    prob_under35: float
    # Top placares
    top5_placares: list[dict]
    # Skellam (diferença de gols)
    skellam_vitoria: float
    skellam_empate: float
    skellam_derrota: float


class FatorContexto(BaseModel):
    """Camada 4 — fatores contextuais aplicados ao modelo."""
    campo_neutro: bool = True
    fadiga_casa: bool = False
    fadiga_fora: bool = False
    primeira_rodada: bool = False
    zebra_alerta: bool = False
    zebra_descricao: str = ""
    confianca_h2h: float = 1.0
    ajuste_under25_aplicado: float = 0.0


class TailRiskResult(BaseModel):
    """Camada 4B — Tail Risk Engine (Taleb)."""
    # Fat Tail Correction (85% DC + 15% Student-t ν=4)
    prob_vitoria_casa_antes: float
    prob_empate_antes: float
    prob_vitoria_fora_antes: float
    prob_vitoria_casa_depois: float
    prob_empate_depois: float
    prob_vitoria_fora_depois: float
    over25_antes: float
    over25_depois: float
    over35_antes: float
    over35_depois: float
    fat_tail_delta: dict             # {"vitoria_casa": +0.3, ...}

    # Fragility Score (proxy por variância de gols)
    fragility_score_casa: float      # 0-100
    fragility_score_fora: float
    fragility_impacto: str           # "nenhum" / "leve" / "moderado" / "alto"

    # Uncertainty Multiplier
    uncertainty_index: float         # 0-100
    uncertainty_fatores: list[str]
    probabilidades_achatadas: bool
    achatamento_alpha: float         # 0.0 = sem achatamento, 0.5 = 50% para 33/33/33

    # Barbell Signal (só se odds disponíveis)
    barbell_sugerido: bool
    barbell_entrada_segura: str | None = None
    barbell_prob_segura: float | None = None
    barbell_entrada_especulativa: str | None = None
    barbell_value_especulativo: float | None = None


class MercadoRecomendado(BaseModel):
    """Camada 4/Score Final — mercado ranqueado."""
    mercado: str
    entrada: str
    prob_dc: float                        # probabilidade do modelo DC (%)
    odd_ref: float | None = None          # odd real da API (None se indisponível)
    value_score: float | None = None      # (prob/100 * odd) - 1 (None se sem odds)
    score_final: float                    # 0-100
    confianca: str                        # Alta / Média / Baixa


# ── Modelos de resposta ───────────────────────────────────────────────────────

class RecomendacaoIA(BaseModel):
    partida_id: int

    # Camada 1
    rating_casa: RatingDinamico
    rating_fora: RatingDinamico

    # Camada 2
    modelo_gols: ModeloGols

    # Camada 3
    odds_disponiveis: bool
    value_bets: list[dict]

    # Camada 4
    contexto: FatorContexto

    # Camada 4B
    tail_risk: TailRiskResult

    top3: list[MercadoRecomendado]

    # Camada 5 — Claude (só narrativa)
    narrativa: str
    resumo_rapido: str
    alertas: list[str]
    analise_completa: str

    # Campos legados (compatibilidade com frontend existente)
    mercado: str
    entrada: str
    confianca: str
    analise: str
    texto_completo: str


class RespostaCopa(BaseModel):
    total: int
    temporada: int
    partidas: list[PartidaResumo]
