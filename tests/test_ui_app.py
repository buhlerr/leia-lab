"""Testes das funções puras do app Streamlit.

Evitam AppTest e banco de dados: cobrem apenas a lógica síncrona e testável
sem Streamlit.
"""

from src.agent.outputs import ChecklistOutput, ChecklistItem
from src.ui.app import can_submit, checklist_rows, retention_warning


def test_warning_tells_to_use_only_fictional_drafts_without_restriction():
    assert "apenas minutas ficticias" in retention_warning("openrouter", False)


def test_warning_does_not_ask_for_fictional_drafts_with_restriction():
    assert "apenas minutas ficticias" not in retention_warning("openrouter", True)


def test_warning_for_deepseek_always_asks_for_fictional_drafts():
    assert "apenas minutas ficticias" in retention_warning("deepseek", True)


class TestCanSubmit:
    def test_no_key_without_consent(self):
        assert can_submit(has_api_key=False, consent=False) is True

    def test_no_key_with_consent(self):
        assert can_submit(has_api_key=False, consent=True) is True

    def test_has_key_without_consent(self):
        assert can_submit(has_api_key=True, consent=False) is False

    def test_has_key_with_consent(self):
        assert can_submit(has_api_key=True, consent=True) is True


class TestChecklistRows:
    def test_two_items(self):
        checklist = ChecklistOutput(
            items=[
                ChecklistItem(item="Cláusula 1", status="presente", evidence="Art. 1"),
                ChecklistItem(item="Cláusula 2", status="ausente", evidence="Não encontrada"),
            ]
        )
        rows = checklist_rows(checklist)
        assert rows == [
            {"Item": "Cláusula 1", "Status": "presente", "Evidencia": "Art. 1"},
            {"Item": "Cláusula 2", "Status": "ausente", "Evidencia": "Não encontrada"},
        ]

    def test_empty_checklist(self):
        assert checklist_rows(ChecklistOutput(items=[])) == []
