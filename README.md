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

## Autenticação

**Todas as rotas da API exigem autenticação** via header `X-Verify-Token`. Sem um token válido, qualquer requisição retorna `401 Unauthorized`.

### Configurando o token

1. **Gere um token seguro** (escolha um dos métodos):

   ```bash
   # Python (recomendado)
   python -c "import secrets; print(secrets.token_hex(32))"

   # OpenSSL
   openssl rand -hex 32
   ```

2. **Adicione ao `.env`** na raiz do projeto:

   ```env
   API_TOKEN=cole_o_token_gerado_aqui
   ```

3. **Reinicie os serviços** para aplicar:

   ```bash
   docker compose up --build
   ```

### Usando o token nas requisições

Passe o token no header `X-Verify-Token` em todas as chamadas:

```bash
# Exemplo com curl
curl -X POST http://localhost:8081/cartao \
  -H "X-Verify-Token: seu_token_aqui" \
  -F "file=@cartao_foto.jpg" -F "dia=1"
```

No **Swagger** (`/docs`), clique em **Authorize** (cadeado) e informe o token antes de executar qualquer endpoint.

> **Atenção:** Se `API_TOKEN` não estiver definido no `.env`, a API rejeita **todas** as requisições com `401`. Sempre configure o token antes de subir o serviço.

---

## Concorrência e escalabilidade

O sistema foi projetado para atender múltiplos usuários simultaneamente.

### Arquitetura

```
Usuários → Uvicorn (4 workers) → Redis Connection Pool → Redis
                                       ↓
                               FastStream Workers (4 réplicas)
```

### API (`/cartao`)

- O Uvicorn sobe com **4 processos independentes** (`--workers 4`), permitindo processamento paralelo real (sem GIL entre processos)
- A extração de imagem (CPU-bound) é executada via `run_in_executor`, liberando o event loop para aceitar novas requisições enquanto processa

### Batch (`/cartao/batch`)

- Apenas enfileira no Redis Stream `omr.batch` e retorna imediatamente
- O processamento real ocorre em **4 workers FastStream** em paralelo (configurado via `replicas: 4` no Compose)
- Para aumentar a capacidade: `docker compose up --scale worker=N`

### Redis

O Redis é configurado com limites explícitos para evitar instabilidade:

| Parâmetro | Valor | Descrição |
|---|---|---|
| `maxmemory` | 512mb | Limite de memória (ajuste conforme o servidor) |
| `maxmemory-policy` | `allkeys-lru` | Remove chaves menos usadas quando cheia |
| `tcp-keepalive` | 60s | Detecta conexões mortas rapidamente |

Cada worker mantém um **connection pool** de até 20 conexões com o Redis, reutilizando-as entre requests em vez de abrir uma nova a cada chamada. Com 4 workers na API e 4 workers de batch, o Redis pode receber até **160 conexões simultâneas** no total.

---

## API

Documentação interativa: http://localhost:8081/docs

### `POST /cartao`

```bash
# Só JSON
curl -X POST http://localhost:8081/cartao \
  -H "X-Verify-Token: seu_token_aqui" \
  -F "file=@cartao_foto.jpg" -F "dia=1"

# JSON + grid em base64
curl -X POST http://localhost:8081/cartao \
  -H "X-Verify-Token: seu_token_aqui" \
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
  -H "X-Verify-Token: seu_token_aqui" \
  -F "files=@foto1.jpg" -F "files=@foto2.jpg" -F "dia=1"
```

---

## Testes

A suite de testes é dividida em duas camadas: **unitários** (sem dependências externas) e **integração** (pipeline real com imagem de cartão).

### Instalação das dependências de desenvolvimento

```bash
uv sync --extra dev
```

Isso instala `pytest`, `fakeredis` e `pytest-cov`.

---

### Estrutura

