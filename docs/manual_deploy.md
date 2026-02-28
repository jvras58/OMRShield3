# Manual de Deploy — Railway

---

## Visão geral

O projeto é composto por **três peças** que precisam rodar em conjunto:

| Serviço | O que faz |
|---|---|
| **API** (FastAPI + Uvicorn) | Recebe imagens, devolve resultados via HTTP |
| **Worker** (FastStream consumer) | Processa jobs da fila Redis em background |
| **Redis** | Fila de mensagens + cache de resultados |

No Railway cada peça vira um **serviço separado** dentro do mesmo projeto.

### Como API e Worker se comunicam

O Worker **não tem endpoint HTTP próprio** — ele nunca recebe chamadas diretas. O único jeito de ativá-lo é via `POST /cartao/batch` da API. O Redis é o único canal entre os dois serviços:

```
cliente HTTP
    │
    │  POST /cartao/batch
    ▼
  API ── salva imagem ──────────► Redis  temp:{job_id}         (imagem bruta)
  API ── publica mensagem ──────► Redis  Stream "omr.batch"    (job leve)
  API ◄── retorna job_ids ────── imediatamente (não bloqueia)

                    Worker (FastStream, em background)
                        │
                        ├─ consome Stream "omr.batch"
                        ├─ carrega imagem de temp:{job_id}
                        ├─ roda pipeline (warp → Hough → threshold → OCR)
                        ├─ salva resultado em grid:{job_id}
                        └─ deleta temp:{job_id} + ACK na mensagem

    │  GET /cartao/{job_id}/status   (cliente faz polling)
    ▼
  API ── lê cache ──────────────► Redis  grid:{job_id}
         └─ "pending"   Worker ainda não terminou
         └─ "done"      resultado disponível
         └─ "failed"    erro irrecuperável no Worker

    │  GET /cartao/{job_id}/grid
    ▼
  API ── lê grid:{job_id} ──────► retorna JPEG anotado
```

Por isso **ambos os serviços precisam da mesma `REDIS_URL`** apontando para o Redis do Railway. Sem ela, o Worker não consegue consumir o stream e os jobs ficam presos em `pending` para sempre.

---

## Por que obrigatoriamente usar o Dockerfile?

O Dockerfile já está configurado como **builder multistage** e instala automaticamente:

- `tesseract-ocr` + `tesseract-ocr-por` — necessários para a extração do CPF via OCR
- `libgl1` / `libglib2.0-0` — dependências do OpenCV

Sem ele, qualquer ambiente que não tenha o Tesseract instalado vai **falhar completamente** na etapa de leitura de CPF. O Railway detecta o `Dockerfile` na raiz automaticamente — não é necessária nenhuma configuração extra de builder.

---

## Passo a passo

### 1. Criar o projeto no Railway

