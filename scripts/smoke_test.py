"""
smoke_test.py — Testa os endpoints da API sem precisar de servidor rodando.

Usa o TestClient do FastAPI/Starlette diretamente.

Uso:
    uv run python scripts/smoke_test.py caminho/para/cartao.jpg
    uv run python scripts/smoke_test.py caminho/para/cartao.jpg --dia 2
    uv run python scripts/smoke_test.py caminho/para/cartao.jpg --salvar-grid
"""

import sys
import json
import argparse
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from src.app import app

client = TestClient(app)


def testar_health():
    r = client.get("/health")
    assert r.status_code == 200
    print(f"  /health ✓  {r.json()}")


def testar_cartao(img_path: Path, dia: int, salvar_grid: bool):
    print(f"\n  POST /cartao  (dia={dia}, incluir_grid={salvar_grid})")
    with img_path.open("rb") as f:
        r = client.post(
            "/cartao",
            data={"dia": str(dia), "incluir_grid": str(salvar_grid).lower()},
            files={"file": (img_path.name, f, "image/jpeg")},
        )

    if r.status_code != 200:
        print(f"  ✗ HTTP {r.status_code}: {r.text[:300]}")
        return

    data = r.json()
    n    = data["total_questoes_detectadas"]
    exp  = data["questoes_esperadas"]
    ok   = "✓" if data["status"] in ("ok", "parcial") else "✗"

    print(f"  {ok} status={data['status']}  cpf={data['cpf']}  "
          f"questoes={n}/{exp}  avisos={len(data['avisos'])}")

    if data["avisos"]:
        for av in data["avisos"]:
            print(f"     ⚠  {av}")

    print(f"\n  Respostas detectadas:")
    resp = data["respostas"]
    linha = "  "
    for i, (q, r_) in enumerate(sorted((int(k), v) for k, v in resp.items()), 1):
        linha += f"Q{q:02d}:{r_:<2} "
        if i % 15 == 0:
            print(linha)
            linha = "  "
    if linha.strip():
        print(linha)

    # Grid
    if salvar_grid and data.get("grid_image_b64"):
        out = Path("outputs") / "grid_smoke_test.jpg"
        out.parent.mkdir(exist_ok=True)
        out.write_bytes(base64.b64decode(data["grid_image_b64"]))
        print(f"\n  Grid salvo em: {out}")

    # Testar endpoint /grid
    job_id = data["job_id"]
    print(f"\n  GET /cartao/{job_id}/grid")
    rg = client.get(f"/cartao/{job_id}/grid")
    if rg.status_code == 200:
        sz = len(rg.content) // 1024
        print(f"  ✓  Imagem JPEG recebida ({sz} KB)")
        if salvar_grid:
            out2 = Path("outputs") / "grid_endpoint.jpg"
            out2.write_bytes(rg.content)
            print(f"     Salvo em: {out2}")
    else:
        print(f"  ✗ HTTP {rg.status_code}")


def testar_batch(img_path: Path, dia: int):
    print(f"\n  POST /cartao/batch  (2× o mesmo arquivo, dia={dia})")
    with img_path.open("rb") as f1, img_path.open("rb") as f2:
        r = client.post(
            "/cartao/batch",
            data={"dia": str(dia)},
            files=[
                ("files", (img_path.name, f1, "image/jpeg")),
                ("files", (img_path.name + "_copia", f2, "image/jpeg")),
            ],
        )

    if r.status_code != 200:
        print(f"  ✗ HTTP {r.status_code}: {r.text[:300]}")
        return

    data = r.json()
    print(f"  ✓  total={data['total_arquivos']}  processados={data['processados']}")
    for item in data["resultados"]:
        print(f"     {item['arquivo']}: {item['status']}  "
              f"q={item['total_questoes_detectadas']}  "
              f"grid_url={item['grid_url']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("imagem")
    ap.add_argument("--dia",         type=int, default=1)
    ap.add_argument("--salvar-grid", action="store_true")
    args = ap.parse_args()

    img_path = Path(args.imagem)
    if not img_path.exists():
        print(f"Arquivo não encontrado: {img_path}")
        sys.exit(1)

    print("=" * 55)
    print("  SMOKE TEST — OMR AutoDetect API")
    print("=" * 55)

    testar_health()
    testar_cartao(img_path, args.dia, args.salvar_grid)
    testar_batch(img_path, args.dia)

    print("\n" + "=" * 55)
    print("  Concluído.")
    print("=" * 55)


if __name__ == "__main__":
    main()
