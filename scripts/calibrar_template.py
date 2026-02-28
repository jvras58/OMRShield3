"""
calibrar_template.py — Regera o template da faixa "QUESTÃO/RESPOSTA".

Use quando o layout do cartão mudar (novo ano, nova versão do impresso).

Uso:
    uv run python calibrar_template.py <imagem_digitalizada.jpg>

A imagem deve ser uma digitalização (scanner) do cartão em branco ou
preenchido — o que importa é que os 4 marcadores de canto estejam visíveis
e a faixa "QUESTÃO/RESPOSTA" esteja nítida.

O script:
  1. Alinha a imagem (warp via marcadores)
  2. Mostra a imagem alinhada e pede que você clique no início da faixa
  3. Recorta automaticamente a faixa e salva em src/assets/

Dependências: opencv-python, numpy
uv run python calibrar_template.py --help
"""

import sys
import argparse
from pathlib import Path

import cv2
import numpy as np

# ── Localiza o src/ do projeto ─────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
# Procura src/core/alignment.py em: mesma pasta, pai, avô
_found = False
for candidate in [SCRIPT_DIR, SCRIPT_DIR.parent, SCRIPT_DIR.parent.parent, Path.cwd()]:
    if (candidate / "src" / "core" / "alignment.py").exists():
        sys.path.insert(0, str(candidate))
        SCRIPT_DIR = candidate  # usa esse como raiz para salvar o .npy
        _found = True
        break
if not _found:
    print("ERRO: Não encontrei src/core/alignment.py.")
    print(
        "Execute o script a partir da raiz do projeto ou passe --saida explicitamente."
    )
    sys.exit(1)

from src.core.alignment import alinhar  # noqa: E402


# ── Estado do clique ───────────────────────────────────────────────────────
_click_y: int | None = None


def _on_mouse(event, x, y, flags, param):
    global _click_y
    if event == cv2.EVENT_LBUTTONDOWN:
        _click_y = y


