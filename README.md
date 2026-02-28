# OMRShield — Leitura Automática de Cartões-Resposta

Sistema de leitura de folhas de respostas para provas objetivas, utilizando visão computacional (OpenCV) e OCR (Tesseract).

Suporta dois modos de processamento:
- **Individual** — envie uma imagem via API e receba o resultado imediatamente
- **Em lote** — envie múltiplas imagens e elas são processadas em background via worker

---

## Como funciona

```
Imagem → Warp (4 marcadores) → HoughCircles → KMeans X/Y → Fill → Threshold → Resposta
```

| Etapa | O que faz |
|---|---|
| **Loader** | Detecta 4 marcadores nos cantos, aplica warp de perspectiva |
| **Separadores** | Projeção vertical detecta os gaps brancos entre os 6 blocos |
| **HoughCircles** | Detecta bordas circulares em cada bloco (~80% das bolhas) |
| **KMeans em X** | Agrupa em 5 clusters → posições das colunas A–E |
| **KMeans em Y** | Estima `oy` (origem) e `labelsGap` (espaçamento entre questões) |
| **Grid completo** | Mede fill em todas as 15×5 posições |
| **Threshold** | Global (jump no histograma) + local por questão |

---

## Requisitos

> **Docker é obrigatório.**
> O projeto depende do [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) para leitura de CPF, que é instalado automaticamente na imagem Docker. Não é possível rodar o serviço diretamente com `uv run` / `python` sem ter o Tesseract instalado no sistema operacional.

Dependências de sistema instaladas no container:
- `tesseract-ocr` + `tesseract-ocr-por`
- `libgl1`, `libglib2.0-0` (OpenCV)

---

## Instalação e execução

**Suba os serviços com Docker Compose:**

```bash
docker compose up --build
```

A API ficará disponível em http://localhost:8081.

---

## API

Documentação interativa: http://localhost:8081/docs

### `POST /cartao`

```bash
# Só JSON
curl -X POST http://localhost:8081/cartao \
  -F "file=@cartao_foto.jpg" -F "dia=1"

# JSON + grid em base64
curl -X POST http://localhost:8081/cartao \
  -F "file=@cartao_foto.jpg" -F "dia=1" -F "incluir_grid=true"
```

Resposta:
```json
{
  "job_id": "3f2a1b...",
  "status": "ok",
  "cpf": "964.516.063-40",
  "tentativas_cpf": 2,
  "total_questoes_detectadas": 90,
  "questoes_esperadas": 90,
  "respostas": {"1": "C", "2": "B", "3": "C", "...": "..."},
  "avisos": [],
  "grid_image_b64": "/9j/4AAQ...",
  "grid_url": "/cartao/3f2a1b.../grid"
}
```

### `GET /cartao/{job_id}/grid`

Retorna JPEG do grid anotado. `job_id` vem da resposta do POST.

**Como visualizar o grid:**

- **Navegador** — cole a URL diretamente na barra de endereços:
  ```
  http://localhost:8081/cartao/<job_id>/grid
  ```
- **Swagger** — use o endpoint `GET /cartao/{job_id}/grid` em `/docs` e clique em *Download file* após executar.
- **curl** — salva o arquivo localmente:
  ```bash
  curl http://localhost:8081/cartao/3f2a1b.../grid --output grid.jpg
  ```

> **Questões em branco:** Se uma questão não estiver marcada no cartão, ela **não aparece** no campo `respostas` e é contabilizada como não detectada no aviso `"X/90 questoes detectadas"`. Isso é comportamento esperado — o sistema só retorna questões que possuem uma bolha preenchida.

### `POST /cartao/batch`

```bash
curl -X POST http://localhost:8081/cartao/batch \
  -F "files=@foto1.jpg" -F "files=@foto2.jpg" -F "dia=1"
```

---

## Smoke test

> Requer a API rodando (`docker compose up`).

```bash
uv run python scripts/smoke_test.py cartao_foto.jpg --salvar-grid
```

---

## Parâmetros (`src/config.py`)

| Parâmetro | Valor | Descrição |
|---|---|---|
| `N_BLOCOS` | 6 | Colunas de questões |
| `N_QUESTOES_POR_BLOCO` | 15 | Questões por coluna |
| `BOLHAS_Y_MIN_FRAC` | 0.66 | Início da área de bolhas (pula cabeçalho) |
| `HOUGH_PARAM2` | 18 | Sensibilidade do Hough |

---


## Estrutura do projeto

```
src/
├── core/
│   ├── alignment.py       ← warp de perspectiva
│   ├── detection.py       ← HoughCircles + KMeans + threshold
│   ├── ocr.py             ← extração de CPF
│   └── visualizer.py      ← grid anotado (antes: visualizer.py)
├── infrastructure/
│   ├── cache.py           ← GridCache em memória
│   └── image_io.py        ← carregar_imagem / carregar_imagem_bytes
├── models/
│   └── resultado.py       ← Resultado, Status
├── settings/
│   └── config.py          ← Pydantic Settings + .env
├── services/
│   └── cartao_service.py  ← ExtratorCartao
├── api/
│   ├── app.py             ← criação do FastAPI
│   ├── routes.py          ← todos os handlers
│   └── schemas.py         ← Pydantic response models
└── worker/
    └── consumer.py        ← placeholder FastStream
```