```
tests/
├── conftest.py                  ← Fixtures globais, mocks e opções de CLI
├── api/
│   ├── test_auth.py             ← Autenticação via X-Verify-Token
│   ├── test_cartao.py           ← POST /cartao (ok, parcial, falhou, dia, grid)
│   ├── test_batch.py            ← POST /cartao/batch (enfileiramento, broker)
│   ├── test_status.py           ← GET /cartao/{id}/status (pending, done, failed)
│   ├── test_grid.py             ← GET /cartao/{id}/grid (JPEG, 404, fluxo completo)
│   ├── test_health.py           ← GET /health
│   └── test_schemas.py          ← Schemas Pydantic (validação e serialização)
├── core/
│   └── test_detection.py        ← Pipeline OpenCV com dados sintéticos
│                                   (separadores, calibração de colunas/linhas, ler_bloco)
├── infrastructure/
│   └── test_cache.py            ← GridCache com FakeRedis (set/get, TTL, temp, failed)
├── models/
│   └── test_resultado.py        ← Resultado, Status, CartaoJob
├── services/
│   └── test_cartao_service.py   ← ExtratorCartao com mocks de OCR e OpenCV
└── integration/
    └── test_smoke.py            ← Pipeline REAL com imagem de cartão (sem mocks)
```

---

### Testes unitários

Não precisam de Redis, Tesseract nem imagens reais. Todas as dependências externas são substituídas por mocks (`fakeredis`, `AsyncMock`, `unittest.mock.patch`).

```bash
# Rodar toda a suite unitária
uv run pytest tests/ --ignore=tests/integration/

# Rodar um módulo específico
uv run pytest tests/api/test_cartao.py -v

# Com relatório de cobertura
uv run pytest tests/ --ignore=tests/integration/ --cov=src --cov-report=term-missing
```

---

### Testes de integração

Executam o pipeline **completo e real** — OpenCV, HoughCircles, KMeans, threshold — com uma imagem JPEG de cartão-resposta. São os equivalentes pytest do `scripts/smoke_test.py`.

**Tesseract OCR:** se não estiver instalado no sistema, apenas o `pytesseract.image_to_string` é mockado (retorna string vazia). O CPF não será detectado, mas toda a detecção de bolhas roda normalmente.

**Redis:** substituído por `fakeredis` em memória — nenhum serviço externo necessário.

#### Rodar

Por padrão, procura por `data/cartao_foto.jpg` ou `data/cartao_digitalizado.jpg`:

```bash
uv run pytest tests/integration/ -v -s
```

Para especificar a imagem e o dia:

```bash
uv run pytest tests/integration/ -v -s --imagem data/cartao_digitalizado.jpg --dia 2
```

Para salvar as imagens de grid geradas em `outputs/`:

```bash
uv run pytest tests/integration/ -v -s --salvar-grid
```

Se nenhuma imagem estiver disponível, os testes são **automaticamente pulados** (`SKIPPED`) sem falhar.

#### O que é verificado

| Teste | Verifica |
|---|---|
| `test_integration_health` | `/health` retorna `ok` |
| `test_integration_cartao_nao_falhou` | status é `ok` ou `parcial` (nunca `falhou`) |
| `test_integration_cartao_detectou_questoes` | pelo menos 1 questão detectada |
| `test_integration_cartao_respostas_sao_letras_validas` | todas as respostas são A–E |
| `test_integration_cartao_tem_grid_url` | `grid_url` presente (img_alinhada gerada) |
| `test_integration_cartao_grid_b64_valido` | base64 retornado é JPEG válido (bytes FF D8 FF) |
| `test_integration_grid_retorna_jpeg` | `GET /grid` devolve `image/jpeg` válido |
| `test_integration_grid_tamanho_razoavel` | imagem do grid tem mais de 10 KB |
| `test_integration_batch_*` | enfileiramento retorna 2 job_ids distintos e `status=enqueued` |
| `test_integration_imprimir_resumo` | imprime todas as respostas detectadas (diagnóstico) |

---

### Suite completa (unitários + integração)

```bash
uv run pytest tests/ -v
```

---

### Cobertura

