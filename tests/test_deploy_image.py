"""Guarda do tamanho da imagem do admin (bead leia-lab-8tr.14).

A imagem chegou a 3,3 GB e encheu o disco do CT 116 (o mesmo do Postgres): o ``chown -R`` depois do
``uv sync`` duplicava a .venv numa camada nova e o cache do uv ficava gravado na imagem.
"""

from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "deploy" / "Dockerfile"


def test_dockerfile_nao_duplica_a_venv_nem_guarda_cache_do_uv():
    lines = [ln.strip() for ln in DOCKERFILE.read_text(encoding="utf-8").splitlines() if not ln.strip().startswith("#")]
    text = "\n".join(lines)
    assert "chown -R" not in text, "chown -R apos o uv sync copia a .venv inteira numa camada nova"
    assert "UV_NO_CACHE=1" in text, "sem UV_NO_CACHE o cache do uv fica gravado na camada"