1. Acesse [railway.app](https://railway.app) → **New Project**
2. Escolha **Deploy from GitHub repo** e selecione o repositório

O Railway vai detectar o `Dockerfile` e configurar o builder automaticamente.

---

### 2. Criar o serviço Redis

O Redis **não pode** ser o embutido da API — ele precisa ser um serviço próprio para ser compartilhado com o Worker.

1. Dentro do projeto, clique em **+ New Service → Database → Redis**
2. O Railway cria o serviço e disponibiliza uma variável de conexão (algo como `REDIS_URL` ou `REDIS_PRIVATE_URL`)
3. Copie a URL completa de conexão — ela será usada no próximo passo

> **Atenção:** use a URL **interna/privada** (geralmente `REDIS_PRIVATE_URL`) para comunicação entre serviços dentro do mesmo projeto Railway. Ela tem menor latência e não consome banda pública.

---

### 3. Configurar as variáveis de ambiente na API

No serviço principal (API), vá em **Variables** e adicione:

```
# ── Obrigatória ────────────────────────────────────────────────────────────
REDIS_URL=<cole aqui a URL interna do Redis gerada pelo Railway>

# ── Autenticação ───────────────────────────────────────────────────────────
API_TOKEN=<token secreto para autenticar os requests — escolha um valor seguro>

# ── CORS ───────────────────────────────────────────────────────────────────
CORS_ORIGINS=["https://seu-frontend.com"]
# em desenvolvimento pode usar: CORS_ORIGINS=["*"]

# ── Cache ──────────────────────────────────────────────────────────────────
CACHE_TTL_SECONDS=3600

# ── Layout do cartão (ajuste somente se o layout mudar) ────────────────────
N_BLOCOS=6
N_QUESTOES_POR_BLOCO=15
N_ALTERNATIVAS=5

BOLHAS_Y_MIN_FRAC=0.66
BOLHAS_Y_MAX_FRAC=1.00

# ── Detecção de bolhas ─────────────────────────────────────────────────────
HOUGH_MIN_DIST=14
HOUGH_PARAM1=30
HOUGH_PARAM2=18
HOUGH_MIN_RADIUS=7
HOUGH_MAX_RADIUS=15
HOUGH_BLUR_SIGMA=1.5

# ── Separadores de bloco ───────────────────────────────────────────────────
SEP_MIN_GAP_PX=6
SEP_DARK_THR=12
SEP_PIXEL_THR=150

# ── Leitura de fill ────────────────────────────────────────────────────────
FILL_RADIUS=9
FILL_MARGIN_FRAC=0.30

# ── Thresholds ─────────────────────────────────────────────────────────────
MIN_JUMP_GLOBAL=25.0
MIN_JUMP_LOCAL=25.0
MAX_UNMARKED_VAL=140.0

# ── OCR ────────────────────────────────────────────────────────────────────
MAX_OCR_RETRIES=3
```

> A variável `PORT` **não precisa ser definida** — o Railway injeta ela automaticamente e o `CMD` do Dockerfile já usa `${PORT:-8000}`.

---

### 4. Criar o serviço Worker

O Worker usa a **mesma imagem/repositório** da API, mas com um comando diferente.

1. No mesmo projeto Railway, clique em **+ New Service → GitHub Repo**
2. Selecione o mesmo repositório
3. Em **Settings → Deploy → Custom Start Command**, defina:

```
faststream run src.worker.consumer:app
```

4. Em **Variables**, adicione **as mesmas variáveis** da API — especialmente:
   - `REDIS_URL` — **deve ser exatamente a mesma URL interna do Redis** usada na API; é por ela que o Worker consome o stream `omr.batch` e salva os resultados no cache
   - as demais variáveis de processamento (thresholds, layout, OCR etc.) se quiser sobrescrever os padrões

> O Worker também usa o Dockerfile, portanto o Tesseract estará disponível para ele também.

---

### 5. Verificar o deploy

Após as três peças estarem no ar (Redis, API, Worker), acesse o endpoint de healthcheck da API:

```
GET https://<sua-url-do-railway>/
```

Se retornar `200 OK`, a aplicação está funcionando corretamente.

---

## Variáveis fixas no código (não configuráveis via `.env`)

Algumas constantes são declaradas como `ClassVar` em `src/settings/config.py` e **não podem ser alteradas** por variáveis de ambiente. Caso precise modificá-las, é necessário editar o código-fonte diretamente:

| Constante | Valor padrão | Descrição |
|---|---|---|
| `ALTERNATIVAS` | `["A","B","C","D","E"]` | Letras das alternativas do cartão |
| `HOUGH_BLUR_KERNEL` | `(7, 7)` | Tamanho do kernel do blur gaussiano |
| `CPF_ROI` | `(0.0, 0.38, 0.155, 0.185)` | Região de interesse para leitura do CPF (frações x0, x1, y0, y1) |

---

## Checklist de deploy

- [ ] Serviço **Redis** criado no Railway
- [ ] `REDIS_URL` (URL interna do Redis) configurada na API e no Worker
- [ ] `API_TOKEN` definido com um valor seguro
- [ ] `CORS_ORIGINS` configurado para o(s) domínio(s) do frontend
- [ ] Demais variáveis do `.env` revisadas e ajustadas se necessário
- [ ] Serviço **Worker** com o start command `faststream run src.worker.consumer:app`
- [ ] Deploy concluído sem erros nos logs
- [ ] `/` responde `200 OK`

---

## Resumo

```
Railway Project
├── api      ← Dockerfile autodetectado, PORT injetado automaticamente
├── worker   ← mesmo repo, start command: faststream run src.worker.consumer:app
└── redis    ← serviço Redis nativo do Railway
```

Com Redis configurado, a URL do Redis apontando para o serviço interno e as demais variáveis preenchidas — a aplicação sobe corretamente.
