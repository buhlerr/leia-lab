"""Testes do renderizador seguro de Markdown."""

import pytest

from src.ui.render import render_safe_html


@pytest.mark.parametrize(
    "text",
    [
        "![a](https://exemplo.test/p.png?d=s)",
        "![a[b]c](https://exemplo.test/p.png?d=s)",
        r"![a\]b](https://exemplo.test/p.png?d=s)",
        "![a][r]\n\n> [r]: https://exemplo.test/p.png?d=s",
        "[a[b]c](https://exemplo.test/x?d=s)",
        "<https://exemplo.test/x?d=s>",
        "<mailto:a@exemplo.test>",
        r"\<mailto:a@exemplo.test>",
        r"https\://exemplo.test/x",
        "https:&#47;&#47;exemplo.test/x",
        "veja https://exemplo.test/x agora",
        "veja www.exemplo.test/x",
        "a@exemplo.test",
    ],
)
def test_no_link_or_image_output(text: str) -> None:
    html = render_safe_html(text)
    assert "<a " not in html
    assert "<img" not in html
    assert "exemplo.test/p.png?" not in html


def test_image_alt_text_is_preserved() -> None:
    assert "logo" in render_safe_html("![logo](https://exemplo.test/p.png)")


def test_link_text_is_preserved() -> None:
    assert "clausula" in render_safe_html("[clausula](https://exemplo.test)")


def test_raw_script_tag_is_not_rendered() -> None:
    assert "<script>" not in render_safe_html("<script>alert(1)</script>")


def test_raw_img_tag_is_not_rendered() -> None:
    assert "<img" not in render_safe_html('<img src="x">')


def test_bold_is_rendered() -> None:
    assert "<strong>N</strong>" in render_safe_html("**N**")


def test_list_item_is_rendered() -> None:
    assert "<li>" in render_safe_html("- item")


def test_table_is_rendered() -> None:
    assert "<table>" in render_safe_html("| a | b |\n|---|---|\n| 1 | 2 |")
