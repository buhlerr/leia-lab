"""scripts/linear_sync.py: a descricao puxada do Linear volta ao Beads sem as secoes que o bd anexa."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "linear_sync", Path(__file__).resolve().parents[1] / "scripts" / "linear_sync.py"
)
linear_sync = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(linear_sync)

BODY = "Contexto. Documento: <https://claude.ai/artifact/x> (secao Pontos para rever)."
AC = "gold-compare a b imprime os contadores. Ver https://claude.ai/artifact/x."
AC_IN_LINEAR = "gold-compare a b imprime os contadores. Ver <https://claude.ai/artifact/x>."


def _bead(description: str, acceptance: str = "", notes: str = "", design: str = "") -> dict:
    return {"description": description, "acceptance_criteria": acceptance, "notes": notes, "design": design}


def test_copies_accumulated_by_round_trips_are_removed():
    pulled = BODY + f"\n\n## Acceptance Criteria\n\n{AC_IN_LINEAR}" * 3
    assert linear_sync.own_description(_bead(pulled, AC)) == BODY


def test_interleaved_criteria_design_and_notes_copies_are_removed():
    block = "\n\n## Acceptance Criteria\n\nfeito\n\n## Design\n\num desenho\n\n## Notes\n\nnota"
    pulled = BODY + block * 2
    assert linear_sync.own_description(_bead(pulled, "feito", notes="nota", design="um desenho")) == BODY


def test_section_edited_in_linear_is_kept():
    pulled = BODY + "\n\n## Acceptance Criteria\n\ncriterio reescrito no Linear"
    assert linear_sync.own_description(_bead(pulled, AC)) == pulled


def test_heading_without_matching_field_is_kept():
    written = BODY + "\n\n## Notes\n\nescrito a mao na descricao"
    assert linear_sync.own_description(_bead(written)) == written


def test_clean_description_is_unchanged():
    assert linear_sync.own_description(_bead(BODY, AC, notes="nota")) == BODY