def _escolher_y_interativo(img_alinhada: np.ndarray) -> int:
    """Mostra a imagem e pede um clique para definir y_inicio da faixa."""
    global _click_y
    _click_y = None

    # Escala para caber na tela (máx 900px de altura)
    h, w = img_alinhada.shape[:2]
    scale = min(1.0, 900 / h)
    display = cv2.resize(img_alinhada, (int(w * scale), int(h * scale)))

    win = "CALIBRAÇÃO — clique no INÍCIO da faixa QUESTÃO/RESPOSTA (depois pressione ENTER)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, _on_mouse)

    linha_y_display = None

    print("\n→ Janela aberta. Clique no início da faixa 'QUESTÃO/RESPOSTA'.")
    print("  Pressione ENTER para confirmar ou ESC para cancelar.\n")

    while True:
        frame = display.copy()

        if _click_y is not None:
            linha_y_display = _click_y
            cv2.line(
                frame,
                (0, linha_y_display),
                (frame.shape[1], linha_y_display),
                (0, 255, 0),
                2,
            )
            y_real = int(linha_y_display / scale)
            cv2.putText(
                frame,
                f"y={y_real}px  frac={y_real / h:.4f}  [ENTER p/ confirmar]",
                (10, max(linha_y_display - 8, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )

        cv2.imshow(win, frame)
        key = cv2.waitKey(20) & 0xFF

        if key == 13 and linha_y_display is not None:  # ENTER
            break
        if key == 27:  # ESC
            cv2.destroyAllWindows()
            print("Cancelado.")
            sys.exit(0)

    cv2.destroyAllWindows()
    return int(linha_y_display / scale)


def _validar_template(template: np.ndarray, img_alinhada: np.ndarray) -> float:
    """Faz match do template na própria imagem e retorna o score."""
    gray = cv2.cvtColor(img_alinhada, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    x0, x1 = w // 4, 3 * w // 4

    ys = int(h * 0.50)
    ye = int(h * 0.85)
    region = gray[ys:ye, x0:x1]

    result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, max_loc = cv2.minMaxLoc(result)
    y_found = ys + max_loc[1]
    return score, y_found


def main():
    parser = argparse.ArgumentParser(
        description="Recalibra o template da faixa QUESTÃO/RESPOSTA."
    )
    parser.add_argument(
        "imagem",
        help="Caminho para a digitalização canônica do cartão (scanner, alta qualidade)",
    )
    parser.add_argument(
        "--saida",
        default=None,
        help="Caminho de saída do .npy (padrão: src/assets/template_questao_resposta.npy)",
    )
    parser.add_argument(
        "--altura",
        type=int,
        default=60,
        help="Altura em px do recorte do template (padrão: 60)",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Modo automático: detecta o pico sem interface gráfica (útil em servidores)",
    )
    args = parser.parse_args()

    # ── Carrega e alinha ───────────────────────────────────────────────────
    img_path = Path(args.imagem)
    if not img_path.exists():
        print(f"ERRO: Imagem não encontrada: {img_path}")
        sys.exit(1)

    print(f"Carregando: {img_path}")
    img = cv2.imread(str(img_path))
    if img is None:
        print("ERRO: Não foi possível abrir a imagem.")
        sys.exit(1)

    print("Alinhando via marcadores de canto...")
    try:
        alinhada = alinhar(img)
    except ValueError as e:
        print(f"ERRO ao alinhar: {e}")
        sys.exit(1)

    h, w = alinhada.shape[:2]
    print(f"Imagem alinhada: {w}×{h}px")

    # ── Obtém y_inicio ─────────────────────────────────────────────────────
    if args.auto:
        # Detecção automática via pico de densidade
        gray = cv2.cvtColor(alinhada, cv2.COLOR_BGR2GRAY)
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        y_min = int(h * 0.50)
        y_max = int(h * 0.85)
        dark = (gray[y_min:y_max, :] < 150).sum(axis=1).astype(np.float32)
        smooth = np.convolve(dark, np.ones(9) / 9, mode="same")
        peak_idx = int(np.argmax(smooth))
        peak_val = smooth[peak_idx]

        # Sobe até o início do pico
        inicio_idx = peak_idx
        for i in range(peak_idx, 0, -1):
            if smooth[i] < peak_val * 0.15:
                inicio_idx = i
                break
        y_inicio = y_min + inicio_idx
        print(
            f"Modo automático: faixa detectada em y={y_inicio}px (frac={y_inicio / h:.4f})"
        )
    else:
        y_inicio = _escolher_y_interativo(alinhada)
        print(f"Y selecionado: {y_inicio}px (frac={y_inicio / h:.4f})")

    # ── Recorta o template ─────────────────────────────────────────────────
    y_fim = y_inicio + args.altura
    if y_fim > h:
        print(f"AVISO: y_fim={y_fim} excede a altura {h}. Ajustando.")
        y_fim = h

    x0, x1 = w // 4, 3 * w // 4
    template_bgr = alinhada[y_inicio:y_fim, x0:x1]
    template_gray = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
    print(f"Template recortado: {template_gray.shape[1]}×{template_gray.shape[0]}px")

    # ── Valida na própria imagem ───────────────────────────────────────────
    score, y_found = _validar_template(template_gray, alinhada)
    print(f"Validação self-match: score={score:.4f}  y_encontrado={y_found}px")

    if score < 0.85:
        print(f"AVISO: score baixo ({score:.4f}). Verifique se o recorte está correto.")
    else:
        print("✓ Template válido.")

    # ── Salva ──────────────────────────────────────────────────────────────
    if args.saida:
        out_path = Path(args.saida)
    else:
        out_path = SCRIPT_DIR / "src" / "assets" / "template_questao_resposta.npy"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(out_path), template_gray)
    print(f"\n✓ Template salvo em: {out_path}")
    print(
        f"  Shape: {template_gray.shape}  |  Tamanho: {template_gray.nbytes / 1024:.1f} KB"
    )

    # Salva também uma prévia visual para inspeção
    preview_path = out_path.with_suffix(".preview.jpg")
    cv2.imwrite(
        str(preview_path),
        cv2.resize(template_bgr, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST),
    )
    print(f"  Prévia salva em: {preview_path}")

    print("\nRecalibração concluída!")
    print("Reinicie o servidor/scanner para o novo template entrar em efeito.")


if __name__ == "__main__":
    main()
