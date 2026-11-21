"""Sonda offline da fronteira de privacidade. Chamada por ``verify.py privacy``; nao use direto.

Sem banco: gera uma minuta DOCX e uma TXT com dados pessoais falsos, passa pelas portas reais
de entrada (``prepare_input``/``prepare_ingest_input``), confere que nada cru sobra, que os
grafos recusam texto nao mascarado e que o admin responde ``/ping/`` e ``/``.
Grava o JSON no caminho do argv[1] e sai 0 so se todas as checagens passarem.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

CPF, EMAIL, NOME = "111.222.333-44", "maria@teste.com.br", "Maria Oliveira"
CORPO = [
    "CONTRATO DE LOCAÇÃO RESIDENCIAL",
    f"Cláusula 1ª - Locatária {NOME}, CPF {CPF}, email {EMAIL}. "
    "Início em 01/05/2026 pelo prazo de 30 meses, aluguel de R$ 3.500,00.",
    "Cláusula 2ª - O locatário renuncia a qualquer indenização por benfeitorias necessárias.",
]


def _leaks(masked: dict[str, str]) -> dict[str, bool]:
    return {
        "raw_filename_leaked": "maria" in masked["filename"].lower() or CPF in masked["filename"],
        "raw_cpf_leaked": CPF in masked["text"],
        "raw_email_leaked": EMAIL in masked["text"],
        "cpf_token_present": "[CPF]" in masked["text"],
        "email_token_present": "[EMAIL]" in masked["text"],
        "alias_ok": masked["filename"].startswith("documento-"),
    }


async def _rejects(graph, state: dict[str, str]) -> bool:
    try:
        await graph.ainvoke(state)
    except ValueError as exc:
        return "masked" in str(exc)
    return False


async def main(out: Path) -> int:
    import django
    import docx
    from django.test import Client

    from src.config import Settings
    from src.graphs.analyze_minuta_graph import build_analyze_minuta_graph, prepare_input
    from src.graphs.ingest_graph import build_ingest_graph, prepare_ingest_input
    from src.graphs.minuta_rules import extract_ficha_candidates, segment_clauses

    with tempfile.TemporaryDirectory() as tmp:
        docx_path = Path(tmp) / f"Minuta_Particular_Maria_{CPF}.docx"
        d = docx.Document()
        for par in CORPO:
            d.add_paragraph(par)
        d.save(str(docx_path))
        txt_path = Path(tmp) / f"Minuta_Particular_Maria_{CPF}.txt"
        txt_path.write_text("\n".join(CORPO), encoding="utf-8")

        docx_in = await prepare_input(file_path=docx_path)
        txt_in = await prepare_input(file_path=txt_path)
        ingest_in = await prepare_ingest_input(file_path=docx_path, doc_name="Lei 8.245/1991, art. 35")

    fichas = extract_ficha_candidates(docx_in["text"])
    settings = Settings(OPENROUTER_API_KEY="", TYPESAFE_API_KEY="")
    analyze_g = build_analyze_minuta_graph(None, settings)  # type: ignore[arg-type]
    ingest_g = build_ingest_graph(None, settings)  # type: ignore[arg-type]

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "src.management.leia_admin.settings")
    django.setup()
    client = Client()
    ping = client.get("/ping/", HTTP_HOST="localhost")
    root = client.get("/", HTTP_HOST="localhost")

    proof = {
        "docx": {"filename_alias": docx_in["filename"], **_leaks(docx_in)},
        "txt": {"filename_alias": txt_in["filename"], **_leaks(txt_in)},
        "ingest_resolved_filename": ingest_in["resolved_filename"],
        "clauses": len(segment_clauses(docx_in["text"])),
        "ficha": {k: [v[0] for v in fichas[k]] for k in ("datas", "prazos", "valores")},
        "analyze_rejects_unmasked": await _rejects(
            analyze_g, {"text": f"CPF {CPF} sem mascara", "filename": "documento-12345678.docx"}
        ),
        "ingest_rejects_unmasked": await _rejects(
            ingest_g, {"masked_text": f"CPF {CPF} sem mascara", "resolved_filename": "Lei 8.245/1991, art. 35"}
        ),
        "ping": [ping.status_code, ping.json()],
        "root": [root.status_code, root.headers.get("Location")],
    }
    checks = {
        f"{kind}.{k}": proof[kind][k] is (k.endswith(("_present", "_ok")))
        for kind in ("docx", "txt")
        for k in _leaks(docx_in)
    }
    checks |= {
        "analyze_rejects_unmasked": proof["analyze_rejects_unmasked"],
        "ingest_rejects_unmasked": proof["ingest_rejects_unmasked"],
        "ping_200_ok": proof["ping"] == [200, {"ok": True}],
        "root_302_admin": proof["root"] == [302, "/admin/"],
    }
    proof["failed_checks"] = [k for k, ok in checks.items() if not ok]
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=False))
    print("PRIVACY_OK" if not proof["failed_checks"] else f"PRIVACY_FAIL {proof['failed_checks']}")
    return 0 if not proof["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(Path(sys.argv[1]))))
