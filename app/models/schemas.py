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
    odds: dict | None = None
    jogadores_destaque_casa: JogadoresDestaque | None = None
    jogadores_destaque_fora: JogadoresDestaque | None = None
    dados_insuficientes: bool = False


# ── Modelos do agente estatístico ─────────────────────────────────────────────

class RatingDinamico(BaseModel):
    """Camada 1 — Rating combinado (Elo + Pi-rating + FIFA Ranking)."""
    # Elo rating
    elo_score: float | None = None        # de eloratings.net (fallback se SPA)
    fonte_elo: str = "indisponível"       # "eloratings.net" | "fallback" | "indisponível"

    # Pi-rating (desempenho recente ponderado)
    pi_rating: float = 0.0

    # FIFA Ranking
    fifa_ranking: int | None = None       # posição no ranking FIFA mundial
    fifa_ranking_copa: int | None = None  # posição entre os 48 times da Copa
    fifa_normalizado: float | None = None # (48 - copa_pos) / 47 → 0.0 a 1.0
    fifa_ranking_disponivel: bool = False

    # Normalização regional
    confederacao: str = ""
    elo_rank_regional: int | None = None  # posição dentro da confederação (na Copa)
    media_elo_regiao: float | None = None
    std_elo_regiao: float | None = None
    elo_z_regional: float | None = None  # z-score dentro da confederação

    # Rating final
    rating_combinado: float = 0.0
    formula_usada: str = ""               # ex: "50% Elo + 30% Pi + 20% FIFA"


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
    home_advantage: bool = False          # True quando país-sede joga em casa
    home_advantage_time: str = ""         # nome do time com vantagem de mando
    home_lambda_boost: float = 0.0        # fator aplicado ao lambda da casa (ex: 1.25)
    away_lambda_penalty: float = 0.0      # fator aplicado ao lambda do visitante (ex: 0.80)
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


class JogadorDestaque(BaseModel):
    nome: str
    posicao: str
    pos_sigla: str                          # GK, DF, MF, FW
    clube: str
    clube_logo: str = ""
    foto_jogador: str = ""
    caps: int | None = None
    categoria: str                          # "goleadores", "assistentes", …
    icone_categoria: str = ""
    stat_label: str                         # "gols/90"
    stat_p90: float | None = None           # P90 bruto
    stat_p90_adj: float | None = None       # P90 × LSS (ajustado pela liga)
    liga_lss: float | None = None           # League Strength Score
    liga_nome: str = ""
    stat_total: int = 0
    minutos_jogados: int = 0
    resumo: str                             # "0.72 gols/90 · 8 gols em 1001 min"
    mercado_sugerido: str = ""
    odd_mercado: float | None = None        # None se odds indisponíveis
    amostra_insuficiente: bool = False      # < 270 min
    dados_insuficientes: bool = False


class JogadoresDestaque(BaseModel):
    time_nome: str
    jogadores: list[JogadorDestaque] = []
    total_squad: int = 0
    fonte_squad: str = ""
    jogadores_analisados: int = 0
    dados_insuficientes: bool = False


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