```bash
uv run pytest tests/ --cov=src --cov-report=term-missing
```

Cobertura atual por módulo crítico:

| Módulo | Cobertura |
|---|---|
| `controllers.py` | 100% |
| `routes.py` | 100% |
| `schemas.py` | 100% |
| `models/resultado.py` | 100% |
| `services/cartao_service.py` | 100% |
| `settings/config.py` | 100% |
| `infrastructure/cache.py` | 93% |
| `core/detection.py` | 62% |

> `core/alignment.py` e `core/ocr.py` têm cobertura menor pois dependem de Tesseract e imagens reais — cobertos pelos testes de integração.

---

## Parâmetros (`src/settings/config.py`)

Os parâmetros abaixo podem ser sobrescritos via `.env`:

| Parâmetro | Valor padrão | Descrição |
|---|---|---|
| `N_BLOCOS` | 6 | Colunas de questões |
| `N_QUESTOES_POR_BLOCO` | 15 | Questões por coluna |
| `N_ALTERNATIVAS` | 5 | Número de alternativas por questão |
| `BOLHAS_Y_MIN_FRAC` | 0.66 | Início da área de bolhas (pula cabeçalho) |
| `BOLHAS_Y_MAX_FRAC` | 1.00 | Fim da área de bolhas |
| `HOUGH_PARAM2` | 18 | Sensibilidade do Hough (menor = detecta mais) |
| `HOUGH_MIN_DIST` | 14 | Distância mínima entre centros de bolhas (px) |
| `FILL_RADIUS` | 9 | Raio do ROI centrado na bolha (px) |
| `MIN_JUMP_GLOBAL` | 25.0 | Jump mínimo no histograma global |
| `MIN_JUMP_LOCAL` | 25.0 | Jump mínimo local por questão |
| `MAX_UNMARKED_VAL` | 140.0 | Valor máximo para considerar bolha sem marcação |
| `MAX_OCR_RETRIES` | 3 | Tentativas de leitura de CPF |
| `CACHE_TTL_SECONDS` | 3600 | Tempo de expiração dos resultados no Redis |

> **Parâmetros estáticos — altere diretamente em `src/settings/config.py`:**
>
> Os campos abaixo são `ClassVar` e **não podem ser configurados via `.env`**. Para alterá-los, edite o arquivo diretamente:
>
> | Parâmetro | Valor padrão | Descrição |
> |---|---|---|
> | `ALTERNATIVAS` | `['A','B','C','D','E']` | Rótulos das alternativas |
> | `HOUGH_BLUR_KERNEL` | `(7, 7)` | Kernel do blur gaussiano antes do Hough |
> | `CPF_ROI` | `(0.0, 0.38, 0.155, 0.185)` | Região de interesse do CPF (frações x0,x1,y0,y1) |

---


## Estrutura do projeto

```
src/
├── core/
│   ├── alignment.py       ← warp de perspectiva
│   ├── detection.py       ← HoughCircles + KMeans + threshold
│   ├── ocr.py             ← extração de CPF
│   └── visualizer.py      ← grid anotado
├── infrastructure/
│   ├── broker.py          ← publicação no Redis Stream
│   ├── cache.py           ← GridCache (resultados e grids em Redis)
│   ├── image_io.py        ← carregar_imagem / carregar_imagem_bytes
│   └── redis_client.py    ← singleton com connection pool
├── models/
│   └── resultado.py       ← Resultado, Status
├── settings/
│   └── config.py          ← Pydantic Settings + .env
├── services/
│   └── cartao_service.py  ← ExtratorCartao
├── api/
│   ├── app.py             ← criação do FastAPI
│   ├── deps.py            ← injeção de dependências (Depends)
│   └── cartao/
│       ├── controllers.py ← lógica de negócio
│       ├── routes.py      ← contrato HTTP (path, método, schema)
│       └── schemas.py     ← Pydantic response models
└── worker/
    └── consumer.py        ← worker FastStream (consome omr.batch)
```