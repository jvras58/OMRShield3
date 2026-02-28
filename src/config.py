"""
config.py — Parâmetros fixos do cartão SIMUREKA 2026.

Tudo que é específico do layout do cartão fica aqui.
Nenhum omr_template.json necessário.
"""

# ── Layout do cartão ─────────────────────────────────────────────────────────

N_BLOCOS             = 6       # colunas de questões na página
N_QUESTOES_POR_BLOCO = 15      # questões por bloco
N_ALTERNATIVAS       = 5       # A B C D E
ALTERNATIVAS         = list("ABCDE")

# Fração vertical da imagem onde vivem as bolhas (ignora cabeçalho + instruções)
BOLHAS_Y_MIN_FRAC = 0.66   # pula cabeçalho "QUESTÃO/RESPOSTA" (varia ~0.64-0.68)
BOLHAS_Y_MAX_FRAC = 1.00

# ── Detecção HoughCircles ─────────────────────────────────────────────────────

HOUGH_MIN_DIST    = 14    # distância mínima entre centros (px, na imagem 1000px)
HOUGH_PARAM1      = 30    # limiar alto do Canny interno
HOUGH_PARAM2      = 18    # acumulador: menor = detecta mais (mais falsos positivos)
HOUGH_MIN_RADIUS  = 7     # raio mínimo de bolha (px)
HOUGH_MAX_RADIUS  = 15    # raio máximo de bolha (px)

HOUGH_BLUR_KERNEL = (7, 7)    # blur antes do Hough
HOUGH_BLUR_SIGMA  = 1.5

# ── Separadores entre blocos ─────────────────────────────────────────────────

SEP_MIN_GAP_PX    = 6     # gap branco precisa ter pelo menos 6px de largura
SEP_DARK_THR      = 12    # coluna é "escura" se tem > N pixels dark
SEP_PIXEL_THR     = 150   # pixel é "dark" se gray < 150

# ── Leitura de fill ───────────────────────────────────────────────────────────

FILL_RADIUS       = 9     # raio do ROI centrado na bolha (px)
FILL_MARGIN_FRAC  = 0.30  # margem interna: ignora 30% das bordas ao calcular mean

# ── Threshold de detecção ─────────────────────────────────────────────────────

MIN_JUMP_GLOBAL   = 25    # jump mínimo no histograma para definir threshold global
MIN_JUMP_LOCAL    = 25    # jump mínimo local por questão
MAX_UNMARKED_VAL  = 140   # se min(vals) > este valor → questão sem marcação

# ── OCR / CPF ─────────────────────────────────────────────────────────────────

CPF_ROI = (0.0, 0.38, 0.155, 0.185)   # (x0, x1, y0, y1) frações da imagem
MAX_OCR_RETRIES = 3

# ── API ───────────────────────────────────────────────────────────────────────

API_HOST = "0.0.0.0"
API_PORT = 8001          # porta diferente do projeto principal para conviver
