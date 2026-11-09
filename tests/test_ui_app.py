"""Testes das funções puras do app Streamlit.

Evitam AppTest e banco de dados: cobrem apenas a lógica síncrona e testável
sem Streamlit.
"""

import pytest
from markdown_it import MarkdownIt

from src.agent.outputs import ChecklistOutput, ChecklistItem
from src.ui.app import can_submit, checklist_rows, retention_warning, safe_markdown


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


class TestSafeMarkdown:
    def test_remote_image_is_removed_keeping_the_alt_text(self):
        text = "veja ![logo](https://exemplo.test/p.png?d=segredo) aqui"
        assert safe_markdown(text) == "veja logo aqui"

    def test_link_keeps_the_text_and_drops_the_url(self):
        assert safe_markdown("[clausula 1](https://exemplo.test/x?d=segredo)") == "clausula 1"

    def test_link_definition_is_removed(self):
        text = "texto\n\n[1]: https://exemplo.test/p.png?d=segredo"
        assert "exemplo.test" not in safe_markdown(text)

    def test_html_media_tag_is_removed(self):
        assert safe_markdown('<img src="https://exemplo.test/p.png">ok') == "ok"

    def test_common_markdown_stays_untouched(self):
        text = "**Negrito**\n\n- item\n\n| a | b |\n|---|---|\n| 1 | 2 |"
        assert safe_markdown(text) == text

    # Conferido no HTML final: regex sobre a sintaxe nao garante o que o parser enxerga.
    @pytest.mark.parametrize(
        "text",
        [
            "![a[b]c](https://exemplo.test/p.png?d=segredo)",
            r"![a\]b](https://exemplo.test/p.png?d=segredo)",
            "[a[b]c](https://exemplo.test/x?d=segredo)",
            "![a][r]\n\n> [r]: https://exemplo.test/p.png?d=segredo",
            "![a][r]\n\n- [r]: https://exemplo.test/p.png?d=segredo",
        ],
    )
    def test_evasive_syntax_never_renders_image_or_link(self, text):
        html = MarkdownIt("commonmark").render(safe_markdown(text))
        assert "<img" not in html
        assert "<a " not in html
