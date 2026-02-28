"""
settings/config.py — Parâmetros do cartão SIMUREKA 2026 via Pydantic Settings.

Valores padrão cobrem 100% dos casos sem .env.
Para sobrescrever, crie um arquivo .env na raiz do projeto, ex.:
  HOUGH_PARAM2=20
  API_PORT=8002
"""

from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Layout do cartão ──────────────────────────────────────────────────────

    N_BLOCOS: int = 6  # colunas de questões na página
    N_QUESTOES_POR_BLOCO: int = 15  # questões por bloco
    N_ALTERNATIVAS: int = 5  # A B C D E
    ALTERNATIVAS: ClassVar[list[str]] = list("ABCDE")

    # Fração vertical da imagem onde vivem as bolhas (ignora cabeçalho)
    BOLHAS_Y_MIN_FRAC: float = 0.66  # pula cabeçalho "QUESTÃO/RESPOSTA"
    BOLHAS_Y_MAX_FRAC: float = 1.00

    # ── Detecção HoughCircles ─────────────────────────────────────────────────

    HOUGH_MIN_DIST: int = 14  # distância mínima entre centros (px, em 1000px)
    HOUGH_PARAM1: int = 30  # limiar alto do Canny interno
    HOUGH_PARAM2: int = 18  # acumulador: menor = detecta mais
    HOUGH_MIN_RADIUS: int = 7  # raio mínimo de bolha (px)
    HOUGH_MAX_RADIUS: int = 15  # raio máximo de bolha (px)

    HOUGH_BLUR_KERNEL: ClassVar[tuple[int, int]] = (7, 7)
    HOUGH_BLUR_SIGMA: float = 1.5

    # ── Separadores entre blocos ──────────────────────────────────────────────

    SEP_MIN_GAP_PX: int = 6  # gap branco precisa ter pelo menos 6px
    SEP_DARK_THR: int = 12  # coluna é "escura" se tem > N pixels dark
    SEP_PIXEL_THR: int = 150  # pixel é "dark" se gray < 150

    # ── Leitura de fill ───────────────────────────────────────────────────────

    FILL_RADIUS: int = 9  # raio do ROI centrado na bolha (px)
    FILL_MARGIN_FRAC: float = 0.30  # margem interna: ignora 30% das bordas

    # ── Threshold de detecção ─────────────────────────────────────────────────

    MIN_JUMP_GLOBAL: float = 25.0  # jump mínimo no histograma global
    MIN_JUMP_LOCAL: float = 25.0  # jump mínimo local por questão
    MAX_UNMARKED_VAL: float = 140.0  # min(vals) > este valor → sem marcação

    # ── OCR / CPF ─────────────────────────────────────────────────────────────

    # (x0_frac, x1_frac, y0_frac, y1_frac) — frações da imagem alinhada
    CPF_ROI: ClassVar[tuple[float, float, float, float]] = (0.0, 0.38, 0.155, 0.185)
    MAX_OCR_RETRIES: int = 3

    # ── Cache / Redis ─────────────────────────────────────────────────────────

    REDIS_URL: str = "redis://localhost:6379"
    CACHE_TTL_SECONDS: int = 3600  # job_ids expiram após 1 hora

    # ── API ───────────────────────────────────────────────────────────────────

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8001
    API_TOKEN: str = ""  # Token obrigatório para autenticar requests. Defina no .env.

    # ── Propriedades derivadas ────────────────────────────────────────────────

    @property
    def QUESTOES_POR_DIA(self) -> int:
        return self.N_BLOCOS * self.N_QUESTOES_POR_BLOCO


settings = Settings()
